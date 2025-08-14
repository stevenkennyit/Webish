<# 
  AZ_manifest.ps1 — Azure AD App Registration manifest scanner (PS 5.1 safe)

  Outputs:
    - .\aad_app_manifest_findings.csv
    - .\aad_app_manifest_findings.json

  Requires:
    - Az.Accounts, Az.Resources
#>

[CmdletBinding()]
param(
  [string]$DisplayNameLike
)

# ---------- Helpers ----------
function Join-Short {
  param($Items, [int]$Max=6)
  if (-not $Items) { return "" }
  $arr = @($Items | ForEach-Object { "$_" })
  if ($arr.Count -le $Max) { return ($arr -join "; ") }
  return (($arr[0..($Max-1)] -join "; ") + "; ...")
}
function Coalesce { param($Value, $Fallback='n/a'); if ($null -ne $Value -and "$Value" -ne '') { $Value } else { $Fallback } }

function Get-GraphToken {
  try {
    return (Get-AzAccessToken -ResourceUrl "https://graph.microsoft.com").Token
  } catch {
    throw "Get-AzAccessToken failed. Ensure Az.Accounts is installed and you're logged in (Connect-AzAccount)."
  }
}

function Get-DaysLeft {
  param($End)  # string, DateTime, or DateTimeOffset
  if ($null -eq $End) { return $null }
  try {
    $endDto = if ($End -is [datetime] -or $End -is [datetimeoffset]) { [datetimeoffset]$End } else { [datetimeoffset]::Parse($End, [Globalization.CultureInfo]::InvariantCulture) }
    $now = [datetimeoffset]::UtcNow
    return [int][math]::Floor(($endDto - $now).TotalDays)
  } catch {
    return $null
  }
}

# Robust OptionalClaims flattener (works for Az & Graph shapes)
function Extract-OptionalClaims {
  param($optionalClaims)
  $out=@()
  if (-not $optionalClaims) { return $out }

  # Shape 1 (Az SDK): array of sets, each has Name + Claim[]
  if ($optionalClaims -is [System.Collections.IEnumerable] -and -not ($optionalClaims -is [string])) {
    foreach ($set in $optionalClaims) {
      if ($null -ne $set.Claim) {
        foreach ($c in $set.Claim) { $out += "$($set.Name):$($c.Name)" }
      }
    }
  }

  # Shape 2 (Graph): object with idToken/accessToken/saml2Token arrays
  foreach ($k in 'idToken','accessToken','saml2Token') {
    $claims = $optionalClaims.$k
    if ($claims) {
      foreach ($c in $claims) {
        $nm = if ($c.PSObject.Properties.Name -contains 'name') { $c.name } else { $c.Name }
        $out += ("{0}:{1}" -f $k, (Coalesce $nm))
      }
    }
  }
  return $out
}

# ---------- Application enumeration with safe fallback ----------
function Get-TenantApplications {
  param([string]$DisplayNameLike)

  Write-Host "[*] Getting applications..." -ForegroundColor Cyan

  # 1) Try native Az (some versions support -All)
  try {
    if ($DisplayNameLike) {
      $tmp = Get-AzADApplication -DisplayName $DisplayNameLike -ErrorAction Stop
      if ($tmp) { return @($tmp) }
    } else {
      $tmp = Get-AzADApplication -All $true -ErrorAction Stop
      if ($tmp) { return @($tmp) }
    }
  } catch { }

  # 2) Try a big single page
  try {
    if ($DisplayNameLike) { $tmp = Get-AzADApplication -DisplayName $DisplayNameLike -First 999 -ErrorAction Stop }
    else { $tmp = Get-AzADApplication -First 999 -ErrorAction Stop }
    if ($tmp -and $tmp.Count -gt 0 -and $tmp.Count -lt 999) { return @($tmp) }
  } catch { }

  # 3) Reliable fallback: Microsoft Graph with @odata.nextLink paging
  $token = Get-GraphToken
  $headers = @{ Authorization="Bearer $token"; ConsistencyLevel="eventual" }

  if ($DisplayNameLike) {
    $safe = $DisplayNameLike -replace "'", "''"
    $url = "https://graph.microsoft.com/v1.0/applications?`$top=999&`$filter=startswith(displayName,'$safe')"
  } else {
    $url = "https://graph.microsoft.com/v1.0/applications?`$top=999"
  }

  $all = @()
  while ($url) {
    $resp = Invoke-RestMethod -Method GET -Uri $url -Headers $headers
    if ($resp.value) { $all += $resp.value }
    $url = $resp.'@odata.nextLink'
    Write-Host ("    pulled total: {0}" -f $all.Count)
  }
  return $all
}

