#!/bin/bash

COMPONENT="church-calendar.eventhandler-handler-down"

log() {
	local level="$1"
	shift
	local msg="$*"
	local ts
	ts=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
	local line="$ts $COMPONENT $level $msg"
	echo "$line"
	logger -t "$COMPONENT" "$line"
}

log "WARN" "handler_down_invoked stream_offline_threshold_reached=true"

# Example action:
# systemctl restart my-service

# Add your commands below:
# killall something
# start backup feed
