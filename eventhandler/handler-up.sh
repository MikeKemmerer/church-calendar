#!/bin/bash

COMPONENT="church-calendar.eventhandler-handler-up"

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

log "INFO" "handler_up_invoked stream_recovered=true"

# Example action:
# killall backup-process

# Add your commands below:
# systemctl stop backup-feed
