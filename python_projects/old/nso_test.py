import satellite_images_nso.api.nso_georegion as nso
from settings import nso_username, nso_password, path_geojson, output_path

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
high_res_links = links[
    (links['resolution'] == "30cm") & 
    (links["link"].str.contains("RGBNED"))
].sort_values("percentage_geojson")

# Process images with vegetation index calculation
for _, row in high_res_links.iterrows():
    georegion.execute_link(
        row["link"], 
        add_ndvi_band=True,
        delete_zip_file=True,
        plot=False
    )