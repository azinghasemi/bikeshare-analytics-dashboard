"""
Batch upsert helpers for writing collected data into MySQL.
Called by collect_live_data.py and aggregate_hourly.py.
"""

import os
import logging
from datetime import datetime
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger(__name__)

_engine = None


def _get_engine():
    global _engine
    if _engine is None:
        host   = os.getenv("MYSQL_HOST", "localhost")
        port   = os.getenv("MYSQL_PORT", "3306")
        user   = os.getenv("MYSQL_USER", "root")
        pw     = os.getenv("MYSQL_PASSWORD", "")
        db     = os.getenv("MYSQL_DB", "bikeshare")
        url    = f"mysql+pymysql://{user}:{pw}@{host}:{port}/{db}?charset=utf8mb4"
        _engine = create_engine(url, pool_pre_ping=True, pool_size=5)
    return _engine


# ---------------------------------------------------------------------------
# Station snapshots
# ---------------------------------------------------------------------------

_INSERT_SNAPSHOT = """
INSERT INTO station_snapshots
    (snapshot_ts, station_id, station_name, latitude, longitude,
     free_bikes, empty_slots, district)
VALUES
    (:snapshot_ts, :station_id, :station_name, :latitude, :longitude,
     :free_bikes, :empty_slots, :district)
"""

def store_snapshots(records: list[dict]) -> int:
    """Insert station snapshot rows; returns number of rows inserted."""
    if not records:
        return 0
    with _get_engine().begin() as conn:
        conn.execute(text(_INSERT_SNAPSHOT), records)
    return len(records)


# ---------------------------------------------------------------------------
# Weather observations
# ---------------------------------------------------------------------------

_INSERT_WEATHER = """
INSERT INTO weather_observations
    (observed_ts, temperature_c, feels_like_c, humidity_pct,
     wind_speed_ms, weather_main, is_rain, is_snow, visibility_m)
VALUES
    (:observed_ts, :temperature_c, :feels_like_c, :humidity_pct,
     :wind_speed_ms, :weather_main, :is_rain, :is_snow, :visibility_m)
"""

def store_weather(record: dict) -> None:
    with _get_engine().begin() as conn:
        conn.execute(text(_INSERT_WEATHER), record)


# ---------------------------------------------------------------------------
# Hourly aggregates (upsert)
# ---------------------------------------------------------------------------

_UPSERT_HOURLY = """
INSERT INTO station_hourly
    (hour_ts, station_id, avg_free_bikes, avg_availability_pct,
     std_availability, min_availability, max_availability, empty_count)
VALUES
    (:hour_ts, :station_id, :avg_free_bikes, :avg_availability_pct,
     :std_availability, :min_availability, :max_availability, :empty_count)
ON DUPLICATE KEY UPDATE
    avg_free_bikes       = VALUES(avg_free_bikes),
    avg_availability_pct = VALUES(avg_availability_pct),
    std_availability     = VALUES(std_availability),
    min_availability     = VALUES(min_availability),
    max_availability     = VALUES(max_availability),
    empty_count          = VALUES(empty_count)
"""

def store_hourly(records: list[dict]) -> int:
    if not records:
        return 0
    with _get_engine().begin() as conn:
        conn.execute(text(_UPSERT_HOURLY), records)
    return len(records)


# ---------------------------------------------------------------------------
# Availability forecasts
# ---------------------------------------------------------------------------

_INSERT_FORECAST = """
INSERT INTO availability_forecasts
    (forecast_run_ts, target_ts, station_id, horizon_hours, pred_availability)
VALUES
    (:forecast_run_ts, :target_ts, :station_id, :horizon_hours, :pred_availability)
"""

def store_forecasts(records: list[dict]) -> int:
    if not records:
        return 0
    with _get_engine().begin() as conn:
        conn.execute(text(_INSERT_FORECAST), records)
    return len(records)


# ---------------------------------------------------------------------------
# Pipeline health log
# ---------------------------------------------------------------------------

_INSERT_LOG = """
INSERT INTO pipeline_log
    (run_ts, source, status, records_in, message, duration_ms)
VALUES
    (:run_ts, :source, :status, :records_in, :message, :duration_ms)
"""

def log_pipeline_run(source: str, status: str, records_in: int,
                     duration_ms: int, message: str = "") -> None:
    try:
        with _get_engine().begin() as conn:
            conn.execute(text(_INSERT_LOG), {
                "run_ts":      datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
                "source":      source,
                "status":      status,
                "records_in":  records_in,
                "message":     message[:65535] if message else "",
                "duration_ms": duration_ms,
            })
    except Exception as exc:
        log.error("Failed to write pipeline log: %s", exc)
