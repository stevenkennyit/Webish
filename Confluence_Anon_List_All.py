import requests
import json
import sys
import getopt
import os

def get_spaces(cURL, headers):
    """Retrieve all spaces in Confluence."""
    url = f"{cURL}/rest/api/space"
    response = requests.get(url, headers=headers)
    spaces = response.json().get("results", [])
    return [space["key"] for space in spaces]

def get_pages_in_space(cURL, headers, space_key):
    """Retrieve all pages within a given space."""
    url = f"{cURL}/rest/api/content?spaceKey={space_key}&expand=space,body.view,version"
    response = requests.get(url, headers=headers)
    pages = response.json().get("results", [])
    return [(page["id"], page["title"]) for page in pages]

def get_attachments(cURL, headers, page_id):
    """Retrieve all attachments from a given page."""
    url = f"{cURL}/rest/api/content/{page_id}/child/attachment"
    response = requests.get(url, headers=headers)
    attachments = response.json().get("results", [])
    return [(att["title"], att["_links"]["download"]) for att in attachments]

def list_all_content(cURL, headers, output_file):
    """List all spaces, pages, and attachments in Confluence and write to file."""
    with open(output_file, "w") as f:
        f.write("[*] Retrieving all spaces...\n")
        spaces = get_spaces(cURL, headers)
        
        for space in spaces:
            f.write(f"[*] Space: {space}\n")
            pages = get_pages_in_space(cURL, headers, space)
            
            for page_id, page_title in pages:
                f.write(f"    [Page] {page_title} (ID: {page_id})\n")
                
                attachments = get_attachments(cURL, headers, page_id)
                for att_name, att_url in attachments:
                    full_url = f"{cURL}{att_url}"
                    f.write(f"        [Attachment] {att_name} -> {full_url}\n")

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
