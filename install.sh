#!/usr/bin/env bash
# codebase-3d 설치 — `codestrata` 명령을 이 기기에 건다.
#
# 왜 래퍼를 만드나: 심볼릭 링크를 쓰면 스크립트가 자기 위치를 찾아야 하는데
#   `readlink -f` 는 GNU 전용이라 맥에서 죽는다. 설치 시점 경로를 박는다.
set -uo pipefail
DRY="no"; [ "${1:-}" = "--dry-run" ] && DRY="yes"
SRC="$(cd "$(dirname "$0")" && pwd)/files"
BIN="$HOME/.local/bin"
log() { echo "[codebase-3d] $*"; }

command -v python3 >/dev/null 2>&1 || { log "⚠️ python3 가 없습니다. 건너뜁니다."; exit 0; }

if [ "$DRY" = "yes" ]; then
  echo "  (dry-run) $BIN/codestrata 래퍼 생성 -> $SRC/codestrata.sh"
  exit 0
fi

mkdir -p "$BIN"
cat > "$BIN/codestrata" <<EOF
#!/usr/bin/env bash
exec "$SRC/codestrata.sh" "\$@"
EOF
chmod +x "$BIN/codestrata"
log "설치: $BIN/codestrata"
cat > "$BIN/codestrata-tui" <<EOF
#!/usr/bin/env bash
exec python3 "$SRC/codestrata-tui.py" "\$@"
EOF
chmod +x "$BIN/codestrata-tui"
cat > "$BIN/codestrata-cli" <<EOF
#!/usr/bin/env bash
exec python3 "$SRC/codestrata-cli.py" "\$@"
EOF
chmod +x "$BIN/codestrata-cli"
log "설치: $BIN/codestrata-cli  (문자형 — chromium 불필요)"
log "설치: $BIN/codestrata-tui  (이미지형 — kitty 그래픽 터미널·chromium 필요)"

# 값으로 확인  — 셸을 안 거치는 환경에서도 잡히는지
if env -i PATH="/usr/local/bin:/usr/bin:/bin:$BIN" sh -c 'command -v codestrata' >/dev/null 2>&1; then
  log "✔ 깨끗한 환경에서도 잡힙니다"
else
  log "⚠️ $BIN 이 PATH 에 없습니다 — .zshrc/.profile 에 추가하세요"
fi
log "사용법:  codestrata-cli [레포경로]   ·   codestrata-tui [레포명]   ·   codestrata <레포경로>"
