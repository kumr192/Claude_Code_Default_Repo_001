#!/usr/bin/env bash
# Orbit VM setup. Run ONCE as root on a fresh Ubuntu 24.04 (x86) server:
#     bash /root/orbit/vm/bootstrap.sh
# It installs: a desktop you can view in the browser (Xvfb + XFCE + x11vnc + noVNC),
# Google Chrome, Node 22, the official Claude Code CLI and Codex CLI, Playwright MCP,
# uv, Tailscale (private network), and the Orbit server as system services.
set -euo pipefail

if [[ $EUID -ne 0 ]]; then echo "Run as root."; exit 1; fi
SRC="$(cd "$(dirname "$0")/.." && pwd)"
APP=/opt/orbit
U=orbit
H=/home/$U
export DEBIAN_FRONTEND=noninteractive

echo "==> 1/8 System packages"
apt-get update -y
apt-get install -y curl wget git rsync ca-certificates gnupg ufw openssl \
  xvfb xfce4 xfce4-terminal dbus-x11 x11vnc novnc websockify \
  fonts-noto fonts-noto-color-emoji python3

echo "==> 2/8 Node.js 22"
if ! command -v node >/dev/null || [[ "$(node -v)" != v22* ]]; then
  curl -fsSL https://deb.nodesource.com/setup_22.x | bash -
  apt-get install -y nodejs
fi

echo "==> 3/8 Google Chrome (the agent's browser)"
if ! command -v google-chrome >/dev/null; then
  wget -qO /tmp/chrome.deb https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
  apt-get install -y /tmp/chrome.deb
  rm -f /tmp/chrome.deb
fi

echo "==> 4/8 Claude Code CLI, Codex CLI, Playwright MCP"
npm install -g @anthropic-ai/claude-code @openai/codex @playwright/mcp

echo "==> 5/8 User '$U' (agents never run as root)"
id $U >/dev/null 2>&1 || useradd -m -s /bin/bash $U
sudo -u $U bash -c 'command -v uv >/dev/null || curl -LsSf https://astral.sh/uv/install.sh | sh'
rsync -a --delete --exclude .git "$SRC/" "$APP/"
chown -R $U:$U "$APP"
sudo -u $U bash -c "cd $APP/server && $H/.local/bin/uv sync"

echo "==> 6/8 Tailscale (private network between your devices and this VM)"
command -v tailscale >/dev/null || curl -fsSL https://tailscale.com/install.sh | sh
if ! tailscale ip -4 >/dev/null 2>&1; then
  echo
  echo ">>> Open the link below in your browser and sign in to Tailscale:"
  tailscale up
fi
TSIP="$(tailscale ip -4 | head -1)"

echo "==> 7/8 Config, VNC password, firewall"
VNCPASS="$(openssl rand -hex 4)"   # x11vnc uses max 8 characters
sudo -u $U mkdir -p $H/.vnc $H/.orbit $H/workspace
sudo -u $U x11vnc -storepasswd "$VNCPASS" $H/.vnc/passwd >/dev/null
sudo -u $U python3 - <<EOF
import json, pathlib, secrets
p = pathlib.Path("$H/.orbit/config.json")
cfg = json.loads(p.read_text()) if p.exists() else {}
cfg.setdefault("token", secrets.token_hex(24))
cfg["computer_url"] = "http://$TSIP:6080/vnc.html?autoconnect=1&resize=scale&password=$VNCPASS"
p.write_text(json.dumps(cfg, indent=2)); p.chmod(0o600)
EOF
# Only SSH is open to the internet. The app and desktop are reachable via Tailscale only.
ufw allow OpenSSH
ufw allow in on tailscale0
ufw --force enable

echo "==> 8/8 Services"
cat > /etc/systemd/system/orbit-xvfb.service <<EOF
[Unit]
Description=Orbit virtual screen
[Service]
User=$U
ExecStart=/usr/bin/Xvfb :1 -screen 0 1440x900x24 -nolisten tcp
Restart=always
[Install]
WantedBy=multi-user.target
EOF

cat > /etc/systemd/system/orbit-desktop.service <<EOF
[Unit]
Description=Orbit desktop (XFCE)
After=orbit-xvfb.service
Requires=orbit-xvfb.service
[Service]
User=$U
Environment=DISPLAY=:1
Environment=HOME=$H
ExecStartPre=/bin/sleep 2
ExecStart=/usr/bin/dbus-launch --exit-with-session /usr/bin/startxfce4
Restart=always
[Install]
WantedBy=multi-user.target
EOF

cat > /etc/systemd/system/orbit-vnc.service <<EOF
[Unit]
Description=Orbit VNC server (localhost only)
After=orbit-xvfb.service
Requires=orbit-xvfb.service
[Service]
User=$U
ExecStartPre=/bin/sleep 3
ExecStart=/usr/bin/x11vnc -display :1 -rfbauth $H/.vnc/passwd -forever -shared -localhost -rfbport 5900 -quiet
Restart=always
[Install]
WantedBy=multi-user.target
EOF

cat > /etc/systemd/system/orbit-novnc.service <<EOF
[Unit]
Description=Orbit browser view of the desktop (noVNC)
After=orbit-vnc.service
[Service]
User=$U
ExecStart=/usr/bin/websockify --web /usr/share/novnc 6080 localhost:5900
Restart=always
[Install]
WantedBy=multi-user.target
EOF

cat > /etc/systemd/system/orbit-server.service <<EOF
[Unit]
Description=Orbit agent server
After=network-online.target orbit-desktop.service
[Service]
User=$U
WorkingDirectory=$APP/server
Environment=HOME=$H
Environment=DISPLAY=:1
Environment=PATH=$H/.local/bin:/usr/local/bin:/usr/bin:/bin
ExecStart=$H/.local/bin/uv run orbit-server
Restart=always
RestartSec=3
[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now orbit-xvfb orbit-desktop orbit-vnc orbit-novnc orbit-server

TOKEN="$(sudo -u $U python3 -c "import json;print(json.load(open('$H/.orbit/config.json'))['token'])")"
cat <<EOF

============================================================
 Orbit is installed.

 App URL (Tailscale only):  http://$TSIP:8787
 Token (paste into the app): $TOKEN
 Desktop view:               http://$TSIP:6080/vnc.html  (password: $VNCPASS)

 LAST STEP: sign in to your two subscriptions (no API keys):
   sudo -iu $U claude auth login        # Claude Pro/Max account
   sudo -iu $U codex login --device-auth   # ChatGPT account
 Then check:
   sudo -iu $U claude auth status
   sudo -iu $U codex login status
============================================================
EOF
