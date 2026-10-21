# IT 3200 – Module 6: Containerized Flask App on AWS EC2

A small Flask web application that displays my name and UVU student ID. It is packaged with Docker and deployed to an AWS EC2 Linux virtual machine.

- **Name:** Jayden Backus
- **UVU Student ID:** [removed]
- **Course:** IT 3200

## Project structure

| File | Purpose |
|------|---------|
| `app.py` | Flask application with a single route (`/`) that renders the page |
| `templates/index.html` | HTML page showing name, student ID, and course |
| `requirements.txt` | Python dependencies (Flask, gunicorn) |
| `Dockerfile` | Instructions to build the container image |
| `.dockerignore` | Files excluded from the Docker build context |

Open http://localhost:3000.

## Monitoring and observability

The app ships with an observability stack defined in `docker-compose.yml`:

| Component | Role |
|-----------|------|
| **Grafana Alloy** | Single collector: scrapes the app's `/metrics`, exports host (node) and container (cAdvisor) metrics, and tails Docker container logs |
| **Prometheus** | Stores metrics (pushed by Alloy via remote write) and evaluates alert rules |
| **Loki** | Stores logs (pushed by Alloy) with 7-day retention |
| **Grafana** | Dashboards and alert views (provisioned from `monitoring/grafana/`) |

```bash
cp .env.example .env          # then set a strong GRAFANA_ADMIN_PASSWORD
docker compose up -d --build
docker compose ps
```

- App: `http://<PUBLIC-IP>:3000`
- Grafana: `http://<PUBLIC-IP>:3001` (open port 3001 to **your IP only** in the security group)
- Prometheus, Loki, and Alloy UIs bind to `127.0.0.1` on the VM. Reach them with an SSH tunnel:
  `ssh -i key.pem -L 9090:localhost:9090 -L 12345:localhost:12345 ec2-user@<PUBLIC-IP>`

To demo alerts, set `ENABLE_SIMULATION=true` in `.env`, run `docker compose up -d`, and then run `./scripts/generate-traffic.sh`.
