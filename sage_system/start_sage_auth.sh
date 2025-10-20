#!/bin/bash
# SAGE Authenticated Startup Script

echo "🚀 Starting SAGE with Authentication..."

# Set password (change this!)
export SCRAPEX_PASSWORD='scrapex2025'

# Go to directory
cd /home/ubuntu/newspaper_project

# Stop any existing instance
pkill -f sage_twitter_interface

# Start authenticated SAGE
nohup python3 sage_twitter_interface_enhanced_v2_auth.py > /home/ubuntu/SAGE4/sage_auth.log 2>&1 &

sleep 2

# Check status
if pgrep -f sage_twitter_interface_enhanced_v2_auth > /dev/null; then
    echo "✅ SAGE is running with authentication!"
    echo "🔗 http://44.225.226.126:8540"
    echo "🔑 Password: $SCRAPEX_PASSWORD"
else
    echo "❌ Failed to start. Check logs:"
    tail -10 /home/ubuntu/SAGE4/sage_auth.log
fi
