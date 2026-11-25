import base64, json, os, requests
from environment import load_environment

load_environment()
API = "https://api.uploadthing.com"

def upload_file(path, ftype="video/mp4"):
    token = os.environ["UPLOADTHING_TOKEN"]
    headers = {"x-uploadthing-api-key": json.loads(base64.b64decode(token))["apiKey"]}
    name = os.path.basename(path)

    prep = requests.post(f"{API}/v7/prepareUpload", headers=headers, timeout=30,
        json={"fileName": name, "fileSize": os.path.getsize(path), "fileType": ftype})
    prep.raise_for_status()
    data = prep.json()

    with open(path, "rb") as f:
        put = requests.put(data["url"], files={"file": (name, f, ftype)}, timeout=300)
    put.raise_for_status()

    key = data["key"]
    url = f"https://utfs.io/f/{key}"
    return key, url