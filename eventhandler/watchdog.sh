#!/bin/bash

SCRIPT_DIR=$(dirname "$(readlink -f "$0")")
SOCK="/tmp/vlc.sock"
HANDLER_DOWN="$SCRIPT_DIR/handler-down.sh"
HANDLER_UP="$SCRIPT_DIR/handler-up.sh"
COMPONENT="church-calendar.eventhandler-watchdog"

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

STATE="/tmp/vlc_stream_dead"      # indicates outage handler fired
COUNT="/tmp/vlc_zero_count"       # consecutive zero-bitrate counter

# Load previous count
if [ -f "$COUNT" ]; then
    ZERO_COUNT=$(cat "$COUNT")
else
    ZERO_COUNT=0
fi

# Query VLC stats
BITRATE=$(echo "stats" | socat - $SOCK 2>/dev/null \
    | grep "bitrate" \
    | awk -F: '{print $2}' \
    | tr -d ' ')

# Treat missing stats as zero bitrate
if [ -z "$BITRATE" ]; then
    BITRATE=0
fi

if [ "$BITRATE" -eq 0 ]; then
    # Stream appears dead
    ZERO_COUNT=$((ZERO_COUNT + 1))
    echo "$ZERO_COUNT" > "$COUNT"

    # Trigger outage handler only once
    if [ "$ZERO_COUNT" -ge 5 ] && [ ! -f "$STATE" ]; then
        touch "$STATE"
        log "WARN" "stream_dead_zero_bitrate_checks=5 action=run_handler_down"
        "$HANDLER_DOWN"
    fi

else
    # Stream is alive
    if [ -f "$STATE" ]; then
        log "INFO" "stream_recovered action=run_handler_up"
        "$HANDLER_UP"
        rm -f "$STATE"
    fi

    # Reset counter
    ZERO_COUNT=0
    echo "$ZERO_COUNT" > "$COUNT"
fi
