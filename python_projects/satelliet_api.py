import requests
from owslib.wmts import WebMapTileService
from PIL import Image
from io import BytesIO
import matplotlib.pyplot as plt

url = "https://api.satellietdataportaal.nl/v2/stac/search"

payload = {
    "collections": ["Pleiades-NEO_Nederland"],
    "bbox": [3.0, 50.7, 7.3, 53.7],   # hele NL
    "datetime": "2023-01-01T00:00:00Z/2024-12-31T23:59:59Z",
    "limit": 5
}

resp = requests.post(
    url,
    json=payload,
    auth=("1015152@hr.nl", "9d650438"),
    headers={"Accept": "application/json"}
)

from pyproj import Transformer

# Bbox van de eerste feature
bbox = resp.json()['features'][0]['bbox']  # [minx, miny, maxx, maxy] in WGS84
center_x = (bbox[0] + bbox[2]) / 2
center_y = (bbox[1] + bbox[3]) / 2

# Transformeer naar EPSG:28992 (RD)
transformer = Transformer.from_crs("EPSG:4326", "EPSG:28992")
rd_x, rd_y = transformer.transform(center_y, center_x)  # Note: lat, lon

print(f"Center in WGS84: {center_x}, {center_y}")
print(f"Center in RD: {rd_x}, {rd_y}")

# WMTS endpoint
wmts_url = "https://wmts.satellietdataportaal.nl/wmts/Pleiades-NEO-2023-6-RGB/service"

layer = "20230606_105231_PNEO-04_1_27_30cm_RD_8bit_RGB_Kampen"

# Open WMTS
wmts = WebMapTileService(wmts_url)

print("Available tilematrixsets:", list(wmts.tilematrixsets.keys()))

# Kies tilematrix (meestal EPSG:28992)
tilematrixset = 'EPSG:28992'  # Gebruik RD coordinatenstelsel
print("Using tilematrixset:", tilematrixset)
print("Available tilematrices for", tilematrixset, ":", list(wmts.tilematrixsets[tilematrixset].tilematrix.keys()))

tilematrix = '10'
print("Using tilematrix:", tilematrix)

# Nu, voor tilematrix 10, bereken tile row en column
tilematrix_obj = wmts.tilematrixsets[tilematrixset].tilematrix[tilematrix]
scale_denominator = tilematrix_obj.scaledenominator
tile_width = tilematrix_obj.tilewidth
tile_height = tilematrix_obj.tileheight
top_left_x = tilematrix_obj.topleftcorner[0]
top_left_y = tilematrix_obj.topleftcorner[1]

print(f"Scale denominator: {scale_denominator}")
print(f"Top left: {top_left_x}, {top_left_y}")

# Pixel size in meters = scale_denominator * 0.00028 (voor 1:1000 schaal)
pixel_size = scale_denominator * 0.00028
tile_size_m = tile_width * pixel_size

print(f"Pixel size: {pixel_size} m")
print(f"Tile size: {tile_size_m} m")

# Tile column = floor((rd_x - top_left_x) / tile_size_m)
# Tile row = floor((top_left_y - rd_y) / tile_size_m)

column = int((rd_x - top_left_x) / tile_size_m)
row = int((top_left_y - rd_y) / tile_size_m)

print(f"Calculated row: {row}, column: {column}")

# Haal 1 tile op (voorbeeld)
print(f"Fetching tile with row={row}, column={column}")
tile_response = wmts.gettile(
    layer=layer,
    tilematrixset=tilematrixset,
    tilematrix=tilematrix,
    row=row,
    column=column,
    format="image/png"
)

tile_data = tile_response.read()
print("Tile fetched, size:", len(tile_data))

# Print the first 500 bytes as text to see if it's an error
try:
    print("Tile content (first 500 chars):", tile_data[:500].decode('utf-8', errors='ignore'))
except:
    print("Tile is binary")

img = Image.open(BytesIO(tile_data))

plt.imshow(img)
plt.axis("off")
plt.title("Pleiades-NEO WMTS tile")
plt.savefig("c:/afstuderen/python_projects/tile.png")  # Sla op in de script directory
print("Image saved as c:/afstuderen/python_projects/tile.png")