"""
Flask health monitor for the ingestion pipeline.
Exposes a simple dashboard at http://localhost:5000 showing:
  - Last run time and status for each source
  - Recent error messages
  - Records ingested in the last hour
"""

import os
from datetime import datetime, timedelta
from flask import Flask, jsonify, render_template_string
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

HTML_DASHBOARD = """
<!DOCTYPE html>
<html>
<head>
  <title>Bike-Share Pipeline Health</title>
  <meta http-equiv="refresh" content="60">
  <style>
    body { font-family: Arial, sans-serif; margin: 40px; background: #f5f5f5; }
    h1   { color: #333; }
    .card { background: white; border-radius: 8px; padding: 20px; margin: 15px 0;
            box-shadow: 0 2px 4px rgba(0,0,0,.1); }
    .ok      { color: #27ae60; font-weight: bold; }
    .warning { color: #f39c12; font-weight: bold; }
    .error   { color: #e74c3c; font-weight: bold; }
    table { border-collapse: collapse; width: 100%; }
    th, td { text-align: left; padding: 8px 12px; border-bottom: 1px solid #eee; }
    th { background: #f0f0f0; }
    .kpi { display: inline-block; margin: 10px 20px 10px 0;
           text-align: center; min-width: 120px; }
    .kpi-value { font-size: 2em; font-weight: bold; color: #2c3e50; }
    .kpi-label { font-size: 0.85em; color: #777; }
  </style>
</head>
<body>
  <h1>Bike-Share Pipeline Health Monitor</h1>
  <p style="color:#888">Auto-refreshes every 60 s &nbsp;|&nbsp; {{ now }}</p>

  <div class="card">
    <h2>KPIs — Last Hour</h2>
    {% for k in kpis %}
    <div class="kpi">
      <div class="kpi-value">{{ k.value }}</div>
      <div class="kpi-label">{{ k.label }}</div>
    </div>
    {% endfor %}
  </div>

  <div class="card">
    <h2>Source Status</h2>
    <table>
      <tr><th>Source</th><th>Last Run</th><th>Status</th><th>Records</th><th>Message</th></tr>
      {% for row in sources %}
      <tr>
        <td>{{ row.source }}</td>
        <td>{{ row.run_ts }}</td>
        <td class="{{ row.status }}">{{ row.status.upper() }}</td>
        <td>{{ row.records_in }}</td>
        <td>{{ row.message }}</td>
      </tr>
      {% endfor %}
    </table>
  </div>

  <div class="card">
    <h2>Recent Errors (last 24 h)</h2>
    {% if errors %}
    <table>
      <tr><th>Time</th><th>Source</th><th>Message</th></tr>
      {% for e in errors %}
      <tr>
        <td>{{ e.run_ts }}</td>
        <td>{{ e.source }}</td>
        <td>{{ e.message }}</td>
      </tr>
      {% endfor %}
    </table>
    {% else %}
    <p class="ok">No errors in the last 24 hours.</p>
    {% endif %}
  </div>
</body>
</html>
"""


def _get_engine():
    host = os.getenv("MYSQL_HOST", "localhost")
    port = os.getenv("MYSQL_PORT", "3306")
    user = os.getenv("MYSQL_USER", "root")
    pw   = os.getenv("MYSQL_PASSWORD", "")
    db   = os.getenv("MYSQL_DB", "bikeshare")
    url  = f"mysql+pymysql://{user}:{pw}@{host}:{port}/{db}?charset=utf8mb4"
    return create_engine(url, pool_pre_ping=True)


def _query(sql: str, params: dict = None) -> list[dict]:
    engine = _get_engine()
    with engine.connect() as conn:
        result = conn.execute(text(sql), params or {})
        keys = result.keys()
        return [dict(zip(keys, row)) for row in result]


@app.route("/")
def dashboard():
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    cutoff_1h  = (datetime.utcnow() - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
    cutoff_24h = (datetime.utcnow() - timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")

    # Latest run per source
    sources = _query("""
        SELECT source, run_ts, status, records_in, message
        FROM pipeline_log
        WHERE id IN (
            SELECT MAX(id) FROM pipeline_log GROUP BY source
        )
        ORDER BY source
    """)

    # KPIs: records in last hour per source
    hourly_counts = _query("""
        SELECT source, SUM(records_in) AS total
        FROM pipeline_log
        WHERE run_ts >= :cutoff AND status = 'ok'
        GROUP BY source
    """, {"cutoff": cutoff_1h})
    count_map = {r["source"]: r["total"] for r in hourly_counts}

    kpis = [
        {"label": "Bike snapshots / hr", "value": count_map.get("citybikes", 0)},
        {"label": "Weather obs / hr",    "value": count_map.get("openweathermap", 0)},
        {"label": "Agg runs / hr",       "value": count_map.get("aggregation", 0)},
        {"label": "Forecast runs / hr",  "value": count_map.get("forecast", 0)},
    ]

    # Recent errors
    errors = _query("""
        SELECT run_ts, source, message
        FROM pipeline_log
        WHERE status = 'error' AND run_ts >= :cutoff
        ORDER BY run_ts DESC
        LIMIT 50
    """, {"cutoff": cutoff_24h})

    return render_template_string(
        HTML_DASHBOARD,
        now=now,
        sources=sources,
        kpis=kpis,
        errors=errors,
    )


@app.route("/api/status")
def api_status():
    """JSON endpoint for programmatic health checks."""
    sources = _query("""
        SELECT source, run_ts, status, records_in
        FROM pipeline_log
        WHERE id IN (
            SELECT MAX(id) FROM pipeline_log GROUP BY source
        )
    """)
    overall = "ok"
    for s in sources:
        if s["status"] == "error":
            overall = "error"
            break
        if s["status"] == "warning" and overall != "error":
            overall = "warning"

    return jsonify({"overall": overall, "sources": sources,
                    "checked_at": datetime.utcnow().isoformat()})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
