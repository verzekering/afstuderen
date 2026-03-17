import requests
import zipfile
import os

# =========================
# USER INPUT
# =========================

USERNAME = "1015152@hr.nl"
PASSWORD = "9d650438"

COLLECTION = "RapidEye_Nederland"   # satellite
START_DATE = "2017-05-01T00:00:00Z"
END_DATE   = "2017-08-31T23:59:59Z"

# Rijksdriehoek extent (xmin, ymin, xmax, ymax)
BBOX_RD = [89945, 440688, 91552, 441553]

WORKDIR = r"C:\temp\satellite_data"

# =========================
# SETUP
# =========================

os.makedirs(WORKDIR, exist_ok=True)

# Transform bbox to WGS84
import arcpy
sr_rd = arcpy.SpatialReference(28992)  # Rijksdriehoek
sr_wgs84 = arcpy.SpatialReference(4326)  # WGS84

# Create a polygon from bbox
bbox_geom = arcpy.Polygon(arcpy.Array([arcpy.Point(BBOX_RD[0], BBOX_RD[1]), 
                                       arcpy.Point(BBOX_RD[2], BBOX_RD[1]), 
                                       arcpy.Point(BBOX_RD[2], BBOX_RD[3]), 
                                       arcpy.Point(BBOX_RD[0], BBOX_RD[3])]), sr_rd)

# Project to WGS84
bbox_wgs84 = bbox_geom.projectAs(sr_wgs84)
extent = bbox_wgs84.extent

BBOX_WGS84 = [extent.XMin, extent.YMin, extent.XMax, extent.YMax]

STAC_SEARCH_URL = "https://api.satellietdataportaal.nl/v2/stac/search"

payload = {
    "collections": [COLLECTION],
    "bbox": BBOX_WGS84,
    "datetime": f"{START_DATE}/{END_DATE}",
    "limit": 1
}

# =========================
# 1️⃣ STAC SEARCH
# =========================

resp = requests.post(
    STAC_SEARCH_URL,
    json=payload,
    auth=(USERNAME, PASSWORD)
)
resp.raise_for_status()

item = resp.json()["features"][0]
scene_id = item["id"]

print(f"Found scene: {scene_id}")

# =========================
# 2️⃣ DOWNLOAD RAW DATA
# =========================

raw_asset = item["assets"]["RE_RGBREI"]
zip_url = raw_asset["href"]

zip_path = os.path.join(WORKDIR, f"{scene_id}.zip")

print("Download URL:", zip_url)

with requests.get(zip_url, auth=(USERNAME, PASSWORD), stream=True) as r:
    r.raise_for_status()
    total_size = int(r.headers.get('content-length', 0))
    print(f"Total file size: {total_size} bytes")
    downloaded = 0
    with open(zip_path, "wb") as f:
        for chunk in r.iter_content(8192):
            f.write(chunk)
            downloaded += len(chunk)
            if total_size > 0:
                progress = (downloaded / total_size) * 100
                print(f"\rDownloaded: {downloaded}/{total_size} bytes ({progress:.2f}%)", end='')
            else:
                print(f"\rDownloaded: {downloaded} bytes", end='')
    print()  # New line after progress

# =========================
# 3️⃣ EXTRACT
# =========================

extract_dir = os.path.join(WORKDIR, scene_id)
os.makedirs(extract_dir, exist_ok=True)

with zipfile.ZipFile(zip_path) as z:
    z.extractall(extract_dir)

# Find GeoTIFF
tif_path = None
for root, _, files in os.walk(extract_dir):
    for f in files:
        if f.lower().endswith(".tif"):
            tif_path = os.path.join(root, f)
            break

if not tif_path:
    raise RuntimeError("No GeoTIFF found in archive")

print("GeoTIFF:", tif_path)