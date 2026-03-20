# Agent Service — TradeReady Platform Testing Agent + ML Strategy System
#
# Installs three local packages in editable mode:
#   1. sdk/         (agentexchange) — REST + WebSocket SDK
#   2. tradeready-gym/ (tradeready-gym) — Gymnasium RL environments
#   3. agent/[all]  — testing agent + dev + ML extras (SB3, torch, xgboost, etc.)
#
# The [all] extra pulls in stable-baselines3, torch, xgboost, scikit-learn, and joblib.
# For CPU-only deployments this is sufficient. For GPU-accelerated RL training,
# swap the base image for the appropriate CUDA variant and install the CUDA-enabled
# torch wheel instead:
#   # For GPU: use nvidia/cuda base image, e.g.
#   #   FROM nvidia/cuda:12.4.1-cudnn9-runtime-ubuntu22.04
#   # then install Python 3.12 manually and use the CUDA torch wheel.
#
# Build context is the repo root so all three packages are accessible.
#   docker build -f agent/Dockerfile -t tradeready-agent .

FROM python:3.12-slim

WORKDIR /app

# Install OS-level build dependencies needed by:
#   - numpy / scipy C extensions (gcc)
#   - some torch wheels (g++)
#   - xgboost cmake-based build (cmake) — only needed when no wheel is available
#   - httpx / asyncpg certificate validation (ca-certificates)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    cmake \
    ca-certificates \
  && rm -rf /var/lib/apt/lists/*

# Upgrade pip to avoid legacy resolver issues with large dependency graphs (torch, SB3)
RUN pip install --no-cache-dir --upgrade pip

# ── Layer 1: install SDK ──────────────────────────────────────────────────────
# Copy and install first so this layer is cached unless sdk/ changes.
COPY sdk/ ./sdk/
RUN pip install --no-cache-dir -e ./sdk/

# ── Layer 2: install tradeready-gym ──────────────────────────────────────────
COPY tradeready-gym/ ./tradeready-gym/
RUN pip install --no-cache-dir -e ./tradeready-gym/

# ── Layer 3: install agent with all extras ────────────────────────────────────
# The [all] extra resolves to [dev,ml], which includes:
#   stable-baselines3[extra], torch, xgboost, scikit-learn, joblib, numpy, pandas
# This is the heaviest layer; it is placed last so earlier layers remain cached
# when only agent/ source files change.
COPY agent/ ./agent/
RUN pip install --no-cache-dir -e "./agent/[all]"

# Create a non-root user for runtime security
RUN adduser --disabled-password --gecos "" agentuser \
  && mkdir -p \
      /app/agent/reports \
      /app/agent/strategies/rl/models \
      /app/agent/strategies/regime/models \
      /app/agent/strategies/evolutionary/results \
  && chown -R agentuser /app/agent/reports \
  && chown -R agentuser /app/agent/strategies

USER agentuser

WORKDIR /app/agent

# Default: run all four workflows and write a platform-validation report.
# Override at runtime via docker run / compose command:
#   command: ["python", "-m", "agent.main", "smoke"]
CMD ["python", "-m", "agent.main", "all"]
