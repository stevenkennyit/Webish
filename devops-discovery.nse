local http = require "http"
local stdnse = require "stdnse"
local shortport = require "shortport"
local nmap = require "nmap"

description = [[
Detects common DevOps applications such as Jira, Confluence, Jenkins, GitLab, SonarQube, and others
by checking known URI paths and verifying response content to reduce false positives.

Automatically detects whether to use HTTP or HTTPS based on Nmap's service detection.

Usage:
    nmap --script devops-discovery.nse -p 80,443 <target>
]]

author = "Your Name"
license = "Same as Nmap"
categories = {"discovery", "safe"}

-- Run this script only on HTTP or HTTPS services
portrule = function(host, port)
    return shortport.http(host, port) or shortport.ssl(host, port)
end

-- List of known DevOps application paths with expected content
local devops_apps = {
    ["Jira"] = {paths={"/", "/jira", "/browse"}, signature="jira"},
    ["Confluence"] = {paths={"/", "/confluence", "/wiki"}, signature="confluence"},
    ["Jenkins"] = {paths={"/", "/jenkins/whoAmI", "/whoAmI"}, signature="Jenkins"},
    ["GitLab"] = {paths={"/", "/gitlab", "/users/sign_in"}, signature="GitLab"},
    ["SonarQube"] = {paths={"/", "/sonarqube", "/about"}, signature="sonarqube"},
    ["Prometheus"] = {paths={"/", "/prometheus", "/graph"}, signature="<title>Prometheus"},
    ["Grafana"] = {paths={"/", "/grafana", "/login"}, signature="<title>Grafana"},
    ["Kibana"] = {paths={"/", "/kibana", "/app/kibana"}, signature="kibana"},
    ["Nexus Repository"] = {paths={"/", "/service/rest"}, signature="nexus"},
    ["Artifactory"] = {paths={"/", "/artifactory", "/ui/login/"}, signature="artifactory"},
    ["Harbor"] = {paths={"/", "/harbor", "/c/login"}, signature="harbor"},
    ["TeamCity"] = {paths={"/", "/teamcity", "/login.html"}, signature="teamcity"},
    ["Bamboo"] = {paths={"/", "/bamboo", "/userlogin!default.action"}, signature="bamboo"},
    ["Azure DevOps"] = {paths={"/", "/azuredevops", "/_signin"}, signature="azure"},
    ["Bitbucket"] = {paths={"/", "/bitbucket", "/dashboard"}, signature="bitbucket"},
    ["Docker Registry"] = {paths={"/", "/v2/_catalog"}, signature="repositories"},
    ["Kubernetes Dashboard"] = {paths={"/", "/api/v1/namespaces/kube-system/services/https:kubernetes-dashboard:/proxy/"}, signature="kubernetes"},
}

action = function(host, port)
    local result = {}

    -- Detect if we should use HTTP or HTTPS
    local scheme = "http"
    if shortport.ssl(host, port) then
        scheme = "https"
    end

    for app_name, app_info in pairs(devops_apps) do
        for _, path in ipairs(app_info.paths) do
            local url = string.format("%s://%s:%s%s", scheme, host.targetname or host.ip, port.number, path)

            stdnse.print_debug(1, "Checking %s at %s", app_name, url)

            local response = http.get(host, port, path, {ssl = (scheme == "https")})

            if response and response.status == 200 and response.body then
                -- Verify the response contains the expected application signature
                if string.match(response.body:lower(), app_info.signature:lower()) then
                    table.insert(result, string.format("[+] %s found at %s", app_name, url))
                    break -- Stop checking further paths for this application if one is found
                else
                    stdnse.print_debug(1, "Skipping false positive at %s", url)
                end
            end
        end
    end

    if #result > 0 then
        return stdnse.format_output(true, result)
    else
        return "No known DevOps applications detected."
    end
end
