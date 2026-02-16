#!/usr/bin/env bash
set -euo pipefail

APP_NAME="NotesToNotion"
APP_PATH="/Applications/${APP_NAME}.app"
DIST_APP="dist/${APP_NAME}.app"
CONFIG_PATH="$HOME/Library/Application Support/NotesToNotion"

echo "🔪 Stopping running instances..."
pkill -f "${APP_NAME}" || true

echo "🧹 Removing old build folders..."
rm -rf build dist

echo "🧹 Removing old app from /Applications..."
rm -rf "${APP_PATH}"

if [[ "${1:-}" == "--reset-config" ]]; then
  echo "⚠️  Removing config and processed state..."
  rm -rf "${CONFIG_PATH}"
fi

echo "🔨 Rebuilding app..."
./build.sh

echo "📦 Installing to /Applications..."
if [[ ! -d "${DIST_APP}" ]]; then
  echo "❌ Build output not found: ${DIST_APP}"
  exit 1
fi

cp -R "${DIST_APP}" "${APP_PATH}"

if [[ ! -d "${APP_PATH}" ]]; then
  echo "❌ Install failed, app not present at: ${APP_PATH}"
  exit 1
fi

echo "🚀 Launching app..."
open "${APP_PATH}"

echo ""
echo "✅ Reinstall complete."
if [[ "${1:-}" == "--reset-config" ]]; then
  echo "⚠️  Config was reset. Run Setup in the app."
fi