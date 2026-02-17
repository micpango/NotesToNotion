#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

APP_NAME="NotesToNotion"
APP_BUNDLE="dist/${APP_NAME}.app"
SIGN_IDENTITY="NotesToNotion Dev"

# Create venv only if missing
if [ ! -d ".venv" ]; then
  python3 -m venv .venv
fi

source .venv/bin/activate

python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install -r requirements-dev.txt

echo
echo "🧪 Running tests..."
python -m pytest -ra
echo "✅ Tests passed."
echo

echo "📦 Building app (spec is source of truth)..."
# NOTE: When building from a spec, do NOT pass --windowed/--icon/--name flags here.
pyinstaller NotesToNotion.spec --noconfirm --clean

if [ ! -d "${APP_BUNDLE}" ]; then
  echo "❌ Build failed: ${APP_BUNDLE} not found"
  exit 1
fi

echo
echo "🔏 Code signing..."
codesign --deep --force --sign "${SIGN_IDENTITY}" "${APP_BUNDLE}"

echo "🔎 Verifying signature..."
codesign --verify --deep --strict --verbose=2 "${APP_BUNDLE}" || true

echo
echo "✅ Built: ${APP_BUNDLE}"
echo "Drag it into /Applications (or run ./reinstall.sh)"