#!/usr/bin/env bash
# install.sh — Installs the St. Demetrios Church Calendar display on a Raspberry Pi.
#
# Idempotent: safe to re-run for upgrades. Installs Python dependencies, deploys the
# app to a target directory, seeds a local config.json if missing, and registers a
# systemd service so the calendar starts on boot.
#
# Usage:
#   sudo ./install.sh                 # install/upgrade with defaults
#   RUN_USER=calendar DEST=/opt/church-calendar sudo -E ./install.sh
#
# Environment overrides:
#   RUN_USER  Service user (default: non-root user that invoked sudo)
#   DEST      Install directory (default: /opt/church-calendar for new installs)
#   PORT      HTTP port the server listens on (informational; default: 8000)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
RUN_USER="${RUN_USER:-}"
SERVICE_NAME="church-calendar"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"

if [[ $EUID -ne 0 ]]; then
    echo "Error: this installer must be run as root (use sudo)." >&2
    exit 1
fi

if [[ -z "$RUN_USER" ]]; then
    if [[ -n "${SUDO_USER:-}" && "$SUDO_USER" != "root" ]]; then
        RUN_USER="$SUDO_USER"
    else
        echo "Error: unable to determine a non-root service user. Set RUN_USER explicitly." >&2
        exit 1
    fi
fi

if [[ "$RUN_USER" == "root" ]]; then
    echo "Error: church-calendar must run as a non-root service user." >&2
    exit 1
fi

if ! id "$RUN_USER" &>/dev/null; then
    echo "Error: user '$RUN_USER' does not exist. Set RUN_USER to a valid account." >&2
    exit 1
fi
RUN_GROUP="$(id -gn "$RUN_USER")"

if [[ -z "${DEST:-}" ]]; then
    EXISTING_DEST=$(systemctl show "$SERVICE_NAME" -p WorkingDirectory --value 2>/dev/null || true)
    LEGACY_DEST="/home/${RUN_USER}/church-calendar"
    if [[ -n "$EXISTING_DEST" && "$EXISTING_DEST" != "/" && -d "$EXISTING_DEST" ]]; then
        DEST="$EXISTING_DEST"
    elif [[ -d "$LEGACY_DEST" ]]; then
        DEST="$LEGACY_DEST"
    else
        DEST="/opt/church-calendar"
    fi
fi

echo "==> Installing system dependencies"
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
# Use distro Python packages (PEP 668 friendly on Raspberry Pi OS Bookworm).
# server.py degrades gracefully if Pillow (python3-pil) is unavailable.
apt-get install -y python3 python3-pil python3-dateutil python3-requests python3-lxml

echo "==> Stopping existing service (if installed)"
systemctl stop "$SERVICE_NAME" 2>/dev/null || true

echo "==> Deploying application to $DEST"
install -d -o "$RUN_USER" -g "$RUN_GROUP" "$DEST"
if [[ "$SCRIPT_DIR" != "$DEST" ]]; then
    # Copy repo contents into DEST, excluding VCS metadata and local runtime files.
    if command -v rsync &>/dev/null; then
        rsync -a --delete \
            --exclude='.git' \
            --exclude='__pycache__' \
            --exclude='*.pyc' \
            --exclude='calendar_cache.json' \
            --exclude='image_cache.json' \
            --exclude='config.json' \
            "$SCRIPT_DIR"/ "$DEST"/
    else
        cp -a "$SCRIPT_DIR"/. "$DEST"/
        rm -rf "$DEST/.git"
    fi
    chown -R "$RUN_USER":"$RUN_GROUP" "$DEST"
fi

echo "==> Ensuring local configuration exists"
if [[ ! -f "$DEST/config.json" ]]; then
    if [[ -f "$DEST/config.example.json" ]]; then
        cp "$DEST/config.example.json" "$DEST/config.json"
        chown "$RUN_USER":"$RUN_GROUP" "$DEST/config.json"
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
