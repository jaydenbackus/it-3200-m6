# IT 3200 – Module 6: Containerized Flask App on AWS EC2

A small Flask web application that displays my name and UVU student ID. It is packaged with Docker and deployed to an AWS EC2 Linux virtual machine.

- **Name:** Jayden Backus
- **UVU Student ID:** 11005564
- **Course:** IT 3200

## Project structure

| File | Purpose |
|------|---------|
| `app.py` | Flask application with a single route (`/`) that renders the page |
| `templates/index.html` | HTML page showing name, student ID, and course |
| `requirements.txt` | Python dependencies (Flask, gunicorn) |
| `Dockerfile` | Instructions to build the container image |
| `.dockerignore` | Files excluded from the Docker build context |

## Run locally with Docker

```bash
docker build -t student-app .
docker run -d -p 3000:3000 --name student-app student-app
docker ps
```

Open http://localhost:3000.

## Deploy to AWS EC2

1. **Launch an EC2 instance**: Amazon Linux 2023, `t3.micro` (free-tier eligible), with a key pair for SSH and a public IP.
2. **Security group inbound rules**:
   - TCP 22 (SSH) from my IP only
   - TCP 3000 (app) from `0.0.0.0/0`
3. **Connect**: `ssh -i it-3200-m6-key.pem ec2-user@<PUBLIC-IP>`
4. **Install Docker and Git**:
   ```bash
   sudo dnf install -y docker git
   sudo systemctl enable --now docker
   sudo usermod -aG docker ec2-user   # log out and back in afterward
   docker --version
   ```
5. **Clone, build, and run**:
   ```bash
   git clone https://github.com/jaydenbackus/it-3200-m6.git
   cd it-3200-m6
   docker build -t student-app .
   docker run -d -p 3000:3000 --restart unless-stopped --name student-app student-app
   docker ps
   ```
6. **Test**: `curl http://localhost:3000` on the VM, then open `http://<PUBLIC-IP>:3000` in a browser.

## Troubleshooting

```bash
docker ps                 # is the container running?
docker logs student-app   # application errors
curl http://localhost:3000
```

If `curl` works on the VM but the browser can't reach the app, check the security group rule for port 3000.

## Cleanup

When done, terminate the EC2 instance and delete the security group and key pair to avoid charges.
