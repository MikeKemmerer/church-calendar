# VLC RTMP Watchdog System

This project provides a lightweight watchdog that monitors a running VLC instance via its RC (remote control) interface. It detects when an RTMP feed has stalled (bitrate = 0) for a configurable number of checks and triggers custom handler scripts. When the stream recovers, a separate recovery handler runs.

This is ideal for broadcast automation, fallback switching, encoder restarts, or any workflow where VLC freezes on the last frame instead of exiting.

---

## Overview

The system consists of three scripts:

| File | Purpose |
|------|---------|
| `watchdog.sh` | Polls VLC stats, tracks consecutive zero‑bitrate readings, triggers handlers |
| `handler-down.sh` | Runs once when the stream has been dead for 5 consecutive checks |
| `handler-up.sh` | Runs once when the stream recovers |

You can customize the handlers to start/stop services, kill processes, switch feeds, or perform any other automation.

---

## Prerequisites

### 1. VLC must be running with the RC interface enabled

Start VLC like this:

```bash
cvlc rtmp://your/feed \
    --extraintf rc \
    --rc-unix /tmp/vlc.sock
```

This creates a UNIX socket at `/tmp/vlc.sock` that the watchdog polls.

### 2. `socat` must be installed

On Debian/Ubuntu:

```bash
sudo apt install socat
```

---

## Installation

1. Copy the three scripts into a directory, for example:

```
/usr/local/bin/vlc-watchdog/
```

2. Make them executable:

```bash
chmod +x /usr/local/bin/vlc-watchdog/watchdog.sh
chmod +x /usr/local/bin/vlc-watchdog/handler-down.sh
chmod +x /usr/local/bin/vlc-watchdog/handler-up.sh
```

3. Edit `watchdog.sh` and update the handler paths:

```bash
HANDLER_DOWN="/usr/local/bin/vlc-watchdog/handler-down.sh"
HANDLER_UP="/usr/local/bin/vlc-watchdog/handler-up.sh"
```

---

## How It Works

### 1. Polling VLC

The watchdog queries VLC’s RC interface:

```bash
echo "stats" | socat - /tmp/vlc.sock
```

It extracts:

```
bitrate (bits/s)
```

If VLC is frozen on the last frame, this value becomes `0`.

---

### 2. Debounce Logic (5 consecutive checks)

The watchdog increments a counter each time bitrate is zero:

- If bitrate > 0 → counter resets  
- If bitrate = 0 → counter increases  
- When counter reaches **5**, the outage handler runs  
- The outage handler runs **only once per outage**  

This prevents false positives from brief RTMP hiccups.

---

### 3. Recovery Detection

When bitrate becomes non‑zero again:

- The recovery handler runs **once**
- The outage state resets
- The counter resets to zero

This ensures clean transitions between outage and recovery states.

---

## Cron Setup

Run the watchdog every minute:

```bash
crontab -e
```

Add:

```
* * * * * /usr/local/bin/vlc-watchdog/watchdog.sh
```

You may adjust the interval depending on your needs.

---

## State Files

The watchdog uses two small files in `/tmp`:

| File | Purpose |
|------|---------|
| `/tmp/vlc_zero_count` | Tracks consecutive zero‑bitrate readings |
| `/tmp/vlc_stream_dead` | Indicates the outage handler has already fired |

These files are automatically created and removed as needed.

---

## Customizing the Handlers

### `handler-down.sh`

Runs when the stream has been dead for 5 checks.

Use this to:

- Start a backup feed  
- Restart an encoder  
- Send alerts  
- Switch camera sources  

### `handler-up.sh`

Runs when the stream recovers.

Use this to:

- Kill backup processes  
- Restore normal routing  
- Log recovery events  

---

## Troubleshooting

### VLC socket not found

Ensure VLC was started with:

```
--extraintf rc --rc-unix /tmp/vlc.sock
```

### Bitrate always zero

Some RTMP servers require:

```
--network-caching=1000
--rtmp-timeout=10
```

### Handlers not running

Check permissions:

```bash
chmod +x handler-down.sh handler-up.sh
```

---