# ---------- Resolve resourceAppId -> permission name maps (Graph) ----------
function Get-ResourceSpMap {
  param([string[]]$ResourceAppIds)

  $unique = $ResourceAppIds | Where-Object { $_ } | Sort-Object -Unique
  Write-Host ("[*] Resolving {0} resource service principals for permission name mapping..." -f $unique.Count) -ForegroundColor Cyan

  $token = Get-GraphToken
  $headers = @{ Authorization="Bearer $token" }
  $map = @{}

  $i = 0
  foreach ($rid in $unique) {
    $i++
    if ($i % 50 -eq 0) { Write-Host ("    resolved: {0}/{1}" -f $i, $unique.Count) }
    try {
      $url = "https://graph.microsoft.com/v1.0/servicePrincipals?`$select=appId,displayName,appRoles,oauth2PermissionScopes&`$filter=appId eq '$rid'"
      $resp = Invoke-RestMethod -Method GET -Uri $url -Headers $headers
      $sp = $resp.value | Select-Object -First 1
      if ($sp) {
        $scopeMap = @{}
        foreach ($s in ($sp.oauth2PermissionScopes | Where-Object { $_ })) { $scopeMap[[string]$s.id] = $s.value }
        $roleMap  = @{}
        foreach ($r in ($sp.appRoles               | Where-Object { $_ })) { $roleMap[[string]$r.id]  = $r.value }
        $map[$rid] = @{ Scopes = $scopeMap; AppRoles = $roleMap; Name = $sp.displayName }
      }
    } catch { }
  }
  return $map
}

# Expand RequiredResourceAccess -> readable permission names
function Expand-Permissions {
  param($requiredResourceAccess, $spMap)
  $out = @()
  foreach ($res in ($requiredResourceAccess | Where-Object { $_ })) {
    $rid = [string]$res.ResourceAppId
    $maps = $spMap[$rid]
    $resName = if ($maps) { $maps.Name } else { $rid }
    foreach ($p in ($res.ResourceAccess | Where-Object { $_ })) {
      $permGuid = [string]$p.Id
      $ptype = $p.Type  # Scope or Role
      $pname = $permGuid
      if ($maps) {
        if ($ptype -eq 'Scope' -and $maps.Scopes.ContainsKey($permGuid)) { $pname = $maps.Scopes[$permGuid] }
        elseif ($ptype -eq 'Role' -and $maps.AppRoles.ContainsKey($permGuid)) { $pname = $maps.AppRoles[$permGuid] }
      }
      $out += [pscustomobject]@{
        ResourceAppId = $rid
        ResourceName  = $resName
        Type          = $ptype
        Permission    = $pname
      }
    }
  }
  return $out
}

# ---------- Main ----------
$HighRiskPermNames = @(
  'Directory.ReadWrite.All','Directory.AccessAsUser.All','Directory.Read.All',
  'User.ReadWrite.All','User.Read.All',
  'Group.ReadWrite.All','RoleManagement.ReadWrite.Directory',
  'AppRoleAssignment.ReadWrite.All','Application.ReadWrite.All',
  'Mail.ReadWrite','Mail.Read','Mail.Send',
  'Files.ReadWrite.All','Files.Read.All',
  'Sites.FullControl.All','Sites.ReadWrite.All',
  'Device.ReadWrite.All','Policy.ReadWrite.ConditionalAccess'
)

