import ee
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from python_projects.beroepsproduct.tsconfig import extent_to_ee, NDVI_START_DATE, NDVI_END_DATE


def compute_monthly_ndvi_series(roi=None, start_date=None, end_date=None, cloud_pct=60):
    """Return a pandas Series (monthly) of mean NDVI over roi between start_date and end_date.
    Uses COPERNICUS/S2_SR monthly median composites.
    """
    if roi is None:
        roi = ee.Geometry.Rectangle(extent_to_ee('ndvi'))
    if start_date is None:
        start_date = NDVI_START_DATE
    if end_date is None:
        end_date = NDVI_END_DATE

    col = (
        ee.ImageCollection('COPERNICUS/S2_SR')
        .filterBounds(roi)
        .filterDate(start_date, end_date)
        .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', cloud_pct))
    )

    months = pd.date_range(start=start_date, end=end_date, freq='MS')
    values = []
    dates = []

    for m in months:
        m_start = m.strftime('%Y-%m-%d')
        next_m = (m + pd.offsets.MonthBegin(1)).strftime('%Y-%m-%d')
        sub = col.filterDate(m_start, next_m)
        try:
            count = sub.size().getInfo()
        except Exception:
            count = 0
        if count == 0:
            values.append(np.nan)
            dates.append(m)
            continue

        img = sub.median().normalizedDifference(['B8', 'B4']).rename('NDVI')
        try:
            mean = img.reduceRegion(ee.Reducer.mean(), roi, scale=10, maxPixels=1e9).get('NDVI').getInfo()
        except Exception:
            mean = None
        if mean is None:
            values.append(np.nan)
        else:
            values.append(float(mean))
        dates.append(m)

    s = pd.Series(values, index=pd.DatetimeIndex(dates))
    s.name = 'NDVI'
    return s


def compute_thresholds(series, percentile=0.30, smooth_window=3):
    """Return fixed threshold (scalar) and variable monthly threshold (series aligned with input index).
    Variable monthly threshold is monthly percentile interpolated and smoothed with rolling window (in months).
    """
    threshold_fixed = series.quantile(percentile)

    monthly_threshold = (
        series.groupby(series.index.month)
        .quantile(percentile)
        .reindex(range(1, 13))
    )
    monthly_threshold = monthly_threshold.interpolate(method='linear')

    threshold_variable = series.index.to_series().map(lambda d: monthly_threshold.loc[d.month])
    threshold_variable = threshold_variable.rolling(window=smooth_window, min_periods=1).mean()

    return threshold_fixed, threshold_variable


def plot_ndvi_with_thresholds(ndvi_series, threshold_fixed, threshold_variable=None, percentile=0.3, ax=None):
    if ax is None:
        fig, ax = plt.subplots(figsize=(12, 4))
    ax.plot(ndvi_series.index, ndvi_series.values, color='green', label='NDVI (monthly median)')
    ax.axhline(threshold_fixed, color='orange', linewidth=2, label=f'NDVI fixed ({int(percentile*100)}th pct)')
    if threshold_variable is not None:
        ax.plot(threshold_variable.index, threshold_variable.values, color='red', linewidth=2, label='NDVI variable (monthly + smooth)')

    is_stress_fixed = ndvi_series <= threshold_fixed
    if threshold_variable is not None:
        is_stress_variable = ndvi_series <= threshold_variable
    else:
        is_stress_variable = None

    ax.fill_between(ndvi_series.index, ndvi_series.values, threshold_fixed, where=is_stress_fixed, color='orange', alpha=0.3, interpolate=True, label='NDVI stress (fixed)')
    if is_stress_variable is not None:
        ax.fill_between(ndvi_series.index, ndvi_series.values, threshold_variable, where=is_stress_variable, color='red', alpha=0.2, interpolate=True, label='NDVI stress (variable)')

    ax.set_ylabel('NDVI')
    ax.set_xlabel('Date')
    ax.set_title('NDVI time series with fixed and variable thresholds')
    ax.legend()
    plt.tight_layout()
    return ax


def compare_with_groundwater(ndvi_series, ndvi_fixed_flag, ndvi_variable_flag, gw_daily, gw_fixed_flag, gw_variable_flag):
    """Compare monthly NDVI flags with groundwater daily flags by aggregating groundwater to monthly (any-day stressed).
    Returns a DataFrame with monthly state categories and draws a timeline plot similar to the notebook's example.
    """
    ndvi_month = ndvi_series.index.to_period('M').to_timestamp()

    # Aggregate groundwater daily flags to month (any day in month stressed -> month stressed)
    gw_fixed_month = gw_fixed_flag.resample('MS').max().reindex(ndvi_month, method='nearest', fill_value=0).astype(bool)
    gw_variable_month = gw_variable_flag.resample('MS').max().reindex(ndvi_month, method='nearest', fill_value=0).astype(bool)

    ndvi_fixed_month = ndvi_fixed_flag.reindex(ndvi_month, method='nearest', fill_value=False).astype(bool)
    ndvi_variable_month = ndvi_variable_flag.reindex(ndvi_month, method='nearest', fill_value=False).astype(bool)

    months = ndvi_month
    rows = []
    for dt in months:
        gw_f = bool(gw_fixed_month.loc[dt])
        gw_v = bool(gw_variable_month.loc[dt])
        nd_f = bool(ndvi_fixed_month.loc[dt])
        nd_v = bool(ndvi_variable_month.loc[dt])
        rows.append({'date': dt, 'gw_fixed': gw_f, 'gw_variable': gw_v, 'ndvi_fixed': nd_f, 'ndvi_variable': nd_v})
    df = pd.DataFrame(rows).set_index('date')

    # For simplicity compare GW variable and fixed separately with NDVI fixed
    fig, ax = plt.subplots(figsize=(12, 2))
    y = 0
    height = 0.8

    # Create color categories for GW-fixed vs NDVI-fixed
    states = []
    for idx, r in df.iterrows():
        gw = r['gw_fixed']
        nd = r['ndvi_fixed']
        if gw and nd:
            color = 'red'
            label = 'Both (GW drought + NDVI stress)'
        elif gw and not nd:
            color = 'blue'
            label = 'GW drought only'
        elif nd and not gw:
            color = 'green'
            label = 'NDVI stress only'
        else:
            color = 'lightgrey'
            label = 'Neither'
        ax.barh(y, pd.Timedelta(30, unit='D'), left=idx, height=height, color=color)
    ax.set_yticks([])
    ax.set_xlabel('Date')
    ax.set_title('Monthly comparison: GW fixed vs NDVI fixed (monthly bins)')
    plt.tight_layout()
    return df


if __name__ == '__main__':
    print('This module provides compute_monthly_ndvi_series(), compute_thresholds(), plot_ndvi_with_thresholds(), and compare_with_groundwater().')
    print('Import and call these from your notebook; pass your groundwater daily series `ts_daily` and drought flags `is_drought_fixed`/`is_drought_variable` if you want comparisons.')
