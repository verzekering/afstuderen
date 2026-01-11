import os
import satellite_images_nso.api.nso_georegion as nso
from settings import nso_username, nso_password, path_geojson, output_path

# Set GDAL_DATA for proper geospatial library functioning
if 'CONDA_PREFIX' in os.environ:
    os.environ['GDAL_DATA'] = os.path.join(os.environ['CONDA_PREFIX'], 'Library', 'share', 'gdal')

# Initialize georegion object
georegion = nso.nso_georegion(
    path_to_geojson=path_geojson, 
    output_folder=output_path,
    username=nso_username,
    password=nso_password
)

# Search for satellite images (80% coverage of your region)
links = georegion.retrieve_download_links(
    max_diff=0.8, 
    start_date="2022-01-01",
    cloud_coverage_whole=60
)

# Filter for high-resolution RGB images
high_res_links = [link for link in links if "30cm" in link and "RGBNED" in link]

# Process images with vegetation index calculation
for link in high_res_links:
    georegion.execute_link(
        link, 
        add_ndvi_band=True,
        delete_zip_file=True,
        plot=False
    )