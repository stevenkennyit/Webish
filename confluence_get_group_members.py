#!/usr/bin/python3

# import necessary packages
import requests
import json
import logging
import os
import sys

# configure logging
logging.basicConfig(level=logging.INFO)

class ConfluenceAPI:
    def __init__(self, base_url, api_endpoint):
        """
        Initializes a Confluence API instance.

        Args:
        - base_url (str): the base URL of the Confluence Data Center environment.
        - api_endpoint (str): the REST API endpoint to call.

        Returns:
        - None
        """
        self.base_url = base_url
        self.api_endpoint = api_endpoint
        self.headers = {'X-Atlassian-Token': 'no-check', 'Content-Type': 'application/json'}

    def get_all_users(self):
        """
        Retrieves all users in the 'confluence-users' group.

        Args:
        - None

        Returns:
        - user_list (list): a list containing all usernames in the 'confluence-users' group.
        """
        # set the URL for the group's members endpoint
        member_api_url = self.base_url + self.api_endpoint
        # create an empty list to store user names
        user_list = []

        # loop through all pages of group members
        while True:
            # make a GET request to the group's members endpoint
            req = requests.get(member_api_url, headers=self.headers)
            # check for errors
            if req.status_code != 200:
                logging.error(f"Error retrieving members: {req.text}")
                break

            # parse the response data as JSON
            data = json.loads(req.text)

            # loop through all members returned in the response
            for result in data['results']:
                user = result['username']
                logging.info(f"Retrieved user: {user}")
                # add the username to the user_list
                user_list.append(user)

            # if there are more pages of members, update the URL and continue looping
            if "next" in data['_links']:
                member_api_url = self.base_url + data['_links']['next']
            else:
                break

        return user_list

if __name__ == '__main__':
    # Check if the number of command-line arguments is correct
    if len(sys.argv) != 4:
        print("Usage: python3 script.py <url> <api_endpoint> <output_file>")
        sys.exit(1)

    # Extract command-line arguments
    url = sys.argv[1]
    api_endpoint = sys.argv[2]
    output_file = sys.argv[3]

    # instantiate new API class
    api = ConfluenceAPI(url, api_endpoint)
    
    # perform user data collection
    user_list = api.get_all_users()
    
    # write list of users to file
    with open(output_file, 'w') as f:
        for user in user_list:
            f.write(user + '\n')

    print(f"Users in 'confluence-users' group written to {output_file}")
