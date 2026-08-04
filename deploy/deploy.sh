#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/cosmirror/api}"
cd "$APP_DIR"

echo "==> Pulling latest API"
git fetch origin main
git reset --hard origin/main

echo "==> Installing dependencies"
python3 -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

echo "==> Migrating"
python manage.py migrate --noinput
python manage.py collectstatic --noinput
python manage.py seed_onboarding || true

echo "==> Restarting API"
systemctl restart cosmirror-api
systemctl is-active cosmirror-api

echo "==> API deploy done"
