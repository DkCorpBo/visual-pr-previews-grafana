import requests
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

def trigger():
    # Replace with your Flask server URL
    url = 'https://YOUR_FLASK_SERVER_DOMAIN_OR_IP:5000/flask/gitea-webhook'
    headers = {
        'X-Gitea-Event': 'pull_request',
        'Content-Type': 'application/json'
    }
    
    # Payload template matching a Gitea Pull Request synchronise event
    payload = {
        "action": "synchronized",
        "number": 2,
        "pull_request": {
            "number": 2,
            "head": {
                "sha": "YOUR_COMMIT_SHA"
            }
        },
        "repository": {
            "name": "YOUR_REPO_NAME",
            "owner": {
                "username": "YOUR_GITEA_USERNAME"
            }
        }
    }
    
    print("Sending simulated Gitea PR synchronized webhook to Flask...")
    r = requests.post(url, headers=headers, json=payload, verify=False)
    print(f"Flask webhook response: {r.status_code} - {r.text}")

trigger()
