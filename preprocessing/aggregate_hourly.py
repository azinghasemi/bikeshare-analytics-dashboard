"""
Aggregate 5-minute station snapshots into hourly statistics.
Scheduled to run every hour (or manually via cron).
Writes to station_hourly; logs to pipeline_log.
"""

import os
import sys
import time
import logging
from datetime import datetime, timedelta

import pandas as pd
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

# Allow imports from sibling data_pipeline package
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "data_pipeline"))
from store_to_mysql import store_hourly, log_pipeline_run

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger(__name__)


def _get_engine():
    host = os.getenv("MYSQL_HOST", "localhost")
    port = os.getenv("MYSQL_PORT", "3306")
    user = os.getenv("MYSQL_USER", "root")
    pw   = os.getenv("MYSQL_PASSWORD", "")
    db   = os.getenv("MYSQL_DB", "bikeshare")
    url  = f"mysql+pymysql://{user}:{pw}@{host}:{port}/{db}?charset=utf8mb4"
    return create_engine(url, pool_pre_ping=True)


def fetch_snapshots_for_hour(hour_start: datetime) -> pd.DataFrame:
    """Load all 5-min snapshots for the given UTC hour."""
    hour_end = hour_start + timedelta(hours=1)
    sql = """
        SELECT station_id, snapshot_ts, free_bikes, empty_slots, availability_pct
        FROM station_snapshots
        WHERE snapshot_ts >= :start AND snapshot_ts < :end
    """
    engine = _get_engine()
    df = pd.read_sql(
        text(sql),
        engine,
        params={
            "start": hour_start.strftime("%Y-%m-%d %H:%M:%S"),
            "end":   hour_end.strftime("%Y-%m-%d %H:%M:%S"),
        }
    )
    return df


def aggregate_hour(df: pd.DataFrame, hour_ts: datetime) -> list[dict]:
    """
    Aggregate snapshot DataFrame into one row per station.

    Metrics produced:
        avg_free_bikes      — mean free bikes across all 5-min intervals
        avg_availability_pct— mean availability %
        std_availability    — std dev of availability % (volatility indicator)
        min_availability    — worst availability in the hour
        max_availability    — best availability in the hour
        empty_count         — number of intervals where free_bikes == 0
    """
    if df.empty:
        return []

    df["availability_pct"] = pd.to_numeric(df["availability_pct"], errors="coerce")
    df["free_bikes"]        = pd.to_numeric(df["free_bikes"],       errors="coerce")

    grouped = df.groupby("station_id")
    records = []
    for station_id, grp in grouped:
        records.append({
            "hour_ts":             hour_ts.strftime("%Y-%m-%d %H:%M:%S"),
            "station_id":          station_id,
            "avg_free_bikes":      round(grp["free_bikes"].mean(), 2),
            "avg_availability_pct":round(grp["availability_pct"].mean(), 2),
            "std_availability":    round(grp["availability_pct"].std(ddof=0), 2),
            "min_availability":    round(grp["availability_pct"].min(), 2),
            "max_availability":    round(grp["availability_pct"].max(), 2),
            "empty_count":         int((grp["free_bikes"] == 0).sum()),
        })
    return records


def run_aggregation(target_hour: datetime | None = None) -> int:
    """
    Aggregate one hour of data.
    Defaults to the last completed hour (UTC).
    Returns number of station-hours written.
    """
    if target_hour is None:
        now = datetime.utcnow()
        target_hour = now.replace(minute=0, second=0, microsecond=0) - timedelta(hours=1)

    log.info("Aggregating hour: %s", target_hour.strftime("%Y-%m-%d %H:00"))
    t0 = time.time()

    snapshots = fetch_snapshots_for_hour(target_hour)
    if snapshots.empty:
        log.warning("No snapshots found for %s", target_hour)
        log_pipeline_run("aggregation", "warning", 0,
                         int((time.time() - t0) * 1000),
                         f"No snapshots for {target_hour}")
        return 0

    log.info("  Loaded %d snapshot rows", len(snapshots))
    records = aggregate_hour(snapshots, target_hour)
    stored  = store_hourly(records)
    duration_ms = int((time.time() - t0) * 1000)

    log.info("  Stored %d station-hour rows (%d ms)", stored, duration_ms)
    log_pipeline_run("aggregation", "ok", stored, duration_ms,
                     f"Hour={target_hour.strftime('%Y-%m-%d %H:00')}, "
                     f"stations={stored}, snapshots={len(snapshots)}")
    return stored


def backfill(start: datetime, end: datetime) -> None:
    """Backfill aggregations for a date range (inclusive start, exclusive end)."""
    current = start.replace(minute=0, second=0, microsecond=0)
    while current < end:
        run_aggregation(current)
        current += timedelta(hours=1)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Aggregate bike-share hourly stats")
    parser.add_argument("--backfill-days", type=int, default=0,
                        help="Backfill N days of history (0 = just last completed hour)")
    args = parser.parse_args()

    if args.backfill_days > 0:
        end   = datetime.utcnow().replace(minute=0, second=0, microsecond=0)
        start = end - timedelta(days=args.backfill_days)
        log.info("Backfilling %d days (%s → %s)", args.backfill_days, start, end)
        backfill(start, end)
    else:
        run_aggregation()