$apps = Get-TenantApplications -DisplayNameLike $DisplayNameLike
if (-not $apps) { Write-Warning "No applications found (or filter too narrow)."; return }
Write-Host ("[*] Got {0} applications." -f $apps.Count) -ForegroundColor Cyan

# Build unique set of resource app IDs to resolve
$resourceIds = [System.Collections.Generic.HashSet[string]]::new()
foreach ($a in $apps) {
  foreach ($r in ($a.RequiredResourceAccess | Where-Object { $_ })) { [void]$resourceIds.Add([string]$r.ResourceAppId) }
}
$spMap = Get-ResourceSpMap -ResourceAppIds @($resourceIds)

$results = foreach ($app in $apps) {
  $web = $app.Web
  $spa = $app.Spa

  # Public client detection across Az/Graph variants
  $publicClientEnabled = $false
  if ($null -ne $app.PublicClient) { $publicClientEnabled = $true }
  if ($app.PSObject.Properties.Name -contains 'IsFallbackPublicClient' -and $app.IsFallbackPublicClient) { $publicClientEnabled = $true }

  # Implicit grant flags if present
  $implicitAccess = $false; $implicitId = $false
  if ($web -and $web.ImplicitGrantSetting) {
    $implicitAccess = [bool]$web.ImplicitGrantSetting.EnableAccessTokenIssuance
    $implicitId     = [bool]$web.ImplicitGrantSetting.EnableIdTokenIssuance
  } elseif ($web -and $web.implicitGrantSettings) {
    $implicitAccess = [bool]$web.implicitGrantSettings.enableAccessTokenIssuance
    $implicitId     = [bool]$web.implicitGrantSettings.enableIdTokenIssuance
  }

  # Redirect URIs
  $redirects = @()
  if ($web -and $web.RedirectUris)          { $redirects += $web.RedirectUris }
  if ($web -and $web.redirectUris)          { $redirects += $web.redirectUris }
  if ($spa -and $spa.RedirectUris)          { $redirects += $spa.RedirectUris }
  if ($spa -and $spa.redirectUris)          { $redirects += $spa.redirectUris }

  $httpRedirects     = $redirects | Where-Object { $_ -match '^http://' -and $_ -notmatch '^http://localhost' }
  $wildcardRedirects = $redirects | Where-Object { $_ -match '\*' }

  # Known client apps (pluralization differs)
  $knownClients = @()
  if ($app.PSObject.Properties.Name -contains 'KnownClientApplications' -and $app.KnownClientApplications) {
    $knownClients = @($app.KnownClientApplications)
  } elseif ($app.PSObject.Properties.Name -contains 'KnownClientApplication' -and $app.KnownClientApplication) {
    $knownClients = @($app.KnownClientApplication)
  }

  # Optional claims (flatten)
  $optionalClaims = Extract-OptionalClaims $app.OptionalClaims
  if (-not $optionalClaims -and $app.optionalClaims) { $optionalClaims = Extract-OptionalClaims $app.optionalClaims }

  # Secrets / certs meta (Graph returns ISO strings)
  $secretMeta = @()
  $pwCreds  = if ($app.PasswordCredentials) { $app.PasswordCredentials } else { $app.passwordCredentials }
  $keyCreds = if ($app.KeyCredentials)      { $app.KeyCredentials }      else { $app.keyCredentials }

  foreach ($p in ($pwCreds | Where-Object { $_ })) {
    $daysLeft = Get-DaysLeft $p.EndDateTime
    $secretMeta += ("secret:{0} exp:{1} d" -f (Coalesce $p.DisplayName ($p.displayName)), $daysLeft)
  }
  foreach ($k in ($keyCreds | Where-Object { $_ })) {
    $daysLeft = Get-DaysLeft $k.EndDateTime
    $secretMeta += ("cert:{0} exp:{1} d" -f (Coalesce $k.DisplayName ($k.displayName)), $daysLeft)
  }

  # Permissions expansion
  $permObjs = Expand-Permissions -requiredResourceAccess $app.RequiredResourceAccess -spMap $spMap
  $permNamesFlat = $permObjs | ForEach-Object {
    if ($_.ResourceName) { "$($_.ResourceName):$($_.Permission)" } else { "$($_.ResourceAppId):$($_.Permission)" }
  }

  $graphRisky = $permObjs |
    Where-Object { $_.ResourceName -eq 'Microsoft Graph' -and $HighRiskPermNames -contains $_.Permission } |
    Select-Object -ExpandProperty Permission -Unique

  # Findings
  $findings = @()
  if ($implicitAccess -or $implicitId) { $findings += "Implicit grant enabled (AccessToken=$implicitAccess, IdToken=$implicitId)" }
  if ($publicClientEnabled)            { $findings += "Public client enabled" }
  if ($httpRedirects)                  { $findings += "Non-HTTPS redirect URIs present" }
  if ($wildcardRedirects)              { $findings += "Wildcard redirect URIs present" }
  if ($graphRisky)                     { $findings += "High-priv Graph perms: " + ($graphRisky -join ', ') }

  $identifierUris = @()
  if ($app.IdentifierUris) { $identifierUris = $app.IdentifierUris }
  elseif ($app.IdentifierUri) { $identifierUris = $app.IdentifierUri }
  if (($identifierUris | Measure-Object).Count -gt 0) { $findings += "Exposes application ID URI(s)" }

  # Credentials expiring soon (<=30 days)
  $expiringSoon = @()
  foreach ($p in ($pwCreds  | Where-Object { $_ })) { $d = Get-DaysLeft $p.EndDateTime; if ($d -ne $null -and $d -le 30) { $expiringSoon += ("secret:{0} ({1} d)" -f (Coalesce $p.DisplayName ($p.displayName)), $d) } }
  foreach ($k in ($keyCreds | Where-Object { $_ })) { $d = Get-DaysLeft $k.EndDateTime; if ($d -ne $null -and $d -le 30) { $expiringSoon += ("cert:{0} ({1} d)" -f   (Coalesce $k.DisplayName ($k.displayName)), $d) } }
  if ($expiringSoon) { $findings += "Credentials expiring soon: " + ($expiringSoon -join '; ') }

  [pscustomobject]@{
    DisplayName          = $app.DisplayName
    AppId                = $app.AppId
    ObjectId             = $app.Id
    SignInAudience       = $app.SignInAudience
    RedirectUris         = Join-Short ($redirects)
    HttpRedirects        = Join-Short ($httpRedirects)
    WildcardRedirects    = Join-Short ($wildcardRedirects)
    PublicClient         = [bool]$publicClientEnabled
    ImplicitAccessToken  = [bool]$implicitAccess
    ImplicitIdToken      = [bool]$implicitId
    KnownClientApps      = ($knownClients -join '; ')
    IdentifierUris       = Join-Short ($identifierUris)
    OptionalClaims       = Join-Short ($optionalClaims)
    Permissions          = Join-Short ($permNamesFlat)
    HighRiskGraphPerms   = ($graphRisky -join '; ')
    SecretsAndCertsMeta  = Join-Short ($secretMeta)
    Findings             = if ($findings) { $findings -join ' | ' } else { '' }
    RawManifestJson      = ($app | ConvertTo-Json -Depth 15)
  }
}

# ---------- Output ----------
$results | Sort-Object { [string]$_.'Findings' } -Descending |
  Select-Object DisplayName, AppId, PublicClient, ImplicitAccessToken, ImplicitIdToken, HighRiskGraphPerms, HttpRedirects, WildcardRedirects, Findings |
  Format-Table -AutoSize

$csv = ".\aad_app_manifest_findings.csv"
$json = ".\aad_app_manifest_findings.json"
$results | Export-Csv -NoTypeInformation -Encoding UTF8 $csv
$results | ConvertTo-Json -Depth 6 | Out-File -Encoding UTF8 $json

Write-Host "`n[+] Wrote $csv and $json" -ForegroundColor Green
Write-Host "[i] Tip: open the JSON for full manifest details, including RawManifestJson per app." -ForegroundColor DarkGray
