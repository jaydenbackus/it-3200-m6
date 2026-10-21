import ipaddress
import logging
import os
import random
import time

from flask import Flask, abort, render_template, request
from prometheus_flask_exporter import PrometheusMetrics

# Log to stdout so Docker captures it and Grafana Alloy can ship it to Loki
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s level=%(levelname)s logger=%(name)s msg=%(message)r",
)
log = logging.getLogger("student-app")

app = Flask(__name__)

# Exposes /metrics with request count, latency histogram, and exception metrics.
# Grouping by endpoint (not raw path) keeps label cardinality bounded when bots probe random URLs.
metrics = PrometheusMetrics(app, group_by="endpoint", excluded_paths=["/metrics"])
metrics.info("student_app_info", "Student app build information", version="1.1.0")

STUDENT = {
    "name": "Jayden Backus",
    "student_id": "[removed]",
    "course": "IT 3200",
}

# Demo routes that produce errors and slow responses, off unless explicitly enabled
SIMULATION_ENABLED = os.getenv("ENABLE_SIMULATION", "false").lower() == "true"


@app.before_request
def restrict_metrics():
    # Only the private Docker network (where Alloy runs) may read /metrics
    if request.path == "/metrics" and not ipaddress.ip_address(request.remote_addr).is_private:
        log.warning("blocked /metrics request from %s", request.remote_addr)
        abort(403)


@app.route("/")
def index():
    return render_template("index.html", **STUDENT)


@app.route("/health")
@metrics.do_not_track()
def health():
    return {"status": "ok"}


@app.route("/simulate/error")
def simulate_error():
    if not SIMULATION_ENABLED:
        abort(404)
    log.error("simulated failure requested")
    abort(500)


@app.route("/simulate/slow")
def simulate_slow():
    if not SIMULATION_ENABLED:
        abort(404)
    delay = random.uniform(0.5, 2.0)
    time.sleep(delay)
    log.info("simulated slow response took %.2fs", delay)
    return {"delay_seconds": round(delay, 2)}


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=3000)
