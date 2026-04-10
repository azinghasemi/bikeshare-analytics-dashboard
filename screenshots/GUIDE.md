# Screenshot Guide

Take these 7 screenshots and save them here with the exact filenames below.
All images should be **1400px wide minimum**, saved as PNG.

---

## 01_station_risk_map.png
**What:** Tableau geographic map of Berlin stations coloured by vacancy risk level
- Zoom to show Berlin city centre and surrounding districts
- Make sure the legend is visible (Critical / Low / Medium / High)
- Ideal time: weekday morning when critical stations are most visible

## 02_heatmap_hourly.png
**What:** Hour × Day-of-week heatmap (Part A dashboard)
- Should show the two clear commuter peaks (7–9am, 5–7pm) in dark colour
- Include the colour legend on the right
- Crop to the heatmap + title only, no unnecessary whitespace

## 03_scatter_variability.png
**What:** AVG Availability vs STD scatter plot with station clusters
- Make sure station labels are visible for the extreme outliers
- Reference lines for AVG and STD should be visible
- Cluster colour legend visible

## 04_flask_health.png
**What:** Flask health monitor at http://localhost:5000
- Start the pipeline and wait for at least 3 sources to show "OK" status
- KPI tiles should show non-zero record counts
- Use browser zoom 90% for a clean screenshot
- Crop to the browser content area (no browser chrome needed)

## 05_live_kpi_dashboard.png
**What:** Part B live Tableau dashboard showing KPI tiles
- Must show: system availability %, empty station count, alert list
- Ideally taken during off-peak hours so the system is not fully alert-red

## 06_forecast_accuracy.png
**What:** Part C forecast vs actual comparison chart
- Show at least the 1h and 3h horizon comparison
- The "Within ±10 pp" green band should be visible
- Peak hour rows highlighted

## 07_streamlit_demo.png
**What:** The Streamlit app running at http://localhost:8501
- Run: `streamlit run app.py`
- Should show: live station map + KPI metrics at the top
- Use browser width ~1400px for a clean layout
- Crop to content area

---

After adding all screenshots, commit and push. The README already references these filenames.
