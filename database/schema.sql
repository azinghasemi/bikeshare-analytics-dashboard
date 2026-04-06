-- ============================================================
-- Bike-Share Analytics — MySQL Schema
-- ============================================================

CREATE DATABASE IF NOT EXISTS bikeshare CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE bikeshare;

-- Live station snapshots (collected every 5 minutes)
CREATE TABLE IF NOT EXISTS station_snapshots (
    id              BIGINT        AUTO_INCREMENT PRIMARY KEY,
    snapshot_ts     DATETIME      NOT NULL,
    station_id      VARCHAR(50)   NOT NULL,
    station_name    VARCHAR(200),
    latitude        DECIMAL(9,6),
    longitude       DECIMAL(9,6),
    free_bikes      INT           DEFAULT 0,
    empty_slots     INT           DEFAULT 0,
    total_capacity  INT           GENERATED ALWAYS AS (free_bikes + empty_slots) STORED,
    availability_pct DECIMAL(5,2) GENERATED ALWAYS AS (
        CASE WHEN (free_bikes + empty_slots) > 0
             THEN ROUND(free_bikes / (free_bikes + empty_slots) * 100, 2)
             ELSE 0 END
    ) STORED,
    district        VARCHAR(100),
    created_at      TIMESTAMP     DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_ts           (snapshot_ts),
    INDEX idx_station      (station_id),
    INDEX idx_station_ts   (station_id, snapshot_ts),
    INDEX idx_district_ts  (district, snapshot_ts)
);

-- Hourly aggregated data (preprocessed from snapshots)
CREATE TABLE IF NOT EXISTS station_hourly (
    id                  BIGINT        AUTO_INCREMENT PRIMARY KEY,
    hour_ts             DATETIME      NOT NULL,
    station_id          VARCHAR(50)   NOT NULL,
    avg_free_bikes      DECIMAL(6,2),
    avg_availability_pct DECIMAL(5,2),
    std_availability    DECIMAL(5,2),
    min_availability    DECIMAL(5,2),
    max_availability    DECIMAL(5,2),
    empty_count         INT,          -- number of 5-min intervals station was empty
    UNIQUE KEY uq_station_hour (station_id, hour_ts),
    INDEX idx_hour     (hour_ts),
    INDEX idx_station  (station_id)
);

-- Weather observations (synced with station data every 5 minutes)
CREATE TABLE IF NOT EXISTS weather_observations (
    id              BIGINT       AUTO_INCREMENT PRIMARY KEY,
    observed_ts     DATETIME     NOT NULL,
    temperature_c   DECIMAL(5,2),
    feels_like_c    DECIMAL(5,2),
    humidity_pct    INT,
    wind_speed_ms   DECIMAL(5,2),
    weather_main    VARCHAR(50),   -- Clear, Rain, Clouds, Snow, etc.
    is_rain         TINYINT(1)    DEFAULT 0,
    is_snow         TINYINT(1)    DEFAULT 0,
    visibility_m    INT,
    created_at      TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_obs_ts (observed_ts)
);

-- ML forecast output stored for dashboard comparison
CREATE TABLE IF NOT EXISTS availability_forecasts (
    id              BIGINT        AUTO_INCREMENT PRIMARY KEY,
    forecast_run_ts DATETIME      NOT NULL,   -- when model was run
    target_ts       DATETIME      NOT NULL,   -- time being predicted
    station_id      VARCHAR(50)   NOT NULL,
    horizon_hours   INT           NOT NULL,   -- 1, 3, 6, or 12
    pred_availability DECIMAL(5,2),
    actual_availability DECIMAL(5,2) DEFAULT NULL,  -- filled in retrospectively
    mae             DECIMAL(5,4)  DEFAULT NULL,
    created_at      TIMESTAMP     DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_target_ts  (target_ts),
    INDEX idx_station    (station_id),
    INDEX idx_horizon    (horizon_hours)
);

-- Pipeline health log (ingestion status)
CREATE TABLE IF NOT EXISTS pipeline_log (
    id          BIGINT       AUTO_INCREMENT PRIMARY KEY,
    run_ts      DATETIME     NOT NULL,
    source      ENUM('citybikes', 'openweathermap', 'aggregation', 'forecast') NOT NULL,
    status      ENUM('ok', 'warning', 'error') NOT NULL,
    records_in  INT          DEFAULT 0,
    message     TEXT,
    duration_ms INT,
    INDEX idx_run_ts (run_ts),
    INDEX idx_source (source)
);
