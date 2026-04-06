"""
XGBoost availability forecasting model.
Trains one model per forecast horizon (1h, 3h, 6h, 12h).
Exposes a TabPy server function for Tableau integration.
Stores predictions in availability_forecasts table.
"""

import os
import sys
import logging
import time
from datetime import datetime

import numpy as np
import pandas as pd
import xgboost as xgb
import joblib
from sklearn.metrics import mean_absolute_error, r2_score
from sklearn.model_selection import TimeSeriesSplit
from dotenv import load_dotenv

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from preprocessing.feature_engineering import (
    build_feature_matrix, FEATURE_COLS, TARGET_COL,
    load_hourly,
)
from data_pipeline.store_to_mysql import store_forecasts, log_pipeline_run

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
log = logging.getLogger(__name__)

HORIZONS     = [1, 3, 6, 12]
MODEL_DIR    = os.path.join(os.path.dirname(__file__), "saved_models")
os.makedirs(MODEL_DIR, exist_ok=True)


# ---------------------------------------------------------------------------
# XGBoost parameters
# ---------------------------------------------------------------------------

XGB_PARAMS = {
    "objective":        "reg:squarederror",
    "n_estimators":      500,
    "max_depth":           6,
    "learning_rate":    0.05,
    "subsample":         0.8,
    "colsample_bytree":  0.8,
    "min_child_weight":    3,
    "reg_alpha":         0.1,
    "reg_lambda":        1.0,
    "random_state":       42,
    "n_jobs":             -1,
    "early_stopping_rounds": 30,
}


# ---------------------------------------------------------------------------
# Training
# ---------------------------------------------------------------------------

def get_available_features(df: pd.DataFrame) -> list[str]:
    """Return FEATURE_COLS that are actually present in df."""
    return [c for c in FEATURE_COLS if c in df.columns]


def train_model(horizon: int) -> dict:
    """
    Train XGBoost for a single forecast horizon.
    Uses TimeSeriesSplit (5 folds) for CV, trains final model on full data.

    Returns dict with model, feature list, and CV metrics.
    """
    log.info("=== Training horizon %dh ===", horizon)
    df = build_feature_matrix(horizon_hours=horizon)

    feature_cols = get_available_features(df)
    X = df[feature_cols].values
    y = df[TARGET_COL].values

    # Time-series cross-validation
    tscv = TimeSeriesSplit(n_splits=5)
    cv_maes, cv_r2s = [], []

    for fold, (train_idx, val_idx) in enumerate(tscv.split(X)):
        X_tr, X_val = X[train_idx], X[val_idx]
        y_tr, y_val = y[train_idx], y[val_idx]

        model = xgb.XGBRegressor(**XGB_PARAMS)
        model.fit(
            X_tr, y_tr,
            eval_set=[(X_val, y_val)],
            verbose=False,
        )
        preds = model.predict(X_val)
        preds = np.clip(preds, 0, 100)
        cv_maes.append(mean_absolute_error(y_val, preds))
        cv_r2s.append(r2_score(y_val, preds))
        log.info("  Fold %d — MAE=%.3f, R²=%.3f", fold + 1, cv_maes[-1], cv_r2s[-1])

    log.info("  CV MAE=%.3f ± %.3f | R²=%.3f",
             np.mean(cv_maes), np.std(cv_maes), np.mean(cv_r2s))

    # Final model on all data
    split = int(len(X) * 0.9)
    final_model = xgb.XGBRegressor(**XGB_PARAMS)
    final_model.fit(
        X[:split], y[:split],
        eval_set=[(X[split:], y[split:])],
        verbose=False,
    )

    model_path = os.path.join(MODEL_DIR, f"xgb_horizon_{horizon}h.joblib")
    joblib.dump({"model": final_model, "features": feature_cols}, model_path)
    log.info("  Saved → %s", model_path)

    return {
        "horizon":     horizon,
        "features":    feature_cols,
        "model":       final_model,
        "cv_mae_mean": np.mean(cv_maes),
        "cv_r2_mean":  np.mean(cv_r2s),
    }


def train_all() -> dict[int, dict]:
    results = {}
    t0 = time.time()
    for h in HORIZONS:
        results[h] = train_model(h)
    duration_ms = int((time.time() - t0) * 1000)

    summary = " | ".join(
        f"{h}h MAE={r['cv_mae_mean']:.2f}" for h, r in results.items()
    )
    log_pipeline_run("forecast", "ok", len(HORIZONS), duration_ms,
                     f"Training complete: {summary}")
    return results


# ---------------------------------------------------------------------------
# Inference & storing predictions
# ---------------------------------------------------------------------------

