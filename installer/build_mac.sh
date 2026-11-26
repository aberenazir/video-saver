#!/bin/bash
# Builds the self-contained "Video Saver.app" (Python, yt-dlp, ffmpeg and Deno inside) and "Video Saver.dmg".
# Anyone can install the .dmg: no Python, Terminal or Claude Code needed on their Mac.
#   bash installer/build_mac.sh            -> ~/All My Apps/20 Video Saver (Mac)/Install/Mac/Video Saver.dmg
#   bash installer/build_mac.sh <out dir>  -> the .dmg goes there instead
# It never touches /Applications or your settings. Needs internet (and uv: https://docs.astral.sh/uv).
# Builds for the Mac it runs on (Apple Silicon here; an Intel Mac build comes from the GitHub workflow).
set -euo pipefail
SRC="$(cd "$(dirname "$0")/.." && pwd)"
OUT="${1:-$HOME/All My Apps/20 Video Saver (Mac)/Install/Mac}"
WORK="$HOME/Library/Caches/VideoSaverBuild"
VENV="$WORK/venv"
export PATH="$HOME/.local/bin:/usr/local/bin:/opt/homebrew/bin:$PATH" UV_HTTP_TIMEOUT=300
ARCH="$(uname -m)"; [ "$ARCH" = "arm64" ] && DENO_ARCH=aarch64 || DENO_ARCH=x86_64
mkdir -p "$WORK" "$OUT"

echo "1/5 Python and packages"
[ -x "$VENV/bin/python" ] || uv venv -q "$VENV" --python 3.12
uv pip install -q --python "$VENV/bin/python" -U -r "$SRC/installer/requirements.txt" pyinstaller

echo "2/5 JavaScript runtime (YouTube needs one for full quality)"
# Deno is the one yt-dlp recommends (~40 MB download). If it can't be downloaded in time, a Node.js 22+ already on this
# Mac is copied in instead (yt-dlp supports both). JS_RUNTIME=node skips the download.
mkdir -p "$WORK/bin"
unset DENO NODE
if [ "${JS_RUNTIME:-deno}" = "deno" ]; then
  if [ ! -x "$WORK/bin/deno" ] || [ "$(lipo -archs "$WORK/bin/deno" 2>/dev/null)" != "$ARCH" ]; then
    rm -f "$WORK/bin/deno"
    curl -fsSL --speed-limit 50000 --speed-time 30 -o "$WORK/deno.zip" \
      "https://github.com/denoland/deno/releases/latest/download/deno-$DENO_ARCH-apple-darwin.zip" \
      && unzip -q -o "$WORK/deno.zip" -d "$WORK/bin" && chmod +x "$WORK/bin/deno" || echo "   (Deno download too slow or failed)"
  fi
  [ -x "$WORK/bin/deno" ] && export DENO="$WORK/bin/deno" && "$DENO" --version | head -1
fi
if [ -z "${DENO:-}" ]; then
  N="$(command -v node || true)"
  [ -n "$N" ] && [ "$("$N" -p 'process.versions.node.split(".")[0]')" -ge 22 ] || { echo "!! no Deno and no Node.js 22+"; exit 1; }
  rm -f "$WORK/bin/node"
  lipo -thin "$ARCH" "$N" -output "$WORK/bin/node" 2>/dev/null || cp "$N" "$WORK/bin/node"
  export NODE="$WORK/bin/node"; echo "   Node.js $("$NODE" -v) (copied from $N)"
fi

echo "3/5 Building the app"
cd "$SRC"
rm -rf "$WORK/dist" "$WORK/build"
"$VENV/bin/pyinstaller" --noconfirm --log-level WARN --distpath "$WORK/dist" --workpath "$WORK/build" \
  installer/VideoSaver.spec
APP="$WORK/dist/Video Saver.app"
xattr -cr "$APP"
codesign --force --deep --sign - "$APP"   # ad-hoc signature (no Apple Developer account)

echo "4/5 Checking the app has everything"
[ -x "$APP/Contents/Frameworks/bin/deno" ] || [ -x "$APP/Contents/Frameworks/bin/node" ] || { echo "!! JavaScript runtime missing"; exit 1; }
ls "$APP/Contents/Frameworks/imageio_ffmpeg/binaries/"ffmpeg-* >/dev/null || { echo "!! ffmpeg missing"; exit 1; }

echo "5/5 Making the .dmg"
STAGE="$WORK/dmg"; rm -rf "$STAGE"; mkdir -p "$STAGE"
ditto "$APP" "$STAGE/Video Saver.app"
ln -s /Applications "$STAGE/Applications"
cp "$SRC/installer/dmg-README.txt" "$STAGE/READ ME FIRST.txt"
DMG="$OUT/Video Saver.dmg"
rm -f "$DMG"
hdiutil create -quiet -volname "Video Saver" -srcfolder "$STAGE" -fs HFS+ -format UDZO -imagekey zlib-level=9 "$DMG"
echo "Built: $DMG ($(du -h "$DMG" | cut -f1)) for $ARCH Macs"
