# Small official Python base image
FROM python:3.12-slim

# All following commands run inside /app in the container
WORKDIR /app

# Install dependencies first so Docker can cache this layer
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application source code
COPY . .

# The app listens on port 3000
EXPOSE 3000

# Run with gunicorn, a production-ready WSGI server
CMD ["gunicorn", "--bind", "0.0.0.0:3000", "app:app"]
