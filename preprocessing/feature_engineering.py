"""
Build the feature matrix for availability forecasting.
Reads station_hourly (+ weather_observations) from MySQL,
produces a DataFrame ready for XGBoost training/inference.

Feature groups
--------------
Time features   : hour_of_day, day_of_week, is_weekend, is_rush_hour
Lag features    : availability 1 h, 3 h, 6 h, 24 h, 48 h ago
Rolling averages: 3-hour and 6-hour trailing mean availability
Historical mean : same hour × same day-of-week average (long-run pattern)
Weather         : temperature_c, humidity_pct, wind_speed_ms, is_rain, is_snow
"""

import os
import logging
from datetime import datetime

import numpy as np
import pandas as pd
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv()
log = logging.getLogger(__name__)


def _get_engine():
    host = os.getenv("MYSQL_HOST", "localhost")
    port = os.getenv("MYSQL_PORT", "3306")
    user = os.getenv("MYSQL_USER", "root")
    pw   = os.getenv("MYSQL_PASSWORD", "")
    db   = os.getenv("MYSQL_DB", "bikeshare")
    url  = f"mysql+pymysql://{user}:{pw}@{host}:{port}/{db}?charset=utf8mb4"
    return create_engine(url, pool_pre_ping=True)


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_hourly(start: str | None = None, end: str | None = None) -> pd.DataFrame:
    """Load station_hourly within an optional datetime window."""
    where = ""
    params = {}
    if start and end:
        where = "WHERE hour_ts BETWEEN :start AND :end"
        params = {"start": start, "end": end}
    elif start:
        where = "WHERE hour_ts >= :start"
        params = {"start": start}

    sql = f"""
        SELECT station_id, hour_ts,
               avg_free_bikes, avg_availability_pct,
               std_availability, min_availability, max_availability, empty_count
        FROM station_hourly
        {where}
        ORDER BY station_id, hour_ts
    """
    engine = _get_engine()
    df = pd.read_sql(text(sql), engine, params=params, parse_dates=["hour_ts"])
    log.info("Loaded %d hourly rows", len(df))
    return df


def load_weather(start: str | None = None, end: str | None = None) -> pd.DataFrame:
    """Load weather observations, resampled to the nearest hour."""
    where = ""
    params = {}
    if start and end:
        where = "WHERE observed_ts BETWEEN :start AND :end"
        params = {"start": start, "end": end}

    sql = f"""
        SELECT observed_ts, temperature_c, feels_like_c, humidity_pct,
               wind_speed_ms, is_rain, is_snow
        FROM weather_observations
        {where}
        ORDER BY observed_ts
    """
    engine = _get_engine()
    df = pd.read_sql(text(sql), engine, params=params, parse_dates=["observed_ts"])
    if df.empty:
        return df

    df = df.set_index("observed_ts")
    numeric_cols = ["temperature_c", "feels_like_c", "humidity_pct",
                    "wind_speed_ms", "is_rain", "is_snow"]
    df = df[numeric_cols].resample("1h").mean().reset_index()
    df = df.rename(columns={"observed_ts": "hour_ts"})
    df["hour_ts"] = df["hour_ts"].dt.floor("h")
    log.info("Loaded %d weather-hour rows", len(df))
    return df


# ---------------------------------------------------------------------------
# Feature construction
# ---------------------------------------------------------------------------

def add_time_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["hour_of_day"]  = df["hour_ts"].dt.hour
    df["day_of_week"]  = df["hour_ts"].dt.dayofweek   # 0=Mon, 6=Sun
    df["is_weekend"]   = (df["day_of_week"] >= 5).astype(int)
    df["is_rush_hour"] = df["hour_of_day"].isin([7, 8, 9, 17, 18, 19]).astype(int)
    return df


