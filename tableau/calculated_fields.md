# Tableau Calculated Fields

All custom calculated fields used across the three dashboards.

---

## Part A — Historical Analysis

### Availability Risk Level
Classifies each station-hour into a risk tier for the geographic map.

```
IF [Avg Availability Pct] < 10 THEN "Critical"
ELSEIF [Avg Availability Pct] < 25 THEN "Low"
ELSEIF [Avg Availability Pct] < 60 THEN "Medium"
ELSE "High"
END
```

### Vacancy Frequency (%)
Proportion of all hourly readings where the station was empty.

```
SUM([Empty Count]) / SUM([Total Intervals]) * 100
```

### 7-Day Rolling Average Availability
Used in the temporal trend line chart. Computed at the dashboard level via a table calculation.

```
WINDOW_AVG(AVG([Avg Availability Pct]), -83, 0)
```
*(168 hours = 7 days; 84 periods look-back at hourly grain)*

### Hour × Day Heatmap Value
Cell colour in the Hour × Day-of-Week heatmap.

```
AVG([Avg Availability Pct])
```

### STD Bucket (for scatter clustering)
Bins stations into volatility quartiles for the AVG vs STD scatter.

```
IF [Std Availability] < 10 THEN "Stable (σ<10)"
ELSEIF [Std Availability] < 20 THEN "Moderate (σ<20)"
ELSEIF [Std Availability] < 30 THEN "Variable (σ<30)"
ELSE "Highly Variable (σ≥30)"
END
```

### Rain Impact Label
Categorical label for rain vs no-rain comparison bars.

```
IF [Is Rain] = 1 THEN "Rainy" ELSE "Dry" END
```

---

## Part B — Live Monitoring

### System Availability %
KPI tile — system-wide mean availability from latest snapshot.

```
AVG([Availability Pct])
```

### Empty Station Count
Number of stations currently at 0 free bikes.

```
COUNTD(IF [Free Bikes] = 0 THEN [Station Id] END)
```

### Alert Stations
Stations below 10% availability in the most recent snapshot.

```
IF [Availability Pct] < 10 THEN [Station Name] END
```

### Hours Since Last Update
Freshness indicator in the live dashboard header.

```
DATEDIFF('hour', MAX([Snapshot Ts]), NOW())
```

### Station Status
Traffic-light status for the live station table.

```
IF [Free Bikes] = 0 THEN "Empty"
ELSEIF [Availability Pct] < 20 THEN "Critical"
ELSEIF [Availability Pct] < 40 THEN "Low"
ELSE "OK"
END
```

---

## Part C — Forecasting & Decision Support

### Forecast Error (MAE)
Absolute error between predicted and actual availability.

```
ABS([Pred Availability] - [Actual Availability])
```

### Error Band
Whether the forecast was within acceptable tolerance (±10 pp).

```
IF ABS([Pred Availability] - [Actual Availability]) <= 10
THEN "Within ±10 pp"
ELSE "Outside ±10 pp"
END
```

### Forecast vs Actual Divergence
Signed error — positive means model over-predicted availability.

```
[Pred Availability] - [Actual Availability]
```

### Peak Hour Flag
Highlights rush-hour rows in the forecast comparison table.

```
IF DATEPART('hour', [Target Ts]) IN (7, 8, 9, 17, 18, 19)
THEN "Peak"
ELSE "Off-Peak"
END
```

### TabPy — 1h Forecast (live Tableau calculation)
Calls the TabPy-registered XGBoost model directly from Tableau.

```
SCRIPT_REAL(
  "return tabpy.query('predict_availability_1h',
     _arg1, _arg2, _arg3, _arg4, _arg5, _arg6)['response']",
  ATTR([Station Id]),
  ATTR(DATEPART('hour', NOW())),
  ATTR(DATEPART('weekday', NOW()) - 1),
  AVG([Lag 1h]),
  AVG([Lag 24h]),
  AVG([Roll Mean 3h])
)
```
*(Repeat for `predict_availability_3h`, `_6h`, `_12h` as needed)*

---

## Colour Palettes

| Dashboard element     | Palette                              |
|-----------------------|--------------------------------------|
| Risk level (map)      | Red (#e74c3c) → Amber → Green (#27ae60) |
| Availability heatmap  | Sequential blue (light = low, dark = high) |
| Station status        | Traffic light: red / amber / green   |
| Forecast error band   | Green (within) / Red (outside)       |
| Weather comparison    | Custom diverging: blue (rain) / orange (dry) |
