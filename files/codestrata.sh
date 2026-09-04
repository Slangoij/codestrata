#!/usr/bin/env bash
# 코드베이스 3D 렌더링 — 레포 하나를 "구조 평면 × 시간 축" 지층으로 세운다.
#
#   codestrata                       현재 위치가 속한 레포 (하위 폴더에서도 됩니다)
#   codestrata <레포경로> [<레포경로>...]
#   codestrata ~                     레포가 아닌 폴더를 주면 그 아래 레포를 전부 찾아 그린다
#   codestrata <레포> --port N --no-serve --out DIR
#
# 무엇을 그리나:
#   바닥 = 구조 (co-change + graphify 코드 의존)   높이 = 시간 (커밋)
#   구슬 = 커밋별 파일 변경                        중심 줄기 = 커밋 그래프(DAG)
#
# ⭐ 첫 줄에 **실제로 열 주소**를 찍는다 — localhost 로 확인하고 "됐다"고 적으면
#    다른 기기에서 열리지 않는다.
set -uo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
PORT=8899; SERVE=1; OUT="$HOME/debug-captures/codebase-3d"

ARGS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --port) PORT="$2"; shift 2 ;;
    --no-serve) SERVE=0; shift ;;
    --out) OUT="$2"; shift 2 ;;
    -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
    -*) echo "모르는 옵션: $1" >&2; exit 2 ;;
    *) ARGS+=("$1"); shift ;;
  esac
done
# 인자가 없으면 지금 위치. 하위 폴더에서 실행해도 레포 루트를 찾아 준다 —
# "최상위에서 돌려야 하나"를 사람이 신경 쓸 일이 아니다.
[ ${#ARGS[@]} -gt 0 ] || ARGS=(".")

mkdir -p "$OUT"

# 인자가 레포가 아니면(예: ~ 같은 상위 폴더) 그 아래 레포를 **알아서 찾는다** —
# "최상위에서 돌리면 밑의 레포가 다 잡히겠지"가 사람의 기대다(2026-09-02 사용자).
#   · 숨김 폴더(.oh-my-zsh 등)·node_modules 는 건너뛴다
#   · 찾아낸 레포 중 커밋이 아주 많은 것(남의 SDK·벤더 트리)은 건너뛰고 알린다 —
#     직접 경로로 주면 그때는 그린다
DISCOVER_MAX_COMMITS=5000
REPOS=()
for a in "${ARGS[@]}"; do
  d=$(cd "$a" 2>/dev/null && pwd) || { echo "그런 경로가 없습니다: $a" >&2; continue; }
  if REPO=$(git -C "$d" rev-parse --show-toplevel 2>/dev/null); then
    REPOS+=("$REPO"); continue
  fi
  echo "[codestrata] $d 는 레포가 아니라 아래 레포를 찾습니다(깊이 3, 숨김 폴더 제외)…"
  found=0
  while IFS= read -r g; do
    r=${g%/.git}
    n=$(git -C "$r" rev-list --count HEAD 2>/dev/null || echo 0)
    if [ "$n" -gt "$DISCOVER_MAX_COMMITS" ]; then
      echo "[codestrata]   건너뜀: $r (커밋 $n 개 — 남의 트리로 보입니다. 원하면 경로를 직접 주세요)"
      continue
    fi
    echo "[codestrata]   발견: $r (커밋 $n)"
    REPOS+=("$r"); found=$((found+1))
  done < <(find "$d" -maxdepth 3 -name .git \( -type d -o -type f \) \
             -not -path '*/.*/*' -not -path '*/node_modules/*' 2>/dev/null | sort)
  [ "$found" -gt 0 ] || echo "git 저장소가 없습니다: $d" >&2
done

BUILT=0
for REPO in "${REPOS[@]}"; do
  NAME=$(basename "$REPO")
  DATA="$OUT/$NAME.json"; HTML="$OUT/$NAME.html"

  # graphify 그래프가 있으면 코드 의존까지 얹는다. 없어도 co-change 로 그려진다.
  if [ ! -f "$REPO/graphify-out/graph.json" ]; then
    echo "[codestrata] $NAME: graphify 그래프 없음 — co-change 만으로 그립니다."
    echo "             코드 의존까지 보려면:  graphify extract \"$REPO\" --code-only"
  fi

  python3 "$HERE/extract.py" "$REPO" "$DATA" || continue
  python3 "$HERE/assemble.py" "$HERE/viewer.html" "$DATA" "$HTML" || continue
  BUILT=$((BUILT+1))
done
[ "$BUILT" -gt 0 ] || { echo "만든 것이 없습니다." >&2; exit 1; }

# 목록 페이지 — 주소에 파일명까지 치지 않아도 되게
python3 "$HERE/makeindex.py" "$OUT" || true

[ "$SERVE" = 1 ] || exit 0

# 이 기기를 다른 기기에서 여는 주소.
# ⭐ MagicDNS 이름이 있으면 IP 보다 그걸 쓴다 — 사람이 치는 건 사람이 읽는 이름이다.
HOSTN=$(tailscale status --json 2>/dev/null | python3 -c \
  "import json,sys;print((json.load(sys.stdin).get('Self',{}).get('DNSName') or '').rstrip('.'))" \
  2>/dev/null || true)
SHORT=${HOSTN%%.*}
IP=$(tailscale ip -4 2>/dev/null | head -1)
[ -n "$IP" ] || IP=$(ipconfig getifaddr en0 2>/dev/null)
[ -n "$IP" ] || IP=$(hostname -I 2>/dev/null | awk '{print $1}')
[ -n "$IP" ] || IP=127.0.0.1
HOST=${SHORT:-$IP}

# 포트가 이미 쓰이는 일은 흔하다(앞서 띄운 창, 다른 레포). 죽지 말고 가른다:
#   비었으면 그대로 · 이미 같은 폴더를 서빙 중이면 그걸 쓰고 · 아니면 옆 포트로 옮긴다.
PICK=$(python3 "$HERE/pickport.py" "$PORT" index)
WANT=$PORT
PORT=${PICK%% *}; MODE=${PICK##* }

case "$MODE" in
  reuse)
    echo ""
    echo "[codestrata] ▶  http://$HOST:$PORT/"
    echo "[codestrata]    (서버가 이미 이 폴더를 서빙 중이라 새로 띄우지 않았습니다 — 새로고침하면 최신입니다)"
    exit 0 ;;
  fail)
    echo "" >&2
    echo "[codestrata] $WANT ~ $((WANT+20)) 이 전부 사용 중입니다. --port 로 다른 포트를 주세요." >&2
    exit 1 ;;
  moved)
    echo ""
    echo "[codestrata] $WANT 는 다른 것이 쓰고 있어 $PORT 로 옮겼습니다." ;;
esac

echo ""
echo "[codestrata] ▶  http://$HOST:$PORT/"
[ "$HOST" = "$IP" ] || echo "[codestrata]    (이름이 안 되면 http://$IP:$PORT/)"
echo "[codestrata]    Ctrl+C 로 종료"
exec python3 "$HERE/serve.py" "$PORT" "$OUT"
