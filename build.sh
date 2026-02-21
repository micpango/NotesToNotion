#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

APP_NAME="NotesToNotion"
APP_BUNDLE="dist/${APP_NAME}.app"
SIGN_IDENTITY="NotesToNotion Dev"
ICON_MASTER="assets/icon_master.png"
DOCK_ICON="assets/app_icon.icns"

# Create venv only if missing
if [ ! -d ".venv" ]; then
  python3 -m venv .venv
fi

source .venv/bin/activate

python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install -r requirements-dev.txt

if [ ! -f "${ICON_MASTER}" ]; then
  echo "❌ Missing dock icon master: ${ICON_MASTER}"
  exit 1
fi

echo "🎨 Building dock icon (${DOCK_ICON}) from ${ICON_MASTER}..."
ICONSET_BASE="$(mktemp -d /tmp/notestonotion.XXXXXX)"
ICONSET_DIR="${ICONSET_BASE}.iconset"
mv "${ICONSET_BASE}" "${ICONSET_DIR}"
trap 'rm -rf "${ICONSET_DIR}"' EXIT
sips -z 16 16 "${ICON_MASTER}" --out "${ICONSET_DIR}/icon_16x16.png" >/dev/null
sips -z 32 32 "${ICON_MASTER}" --out "${ICONSET_DIR}/icon_16x16@2x.png" >/dev/null
sips -z 32 32 "${ICON_MASTER}" --out "${ICONSET_DIR}/icon_32x32.png" >/dev/null
sips -z 64 64 "${ICON_MASTER}" --out "${ICONSET_DIR}/icon_32x32@2x.png" >/dev/null
sips -z 128 128 "${ICON_MASTER}" --out "${ICONSET_DIR}/icon_128x128.png" >/dev/null
sips -z 256 256 "${ICON_MASTER}" --out "${ICONSET_DIR}/icon_128x128@2x.png" >/dev/null
sips -z 256 256 "${ICON_MASTER}" --out "${ICONSET_DIR}/icon_256x256.png" >/dev/null
sips -z 512 512 "${ICON_MASTER}" --out "${ICONSET_DIR}/icon_256x256@2x.png" >/dev/null
sips -z 512 512 "${ICON_MASTER}" --out "${ICONSET_DIR}/icon_512x512.png" >/dev/null
sips -z 1024 1024 "${ICON_MASTER}" --out "${ICONSET_DIR}/icon_512x512@2x.png" >/dev/null
iconutil -c icns "${ICONSET_DIR}" -o "${DOCK_ICON}"

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
