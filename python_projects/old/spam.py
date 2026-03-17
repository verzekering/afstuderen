from python_projects.beroepsproduct.tsconfig import START_DATE, END_DATE, extent_to_rd, extent_to_ee
import pandas as pd
import matplotlib.pyplot as plt
import hydropandas as hpd
import numpy as np

organisation = "rotterdam"

auth = ("__key__", "D5aclEis.RBUeIvKA6jrLVUzNpPATjvGyLXsLAx7P")

my_extent = extent_to_rd("gw") 
oc = hpd.read_lizard(
    extent=my_extent,
    which_timeseries=["hand", "diver", "diver_validated"],
    datafilters=None,
    combine_method="merge",
    organisation=organisation,
    auth=auth,
)

gw = oc.obs["GMW000000038241001"]

# Create a subset with only this well
oc_subset = hpd.ObsCollection([gw])
oc_subset.plots.section_plot(plot_obs=True)
plt.show()