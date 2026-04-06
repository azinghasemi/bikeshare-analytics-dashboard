"""
Collect live bike-share and weather data every 5 minutes.
Sources: Citybikes API (Nextbike Berlin) + OpenWeatherMap
"""

import os
import time
import logging
import requests
import schedule
from datetime import datetime
from dotenv import load_dotenv
from store_to_mysql import store_snapshots, store_weather, log_pipeline_run

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger(__name__)

CITYBIKES_URL = "https://api.citybik.es/v2/networks/{network}"
OPENWEATHER_URL = "https://api.openweathermap.org/data/2.5/weather"

NETWORK = os.getenv("CITYBIKES_NETWORK", "nextbike-berlin")
OWM_KEY = os.getenv("OPENWEATHERMAP_API_KEY")

# Berlin coordinates (used for weather lookup)
BERLIN_LAT = 52.5200
BERLIN_LON = 13.4050


def fetch_citybikes() -> list[dict]:
    """Fetch all station snapshots from Citybikes API."""
    url = CITYBIKES_URL.format(network=NETWORK)
    resp = requests.get(url, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    stations = data["network"]["stations"]
    snapshot_ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

    records = []
    for s in stations:
        extra = s.get("extra", {})
        records.append({
            "snapshot_ts": snapshot_ts,
            "station_id":  s["id"],
            "station_name": s.get("name", ""),
            "latitude":    s.get("latitude"),
            "longitude":   s.get("longitude"),
            "free_bikes":  s.get("free_bikes", 0),
            "empty_slots": s.get("empty_slots", 0),
            "district":    extra.get("district") or _infer_district(s.get("name", "")),
        })
    return records


def fetch_weather() -> dict | None:
    """Fetch current weather for Berlin from OpenWeatherMap."""
    if not OWM_KEY:
        log.warning("OPENWEATHERMAP_API_KEY not set — skipping weather collection")
        return None

    params = {
        "lat":   BERLIN_LAT,
        "lon":   BERLIN_LON,
        "appid": OWM_KEY,
        "units": "metric",
    }
    resp = requests.get(OPENWEATHER_URL, params=params, timeout=10)
    resp.raise_for_status()
    d = resp.json()

    weather_main = d["weather"][0]["main"] if d.get("weather") else ""
    return {
        "observed_ts":   datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
        "temperature_c": d["main"]["temp"],
        "feels_like_c":  d["main"]["feels_like"],
        "humidity_pct":  d["main"]["humidity"],
        "wind_speed_ms": d.get("wind", {}).get("speed", 0),
        "weather_main":  weather_main,
        "is_rain":       1 if weather_main in ("Rain", "Drizzle", "Thunderstorm") else 0,
        "is_snow":       1 if weather_main == "Snow" else 0,
        "visibility_m":  d.get("visibility", None),
    }


def _infer_district(name: str) -> str | None:
    """Best-effort district extraction from station name (Berlin-specific)."""
    berlin_districts = [
        "Mitte", "Prenzlauer Berg", "Friedrichshain", "Kreuzberg",
        "Neukölln", "Tempelhof", "Schöneberg", "Charlottenburg",
        "Spandau", "Steglitz", "Zehlendorf", "Reinickendorf",
        "Pankow", "Lichtenberg", "Marzahn", "Treptow", "Köpenick",
        "Wilmersdorf", "Tiergarten", "Wedding",
    ]
    for district in berlin_districts:
        if district.lower() in name.lower():
            return district
    return None


def collect_cycle():
    """One collection cycle: bikes + weather → MySQL."""
    cycle_start = time.time()

    # --- Citybikes ---
    try:
        t0 = time.time()
        snapshots = fetch_citybikes()
        store_snapshots(snapshots)
        duration_ms = int((time.time() - t0) * 1000)
        log_pipeline_run("citybikes", "ok", len(snapshots), duration_ms,
                         f"Stored {len(snapshots)} station snapshots")
        log.info("Citybikes: %d stations stored (%d ms)", len(snapshots), duration_ms)
    except Exception as exc:
        log.error("Citybikes collection failed: %s", exc)
        log_pipeline_run("citybikes", "error", 0, 0, str(exc))

    # --- Weather ---
    try:
        t0 = time.time()
        weather = fetch_weather()
        if weather:
            store_weather(weather)
            duration_ms = int((time.time() - t0) * 1000)
            log_pipeline_run("openweathermap", "ok", 1, duration_ms,
                             f"Temp={weather['temperature_c']}°C, {weather['weather_main']}")
            log.info("Weather: %.1f°C, %s (%d ms)",
                     weather["temperature_c"], weather["weather_main"], duration_ms)
    except Exception as exc:
        log.error("Weather collection failed: %s", exc)
        log_pipeline_run("openweathermap", "error", 0, 0, str(exc))

    log.info("Cycle completed in %.1f s", time.time() - cycle_start)


def main():
    log.info("Starting live data collection — network: %s, interval: 5 min", NETWORK)
    collect_cycle()                          # run immediately on startup
    schedule.every(5).minutes.do(collect_cycle)

    while True:
        schedule.run_pending()
        time.sleep(10)


if __name__ == "__main__":
    main()
