# Backend Dockerfile for CodeBrain AI System
FROM python:3.11-slim AS base

WORKDIR /app

# Install system dependencies needed for tree-sitter, git, and reportlab
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy and install python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend source code
COPY . .

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD curl -f http://localhost:8000/ || exit 1

# Launch uvicorn
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
