#!/bin/bash
# St. Demetrios Church Calendar Server Startup Script
# For Raspberry Pi OS

COMPONENT="church-calendar.startup"

log() {
	local level="$1"
	shift
	local msg="$*"
	local ts
	ts=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
	echo "$ts $COMPONENT $level $msg"
}

log "INFO" "Starting St. Demetrios Church Calendar Server"

# Change to the script directory
cd "$(dirname "$0")"

# Start the Python server
python3 server.py

log "INFO" "Server stopped"
read -p "Press Enter to exit..."