def add_lag_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Create lag availability columns per station.
    Requires df sorted by (station_id, hour_ts).
    """
    df = df.sort_values(["station_id", "hour_ts"]).copy()
    grp = df.groupby("station_id")["avg_availability_pct"]

    for lag in [1, 3, 6, 24, 48]:
        df[f"lag_{lag}h"] = grp.shift(lag)

    return df


def add_rolling_features(df: pd.DataFrame) -> pd.DataFrame:
    """3-hour and 6-hour trailing mean (excludes current row)."""
    df = df.sort_values(["station_id", "hour_ts"]).copy()
    grp = df.groupby("station_id")["avg_availability_pct"]

    for window in [3, 6]:
        df[f"roll_mean_{window}h"] = (
            grp.transform(lambda x: x.shift(1).rolling(window, min_periods=1).mean())
        )
    return df


def add_historical_mean(df: pd.DataFrame) -> pd.DataFrame:
    """
    Long-run average availability for the same station × hour × day-of-week.
    Uses leave-one-out-safe groupby mean (the entire dataset's mean is fine
    for historical context — it doesn't leak the target).
    """
    df = df.copy()
    hist = (
        df.groupby(["station_id", "hour_of_day", "day_of_week"])["avg_availability_pct"]
        .mean()
        .reset_index()
        .rename(columns={"avg_availability_pct": "hist_mean_avail"})
    )
    df = df.merge(hist, on=["station_id", "hour_of_day", "day_of_week"], how="left")
    return df


# ---------------------------------------------------------------------------
# Main builder
# ---------------------------------------------------------------------------

def build_feature_matrix(
    start: str | None = None,
    end:   str | None = None,
    horizon_hours: int = 1,
) -> pd.DataFrame:
    """
    Full feature matrix for training or inference.

    Parameters
    ----------
    start, end      : ISO datetime strings (optional filter)
    horizon_hours   : forecast horizon — shifts the target column forward.
                      Use 1, 3, 6, or 12.

    Returns
    -------
    DataFrame with features + 'target_availability' (future availability).
    Rows with NaN in critical lags are dropped.
    """
    hourly  = load_hourly(start, end)
    weather = load_weather(start, end)

    if hourly.empty:
        raise ValueError("No hourly data found for the given date range.")

    df = add_time_features(hourly)
    df = add_lag_features(df)
    df = add_rolling_features(df)
    df = add_historical_mean(df)

    if not weather.empty:
        df = df.merge(weather, on="hour_ts", how="left")
        weather_cols = ["temperature_c", "feels_like_c", "humidity_pct",
                        "wind_speed_ms", "is_rain", "is_snow"]
        for col in weather_cols:
            if col in df.columns:
                df[col] = df.groupby("station_id")[col].transform(
                    lambda x: x.fillna(method="ffill").fillna(method="bfill")
                )

    # Target: availability N hours ahead
    df = df.sort_values(["station_id", "hour_ts"])
    df["target_availability"] = (
        df.groupby("station_id")["avg_availability_pct"].shift(-horizon_hours)
    )

    # Drop rows where key features or target are missing
    required = ["lag_1h", "lag_24h", "roll_mean_3h", "target_availability"]
    df = df.dropna(subset=required)

    log.info(
        "Feature matrix: %d rows, %d columns (horizon=%dh)",
        len(df), len(df.columns), horizon_hours
    )
    return df


FEATURE_COLS = [
    "hour_of_day", "day_of_week", "is_weekend", "is_rush_hour",
    "lag_1h", "lag_3h", "lag_6h", "lag_24h", "lag_48h",
    "roll_mean_3h", "roll_mean_6h",
    "hist_mean_avail",
    "avg_free_bikes", "std_availability",
    # weather (may be absent if OWM key not set)
    "temperature_c", "humidity_pct", "wind_speed_ms", "is_rain", "is_snow",
]

TARGET_COL = "target_availability"


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s")
    for h in [1, 3, 6, 12]:
        mat = build_feature_matrix(horizon_hours=h)
        print(f"Horizon {h:2d}h → {len(mat):,} rows, "
              f"{mat[FEATURE_COLS].notna().all(axis=1).sum():,} complete")
