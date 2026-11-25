import json

import requests

API_KEY = "67f31d80b96cb4f6538137b816a76d26"
BASE_URL = "https://api.vtugate.com/api/v1"
SERVICE_TYPES_URL = f"{BASE_URL}/fetchservices"
PLANS_URL = f"{BASE_URL}/fetchdataplans"

HEADERS = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/x-www-form-urlencoded",
}


def post_form(url, data):
    response = requests.post(url, headers=HEADERS, data=data, timeout=30)
    response.raise_for_status()
    result = response.json()
    if not result.get("status"):
        raise RuntimeError(result.get("message", f"VTUGATE request failed: {url}"))
    return result


services = post_form(SERVICE_TYPES_URL, {"service_type": "data"}).get("data", [])
target_services = [
    service
    for service in services
    if service.get("data_type", "").lower() == "cg"
]

plans_by_service = []
for service in target_services:
    result = post_form(PLANS_URL, {"service_id": service["service_id"]})
    corporate_plans = [
        plan
        for plan in result.get("data", {}).get("data_plans", [])
        if "corporate gifting" in plan.get("name", "").lower()
        or " cg " in f" {plan.get('name', '').lower()} "
    ]
    plans_by_service.append((service, corporate_plans))

print("========== CORPORATE GIFTING (CG) DATA PLANS ==========\n")
if not plans_by_service:
    print("No corporate-gifting (CG) data services are available.")
else:
    for service, plans in plans_by_service:
        print(
            f"--- {service.get('network_name', 'Unknown network')} "
            f"(service_id={service['service_id']}) — {len(plans)} plans ---"
        )
        for plan in plans:
            print(json.dumps(plan, ensure_ascii=False))
