import base64, json, os, requests
from environment import load_environment

load_environment()
def delete_file(key):
    token = os.environ["UPLOADTHING_TOKEN"]
    headers = {"x-uploadthing-api-key": json.loads(base64.b64decode(token))["apiKey"]}

    r = requests.post(
        "https://api.uploadthing.com/v6/deleteFiles",
        headers=headers,
        json={"fileKeys": [key]},
        timeout=30,
    )
    print(r.status_code, r.text)
    return r.json().get("success", False)