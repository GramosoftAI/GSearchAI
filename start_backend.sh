#!/bin/bash
# Startup script for GraphMind backend with detailed logging

echo "=========================================="
echo "🚀 Starting GraphMind Backend"
echo "=========================================="
echo ""
echo "Configuration:"
echo "  LOG_LEVEL: DEBUG"
echo "  POSTGRES_ECHO: true"
echo "  Environment: development"
echo ""
echo "Starting uvicorn with detailed output..."
echo "=========================================="
echo ""

# Ensure we are in the correct directory
cd "$(dirname "$0")"

# Use the virtual environment uvicorn if it exists, otherwise fallback to global
if [ -f "venv/bin/uvicorn" ]; then
    UVICORN_CMD="./venv/bin/uvicorn"
else
    UVICORN_CMD="uvicorn"
fi

echo "🚀 Launching Memory API in background on port 4917..."
PYTHONPATH=./app/memory/app $UVICORN_CMD app.memory.app.main:app --host 0.0.0.0 --port 4917 &

echo "🚀 Launching Main API on port 4915..."
$UVICORN_CMD app.main:app --host 0.0.0.0 --port 4915 --log-level debug



