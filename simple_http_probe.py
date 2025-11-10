#!/usr/bin/env python3
"""
simple_port_probe.py

Simple, WAF-friendly per-port HTTP(S) GET probe.

- Tries HTTPS first, then HTTP for each port.
- If response matches "HTTP/1.1 503 Service Unavailable" (status 503 + reason contains "Service Unavailable"),
  marks the port as "NOT OPEN".
- Any other HTTP response -> "POTENTIAL OPEN".
- Connection errors/timeouts -> "NO RESPONSE".

Run only with explicit authorization.
"""
import argparse
import csv
import random
import time
from urllib.parse import urljoin

import requests
from requests.adapters import HTTPAdapter, Retry

import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# --- default web ports (your list) ---
DEFAULT_PORTS = [
    80, 443,
    8080, 8000, 8008, 8888, 8081, 8181, 3000, 3001, 3002, 5000, 5001, 4200, 4201,
    8443, 9443, 10443, 8444, 9200, 9300, 5601, 5984, 9090, 9091, 10000, 10080,
    7000, 7001, 8880, 7080, 7081, 3168, 4161, 49152
]

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/117.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.4 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/117.0.0.0 Safari/537.36",
]

DEFAULT_TIMEOUT = 7.0
DEFAULT_DELAY = 0.8

def make_session(timeout=DEFAULT_TIMEOUT, max_retries=1):
    s = requests.Session()
    retries = Retry(total=max_retries, backoff_factor=0.2, status_forcelist=(429, 502, 503, 504))
    adapter = HTTPAdapter(max_retries=retries)
    s.mount("http://", adapter)
    s.mount("https://", adapter)
    s.headers.update({
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
    })
    return s

def probe_once(session, url, timeout, verify_tls):
    """Return a tuple: (result_str, status_code_or_None, reason_or_None, details)"""
    try:
        r = session.get(url, timeout=timeout, allow_redirects=False, verify=verify_tls)
        # r.status_code is integer; r.reason is textual phrase like "Service Unavailable"
        if r.status_code == 503 and r.reason and "Service Unavailable" in r.reason:
            return ("NOT OPEN (503 Service Unavailable)", r.status_code, r.reason, {"headers": dict(r.headers)})
        else:
            # Any other HTTP response -> potential open
            return ("POTENTIAL OPEN", r.status_code, r.reason, {"headers": dict(r.headers), "snippet": r.text[:300]})
    except requests.exceptions.SSLError as e:
        # TLS handshake failed - treat as NO RESPONSE for HTTPS attempt
        return ("NO RESPONSE (ssl_error)", None, None, {"error": str(e)})
    except requests.exceptions.ConnectTimeout:
        return ("NO RESPONSE (connect_timeout)", None, None, {})
    except requests.exceptions.ReadTimeout:
        return ("NO RESPONSE (read_timeout)", None, None, {})
    except requests.exceptions.ConnectionError as e:
        return ("NO RESPONSE (connection_error)", None, None, {"error": str(e)})
    except Exception as e:
        return ("NO RESPONSE (unknown_error)", None, None, {"error": str(e)})

def main():
    p = argparse.ArgumentParser(description="Simple port probe (HTTP(S) GET) - mark 503 as not open, else potential open")
    p.add_argument("--target", "-t", required=True, help="Target hostname or IP (no scheme)")
    p.add_argument("--ports", "-p", default=",".join(str(x) for x in DEFAULT_PORTS),
                   help="Comma-separated ports to test")
    p.add_argument("--path", default="/", help="Path to GET (default '/')")
    p.add_argument("--delay", type=float, default=DEFAULT_DELAY, help="Delay between probes (seconds)")
    p.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT, help="Request timeout (seconds)")
    p.add_argument("--verify-tls", action="store_true", help="Verify TLS certs for HTTPS (default: False)")
    p.add_argument("--out-csv", default="probe_results.csv", help="CSV output filename")
    args = p.parse_args()

    target = args.target
    ports = [int(x) for x in args.ports.split(",") if x.strip()]
    path = args.path if args.path.startswith("/") else "/" + args.path

    session = make_session(timeout=args.timeout)

    # Prepare CSV
    csvfile = open(args.out_csv, "w", newline="", encoding="utf-8")
    writer = csv.writer(csvfile)
    writer.writerow(["timestamp", "target", "port", "scheme", "url", "result", "status_code", "reason", "notes"])

    for port in ports:
        # Try HTTPS first, then HTTP
        for scheme in ("https", "http"):
            # omit explicit port when using standard ports
            use_standard = (scheme == "https" and port == 443) or (scheme == "http" and port == 80)
            netloc = f"{target}:{port}" if not use_standard else target
            url = f"{scheme}://{netloc}{path}"
            # probe
            result, status_code, reason, details = probe_once(session, url, timeout=args.timeout, verify_tls=args.verify_tls)
            timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            notes = details.get("error") if details.get("error") else (details.get("snippet")[:200] if details.get("snippet") else "")
            print(f"{timestamp}  {target}:{port}  {scheme.upper():5}  -> {result}  (status={status_code} reason={reason})")
            writer.writerow([timestamp, target, port, scheme, url, result, status_code or "", reason or "", notes])
            csvfile.flush()

            # If we got any HTTP response (including 503), don't try the other scheme for the same port
            # (keeps behavior simple). If you prefer to always try both, remove the following break.
            if status_code is not None:
                break

            # small polite delay between scheme tries (less than inter-port delay)
            time.sleep(max(0, args.delay * 0.25))

        # polite per-port delay
        time.sleep(max(0, args.delay))

    csvfile.close()
    print(f"Done. Results saved to {args.out_csv}")

if __name__ == "__main__":
    main()