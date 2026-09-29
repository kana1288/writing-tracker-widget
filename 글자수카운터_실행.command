#!/bin/bash
# 글쓰기 트래커 실행 — 원고 폴더를 감시한다.
#
# 더블클릭(또는 터미널에서 실행)하면 서버가 뜨고 위젯이 열린다.
# 창을 닫으면 서버도 종료된다.

set -e

# 이 스크립트가 있는 위치 = 저장소 루트. 어느 데서 실행해도 같은 파일을 본다.
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# 감시할 원고 폴더는 tracker.py의 DEFAULT_FOLDER가 단일 출처다.
# 여기서 경로를 지정하면 둘이 어긋날 수 있으므로(--folder 미지정 시) 기본값을 쓴다.
PORT=8000

# venv 파이썬이 있으면 쓰고, 없으면 시스템 파이썬으로 떨어진다.
if [ -x "$HERE/.venv/bin/python3" ]; then
  PY="$HERE/.venv/bin/python3"
else
  PY="python3"
fi

cd "$HERE"
exec "$PY" tracker.py --port "$PORT"
