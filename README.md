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

Open http://localhost:3000.
