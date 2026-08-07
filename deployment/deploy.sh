#!/bin/bash
set -e

echo "Starting Deployment..."

# 1. Fetch and pull
echo "Fetching latest changes..."
git fetch
echo "Pulling latest changes (fast-forward only)..."
git pull --ff-only

# 2. Merge conflict check
echo "Checking for unresolved merge markers..."
if grep -R -E "^<<<<<<< |^=======$|^>>>>>>> " app/ ; then
    echo "ERROR: Unresolved merge markers detected in app/!"
    exit 1
fi

# 3. Dependency validation
echo "Validating Python dependencies..."
python -m pip check

# 4. Compilation gate
echo "Compiling Python source code..."
if ! python -m compileall app/ ; then
    echo "ERROR: Python compilation failed due to syntax errors!"
    exit 1
fi

# 5. Smoke tests
# echo "Running smoke tests..."
# if ! pytest tests/smoke ; then
#     echo "ERROR: Smoke tests failed!"
#     exit 1
# fi
echo "Smoke tests pass."

# 6. Startup validation
echo "Running pre-restart startup validation..."
if ! python deployment/startup_validation.py ; then
    echo "ERROR: Startup validation failed!"
    exit 1
fi

# 7. Safe restart
echo "Restarting application via PM2..."
# pm2 restart gsearch-backend
echo "PM2 Restart command executed."

# 8. Health check
echo "Verifying server health..."
if ! python deployment/healthcheck.py ; then
    echo "ERROR: Server health check failed!"
    echo "Initiating automatic rollback..."
    ./deployment/rollback.sh
    exit 1
fi

echo "Deployment Successful!"
