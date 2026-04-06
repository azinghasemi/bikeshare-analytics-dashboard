# Bike-Share Analytics Dashboard

A full-stack data analytics system for urban bike-sharing operations — combining **real-time monitoring**, **historical pattern analysis**, and **short-term availability forecasting** via Tableau, Python, and MySQL.

> By 2022 there were 2,000+ bike-sharing systems worldwide (~9M bikes). Station imbalance — not total demand — is the primary operational problem. This project builds a decision-support system to detect, predict, and act on that imbalance.

---

## System Architecture

```
Citybikes API (Nextbike Berlin)  ──┐
OpenWeatherMap API               ──┤──► MySQL ──► Tableau Dashboards
Open-Meteo API                   ──┘         └──► TabPy (ML forecasts)
                                                   └──► Flask Health Monitor
```

**Data volume:** 20M+ records collected at 5-minute intervals over several months  
**Coverage:** 2,000+ stations across Berlin

---

## Three Analytical Parts

### Part A — Historical Analysis (Tableau)
- Station variability: AVG vs STD scatter with clustering and reference lines
- Geographic map: station vacancy frequency coloured by risk level
- Temporal trends: hourly line chart, 7-day moving average, Hour × Day-of-Week heatmap
- Weather analysis: temperature vs availability scatter, rain impact comparison

### Part B — Live Monitoring Pipeline
- Collects Citybikes + weather data every **5 minutes** → stores to MySQL
- Flask health dashboard monitors API status and ingestion pipeline
- Live Tableau dashboard shows station states with up to 24h of data
- KPI tiles: system-wide availability %, empty station count, alert list

### Part C — Forecasting & Decision Support
- XGBoost regressor predicts availability **1h, 3h, 6h, 12h** ahead
- Features: lag values (1h, 24h, 48h), rolling averages (3h, 6h), historical same-hour averages
- Connected to Tableau via **TabPy** for in-dashboard prediction
- Forecast vs actual comparison dashboard highlights model weaknesses at peak hours

---

## Project Structure

```
bikeshare-analytics-dashboard/
├── data_pipeline/
│   ├── collect_live_data.py       ← Citybikes + OpenWeatherMap collector (every 5 min)
│   ├── store_to_mysql.py          ← Batch upsert into MySQL
│   └── pipeline_health.py        ← Flask health monitor for ingestion status
├── preprocessing/
│   ├── aggregate_hourly.py        ← 5-min → hourly aggregation + derived metrics
│   └── feature_engineering.py    ← Lag, rolling, and historical average features
├── forecasting/
│   └── availability_forecast.py   ← XGBoost model training + TabPy server function
├── database/
│   └── schema.sql                 ← MySQL schema for bike + weather tables
├── notebooks/
│   └── historical_analysis.ipynb  ← EDA: scatter, heatmap, temporal, weather charts
├── tableau/
│   └── calculated_fields.md       ← All Tableau calculated fields documented
├── requirements.txt
└── README.md
```

---

## Key Findings

| Finding | Operational Implication |
|---------|------------------------|
| Peak demand: weekdays 7–9am & 5–7pm | Pre-position bikes before peak, not during |
| Weekends: flat, unpredictable pattern | Separate weekend vs weekday rebalancing plans |
| Some stations persistently empty/full | Structural issue → CAPEX/removal decision, not rebalancing |
| Average availability masks station-level risk | Monitor % of near-empty stations, not system average |
| Temperature ↓ → availability more erratic | Cold-weather contingency plans needed |
| Rain: small but statistically significant drop | Mild weather buffer in rebalancing model |

**Core insight:** The challenge is **unbalanced distribution**, not insufficient supply. Smart rebalancing (OPEX) outperforms adding more bikes (CAPEX).

---

## Setup

### 1. Database
```bash
mysql -u root -p -e "CREATE DATABASE bikeshare;"
mysql -u root -p bikeshare < database/schema.sql
```

### 2. Environment
```bash
pip install -r requirements.txt
cp .env.example .env   # add your API keys
```

### 3. Start live collection (runs every 5 minutes)
```bash
python data_pipeline/collect_live_data.py
```

### 4. Flask health monitor
```bash
python data_pipeline/pipeline_health.py
# Visit http://localhost:5000
```

### 5. Train forecast model
```bash
python forecasting/availability_forecast.py
```

### 6. Start TabPy server (for Tableau integration)
```bash
tabpy
# Tableau connects to localhost:9004
```

### 7. Historical analysis notebook
```bash
jupyter notebook notebooks/historical_analysis.ipynb
```

---

## APIs Used

| API | Purpose | Interval |
|-----|---------|----------|
| [Citybikes API](https://api.citybik.es/v2/) | Live station data (Nextbike Berlin) | 5 min |
| [OpenWeatherMap](https://openweathermap.org/api) | Current weather | 5 min |
| [Open-Meteo](https://open-meteo.com/) | Weather forecast (for predictive features) | Hourly |

---

## Requirements

- Python 3.8+, MySQL 8.0+, Tableau Desktop (2023+), TabPy
- See `requirements.txt` for Python packages
