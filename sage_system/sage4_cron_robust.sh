#!/bin/bash
# SAGE 4.2 ROBUST PRODUCTION CRON
# Gmail-only with enterprise-grade reliability
# Created: October 9, 2025

# Exit on any error
set -e

# Configuration
SCRIPT_DIR="/home/ubuntu/newspaper_project"
LOG_DIR="$SCRIPT_DIR/logs"
LOG_FILE="$LOG_DIR/sage4_cron.log"
ERROR_LOG="$LOG_DIR/sage4_errors.log"
HEALTH_FILE="$LOG_DIR/sage4_health.json"
LOCKFILE="/tmp/sage4_cron.lock"
PIDFILE="/tmp/sage4_cron.pid"
PYTHON="/usr/bin/python3"
GMAIL_SCRIPT="$SCRIPT_DIR/sage4_gmail_robust.py"

# Environment setup
export PATH=/usr/local/bin:/usr/bin:/bin
export HOME=/home/ubuntu
export TZ='America/New_York'
export PYTHONUNBUFFERED=1

# Create log directory
mkdir -p "$LOG_DIR"

# Function to log messages
log_message() {
    local level=$1
    local message=$2
    local timestamp=$(TZ='America/New_York' date '+%Y-%m-%d %I:%M:%S %p ET')
    echo "[$timestamp] [$level] $message" >> "$LOG_FILE"
    echo "[$timestamp] [$level] $message"
}

# Function to log errors
log_error() {
    local message=$1
    local timestamp=$(TZ='America/New_York' date '+%Y-%m-%d %I:%M:%S %p ET')
    echo "[$timestamp] [ERROR] $message" >> "$ERROR_LOG"
    echo "[$timestamp] [ERROR] $message" >> "$LOG_FILE"
    echo "[$timestamp] [ERROR] $message" >&2
}

# Function to update health status
update_health() {
    local status=$1
    local message=$2
    local timestamp=$(TZ='America/New_York' date '+%Y-%m-%d %I:%M:%S %p ET')
    
    cat > "$HEALTH_FILE" <<EOF
{
    "status": "$status",
    "message": "$message",
    "timestamp": "$timestamp",
    "pid": $$,
    "last_run": "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
}
EOF
}

# Function to clean up on exit
cleanup() {
    local exit_code=$?
    
    if [ $exit_code -eq 0 ]; then
        update_health "success" "Completed successfully"
    else
        update_health "failed" "Failed with exit code $exit_code"
    fi
    
    rm -f "$LOCKFILE" "$PIDFILE"
    log_message "INFO" "Cleanup completed (exit code: $exit_code)"
}

# Set trap for cleanup
trap cleanup EXIT INT TERM

# Check if another instance is running
check_lock() {
    if [ -f "$LOCKFILE" ]; then
        if [ -f "$PIDFILE" ]; then
            OLD_PID=$(cat "$PIDFILE")
            
            # Check if process is actually running
            if kill -0 "$OLD_PID" 2>/dev/null; then
                # Check if it's been running too long (>10 minutes)
                local lock_age=$(( $(date +%s) - $(stat -c %Y "$LOCKFILE") ))
                if [ $lock_age -gt 600 ]; then
                    log_message "WARN" "Stale lock detected (age: ${lock_age}s), killing old process $OLD_PID"
                    kill -TERM "$OLD_PID" 2>/dev/null || true
                    sleep 2
                    kill -KILL "$OLD_PID" 2>/dev/null || true
                    rm -f "$LOCKFILE" "$PIDFILE"
                else
                    log_message "INFO" "Another instance is running (PID: $OLD_PID, age: ${lock_age}s). Skipping."
                    exit 0
                fi
            else
                log_message "INFO" "Removing stale lock file (process $OLD_PID not running)"
                rm -f "$LOCKFILE" "$PIDFILE"
            fi
        fi
    fi
}

# Function to verify environment
verify_environment() {
    local errors=0
    
    # Check Python
    if ! command -v "$PYTHON" &> /dev/null; then
        log_error "Python3 not found at $PYTHON"
        errors=$((errors + 1))
    fi
    
    # Check Gmail script
    if [ ! -f "$GMAIL_SCRIPT" ]; then
        log_error "Gmail script not found: $GMAIL_SCRIPT"
        errors=$((errors + 1))
    fi
    
    # Check credentials
    if [ ! -f "$SCRIPT_DIR/gmail_env.sh" ]; then
        log_error "Gmail credentials file not found: $SCRIPT_DIR/gmail_env.sh"
        errors=$((errors + 1))
    fi
    
    # Check required Python packages
    $PYTHON -c "import lancedb, pandas, pytz" 2>/dev/null || {
        log_error "Required Python packages not installed"
        errors=$((errors + 1))
    }
    
    if [ $errors -gt 0 ]; then
        log_error "Environment verification failed with $errors errors"
        exit 1
    fi
    
    log_message "INFO" "Environment verification passed"
}