def load_model(horizon: int) -> dict:
    path = os.path.join(MODEL_DIR, f"xgb_horizon_{horizon}h.joblib")
    if not os.path.exists(path):
        raise FileNotFoundError(f"Model not found: {path}. Run train_all() first.")
    return joblib.load(path)


def predict_and_store(horizon: int) -> int:
    """
    Generate forecasts for the current hour and store in availability_forecasts.
    Returns number of forecast records written.
    """
    t0 = time.time()
    artifact = load_model(horizon)
    model    = artifact["model"]
    features = artifact["features"]

    # Build features using last 48h of data (enough for all lags)
    from preprocessing.feature_engineering import build_feature_matrix
    df = build_feature_matrix(horizon_hours=horizon)

    # Keep only the most recent row per station
    latest = df.sort_values("hour_ts").groupby("station_id").last().reset_index()

    X = latest[features].values
    preds = np.clip(model.predict(X), 0, 100)

    now = datetime.utcnow()
    from datetime import timedelta
    target_ts = (now + timedelta(hours=horizon)).strftime("%Y-%m-%d %H:00:00")
    run_ts    = now.strftime("%Y-%m-%d %H:%M:%S")

    records = [
        {
            "forecast_run_ts":  run_ts,
            "target_ts":        target_ts,
            "station_id":       row["station_id"],
            "horizon_hours":    horizon,
            "pred_availability": round(float(pred), 2),
        }
        for (_, row), pred in zip(latest.iterrows(), preds)
    ]
    stored = store_forecasts(records)
    duration_ms = int((time.time() - t0) * 1000)
    log.info("Forecast horizon=%dh: %d predictions stored (%d ms)",
             horizon, stored, duration_ms)
    log_pipeline_run("forecast", "ok", stored, duration_ms,
                     f"horizon={horizon}h, target={target_ts}")
    return stored


# ---------------------------------------------------------------------------
# TabPy server function (called from Tableau)
# ---------------------------------------------------------------------------

def tabpy_predict(station_ids, hour_of_day, day_of_week,
                  lag_1h, lag_24h, roll_mean_3h,
                  horizon_hours=1):
    """
    TabPy-compatible function signature.
    All arguments are Python lists (Tableau passes columns as lists).
    Returns list of predicted availability percentages.
    """
    import pandas as pd
    import numpy as np

    n = len(station_ids)
    df = pd.DataFrame({
        "station_id":    station_ids,
        "hour_of_day":   hour_of_day,
        "day_of_week":   day_of_week,
        "is_weekend":    [1 if d >= 5 else 0 for d in day_of_week],
        "is_rush_hour":  [1 if h in (7,8,9,17,18,19) else 0 for h in hour_of_day],
        "lag_1h":        lag_1h,
        "lag_3h":        lag_1h,       # approximate when not available
        "lag_6h":        lag_1h,
        "lag_24h":       lag_24h,
        "lag_48h":       lag_24h,
        "roll_mean_3h":  roll_mean_3h,
        "roll_mean_6h":  roll_mean_3h,
        "hist_mean_avail": lag_24h,
        "avg_free_bikes": [0.0] * n,
        "std_availability": [5.0] * n,
    })

    artifact = load_model(horizon_hours)
    model    = artifact["model"]
    features = artifact["features"]

    # Fill any missing feature columns with 0
    for col in features:
        if col not in df.columns:
            df[col] = 0.0

    preds = np.clip(model.predict(df[features].values), 0, 100)
    return list(preds.astype(float))


def register_tabpy():
    """Register prediction function with a running TabPy server."""
    try:
        import tabpy_client
        conn = tabpy_client.Client("http://localhost:9004/")
        for h in HORIZONS:
            name = f"predict_availability_{h}h"
            conn.deploy(
                name,
                lambda *args, horizon=h: tabpy_predict(*args, horizon_hours=horizon),
                f"XGBoost availability forecast {h}h ahead",
                override=True,
            )
            log.info("Registered TabPy function: %s", name)
    except Exception as exc:
        log.error("TabPy registration failed: %s", exc)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Availability forecasting")
    parser.add_argument("--train",    action="store_true", help="Train all models")
    parser.add_argument("--predict",  action="store_true", help="Generate & store forecasts")
    parser.add_argument("--tabpy",    action="store_true", help="Register with TabPy server")
    parser.add_argument("--horizon",  type=int, default=None,
                        help="Single horizon (default: all)")
    args = parser.parse_args()

    horizons = [args.horizon] if args.horizon else HORIZONS

    if args.train:
        for h in horizons:
            train_model(h)

    if args.predict:
        for h in horizons:
            predict_and_store(h)

    if args.tabpy:
        register_tabpy()

    if not any([args.train, args.predict, args.tabpy]):
        log.info("No action specified. Use --train, --predict, or --tabpy.")
        parser.print_help()
