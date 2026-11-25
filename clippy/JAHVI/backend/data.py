
import requests
import json
from getpass import getpass

API_KEY = "mele_pub_4ad54843127da9e880bf632470c2f136"

url = "https://meledata.ng/api/v1/developer/data/plans"

try:
    response = requests.get(
        url,
        headers={"X-API-Key": API_KEY},
        timeout=30
    )

    print("HTTP Status:", response.status_code)
    print("Response:")

    try:
        result = response.json()
        print(json.dumps(result, indent=2, ensure_ascii=False))

        if response.ok:
            plans = result.get("plans", []) if isinstance(result, dict) else result

            if isinstance(plans, list):
                print(f"\nTotal plans found: {len(plans)}")

                with open("meledata_plans.json", "w", encoding="utf-8") as f:
                    json.dump(plans, f, indent=2, ensure_ascii=False)

                print("Saved to meledata_plans.json")

    except ValueError:
        print(response.text[:5000])

except requests.RequestException as e:
    print("Request failed:", e)