# Function to get database statistics
get_db_stats() {
    $PYTHON <<'PYTHON_EOF' 2>/dev/null || echo "Could not get stats"
import lancedb
import pytz
from datetime import datetime

try:
    db = lancedb.connect('s3://sage-unified-feed-lance/sage4/')
    table = db.open_table('unified_feed')
    df = table.to_pandas()
    
    emails = df[df['source_type'] == 'email']
    total = len(df)
    email_count = len(emails)
    
    # Get latest email time
    if email_count > 0:
        df['created_at'] = df['created_at'].astype('datetime64[ns]')
        latest = emails['created_at'].max()
        et = pytz.timezone('America/New_York')
        latest_et = latest.tz_localize('UTC').tz_convert(et) if latest.tz is None else latest
        latest_str = latest_et.strftime('%I:%M %p ET on %b %d')
    else:
        latest_str = "No emails yet"
    
    # Check for duplicates
    unique_ids = df['id'].nunique()
    duplicates = len(df) - unique_ids
    
    print(f"Total: {total} | Emails: {email_count} | Latest: {latest_str}", end="")
    if duplicates > 0:
        print(f" | ⚠️ {duplicates} duplicates!", end="")
    
except Exception as e:
    print(f"Error: {e}")
PYTHON_EOF
}

# Main execution
main() {
    log_message "INFO" "=========================================="
    log_message "INFO" "SAGE 4.2 Cron Job Started (Gmail-only mode)"
    update_health "running" "Cron job started"
    
    # Change to script directory
    cd "$SCRIPT_DIR"
    
    # Check lock
    check_lock
    
    # Create lock
    touch "$LOCKFILE"
    echo $$ > "$PIDFILE"
    
    # Verify environment
    verify_environment
    
    # Load Gmail credentials
    if [ -f gmail_env.sh ]; then
        source gmail_env.sh
        log_message "INFO" "Gmail credentials loaded"
    else
        log_error "gmail_env.sh not found!"
        exit 1
    fi
    
    # Kill any stray processes (cleanup)
    pkill -f sage4_gmail_beautiful_fixed 2>/dev/null || true
    pkill -f sage4_gmail_batch_limited 2>/dev/null || true
    sleep 1
    
    # Get initial stats
    log_message "INFO" "Database before: $(get_db_stats)"
    
    # Run Gmail fetcher with timeout (5 minutes max)
    log_message "INFO" "Starting Gmail fetch (max 5 minutes)..."
    
    if timeout 300 "$PYTHON" "$GMAIL_SCRIPT" >> "$LOG_FILE" 2>&1; then
        GMAIL_EXIT=0
        log_message "SUCCESS" "✅ Gmail fetch completed successfully"
        update_health "success" "Gmail fetch successful"
    else
        GMAIL_EXIT=$?
        if [ $GMAIL_EXIT -eq 124 ]; then
            log_error "⚠️ Gmail fetch timed out after 5 minutes"
            update_health "timeout" "Gmail fetch timed out"
        else
            log_error "❌ Gmail fetch failed with exit code $GMAIL_EXIT"
            update_health "failed" "Gmail fetch failed: exit $GMAIL_EXIT"
        fi
    fi
    
    # Get final stats
    log_message "INFO" "Database after: $(get_db_stats)"
    
    # Rotate logs if too large (>10MB)
    if [ -f "$LOG_FILE" ] && [ $(stat -c%s "$LOG_FILE") -gt 10485760 ]; then
        log_message "INFO" "Rotating large log file"
        mv "$LOG_FILE" "$LOG_FILE.$(date +%Y%m%d_%H%M%S)"
        tail -n 5000 "$LOG_FILE".* | head -n 5000 > "$LOG_FILE"
        find "$LOG_DIR" -name "sage4_cron.log.*" -mtime +7 -delete
    fi
    
    log_message "INFO" "Cron job completed"
    log_message "INFO" "=========================================="
}

# Execute main function
main

exit $GMAIL_EXIT



