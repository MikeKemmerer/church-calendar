#!/usr/bin/env bash
# install.sh — Installs the St. Demetrios Church Calendar display on a Raspberry Pi.
#
# Idempotent: safe to re-run for upgrades. Installs Python dependencies, deploys the
# app to a target directory, seeds a local config.json if missing, and registers a
# systemd service so the calendar starts on boot.
#
# Usage:
#   sudo ./install.sh                 # install/upgrade with defaults
#   RUN_USER=pi DEST=/home/pi/church-calendar sudo -E ./install.sh
#
# Environment overrides:
#   RUN_USER  Service user (default: pi)
#   DEST      Install directory (default: /home/$RUN_USER/church-calendar)
#   PORT      HTTP port the server listens on (informational; default: 8000)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
RUN_USER="${RUN_USER:-pi}"
DEST="${DEST:-/home/${RUN_USER}/church-calendar}"
SERVICE_NAME="church-calendar"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"

if [[ $EUID -ne 0 ]]; then
    echo "Error: this installer must be run as root (use sudo)." >&2
    exit 1
fi

if ! id "$RUN_USER" &>/dev/null; then
    echo "Error: user '$RUN_USER' does not exist. Set RUN_USER to a valid account." >&2
    exit 1
fi

echo "==> Installing system dependencies"
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
# Use distro Python packages (PEP 668 friendly on Raspberry Pi OS Bookworm).
# server.py degrades gracefully if Pillow (python3-pil) is unavailable.
apt-get install -y python3 python3-pil python3-dateutil python3-requests python3-lxml rsync

echo "==> Stopping existing service (if installed)"
systemctl stop "$SERVICE_NAME" 2>/dev/null || true

echo "==> Deploying application to $DEST"
install -d -o "$RUN_USER" -g "$RUN_USER" "$DEST"
if [[ "$SCRIPT_DIR" != "$DEST" ]]; then
    # Copy repo contents into DEST, excluding VCS metadata and local runtime files.
    rsync -a --delete \
        --exclude='.git' \
        --exclude='__pycache__' \
        --exclude='*.pyc' \
        --exclude='calendar_cache.json' \
        --exclude='image_cache.json' \
        --exclude='config.json' \
        "$SCRIPT_DIR"/ "$DEST"/
    chown -R "$RUN_USER":"$RUN_USER" "$DEST"
fi

echo "==> Ensuring local configuration exists"
if [[ ! -f "$DEST/config.json" ]]; then
    if [[ -f "$DEST/config.example.json" ]]; then
        cp "$DEST/config.example.json" "$DEST/config.json"
        chown "$RUN_USER":"$RUN_USER" "$DEST/config.json"
        echo "    Seeded config.json from config.example.json — edit it to set your calendar."
    else
        echo "    Warning: no config.example.json found; create $DEST/config.json manually." >&2
    fi
else
    echo "    Existing config.json kept."
fi

echo "==> Writing systemd service"
cat > "$SERVICE_FILE" <<EOF
[Unit]
Description=St. Demetrios Church Calendar Display
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${RUN_USER}
WorkingDirectory=${DEST}
ExecStart=/usr/bin/python3 ${DEST}/server.py
Restart=always
RestartSec=5
NoNewPrivileges=yes

[Install]
WantedBy=multi-user.target
EOF

echo "==> Enabling and starting service"
systemctl daemon-reload
systemctl enable "$SERVICE_NAME"
systemctl restart "$SERVICE_NAME"

echo ""
echo "Done. church-calendar is installed at $DEST and running as a systemd service."
echo "  Status:  systemctl status ${SERVICE_NAME}"
echo "  Logs:    journalctl -u ${SERVICE_NAME} -f"
echo "  Display: http://localhost:${PORT:-8000}/"
