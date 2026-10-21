# Adding Prometheus Monitoring to My Cloud App

*IT 3200 · Jayden Backus · Code: [github.com/jaydenbackus/it-3200-m6](https://github.com/jaydenbackus/it-3200-m6)*

## What I built

My Flask app still runs in Docker on an AWS EC2 instance (Amazon Linux 2023, `t3.small`). Prometheus now runs beside it, on the same server, in its own container.

Prometheus collects numbers about a running system, such as requests served or memory used, and stores each one with a timestamp. It gathers them by *scraping*: every 15 seconds it requests a target's `/metrics` page and records what it finds. I query the stored numbers with PromQL.

```
My computer ──HTTP :9090 (my IP only)──▶ EC2 instance
                                          ├── Docker: Flask app      :3000
                                          ├── Docker: Prometheus     :9090 ◀─ scrapes itself
                                          └── Docker: Grafana Alloy  ─ pushes app, host,
                                                                       and container metrics
```

## Setup

**Configuration.** My Prometheus directory is `monitoring/prometheus/`. Its `prometheus.yml` sets a 15-second scrape interval and tells Prometheus to scrape itself:

```yaml
global:
  scrape_interval: 15s
  evaluation_interval: 15s

rule_files:
  - /etc/prometheus/alerts.yml

scrape_configs:
  - job_name: "prometheus"
    static_configs:
      - targets: ["localhost:9090"]
```

**Running it.** I start Prometheus with Docker Compose instead of a single `docker run`, because the same file also starts my app and the other monitoring containers. The Compose entry does what the assignment's `docker run` command does: it names the image, publishes port 9090, and mounts the configuration file.

```yaml
  prometheus:
    image: prom/prometheus:v3.15.0
    command:
      - --config.file=/etc/prometheus/prometheus.yml
      - --storage.tsdb.retention.time=15d
      - --web.enable-remote-write-receiver
    volumes:
      - ./monitoring/prometheus:/etc/prometheus:ro
      - prometheus-data:/prometheus
    ports:
      - "9090:9090"
```

I pin the version (`v3.15.0`) rather than use `latest`, so a rebuild cannot silently change Prometheus. A named volume keeps the data when the container restarts.

**Going further.** Prometheus also stores metrics that Grafana Alloy pushes in through the remote-write receiver: the app's request counts and latency, host CPU, memory, and disk (the Node Exporter code, built into Alloy), and per-container resources. Those targets do not appear on the Targets page, because Prometheus does not scrape them itself; their `up` series still appear in queries.

**Networking.** The EC2 security group allows TCP 9090 from my IP address only. Prometheus has no login page, so this rule is its only lock.

## Verification

- `docker --version` and `docker ps` show Docker running the app, Prometheus, and the monitoring containers.
- `curl http://localhost:9090/-/ready` on the server returns `Prometheus Server is Ready.`
- `http://<PUBLIC-IP>:9090` opens the Prometheus web interface from my browser.
- The **Targets** page lists the `prometheus` job, `http://localhost:9090/metrics`, as **UP**.
- The query `up` returns `1` for all seven targets.

## Metric analysis: why a counter needs `rate()`

The app counts requests in `flask_http_request_total`, a *counter*: a number that only goes up. To study it, I sent four minutes of steady traffic, restarted the app container at 05:39:29 UTC, and sent four more minutes. I then graphed two queries:

```promql
sum(flask_http_request_total{status="200"})
sum(rate(flask_http_request_total{status="200"}[1m]))
```

| Time (UTC) | Raw counter | `rate()` per second |
|---|---|---|
| 05:36:27 | 148 | 3.24 |
| 05:37:57 | 428 | 3.24 |
| 05:39:27 | 708 | 3.11 |
| **05:39:57** | **35** | **2.80** |
| 05:41:27 | 287 | 2.82 |
| 05:43:27 | 644 | 2.98 |

**The raw counter fell from 708 to 35 when the app restarted.** The counter lives in the app's memory, so a restart sets it back to zero. Read naively, the graph says the app "lost" 673 requests. Subtracting one sample from the next would report a negative request rate, which is impossible.

**`rate()` stayed level across the restart.** PromQL's `rate()` detects the drop, treats it as a reset, and counts from zero again. It turned a sawtooth line into a steady 2.8 to 3.2 requests per second. A counter is meaningless without it: the raw number mostly tells me how long the app has run since its last restart.

**The small dip after the restart was not the app.** Traffic fell from about 3.1 to 2.8 requests per second. A dip like that could mean the app slowed down, so I checked latency. The median response time for the home page held at 2.5 ms before and after. The cause was my load generator: it waits for each request to finish, and its deliberately slow requests happened to average 1.31 seconds after the restart against 1.16 seconds before. Longer waits meant fewer requests per second. The lesson: before blaming a server for lower traffic, check whether the clients changed.

**What this means in practice.** Every restart, deploy, or crash resets the app's counters. Dashboards and alerts must use `rate()` or `increase()`, never the raw counter, or every deploy would look like an outage.

The `up` query showed `1` for all seven targets after the test, so no target was down.

## Security

- **Port 9090 answers my IP alone.** Prometheus has no authentication, so anyone who could reach it could read every metric and, through the remote-write receiver, insert false ones. Restricting the source IP closes that door; a production setup would add a password or a reverse proxy with TLS.
- **Shared networks weaken the rule.** On campus Wi-Fi, many people share one public IP, and the rule admits all of them. I remove or tighten the rule when I am not using it.
- **Nothing private is committed.** The repository holds no keys, passwords, or personal IDs.

## Cleanup

When I finish, I will delete the port 9090 rule, stop the instance so it stops billing, and check the AWS billing dashboard.

## References

- Prometheus overview: https://prometheus.io/docs/introduction/overview/
- Prometheus configuration: https://prometheus.io/docs/prometheus/latest/configuration/configuration/
- Jobs and instances: https://prometheus.io/docs/concepts/jobs_instances/
- Querying basics (PromQL): https://prometheus.io/docs/prometheus/latest/querying/basics/
- PromQL functions (`rate`): https://prometheus.io/docs/prometheus/latest/querying/functions/
- Amazon EC2 security groups: https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/ec2-security-groups.html
