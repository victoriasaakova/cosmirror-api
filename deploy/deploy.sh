#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/cosmirror/api}"
SERVICE="${SERVICE:-cosmirror-api}"
LOCK_FILE="${LOCK_FILE:-/var/lock/cosmirror-api-deploy.lock}"
STAMP_FILE="${STAMP_FILE:-$APP_DIR/.deployed-sha}"

cd "$APP_DIR"

exec 9>"$LOCK_FILE"
if ! flock -w 600 9; then
  echo "ERROR: timed out waiting for another cosmirror-api deploy"
  exit 1
fi

echo "==> Pulling latest API"
git fetch origin main
WANT="$(git rev-parse origin/main)"

if [[ -f "$STAMP_FILE" && "$(tr -d '[:space:]' < "$STAMP_FILE")" == "$WANT" ]] \
  && systemctl is-active --quiet "$SERVICE"; then
  echo "==> Already deployed $WANT — skip"
  echo "==> API deploy done"
  exit 0
fi

git reset --hard origin/main

echo "==> Installing dependencies"
python3 -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

echo "==> Swiss Ephemeris files"
EPHE_DIR="$APP_DIR/core/services/ephemeris/swiss"
mkdir -p "$EPHE_DIR"
for ephe_file in sepl_18.se1 semo_18.se1 seas_18.se1; do
  path="$EPHE_DIR/$ephe_file"
  size=0
  if [[ -f "$path" ]]; then
    size="$(wc -c < "$path" | tr -d ' ')"
  fi
  if [[ "${size:-0}" -lt 10000 ]]; then
    echo "Downloading $ephe_file"
    curl -fsSL -o "$path" \
      "https://cdn.jsdelivr.net/gh/aloistr/swisseph@master/ephe/$ephe_file"
  fi
done

echo "==> Migrating"
python manage.py migrate --noinput
python manage.py collectstatic --noinput
python manage.py seed_onboarding || true

echo "==> Restarting API"
systemctl restart "$SERVICE"
systemctl is-active "$SERVICE"
printf '%s\n' "$WANT" > "$STAMP_FILE"

echo "==> API deploy done"
