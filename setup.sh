#!/usr/bin/env bash
# Steerable: create a new company project run by Claude Code.
#
#   ./setup.sh <target-dir> "<Company Name>" [--services]
#
# Copies template/ into the target, fills in the name and date, then sets up
# .venv, Playwright and git. With --services it asks before installing the cron
# jobs (heartbeat, daily brief) and the Telegram bridge service.
set -euo pipefail

KIT="$(cd "$(dirname "$0")" && pwd)"
USAGE='usage: ./setup.sh <target-dir> "<Company Name>" [--services]'
TARGET="${1:?$USAGE}"
NAME="${2:?$USAGE}"
SERVICES="${3:-}"
SLUG="$(echo "$NAME" | tr '[:upper:]' '[:lower:]' | tr -cs 'a-z0-9' '-' | sed 's/^-//;s/-$//')"
TODAY="$(date +%F)"

for cmd in python3 git; do
  command -v "$cmd" >/dev/null || { echo "Missing: $cmd" >&2; exit 1; }
done
command -v claude >/dev/null || echo "Note: Claude Code isn't installed yet (https://claude.com/claude-code)."
if [ -e "$TARGET" ] && [ -n "$(ls -A "$TARGET" 2>/dev/null)" ]; then
  echo "Refusing: $TARGET exists and isn't empty." >&2; exit 1
fi

# 1. Copy the template and fill in the placeholders
mkdir -p "$TARGET"
TARGET="$(cd "$TARGET" && pwd)"
echo "Creating '$NAME' in $TARGET"
cp -r "$KIT/template/." "$TARGET/"
python3 - "$TARGET" "$NAME" "$SLUG" "$TODAY" <<'PY'
import pathlib, sys
root, name, slug, today = sys.argv[1:]
for p in pathlib.Path(root).rglob("*"):
    if p.is_file() and (p.suffix == ".md" or p.name == ".env.example"):
        t = p.read_text()
        p.write_text(t.replace("{{COMPANY}}", name).replace("{{SLUG}}", slug).replace("{{DATE}}", today))
PY

# 2. Python environment, browser and git
python3 -m venv "$TARGET/.venv"
"$TARGET/.venv/bin/pip" install -q -r "$TARGET/requirements.txt"
"$TARGET/.venv/bin/python" -m playwright install chromium >/dev/null
git -C "$TARGET" init -q
# A VS Code workspace showing every folder Claude works in, so the owner can watch all changes
printf '{\n  "folders": [\n    { "name": "%s (ops)", "path": "." },\n    { "name": "services", "path": "%s" }\n  ],\n  "settings": { "files.exclude": { "**/.venv": true, "**/__pycache__": true, "**/node_modules": true } }\n}\n' "$NAME" "$HOME/services" > "$TARGET/$SLUG.code-workspace"
# A starter .env (gitignored): company name, a generated backup password and a per-company backup path
python3 - "$TARGET/.env" "$NAME" "$SLUG" <<'PY'
import secrets, sys
path, name, slug = sys.argv[1:]
open(path, "w").write(f"COMPANY_NAME={name}\nRESTIC_PASSWORD={secrets.token_urlsafe(32)}\n"
                      f"RESTIC_LOCAL_REPOSITORY=~/backups/{slug}/restic\n")
PY
chmod 600 "$TARGET/.env"
"$TARGET/.venv/bin/python" "$TARGET/scripts/heartbeat.py" --dry-run
echo "✓ Project ready, and the heartbeat runs."

# 3. Optional background services, each one confirmed
if [ "$SERVICES" = "--services" ]; then
  read -rp "Install cron jobs (heartbeat every 15 min, brief at 09:00)? [y/N] " a
  if [ "$a" = "y" ]; then
    (crontab -l 2>/dev/null
     echo "*/15 * * * * cd \"$TARGET\" && .venv/bin/python scripts/heartbeat.py >> logs/cron.log 2>&1"
     echo "0 9 * * * cd \"$TARGET\" && .venv/bin/python scripts/brief.py >> logs/cron.log 2>&1") | crontab -
    echo "✓ Cron installed"
  fi
  read -rp "Install the Telegram bridge service ($SLUG-bridge)? [y/N] " a
  if [ "$a" = "y" ]; then
    mkdir -p ~/.config/systemd/user
    cat > ~/.config/systemd/user/"$SLUG"-bridge.service <<EOF
[Unit]
Description=$NAME Telegram bridge
After=network-online.target

[Service]
WorkingDirectory=$TARGET
ExecStart="$TARGET/.venv/bin/python" scripts/bridge.py
Environment=PATH=$(dirname "$(command -v claude || echo /usr/bin/claude)"):/usr/bin:/bin
Restart=always
RestartSec=10

[Install]
WantedBy=default.target
EOF
    systemctl --user daemon-reload
    systemctl --user enable --now "$SLUG"-bridge
    echo "✓ Bridge service installed (it idles until the .env token is set)"
    if [ "$(loginctl show-user "$USER" -p Linger --value 2>/dev/null)" != "yes" ]; then
      read -rp "Keep the bridge running when you're logged out (enables systemd linger)? [y/N] " a
      [ "$a" = "y" ] && loginctl enable-linger "$USER" && echo "✓ Linger enabled"
    fi
  fi
fi

cat <<EOF

Next steps:
  1. Fill in "$TARGET/.env" (see .env.example): Telegram bot token from @BotFather, budget.
  2. If you installed the bridge: systemctl --user restart $SLUG-bridge, then send /start to your bot
  3. Run claude in that folder and say "start onboarding"
EOF
