#!/bin/bash
set -euo pipefail

PI_USER="${PI_USER:-pi}"
SHARE_PATH="${SHARE_PATH:-/pic_shared}"
CAPTURE_ROOT="${CAPTURE_ROOT:-$SHARE_PATH/captures}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CAPTURE_SCRIPT_TARGET="/usr/local/bin/projectif-capture-images.sh"
SERVICE_PATH="/etc/systemd/system/projectif-capture.service"
TIMER_PATH="/etc/systemd/system/projectif-capture.timer"
ENV_PATH="/etc/default/projectif-capture"
SAMBA_CONFIG="/etc/samba/smb.conf"

if [ "$(id -u)" -ne 0 ]; then
  echo "Run this script with sudo." >&2
  exit 1
fi

if ! command -v lsb_release >/dev/null 2>&1; then
  apt-get update
  apt-get install -y lsb-release curl gnupg2 ca-certificates
fi

DISTRO_ID="$(lsb_release -is)"
DISTRO_CODENAME="$(lsb_release -sc)"

apt-get update
apt-get install -y \
  curl gnupg2 ca-certificates lsb-release \
  samba samba-common-bin ffmpeg v4l-utils fswebcam

usermod -aG video "$PI_USER"

mkdir -p "$CAPTURE_ROOT"
chmod 1777 "$SHARE_PATH"
chown "$PI_USER:$PI_USER" "$CAPTURE_ROOT"

if ! grep -q "^\[pic_shared\]" "$SAMBA_CONFIG"; then
  cat >> "$SAMBA_CONFIG" <<'EOF'

[pic_shared]
path = /pic_shared
writeable = yes
browseable = yes
create mask = 0777
directory mask = 0777
public = no
force user = pi
EOF
fi

echo "Set the Samba password for user $PI_USER when prompted."
smbpasswd -a "$PI_USER"
systemctl restart smbd
systemctl enable smbd

install -m 0755 "$SCRIPT_DIR/capture_images.sh" "$CAPTURE_SCRIPT_TARGET"

cat > "$ENV_PATH" <<EOF
PI_USER=$PI_USER
CAPTURE_ROOT=$CAPTURE_ROOT
CAPTURE_COMMAND=auto
IMAGE_BASENAME=capture
VIDEO_DEVICE=auto
VIDEO_SIZE=1280x720
VIDEO_INPUT_FORMAT=mjpeg
FFMPEG_EXTRA_ARGS=
EOF

cat > "$SERVICE_PATH" <<EOF
[Unit]
Description=ProjectIF image capture job on $DISTRO_ID $DISTRO_CODENAME
After=network-online.target smbd.service
Wants=network-online.target

[Service]
Type=oneshot
User=$PI_USER
EnvironmentFile=$ENV_PATH
ExecStart=$CAPTURE_SCRIPT_TARGET
EOF

cat > "$TIMER_PATH" <<EOF
[Unit]
Description=Run ProjectIF image capture every 3 hours

[Timer]
OnBootSec=2min
OnUnitActiveSec=3h
Unit=projectif-capture.service
Persistent=true

[Install]
WantedBy=timers.target
EOF

systemctl daemon-reload
systemctl enable --now projectif-capture.timer

cat <<EOF
Pi setup complete.

Next steps:
1. Inspect the timer with: systemctl status projectif-capture.timer
2. Trigger an immediate capture with: systemctl start projectif-capture.service
3. Confirm the share is exported with: smbclient -L localhost -U $PI_USER
4. Log out and back in so the $PI_USER video-group membership is refreshed.
5. If needed, set VIDEO_DEVICE in $ENV_PATH to a different /dev/videoN node and rerun the service.
EOF
