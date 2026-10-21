---
title: "Monitoring a Flask App on EC2 with Grafana Alloy, Prometheus, Loki, and Grafana"
published: false
tags: observability, grafana, prometheus, aws
---

# Monitoring a Flask App on EC2 with Grafana Alloy, Prometheus, Loki, and Grafana

*IT 3200 · Jayden Backus · Code: [github.com/jaydenbackus/it-3200-m6](https://github.com/jaydenbackus/it-3200-m6)*

## 1. Introduction

In an earlier module I built a small Flask app, packed it into a Docker image, and ran it on an AWS EC2 instance. The app shows one page with my name, student ID, and course. Gunicorn runs it on port 3000.

The app is simple, but it sits on a public IP address, and the internet notices. Three minutes after I started it on a new instance, my logs showed two requests for `/api/v1/version`, a path my app has never had, from a client calling itself only `Mozilla/5.0`. Something was scanning for exposed services.

Without monitoring, I could not see that. I would learn the app was down only when someone told me. I could not say how fast it answers, how often it fails, or whether the server is short of memory or disk. To read a log, I had to SSH in and run `docker logs`.

I set out to answer three questions without logging in to the server:

1. Is the app up, and is it healthy? (request rate, error rate, latency)
2. Is the machine under it healthy? (CPU, memory, and disk for the host and for each container)
3. What happened? (searchable application and access logs)

I also wanted the system to tell me when something breaks, rather than wait for me to look.

## 2. Why I chose these tools

I built the solution from four open-source tools:

| Tool | Job | Data |
|---|---|---|
| **Grafana Alloy** | Finds targets, collects metrics and logs, filters them, and sends them on | Metrics, logs |
| **Prometheus** | Stores metrics and checks alert rules | Metrics |
| **Loki** | Stores logs; indexes labels, not full text | Logs |
| **Grafana** | Queries both stores and draws dashboards | Visualization |

Alloy is the choice that matters most, so I explain it first.

### Why Alloy replaces three agents

Many "Prometheus and Loki on Docker" tutorials run three collectors: **node_exporter** for host metrics, **cAdvisor** for container metrics, and **Promtail** to ship logs to Loki. While reading the Loki documentation, I found that Promtail reached end of life on March 2, 2026, and that "all future feature development will occur in Grafana Alloy." I saw no reason to build a new project on a dead agent.

Alloy replaces all three, not just Promtail. It contains each of their jobs as a component:

- `prometheus.exporter.unix` runs the node_exporter code.
- `prometheus.exporter.cadvisor` runs cAdvisor.
- `loki.source.docker` reads container logs through the Docker API, as Promtail did.

One collector instead of three saves memory, and my `t3.small` has only 2 GB. It also puts the whole data pipeline in one file I can read top to bottom.

### Why Prometheus and Loki

Prometheus is the most widely used metrics store. One Python library, `prometheus-flask-exporter`, makes my app speak its format, and its query language, PromQL, turns raw counters into rates, error ratios, and latency percentiles.

Loki labels logs the same way Prometheus labels metrics, so `service="app"` finds the app in both. Because Loki indexes only labels, it needs far less memory and disk than a full-text engine such as Elasticsearch.

### Strengths

- Free and open source, with no charge per gigabyte stored.
- One collector for every signal. Adding traces later means adding Alloy components, not another agent.
- Every piece is code: the Alloy pipeline, the alert rules, and the Grafana dashboard. `docker compose up` rebuilds the whole stack.

### Limitations

- **I run it myself.** I must patch it, size its storage, and back it up. If the instance dies, the monitoring dies with it. A production system would watch from separate machines.
- **Alloy needs privileged access** to read host and container statistics. Section 6 covers the risk.
- **Nothing pages me yet.** Prometheus decides when an alert fires, but sending it to email or chat needs Alertmanager or Grafana contact points, which I have not set up.
- **Loki is not a search engine.** A text search scans every line in the chosen streams. At my volume this is instant; at terabytes it would be slow.

### What I rejected

- **AWS CloudWatch** needs no servers and knows EC2 well. But its Container Insights feature targets ECS and EKS, not plain Docker on EC2; it bills per custom metric; and it ties me to AWS. I wanted a stack I could run anywhere, including my laptop.
- **Elastic Stack or OpenSearch** search logs well and suit security work, but Elasticsearch is far heavier than Loki and alone would strain a 2 GB server.
- **Prometheus with Promtail, node_exporter, and cAdvisor** works, but it means three agents, one of them dead.

## 3. Installation and configuration

The repository holds every file below. Clone it, set one password, and run one command.

### 3.1 Architecture

![Architecture diagram](https://raw.githubusercontent.com/jaydenbackus/it-3200-m6/main/docs/architecture.png)

Data moves in five steps:

1. Users reach the Flask app on port 3000. The app exposes `/metrics` and writes logs to stdout, where Docker keeps them.
2. Alloy scrapes `/metrics` every 15 seconds. It reads host statistics from `/proc` and `/sys`, container statistics from cgroups, and every container's logs from the Docker socket.
3. Alloy pushes metrics to Prometheus through the remote-write API, and logs to Loki through its push API.
4. Prometheus stores the metrics and checks the alert rules every 15 seconds. Loki stores the logs.
5. Grafana queries both and draws the dashboard.

The internet can reach two ports: the app (3000) and Grafana (3001). Grafana answers only my IP address. Prometheus, Loki, and Alloy listen on `127.0.0.1`, so I reach them through an SSH tunnel.

### 3.2 Launch the EC2 instance

In the EC2 console I launched:

- **AMI:** Amazon Linux 2023, x86_64
- **Type:** `t3.small` (2 vCPUs, 2 GB). Five containers do not fit in a `t3.micro`'s 1 GB.
- **Disk:** 20 GiB gp3. The default 8 GiB leaves too little room for images, metrics, and logs.
- **Security group** `it-3200-monitoring-sg`:

| Port | Source | Purpose |
|---|---|---|
| 22 | My IP | SSH |
| 3000 | 0.0.0.0/0 | Flask app |
| 3001 | My IP | Grafana |

**A mistake worth sharing:** EC2 key pairs belong to one region. My old key pair did not exist in us-west-1, so AWS launched my first instance with a key I did not hold, and SSH refused me. I printed my public key with `ssh-keygen -y -f key.pem`, imported it under **Key pairs → Import key pair** in the right region, and launched again.

<!-- SCREENSHOT: EC2 instance summary and security group inbound rules -->

### 3.3 Install Docker, Compose, and Buildx

Amazon Linux 2023's `docker` package lacks the Compose and Buildx plugins, so I installed both by hand, following Docker's guide "Install the Docker Compose plugin":

```bash
sudo dnf install -y docker git
sudo systemctl enable --now docker
sudo usermod -aG docker ec2-user          # log out and back in afterward

PLUG=/usr/local/lib/docker/cli-plugins
sudo mkdir -p $PLUG
sudo curl -fsSL https://github.com/docker/compose/releases/latest/download/docker-compose-linux-x86_64 \
  -o $PLUG/docker-compose
# "docker compose build" needs a recent Buildx
BX=$(curl -fsSI https://github.com/docker/buildx/releases/latest | grep -i '^location' | sed 's#.*/tag/##' | tr -d '\r')
sudo curl -fsSL https://github.com/docker/buildx/releases/download/$BX/buildx-$BX.linux-amd64 \
  -o $PLUG/docker-buildx
sudo chmod +x $PLUG/*

# 1 GB of swap absorbs memory spikes
sudo dd if=/dev/zero of=/swapfile bs=1M count=1024
sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

### 3.4 Clone, set the password, start

```bash
git clone https://github.com/jaydenbackus/it-3200-m6.git
cd it-3200-m6
cp .env.example .env
sed -i "s|^GRAFANA_ADMIN_PASSWORD=.*|GRAFANA_ADMIN_PASSWORD=$(openssl rand -base64 24 | tr -d '/+=')|" .env
chmod 600 .env
docker compose up -d --build
docker compose ps
```

Git ignores `.env`, so the password never reaches GitHub. If the variable is missing, Compose refuses to start Grafana (`${GRAFANA_ADMIN_PASSWORD:?...}`), so Grafana can never fall back to its default `admin/admin`.

### 3.5 Repository layout

```
it-3200-m6/
├── app.py                       # Flask app with prometheus-flask-exporter
├── Dockerfile                   # gunicorn: 1 worker, 4 threads, access log to stdout
├── docker-compose.yml           # app, alloy, prometheus, loki, grafana
├── .env.example                 # GRAFANA_ADMIN_PASSWORD, ENABLE_SIMULATION
├── monitoring/
│   ├── alloy/config.alloy       # the whole collection pipeline
│   ├── prometheus/prometheus.yml
│   ├── prometheus/alerts.yml    # six alert rules
│   ├── loki/loki.yml            # local disk, 7-day retention
│   └── grafana/
│       ├── provisioning/        # data sources and dashboard loader
│       └── dashboards/student-app.json
└── scripts/generate-traffic.sh  # load generator for demos
```

### 3.6 Key settings

**Compose.** I pin every image version, and only the app and Grafana listen on public ports:

```yaml
  prometheus:
    image: prom/prometheus:v3.15.0
    command:
      - --config.file=/etc/prometheus/prometheus.yml
      - --storage.tsdb.retention.time=15d
      - --storage.tsdb.retention.size=2GB
      - --web.enable-remote-write-receiver   # Alloy pushes metrics here
    ports:
      - "127.0.0.1:9090:9090"                # closed to the internet
```

**Alloy.** Each block is a component. One component's output, such as `.targets` or `.receiver`, feeds the next, so the file reads like a flow chart:

```alloy
// Host metrics, in place of node_exporter
prometheus.exporter.unix "host" {
  procfs_path = "/host/proc"
  sysfs_path  = "/host/sys"
  rootfs_path = "/rootfs"
}

prometheus.scrape "host" {
  targets    = prometheus.exporter.unix.host.targets
  forward_to = [prometheus.remote_write.local.receiver]
}

// Container logs, in place of Promtail
loki.source.docker "containers" {
  host          = "unix:///var/run/docker.sock"
  targets       = discovery.docker.containers.targets
  relabel_rules = discovery.relabel.container_logs.rules
  forward_to    = [loki.process.redact.receiver]
}

// Blank out anything that looks like a credential before Loki stores it
loki.process "redact" {
  stage.replace {
    expression = "(?i)(?:password|passwd|secret|token|api[_-]?key)=(\\S+)"
    replace    = "<redacted>"
  }
  forward_to = [loki.write.local.receiver]
}
```

**Prometheus** scrapes nothing itself. Its config only loads the alert rules; Alloy does all the collecting.

**Loki** keeps logs on local disk and runs a compactor that deletes them after seven days (`retention_period: 168h`).

**Grafana** builds itself from files. At startup it loads the Prometheus and Loki data sources and an 18-panel dashboard, so a fresh deploy needs no clicking.

## 4. Implementation

### 4.1 Instrumenting the app

I added `prometheus-flask-exporter` and changed a few lines of `app.py`:

```python
from prometheus_flask_exporter import PrometheusMetrics

# Label by Flask endpoint, not raw URL. Scanners that request random paths
# all land in endpoint="None" instead of creating new time series.
metrics = PrometheusMetrics(app, group_by="endpoint", excluded_paths=["/metrics"])
metrics.info("student_app_info", "Student app build information", version="1.1.0")

@app.before_request
def restrict_metrics():
    # Only the private Docker network, where Alloy runs, may read /metrics
    if request.path == "/metrics" and not ipaddress.ip_address(request.remote_addr).is_private:
        abort(403)
```

I also:

- added a `/health` endpoint and left it out of the metrics, so health checks do not inflate traffic numbers;
- turned on gunicorn's access log (`--access-logfile -`), so every request becomes a line in Loki;
- fixed gunicorn at one worker with four threads. The Prometheus client keeps counters in process memory, so several worker processes would each report a fraction of the truth;
- added two demo routes: `/simulate/error` returns HTTP 500, and `/simulate/slow` waits 0.5 to 2 seconds. Both return 404 unless `ENABLE_SIMULATION=true`.

### 4.2 What I collect

**Metrics,** kept 15 days or 2 GB, whichever comes first:

| Source | Alloy component | Sample metrics |
|---|---|---|
| Flask app | `prometheus.scrape "student_app"` | `flask_http_request_total`, `flask_http_request_duration_seconds_bucket` |
| EC2 host | `prometheus.exporter.unix` | `node_cpu_seconds_total`, `node_memory_MemAvailable_bytes`, `node_filesystem_avail_bytes` |
| Containers | `prometheus.exporter.cadvisor` | `container_cpu_usage_seconds_total`, `container_memory_working_set_bytes` |
| The stack itself | `prometheus.exporter.self`, `prometheus.scrape "stack"` | `up`, internals of Prometheus, Loki, and Grafana |

**Logs,** kept seven days: stdout and stderr from every container, labeled `service`, `container`, `stream`, and `host`. I keep labels few on purpose. Loki slows down when labels take many values, so I pull fields such as the HTTP status out at query time with LogQL instead of storing them as labels.

**Traces:** none yet. Alloy can receive OpenTelemetry traces and send them to Grafana Tempo; that is the next step.

### 4.3 Dashboard

The **Student App Observability** dashboard has four rows:

1. **Application:** up or down, request rate, share of 5xx errors, p95 latency, requests by status code, p50/p95/p99 latency, and requests by endpoint.
2. **Containers:** CPU and memory for each container.
3. **EC2 host:** CPU, memory, and root-disk use.
4. **Logs:** the app's live log, and a panel of errors from every container, found with this LogQL query:

```logql
{service=~".+"} |~ "(?i)level=(error|warning)|traceback|\" 5\\d\\d "
```

### 4.4 Alerts

Prometheus checks six rules (`monitoring/prometheus/alerts.yml`):

| Alert | Fires when | For |
|---|---|---|
| `StudentAppDown` | Alloy cannot scrape the app (`up == 0`) | 1 min |
| `StudentAppHighErrorRate` | more than 5% of requests return 5xx | 2 min |
| `StudentAppHighLatency` | p95 latency exceeds 1 second | 5 min |
| `HostHighCpu` | host CPU exceeds 85% | 10 min |
| `HostLowMemory` | less than 10% of memory is free | 5 min |
| `HostDiskAlmostFull` | less than 15% of the root disk is free | 10 min |

The **For** column guards against noise. A rule whose condition turns true first enters the *pending* state; it fires only if the condition holds for the full period. One slow request pages no one.

Grafana lists these rules under **Alerting → Alert rules** beside the dashboard.

## 5. Show it working

To create evidence, I turned on the demo routes and ran `scripts/generate-traffic.sh` on the instance for ten minutes. Each pass sent six normal requests, one health check, one request for a missing page (404), one forced error (500), and one slow request. I then stopped the app container for two and a half minutes and started it again.

The test also caught a bug in my own tooling. I had meant to send three more minutes of traffic after the restart, but my load generator quit at once. Its first request reached the app before gunicorn was listening, and the script's `set -e` treated that failed `curl` as fatal. A load generator must survive the outage it exists to test, so I removed `set -e`.

### Alert timeline

Prometheus records every alert's state in a series called `ALERTS`. Querying it, together with my test log, gives this timeline (UTC):

| Time | Event |
|---|---|
| 04:43:14 | Traffic starts: about one tracked request in nine fails, and as many are slow |
| 04:44:00 | `StudentAppHighErrorRate` and `StudentAppHighLatency` turn **pending** |
| 04:46:00 | `StudentAppHighErrorRate` **fires**, two minutes later, as its rule requires |
| 04:49:00 | `StudentAppHighLatency` **fires**, five minutes after turning pending |
| 04:53:15 | I stop the app container |
| 04:53:45 | `StudentAppDown` turns **pending** after Alloy's first failed scrape |
| 04:54:45 | `StudentAppDown` **fires** |
| 04:55:46 | I start the app container |
| 04:56:00 | `StudentAppDown` **resolves**, 14 seconds after the restart |
| 04:58:00 | The error and latency alerts **resolve**, about five minutes after the last failed request |

One detail surprised me. The error-rate alert kept firing through the outage, even though a stopped app returns no errors. The rule averages over the last five minutes (`rate(...[5m])`), and those minutes still held the earlier failures. The rule says "errors were high recently," not "errors are high this second." That is what I want from an alert, but it is easy to misread on a dashboard.

### Queries

I ran these PromQL queries against Prometheus for 04:50 UTC, the peak of the test:

```promql
sum by (status) (rate(flask_http_request_total[5m]))
```

| status | requests/second |
|---|---|
| 200 | 2.98 |
| 404 | 0.43 |
| 500 | 0.42 |

```promql
sum(rate(flask_http_request_total{status=~"5.."}[5m]))
  / sum(rate(flask_http_request_total[5m]))
```

**0.111**: 11% of requests failed, more than double the 5% threshold.

```promql
histogram_quantile(0.95, sum by (le) (rate(flask_http_request_duration_seconds_bucket[5m])))
```

**1.50 seconds**: half again over the 1-second threshold.

The logs agree with the metrics. Between 04:43 and 04:53, Loki stored **251** access-log lines for HTTP 500 responses (`{service="app"} |= "\" 500 "`), and Prometheus counted **248** (`increase(flask_http_request_total{status="500"}[10m])`). The small gap comes from the edges of the counting window.

Memory per container (`container_memory_working_set_bytes`) at the same moment:

| Container | Memory |
|---|---|
| Grafana | 199 MiB |
| Alloy | 122 MiB |
| Loki | 99 MiB |
| Prometheus | 74 MiB |
| Flask app | 36 MiB |

Together the containers used about 530 MiB. With the operating system and page cache, the host stood at 50% of its 2 GB. A 1 GB `t3.micro` would have had little room left.

### Screenshots

<!-- SCREENSHOT 1: Dashboard, Application row during the traffic test (error ratio and latency in red) -->
<!-- SCREENSHOT 2: Dashboard, App status = DOWN during the outage -->
<!-- SCREENSHOT 3: Alerting → Alert rules with StudentAppHighErrorRate and StudentAppDown firing -->
<!-- SCREENSHOT 4: Explore → Loki, {service="app"} |= " 500 " showing the failed requests -->
<!-- SCREENSHOT 5: Dashboard, Containers and EC2 host rows -->
<!-- SCREENSHOT 6: Prometheus through the SSH tunnel, Status → Targets or Alerts -->

### Security checks

From my laptop, I probed the instance's public address:

```
$ for p in 3000 3001 9090 3100 12345; do nc -z -G 5 3.101.30.170 $p && echo "$p OPEN" || echo "$p closed"; done
port 3000: OPEN              # the app, public by design
port 3001: OPEN              # Grafana, open only because my laptop is "My IP"
port 9090: closed/filtered   # Prometheus
port 3100: closed/filtered   # Loki
port 12345: closed/filtered  # Alloy
```

On the server, `ss -tlnp` shows why. Docker publishes the internal tools on the loopback address only:

```
0.0.0.0:3000      127.0.0.1:9090
0.0.0.0:3001      127.0.0.1:3100
0.0.0.0:22        127.0.0.1:12345
```

<!-- SCREENSHOT 7: browser at http://<PUBLIC-IP>:3000/metrics showing 403 Forbidden -->

## 6. Security considerations

**Network exposure.** I set two layers of walls:

- The security group opens three ports. SSH (22) and Grafana (3001) answer my IP address alone; only the app (3000) answers everyone.
- Prometheus (9090), Loki (3100), and Alloy (12345) listen on `127.0.0.1`. If I misconfigured the security group, they would still not answer on the public interface. I reach them through an SSH tunnel: `ssh -L 9090:localhost:9090 ec2-user@<ip>`.
- Loki runs with `auth_enabled: false`, and Prometheus accepts remote writes without a password. That is safe only because nothing outside the server can reach either. Exposed, they would let anyone read or forge my data.
- The app answers `/metrics` with **403** for any public IP address, so the internet cannot read internal numbers through port 3000.

**Authentication and authorization.**

- A random generator creates the Grafana admin password. It lives in `.env` with mode `600` and never enters Git, and Compose will not start Grafana without it.
- I turned off self sign-up and anonymous access. The data sources and dashboard load read-only (`editable: false`, `allowUiUpdates: false`), so no one can change them quietly in the browser.
- Grafana speaks plain HTTP, so my password crosses the network unencrypted. A real deployment would put Grafana behind TLS, through a reverse proxy or an AWS load balancer with an ACM certificate, and sign users in through SSO.

**The privileged collector.** Alloy runs with `privileged: true` and mounts the Docker socket and host file system, because its cAdvisor and node exporters need them. This is the largest risk in the design: anyone who controls the Docker socket controls the host. I limited it by mounting everything read-only, pinning the image version, and keeping Alloy's web page off the internet. A Docker socket proxy that allows only read calls would tighten it further.

**Sensitive data in logs.** Alloy's `redact` stage blanks the values of `password=`, `token=`, `secret=`, and `api_key=` before Loki stores a line. The app logs no request bodies or headers. Gunicorn's access log does record client IP addresses, which privacy laws such as the GDPR treat as personal data; that is one more reason to keep logs only a week.

**Retention.** Loki deletes logs after seven days. Prometheus deletes metrics after fifteen days or 2 GB. These limits keep the disk from filling, which would itself trip the `HostDiskAlmostFull` alert, and they cap how long I hold anyone's personal data.

**Credentials.** My SSH key is an ED25519 key with mode `400`, kept outside the repository. `.gitignore` excludes `*.pem` in case I ever slip.

## 7. Conclusion

With one `docker compose up`, my app now reports its own health. In testing, every alert fired when it should and cleared on its own. The error-rate alert fired under three minutes after errors began. The outage alert fired ninety seconds after I stopped the app and cleared fourteen seconds after it returned. Loki and Prometheus agreed on the number of failed requests to within three.

The biggest lesson was how much Alloy simplifies collection. One agent and one config file replaced three agents, one of them dead. That made the system easier to draw, to explain, and to secure.

Next steps:

- Send alerts to email or Discord through Alertmanager or Grafana contact points.
- Serve Grafana over HTTPS.
- Add OpenTelemetry tracing to the app and send traces through Alloy to Grafana Tempo.
- Move monitoring to its own machine, so a dead instance cannot hide its own death.

## References

**Grafana Alloy**
- Grafana Alloy documentation: https://grafana.com/docs/alloy/latest/
- Migrate from Promtail to Grafana Alloy: https://grafana.com/docs/alloy/latest/set-up/migrate/from-promtail/
- `prometheus.exporter.unix`: https://grafana.com/docs/alloy/latest/reference/components/prometheus/prometheus.exporter.unix/
- `prometheus.exporter.cadvisor`: https://grafana.com/docs/alloy/latest/reference/components/prometheus/prometheus.exporter.cadvisor/
- `loki.source.docker`: https://grafana.com/docs/alloy/latest/reference/components/loki/loki.source.docker/
- `prometheus.remote_write`: https://grafana.com/docs/alloy/latest/reference/components/prometheus/prometheus.remote_write/
- `loki.process`: https://grafana.com/docs/alloy/latest/reference/components/loki/loki.process/

**Loki**
- Promtail end-of-life notice: https://grafana.com/docs/loki/latest/send-data/promtail/
- Log retention: https://grafana.com/docs/loki/latest/operations/storage/retention/

**Prometheus**
- Storage and retention: https://prometheus.io/docs/prometheus/latest/storage/
- Alerting rules: https://prometheus.io/docs/prometheus/latest/configuration/alerting_rules/
- Querying basics: https://prometheus.io/docs/prometheus/latest/querying/basics/

**Grafana**
- Provision Grafana: https://grafana.com/docs/grafana/latest/administration/provisioning/
- Configure security: https://grafana.com/docs/grafana/latest/setup-grafana/configure-security/

**Application and platform**
- prometheus-flask-exporter: https://github.com/rycus86/prometheus_flask_exporter
- Install the Docker Compose plugin: https://docs.docker.com/compose/install/linux/
- Amazon EC2 key pairs: https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/ec2-key-pairs.html
- Amazon EC2 security groups: https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/ec2-security-groups.html
