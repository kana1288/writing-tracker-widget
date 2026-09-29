#!/bin/bash
# 글쓰기 트래커 실행 — 원고 폴더를 감시한다.
#
# 더블클릭(또는 터미널에서 실행)하면 서버가 뜨고 위젯이 열린다.
# 창을 닫으면 서버도 종료된다.

set -e

# 이 스크립트가 있는 위치 = 저장소 루트. 어느 데서 실행해도 같은 파일을 본다.
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# 감시할 원고 폴더. 여기에 .txt / .hwpx 파일을 두면 글자 수를 센다.
# 데스크탑의 '글자수자동집계폴더'에 원고를 두고 쓴다.
FOLDER="$HOME/Desktop/글자수자동집계폴더"
PORT=8000

# 폴더가 없으면 만들어 준다 (집계 폴더를 처음 쓸 때).
mkdir -p "$FOLDER"

# venv 파이썬이 있으면 쓰고, 없으면 시스템 파이썬으로 떨어진다.
if [ -x "$HERE/.venv/bin/python3" ]; then
  PY="$HERE/.venv/bin/python3"
else
  PY="python3"
fi

cd "$HERE"
exec "$PY" tracker.py --port "$PORT" --folder "$FOLDER"
