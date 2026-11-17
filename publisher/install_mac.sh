#!/bin/bash
# 맥 노트북 설치: 터미널에서  bash install_mac.sh
set -e
cd "$(dirname "$0")"
DIR="$(pwd)"
echo "[1/3] 필요한 프로그램 설치"
python3 -m pip install --user -r requirements.txt
python3 -m playwright install chromium
echo "[2/3] 로그인 (열리는 브라우저에서 티스토리와 네이버에 로그인한 뒤 여기서 Enter)"
python3 publish.py login
read -p "매일 몇 시에 올릴까요? 시(0-23, 그냥 Enter 면 21): " H
H=${H:-21}
echo "[3/3] 매일 ${H}시 자동 실행 예약"
PLIST="$HOME/Library/LaunchAgents/com.sohyunrichlab.publish.plist"
cat > "$PLIST" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
 <key>Label</key><string>com.sohyunrichlab.publish</string>
 <key>ProgramArguments</key><array><string>$(command -v python3)</string><string>$DIR/publish.py</string><string>all</string></array>
 <key>WorkingDirectory</key><string>$DIR</string>
 <key>StartCalendarInterval</key><dict><key>Hour</key><integer>$H</integer><key>Minute</key><integer>0</integer></dict>
 <key>StandardOutPath</key><string>$DIR/launchd.log</string>
 <key>StandardErrorPath</key><string>$DIR/launchd.log</string>
</dict></plist>
PL
launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"
echo "끝났습니다. 매일 ${H}시에 발행합니다."
