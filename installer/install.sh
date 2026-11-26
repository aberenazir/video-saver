#!/bin/bash
# Installs or updates "Video Saver.app" in /Applications from this folder.
# Your saved list and settings (~/Library/Application Support/Video Saver) are never touched.
set -e
SRC="$(cd "$(dirname "$0")/.." && pwd)"
A="/Applications/Video Saver.app"
DATA="$HOME/Library/Application Support/Video Saver"
R="$A/Contents/Resources/app"
if [ "$SRC" = "$R" ]; then  # running the copy inside the app: work from a temporary copy
  TMP="$(mktemp -d)"; cp -R "$SRC/." "$TMP/"; SRC="$TMP"
fi
export PATH="$HOME/.local/bin:/usr/local/bin:/opt/homebrew/bin:$PATH"
export UV_HTTP_TIMEOUT=300

if ! command -v uv >/dev/null; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
fi
if ! command -v node >/dev/null; then
  echo "Note: Node.js isn't installed. Most sites work without it; for YouTube install it from https://nodejs.org"
fi

osascript -e 'quit app "Video Saver"' 2>/dev/null || true
pkill -f "Video Saver.app/Contents/Resources/app/window.py" 2>/dev/null || true
sleep 1

mkdir -p "$DATA"
if [ ! -x "$DATA/venv/bin/python" ]; then
  uv venv -q "$DATA/venv" --python 3.11
fi
for i in 1 2 3; do
  uv pip install -q --python "$DATA/venv/bin/python" -U "yt-dlp[default]" && \
  uv pip install -q --python "$DATA/venv/bin/python" fastapi "uvicorn[standard]" imageio-ffmpeg pywebview && break
  echo "retrying download ($i)…"
done

rm -rf "$A"
mkdir -p "$A/Contents/MacOS" "$R/installer"
cat > "$A/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>Video Saver</string>
  <key>CFBundleDisplayName</key><string>Video Saver</string>
  <key>CFBundleIdentifier</key><string>local.videosaver.app</string>
  <key>CFBundleExecutable</key><string>Video Saver</string>
  <key>CFBundleIconFile</key><string>AppIcon</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>CFBundleVersion</key><string>1</string>
  <key>LSMinimumSystemVersion</key><string>12.0</string>
  <key>LSApplicationCategoryType</key><string>public.app-category.utilities</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>NSAppleEventsUsageDescription</key><string>Video Saver uses this to show notifications.</string>
</dict></plist>
PLIST
cat > "$A/Contents/MacOS/Video Saver" <<'LAUNCH'
#!/bin/bash
DATA="$HOME/Library/Application Support/Video Saver"
APPDIR="$(cd "$(dirname "$0")/../Resources/app" && pwd)"
export PATH="/usr/local/bin:/opt/homebrew/bin:$HOME/.local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
mkdir -p "$DATA"
cd "$APPDIR"
exec "$DATA/venv/bin/python" "$APPDIR/window.py" >> "$DATA/app.log" 2>&1
LAUNCH
chmod +x "$A/Contents/MacOS/Video Saver"
cp "$SRC/installer/AppIcon.icns" "$A/Contents/Resources/AppIcon.icns"
cp "$SRC"/*.py "$SRC"/index.html "$SRC"/icon.png "$SRC"/icon_large.png "$R/"
[ -f "$SRC/README.md" ] && cp "$SRC/README.md" "$R/"
cp "$SRC"/installer/{install.sh,AppIcon.icns,make_icon.py,VERSION} "$R/installer/"
chmod +x "$R/installer/install.sh"
codesign --force --deep -s - "$A" >/dev/null 2>&1 || true
/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister -f "$A" >/dev/null 2>&1 || true
touch "$A"
echo "Installed: $A"
