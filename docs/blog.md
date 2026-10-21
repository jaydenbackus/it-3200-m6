---
title: "Monitoring a Flask App on EC2 with Grafana Alloy, Prometheus, and Loki"
published: false
tags: observability, grafana, prometheus, aws
---

# Monitoring a Flask App on EC2 with Grafana Alloy, Prometheus, and Loki

*IT 3200 · Jayden Backus · Code: [github.com/jaydenbackus/it-3200-m6](https://github.com/jaydenbackus/it-3200-m6)*

## 1. Introduction

In an earlier module I put a small Flask app in a Docker container and ran it on an AWS EC2 instance. It shows one page, and gunicorn serves it on port 3000.

A public IP draws attention fast. Three minutes after I started the app on a new instance, my logs showed requests for `/api/v1/version`, a path my app has never had. Something was scanning for exposed services.

Before this project I could not have seen that. I would have learned of an outage only when someone told me, and to read a log I had to SSH in. I wanted to know, without logging in, whether the app is up and fast, whether the server is healthy, and what happened when something failed. I also wanted the system to warn me.

## 2. Why I chose these tools

I used four open-source tools:

- **Grafana Alloy** collects metrics and logs and forwards them.
- **Prometheus** stores metrics and checks alert rules.
- **Loki** stores logs, indexing only their labels.
- **Grafana** draws dashboards from both.

**Alloy was the key choice.** Many tutorials run three collectors: node_exporter for host metrics, cAdvisor for container metrics, and Promtail for logs. The Loki docs say Promtail reached end of life on March 2, 2026, and that new work happens in Alloy. Alloy also contains node_exporter and cAdvisor as built-in components, so one agent and one config file replace all three. On a 2 GB server, that matters.

**Prometheus and Loki fit together.** Both label data the same way, so `service="app"` finds the app's metrics and its logs. A one-line library, `prometheus-flask-exporter`, makes Flask speak Prometheus's format. Loki's label-only index keeps it far lighter than Elasticsearch.

**Limitations.** I host it all myself, on the same server as the app, so if the server dies, so does its monitoring. Alloy needs privileged access (see section 6). Alerts fire but don't page anyone yet; that needs Alertmanager.

**What I rejected.** AWS CloudWatch needs no servers, but its container features target ECS and EKS rather than plain Docker, it bills per custom metric, and it ties me to AWS. The Elastic Stack searches logs well but would strain a 2 GB server.

## 3. Installation and configuration

![Architecture diagram](https://raw.githubusercontent.com/jaydenbackus/it-3200-m6/main/docs/architecture.png)

Alloy scrapes the app's `/metrics` every 15 seconds, reads host and container statistics, and tails every container's logs through the Docker socket. It pushes metrics to Prometheus and logs to Loki. Grafana queries both.

**1. Launch EC2.** I used Amazon Linux 2023 on a `t3.small` (2 GB; five containers won't fit in a `t3.micro`) with a 20 GiB disk. The security group allows SSH (22) and Grafana (3001) from my IP only, and the app (3000) from anywhere.

*Lesson learned:* key pairs belong to one region. My old key didn't exist in mine, so SSH refused me. I imported my public key (`ssh-keygen -y -f key.pem`) under **Key pairs → Import key pair** and relaunched.

**2. Install Docker.** Amazon Linux's Docker package lacks the Compose and Buildx plugins, so I added them as Docker's docs describe:

```bash
sudo dnf install -y docker git && sudo systemctl enable --now docker
P=/usr/local/lib/docker/cli-plugins && sudo mkdir -p $P
sudo curl -fsSL https://github.com/docker/compose/releases/latest/download/docker-compose-linux-x86_64 -o $P/docker-compose
BX=$(curl -fsSI https://github.com/docker/buildx/releases/latest | grep -i '^location' | sed 's#.*/tag/##' | tr -d '\r')
sudo curl -fsSL https://github.com/docker/buildx/releases/download/$BX/buildx-$BX.linux-amd64 -o $P/docker-buildx
sudo chmod +x $P/*
```

**3. Start the stack.**

```bash
git clone https://github.com/jaydenbackus/it-3200-m6.git && cd it-3200-m6
cp .env.example .env    # then set GRAFANA_ADMIN_PASSWORD to a long random value
chmod 600 .env
sudo docker compose up -d --build
```

Grafana loads its data sources and dashboard from files at startup, so nothing needs clicking.

**The Alloy config** reads like a pipeline: each component's output feeds the next. Here is the log path:

```alloy
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

## 4. Implementation

**The app.** I added `prometheus-flask-exporter`, turned on gunicorn's access log, and added a `/health` route. I group metrics by Flask endpoint rather than by URL, so scanners requesting random paths can't create endless new time series. Two demo routes, `/simulate/error` and `/simulate/slow`, let me trigger failures. They work only when `ENABLE_SIMULATION=true` and only from the server itself.

**What I collect:**

| Signal | Source | Stored in | Kept |
|---|---|---|---|
| Request rate, errors, latency | Flask `/metrics` | Prometheus | 15 days |
| CPU, memory, disk | EC2 host, via Alloy | Prometheus | 15 days |
| CPU and memory per container | Docker, via Alloy | Prometheus | 15 days |
| App, access, and stack logs | Docker, via Alloy | Loki | 7 days |

**Dashboard.** One Grafana dashboard shows app status, request rate, error ratio, latency percentiles, per-container and host resources, and live logs.

**Alerts.** Prometheus checks six rules:

| Alert | Fires when |
|---|---|
| `StudentAppDown` | Alloy can't scrape the app for 1 minute |
| `StudentAppHighErrorRate` | over 5% of requests fail for 2 minutes |
| `StudentAppHighLatency` | p95 latency exceeds 1 second for 5 minutes |
| `HostHighCpu`, `HostLowMemory`, `HostDiskAlmostFull` | the server runs short of CPU, memory, or disk |

The waiting period keeps one slow request from raising an alarm.

## 5. Show it working

I sent ten minutes of mixed traffic, about one failed and one slow request in every nine, then stopped the app for two and a half minutes. Prometheus's `ALERTS` series recorded what followed (UTC):

| Time | Event |
|---|---|
| 04:43 | Traffic starts |
| 04:46 | `StudentAppHighErrorRate` fires |
| 04:49 | `StudentAppHighLatency` fires |
| 04:53:15 | I stop the app |
| 04:54:45 | `StudentAppDown` fires |
| 04:55:46 | I restart the app |
| 04:56:00 | `StudentAppDown` resolves |
| 04:58 | Error and latency alerts resolve |

At the peak, PromQL showed an **11%** error ratio and a **1.5-second** p95 latency, both well past their thresholds. Logs and metrics agreed: Loki held 251 lines for HTTP 500 responses, and Prometheus counted 248.

One surprise: the error alert kept firing during the outage, though a stopped app returns no errors. The rule averages the last five minutes, which still held the earlier failures.

The test also exposed a bug in my load generator. It quit when the app went down, because `set -e` treated one failed request as fatal. I removed it.

<!-- SCREENSHOT: dashboard during the test (error ratio and latency in red) -->
<!-- SCREENSHOT: Alerting page with StudentAppHighErrorRate and StudentAppDown firing -->
<!-- SCREENSHOT: Explore → Loki, {service="app"} |= " 500 " -->
<!-- SCREENSHOT: browser showing 403 Forbidden for /metrics -->

## 6. Security considerations

- **Exposure.** Only the app is open to the internet; Grafana and SSH accept my IP alone. Prometheus, Loki, and Alloy listen on `127.0.0.1`, and a port scan from outside found them closed. I reach them through an SSH tunnel.
- **Unauthenticated internals.** Loki and Prometheus accept data without a password. That is safe only because nothing outside the server can reach them.
- **App endpoints.** `/metrics` returns 403 to the public, and the demo routes return 404, so outsiders can neither read internal numbers nor trigger slow requests to tie up the app.
- **Grafana.** A random admin password lives in `.env`, which Git ignores. Sign-up and anonymous access are off. Grafana runs over plain HTTP; a real deployment would add TLS.
- **Privileged collector.** Alloy reads the Docker socket and host files, and control of the Docker socket means control of the host. I mount everything read-only, pin the image version, and keep Alloy's web page private.
- **Logs.** Alloy blanks credential-like values before storage. Access logs hold client IPs, which count as personal data, so Loki deletes logs after seven days.
- **Repository.** No keys, passwords, or server addresses are committed. `.gitignore` excludes `.env` and `*.pem`.

## 7. Conclusion

One `docker compose up` gave my app metrics, logs, a dashboard, and alerts that fired and cleared as designed. The biggest lesson was how much Alloy simplifies collection: one agent replaced three, which made the system easier to explain and to secure. Next I would send alerts to email, add HTTPS, and add tracing with OpenTelemetry.

## References

- Grafana Alloy: https://grafana.com/docs/alloy/latest/
- Migrate from Promtail to Alloy: https://grafana.com/docs/alloy/latest/set-up/migrate/from-promtail/
- Promtail end-of-life notice: https://grafana.com/docs/loki/latest/send-data/promtail/
- Alloy `prometheus.exporter.cadvisor`: https://grafana.com/docs/alloy/latest/reference/components/prometheus/prometheus.exporter.cadvisor/
- Alloy `loki.source.docker`: https://grafana.com/docs/alloy/latest/reference/components/loki/loki.source.docker/
- Loki retention: https://grafana.com/docs/loki/latest/operations/storage/retention/
- Prometheus alerting rules: https://prometheus.io/docs/prometheus/latest/configuration/alerting_rules/
- Prometheus storage: https://prometheus.io/docs/prometheus/latest/storage/
- Grafana provisioning: https://grafana.com/docs/grafana/latest/administration/provisioning/
- prometheus-flask-exporter: https://github.com/rycus86/prometheus_flask_exporter
- Install the Docker Compose plugin: https://docs.docker.com/compose/install/linux/
- Amazon EC2 key pairs: https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/ec2-key-pairs.html
