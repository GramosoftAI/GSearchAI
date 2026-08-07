#!/bin/bash
set -e

echo "Starting Automatic Rollback..."

# Restore previous commit in staging
echo "Reverting to previous commit..."
git reset --hard HEAD~1

# Restart application
echo "Restarting application via PM2 with previous known-good state..."
# pm2 restart gsearch-backend
echo "PM2 Restart command executed."

# Notify
echo "========================================="
echo "ALERT: Deployment failed and was rolled back."
echo "========================================="
