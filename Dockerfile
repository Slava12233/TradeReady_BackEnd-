# API Service — FastAPI gateway
# Python 3.12-slim base keeps the image small while staying on the target runtime.
FROM python:3.12-slim

WORKDIR /app

# Install OS-level deps needed by asyncpg / bcrypt C extensions
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    curl \
  && rm -rf /var/lib/apt/lists/*

# Layer dependencies separately so they are cached unless requirements change
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY src/ ./src/
COPY alembic/ ./alembic/
COPY alembic.ini .
COPY scripts/ ./scripts/
# .env is optional at build time — runtime env vars from docker-compose env_file take precedence
COPY .env* ./

EXPOSE 8000

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
