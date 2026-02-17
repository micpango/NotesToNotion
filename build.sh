#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

# Create venv only if missing
if [ ! -d ".venv" ]; then
  python3 -m venv .venv
fi

source .venv/bin/activate

python -m pip install --upgrade pip
python -m pip install -r requirements.txt

# ✅ Install dev deps + run tests (build stops if tests fail)
python -m pip install -r requirements-dev.txt

echo
echo "🧪 Running tests..."
python -m pytest -ra
echo "✅ Tests passed."
echo

pyinstaller --noconfirm --clean --windowed \
  --name "NotesToNotion" \
  --icon "assets/icon.icns" \
  run.py

echo
echo "✅ Built: dist/NotesToNotion.app"
echo "Drag it into /Applications (or run ./reinstall.sh)"