#!/data/data/com.termux/files/usr/bin/bash
# Auto-download and trigger APK install
set -e

OWNER="SleepSheepQwQ"
REPO="kiomet-webview"
DL_DIR="/tmp/kiomet-apk"

mkdir -p "$DL_DIR"

# Get latest successful run
echo "Fetching latest build..."
RUN_INFO=$(curl -s --connect-timeout 10 --max-time 20 \
  -H "Accept: application/vnd.github+json" \
  "https://api.github.com/repos/$OWNER/$REPO/actions/runs?per_page=1&status=success&branch=main")

RUN_ID=$(echo "$RUN_INFO" | python3 -c "import json,sys;d=json.load(sys.stdin);print(d['workflow_runs'][0]['id'])" 2>/dev/null)
echo "Build #$RUN_ID"

# Get artifact
ARTIFACT_INFO=$(curl -s --connect-timeout 10 --max-time 20 \
  -H "Accept: application/vnd.github+json" \
  "https://api.github.com/repos/$OWNER/$REPO/actions/runs/$RUN_ID/artifacts")

ARTIFACT_URL=$(echo "$ARTIFACT_INFO" | python3 -c "import json,sys;d=json.load(sys.stdin);print(d['artifacts'][0]['archive_download_url'])" 2>/dev/null)

# Download artifact
ZIP_FILE="$DL_DIR/artifact.zip"
echo "Downloading APK..."
curl -sL --connect-timeout 10 --max-time 120 -o "$ZIP_FILE" "$ARTIFACT_URL"

# Extract
cd "$DL_DIR"
unzip -o -q "$ZIP_FILE" 2>/dev/null
APK=$(ls *.apk 2>/dev/null | head -1)

if [ -z "$APK" ]; then
  echo "No APK found in artifact"
  exit 1
fi

echo "APK: $APK ($(du -h "$APK" | cut -f1))"

# Try pm install (may require specific permissions)
echo "Attempting install..."
pm install -r "$DL_DIR/$APK" 2>&1 && echo "SUCCESS" || echo "MANUAL INSTALL REQUIRED: termux-open $DL_DIR/$APK"
