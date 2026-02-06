# Use official Python runtime as specific as possible
FROM python:3.11-slim

# Set environment variables
# PYTHONDONTWRITEBYTECODE: prevents Python from writing pyc files to disc
# PYTHONUNBUFFERED: prevents Python buffering stdout and stderr
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Install system dependencies
# gcc and python3-dev are often required for building python extensions
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

# Set work directory
WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy project
COPY . .

# Run as non-root user for security (Cloud Run runs as root by default, but good practice)
# However, for simplicity and to avoid permission issues with some libraries, we'll stick to default for now
# or ensure permissions are correct if we switch users.
# Keeping it simple for now.

# Expose port (Cloud Run sets $PORT env var, default 8080)
# We don't strictly need EXPOSE for Cloud Run, but it documents intent
EXPOSE 8080

# Command to run the application using Gunicorn
# Bind to 0.0.0.0:$PORT
CMD exec gunicorn --bind :$PORT --workers 1 --threads 8 --timeout 0 unified_app:app
