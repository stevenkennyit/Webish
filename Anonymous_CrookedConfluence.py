import requests
import json
import sys
import getopt
import time
import os

# Set that holds all of the pages found in the keyword search
contentSet = set()

# Set these ENV Variables to proxy through burp:
# export REQUESTS_CA_BUNDLE='/path/to/pem/encoded/cert'
# export HTTP_PROXY="http://127.0.0.1:8080"
# export HTTPS_PROXY="http://127.0.0.1:8080"

form_token_headers = {
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "X-Atlassian-Token": "no-check",
}


def getNumberOfPages(query, cURL, default_headers):
    totalSize = 0
    q = "/rest/api/search"
    URL = cURL + q
    response = requests.request("GET", URL, headers=default_headers, params=query)

    jsonResp = response.json()
    totalSize = int(jsonResp["totalSize"])
    return totalSize


def searchKeyWords(path, cURL, default_headers, limit):
    search_term = " "

    try:
        f = open(path, "r")
    except Exception as e:
        print('[*] An Error occurred opening the dictionary file: %s' % str(e))
        sys.exit(2)

    print("[*] Searching for Confluence content for keywords and compiling a list of pages")
    for line in f:
        tempSetCount = len(contentSet)
        count = 0
        search_term = line.strip()
        searchQuery = {"cql": '{text~\"' + search_term + '\"}'}
        totalSize = getNumberOfPages(searchQuery, cURL, default_headers)
        if totalSize:
            print("[*] Setting {total} results for search term: {term}".format(total=totalSize, term=search_term))
            start_point = 1
            if totalSize > limit:
                totalSize = limit
            while start_point < totalSize:
                print("[*] Setting {startpoint} of {total} results for search term: {term}".format(startpoint=start_point, total=totalSize, term=search_term))
                q = "/rest/api/search?start={startpoint}&limit=250".format(startpoint=start_point)
                URL = cURL + q

                response = requests.request("GET", URL, headers=default_headers, params=searchQuery)

                jsonResp = json.loads(response.text)
                for results in jsonResp["results"]:
                    try:
                        pageId = ""
                        id_and_name = ""
                        contentId = results["content"]["id"]
                        pageId_url = results["content"]["_links"]["webui"]
                        page_name = results["content"]["title"]
                        # Some results will have a pageId and some only a contentId.
                        # Need pageId if it exists, otherwise use contentId

                        id_and_name = pageId_url + "," + page_name + "," + search_term
                        contentSet.add(id_and_name)
                    except Exception as e:
                        print("Error: " + str(e))
                start_point += 250

            if len(contentSet) > tempSetCount:
                count = len(contentSet) - tempSetCount
                tempSetCount = len(contentSet)
            print("[*] %i unique pages added to the set for search term: %s." % (count, search_term))
        else:
            print("[*] No documents found for search term: %s" % search_term)
    # print(contentSet)
    print("[*] Compiled set of %i unique pages to download from your search" % len(contentSet))


def saveContent(ogURL):
    print("[*] Saving content to file")
    save_path = "./loot"
    file_name = "confluence_content.txt"
    completeName = os.path.join(save_path, file_name)
    f = open(completeName, "w")
    for page in contentSet:
        pageId = page.split(",")[0]
        pageName = page.split(",")[1]
        searchTerm = page.split(",")[2]
        q = pageId
        URL = ogURL + q
        f.write(URL + "\n" + "      " + pageName + " - Found using term: " + searchTerm + "\n")
    f.close()
    print("[*] Saved content to file")


def main():
    cURL = ""
    dict_path = ""
    user_agent = ""
    limit = sys.maxsize  # default limit

    # usage
    usage = '\nusage: python3 conf_thief.py [-h] -c <TARGET URL> -d <DICTIONARY FILE PATH> [-a] "<UA STRING> [-l] <limit of results>"'

    # try parsing options and arguments
    try:
        opts, args = getopt.getopt(
            sys.argv[1:],
            "hc:d:a:l:",
            ["help", "url=", "dict=", "user-agent=", "limit="],
        )
    except getopt.GetoptError as err:
        print(str(err))
        print(usage)
        sys.exit(2)
    for opt, arg in opts:
        if opt in ("-h", "--help"):
            print(help)
            sys.exit()
        if opt in ("-c", "--url"):
            cURL = arg
        if opt in ("-d", "--dict"):
            dict_path = arg
        if opt in ("-a", "--user-agent"):
            user_agent = arg
        if opt in ("-l", "--limit"):
            limit = int(arg)

    # check for mandatory arguments

    if not dict_path:
        print("\nDictionary Path  (-d, --dict) is a mandatory argument\n")
        print(usage)
        sys.exit(2)
    if not cURL:
        print("\nConfluence URL  (-c, --url) is a mandatory argument\n")
        print(usage)
        sys.exit(2)

    # Strip trailing / from URL if it has one
    if cURL.endswith("/"):
        cURL = cURL[:-1]

    ogURL = cURL

    default_headers = {"Accept": "application/json"}

    # Check for user-agent argument
    if user_agent:
        default_headers["User-Agent"] = user_agent
        form_token_headers["User-Agent"] = user_agent

    searchKeyWords(dict_path, cURL, default_headers, limit)
    saveContent(ogURL)


if __name__ == "__main__":
    main()
