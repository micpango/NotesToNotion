#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

python3 -m venv .venv
source .venv/bin/activate

pip install --upgrade pip
pip install -r requirements.txt

pyinstaller --noconfirm --clean --windowed \
  --name "NotesToNotion" \
  --icon "assets/icon.icns" \
  run.py

echo
echo "✅ Built: dist/NotesToNotion.app"
echo "Drag it into /Applications (or run ./reinstall.sh)"