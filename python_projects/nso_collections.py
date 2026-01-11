import requests

BASE_URL = "https://api.satellietdataportaal.nl/v2/stac"
SEARCH_URL = f"{BASE_URL}/search"

USERNAME = "1015152@hr.nl"
PASSWORD = "9d650438"

# =========================
# 1️⃣ GET COLLECTIONS
# =========================

collections_resp = requests.get(
    "https://api.satellietdataportaal.nl/v2/stac/collections",
    auth=(USERNAME, PASSWORD)
)
collections_resp.raise_for_status()

collections_resp.raise_for_status()

collections = collections_resp.json()["collections"]

print(f"Found {len(collections)} collections\n")

# =========================
# 2️⃣ PER COLLECTION: LIST ASSETS
# =========================

for col in collections:
    col_id = col["id"]
    print("=" * 60)
    print(f"COLLECTION: {col_id}")

    payload = {
        "collections": [col_id],
        "limit": 1
    }

    resp = requests.post(
        SEARCH_URL,
        json=payload,
        auth=(USERNAME, PASSWORD)
    )

    if resp.status_code != 200:
        print("  ❌ Search failed")
        continue

    data = resp.json()

    if not data.get("features"):
        print("  ⚠️ No items found")
        continue

    item = data["features"][0]
    assets = item.get("assets", {})

    if not assets:
        print("  ⚠️ No assets found")
        continue

    print("  Assets:")
    for name, asset in assets.items():
        print(f"   - {name}")
        print(f"     title: {asset.get('title')}")
        print(f"     gsd: {asset.get('gsd')}")
        print(f"     type: {asset.get('type')}")

print("\nDone.")