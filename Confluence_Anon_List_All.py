import requests
import json
import sys
import getopt
import os
from tqdm import tqdm
import urllib3

# Disable SSL warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

def safe_request(url, headers):
    """Handles API requests with error handling."""
    try:
        response = requests.get(url, headers=headers, verify=False)
        response.raise_for_status()  # Raises HTTPError for bad responses (4xx and 5xx)
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Error: Request failed for {url} -> {e}")
        return None
    except json.JSONDecodeError:
        print(f"Error: Invalid JSON response from {url}")
        return None

def get_spaces(cURL, headers):
    """Retrieve all spaces in Confluence."""
    url = f"{cURL}/rest/api/space"
    data = safe_request(url, headers)
    if not data:
        return []
    return [(space["key"], f"{cURL}/spaces/viewspace.action?key={space['key']}") for space in data.get("results", [])]

def get_child_pages(cURL, headers, parent_id):
    """Recursively retrieve all child pages of a given page."""
    url = f"{cURL}/rest/api/content/{parent_id}/child/page"
    data = safe_request(url, headers)
    if not data:
        return []
    
    child_pages = [(page["id"], page["title"], f"{cURL}/pages/viewpage.action?pageId={page['id']}") for page in data.get("results", [])]
    for page_id, page_title, page_url in tqdm(child_pages, desc=f"Retrieving child pages for {parent_id}"):
        child_pages.extend(get_child_pages(cURL, headers, page_id))
    
    return child_pages

def get_pages_in_space(cURL, headers, space_key):
    """Retrieve all top-level pages within a given space."""
    url = f"{cURL}/rest/api/content?spaceKey={space_key}&expand=space,body.view,version"
    data = safe_request(url, headers)
    if not data:
        return []
    return [(page["id"], page["title"], f"{cURL}/pages/viewpage.action?pageId={page['id']}") for page in data.get("results", [])]

def get_attachments(cURL, headers, page_id):
    """Retrieve all attachments from a given page."""
    url = f"{cURL}/rest/api/content/{page_id}/child/attachment"
    data = safe_request(url, headers)
    if not data:
        return []
    return [(att["title"], f"{cURL}{att['_links']['download']}") for att in data.get("results", [])]

def list_all_content(cURL, headers, output_file):
    """List all spaces, pages (recursively), and attachments in Confluence and write to file."""
    with open(output_file, "w", encoding="utf-8") as f:
        f.write("[*] Retrieving all spaces...\n")
        spaces = get_spaces(cURL, headers)
        
        for space, space_url in tqdm(spaces, desc="Processing spaces"):
            f.write(f"[*] Space: {space} -> {space_url}\n")
            pages = get_pages_in_space(cURL, headers, space)
            
            for page_id, page_title, page_url in tqdm(pages, desc=f"Retrieving pages in space {space}"):
                f.write(f"    [Page] {page_title} (ID: {page_id}) -> {page_url}\n")
                
                # Recursively get child pages
                child_pages = get_child_pages(cURL, headers, page_id)
                for child_id, child_title, child_url in tqdm(child_pages, desc=f"Processing child pages of {page_title}"):
                    f.write(f"        [Sub-Page] {child_title} (ID: {child_id}) -> {child_url}\n")
                    
                    attachments = get_attachments(cURL, headers, child_id)
                    for att_name, att_url in tqdm(attachments, desc=f"Retrieving attachments for {child_title}"):
                        f.write(f"            [Attachment] {att_name} -> {att_url}\n")
                
                # Get attachments for top-level pages as well
                attachments = get_attachments(cURL, headers, page_id)
                for att_name, att_url in tqdm(attachments, desc=f"Retrieving attachments for {page_title}"):
                    f.write(f"        [Attachment] {att_name} -> {att_url}\n")

def main():
    cURL = ""
    user_agent = ""
    output_file = "confluence_output.txt"

    usage = 'usage: python3 conf_list.py -c <TARGET URL>'
    
    try:
        opts, args = getopt.getopt(sys.argv[1:], "hc:a:o:", ["help", "url=", "user-agent=", "output="])
    except getopt.GetoptError as err:
        print(str(err))
        print(usage)
        sys.exit(2)
    
    for opt, arg in opts:
        if opt in ("-h", "--help"):
            print(usage)
            sys.exit()
        elif opt in ("-c", "--url"):
            cURL = arg
        elif opt in ("-a", "--user-agent"):
            user_agent = arg
        elif opt in ("-o", "--output"):
            output_file = arg
    
    if not cURL:
        print("\nConfluence URL (-c, --url) is required\n")
        print(usage)
        sys.exit(2)
    
    headers = {"Accept": "application/json"}
    if user_agent:
        headers["User-Agent"] = user_agent
    
    list_all_content(cURL, headers, output_file)
    print(f"[*] Output saved to {output_file}")

if __name__ == "__main__":
    main()
