"""글쓰기 트래커 — 파일 스캔 기반 자동 글자 수 집계.

폴더 안의 .txt / .hwpx 파일 글자 수를 주기적으로 스캔하고, 직전 스캔 대비 증가분
(델타)을 위젯에 전달한다. 글자 수는 "공백 포함, 줄바꿈 제외"로 센다.

데이터 소유권: 원본은 위젯(브라우저 localStorage). 이 프로그램은 델타만 계산해
전달하며, 스캔 기준점(baseline)만 로컬 파일에 보관한다.

표준 라이브러리만 사용한다 (윈도우 · 맥 공통). HWPX는 ZIP + XML이라 외부 도구
(pyhwp, LibreOffice) 없이도 텍스트를 뽑을 수 있다.
"""

from __future__ import annotations

import argparse
import json
import re
import socket
import sys
import zipfile
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

DEFAULT_FOLDER = str(Path.home() / "Desktop" / "글자수자동집계폴더")
DEFAULT_PORT = 8000
POLL_INTERVAL_SECONDS = 10

PROJECT_ROOT = Path(__file__).resolve().parent
INDEX_HTML = PROJECT_ROOT / "index.html"
# 기준점은 저장소가 아니라 홈 아래 별도 위치에 둔다. 저장소에 두면 저장소 밖
# 원고를 읽어 만든 파생 데이터가 GitHub에 올라갈 위험이 있다.
STATE_DIR = Path.home() / ".writing-tracker"

# 집계 대상 확장자. .hwp(구형 바이너리)는 순수 표준 라이브러리로 파싱하기 어려워
# 제외한다. 필요하면 pyhwp 등 외부 의존성을 도입해야 한다.
TEXT_SUFFIXES = frozenset({".txt", ".hwpx"})

# HWPX 내부 구조: Contents/section<N>.xml에 문단이 들어 있다.
# N이 두 자리 넘어가면 문자열 정렬이 section10을 section2보다 앞에 놓는다.
# 본문 순서가 곧 글자 순서이므로 숫자로 정렬해야 한다.
_SECTION_RE = re.compile(r"^Contents/section(\d+)\.xml$")
_PARAGRAPH_RE = re.compile(r"<hp:p\b.*?</hp:p>", re.S)
_TEXT_RUN_RE = re.compile(r"<hp:t(?:\s[^>]*)?>(.*?)</hp:t>", re.S)
# 태그를 제거하고 엔티티만 되돌린다. 문단 안의 줄바꿈/탭은 글자 수에 넣지 않는다.
_TAG_RE = re.compile(r"<[^>]+>")
_LINEBREAK_RE = re.compile(r"[\r\n\t]+")
_ENTITY_RE = re.compile(r"&(#x?[0-9a-fA-F]+|[a-zA-Z]+);")
_BUILTIN_ENTITIES = {"quot": '"', "apos": "'", "amp": "&", "lt": "<", "gt": ">"}


def _unescape_xml(text: str) -> str:
    """XML 엔티티를 문자로 되돌린다. 숫자 참조(&#10; &#xA;)도 처리한다."""

    def repl(match: re.Match[str]) -> str:
        body = match.group(1)
        if body.startswith("#"):
            try:
                code = int(body[2:], 16) if body[1] in "xX" else int(body[1:])
            except ValueError:
                return match.group(0)
            if 0 <= code <= 0x10FFFF:
                return chr(code)
            return match.group(0)
        return _BUILTIN_ENTITIES.get(body, match.group(0))

    return _ENTITY_RE.sub(repl, text)


def count_characters(text: str) -> int:
    """글자 수를 센다 — 공백 포함, 줄바꿈(\\n, \\r) 제외.

    Python len()은 유니코드 코드포인트 기준이므로 한글도 1자 = 1코드포인트다.
    """
    return len(text) - text.count("\n") - text.count("\r")


def extract_hwpx_text(path: Path) -> str:
    """HWPX 파일에서 본문 텍스트를 뽑아 하나의 문자열로 돌려준다.

    HWPX는 ZIP으로, 본문은 Contents/section<N>.xml에 들어 있다. 각 XML에서 문단
    (hp:p)을 찾아 그 안의 텍스트 런(hp:t)을 이어 붙이고, 문단 사이에 개행을 넣는다.
    개행은 count_characters()에서 제외되므로 글자 수에는 영향이 없고, 문단 경계가
    붙어버리는 것만 막는다.

    본문이 여러 section에 나뉘어 있어도 숫자 순서대로 이어 붙인다(문자열 정렬이면
    section10이 section2보다 앞에 온다).
    """
    chunks: list[str] = []
    with zipfile.ZipFile(path) as archive:
        sections = []
        for name in archive.namelist():
            match = _SECTION_RE.match(name)
            if match:
                sections.append((int(match.group(1)), name))
        for _, name in sorted(sections):
            xml = archive.read(name).decode("utf-8", errors="replace")
            for paragraph in _PARAGRAPH_RE.findall(xml):
                runs = _TEXT_RUN_RE.findall(paragraph)
                text = _LINEBREAK_RE.sub("", _unescape_xml(_TAG_RE.sub("", "".join(runs))))
                chunks.append(text)
    return "\n".join(chunks)


def read_text_file(path: Path) -> str:
    """확장자에 맞춰 텍스트를 읽는다. 지원하지 않는 형식이면 OSError."""
    if path.suffix.lower() == ".hwpx":
        return extract_hwpx_text(path)
    return path.read_text(encoding="utf-8")


def scan_folder(folder: Path) -> dict[str, int]:
    """폴더를 재귀 탐색해 집계 대상 파일별 글자 수를 반환한다.

    키는 폴더 기준 상대 경로(슬래시 구분)다. 읽을 수 없는 파일은 건너뛴다.
    """
    snapshot: dict[str, int] = {}
    for path in sorted(folder.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        if path.name.startswith("."):
            continue  # 에디터 임시 파일 등 제외
        try:
            text = read_text_file(path)
        except (OSError, UnicodeDecodeError, zipfile.BadZipFile):
            continue
        snapshot[path.relative_to(folder).as_posix()] = count_characters(text)
    return snapshot


def compute_delta(current: dict[str, int], baseline: dict[str, int]) -> int:
    """직전 스캔 대비 증가분 합계.

    글자 수가 줄었으면 그 파일의 델타는 0 (카운터가 뒤로 가지 않는다).
    삭제된 파일도 반영하지 않는다. 이전에 없던 파일은 전체 글자 수를 더한다.
    """
    total = 0
    for name, size in current.items():
        previous = baseline.get(name, 0)
        if size > previous:
            total += size - previous
    return total


def load_baseline(path: Path) -> dict[str, int]:
    """기준점을 읽는다. 없거나 손상됐으면 빈 dict (→ 첫 스캔 델타 0)."""
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if isinstance(data, dict):
        files = data.get("files")
        if isinstance(files, dict):
            return {str(k): int(v) for k, v in files.items()}
        # 구형(bare dict) 형식도 수용
        return {str(k): int(v) for k, v in data.items()}
    return {}


def save_baseline(path: Path, snapshot: dict[str, int]) -> None:
    """기준점을 저장한다."""
    payload = {
        "files": snapshot,
        "updatedAt": datetime.now().astimezone().isoformat(),
    }
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def scan_and_update(folder: Path, baseline_path: Path) -> tuple[int, str]:
    """한 번 스캔해 델타를 계산하고 기준점을 갱신한다. (델타, 타임스탬프) 반환.

    첫 실행(기준점 파일 없음)은 기준점만 세우고 델타 0을 반환한다. 그래야 기존
    원고 전체가 "오늘 쓴 양"으로 잡히지 않는다. 기준점이 이미 있으면 이번 스캔
    이후 실제로 늘어난 만큼만 반환한다.
    """
    first_run = not baseline_path.exists()
    baseline = load_baseline(baseline_path)
    current = scan_folder(folder)
    delta = 0 if first_run else compute_delta(current, baseline)
    save_baseline(baseline_path, current)
    return delta, datetime.now().astimezone().isoformat()


def default_baseline_path(folder: Path) -> Path:
    """감시 폴더별 기준점 파일 경로를 만든다.

    폴더마다 다른 파일을 써야 한다. 기준점을 공유하면 폴더를 바꿨을 때 이전
    폴더와 글자 수가 겹치지 않는 한위 파일이 "새로 작성한 글자"로 잡힌다.
    폴더 경로에서 안전하지 않은 문자를 제거해 파일명으로 쓴다.
    """
    slug = re.sub(r"[^\w\-]+", "_", str(folder).strip("/")).strip("_")
    return STATE_DIR / f"baseline-{slug}.json"


def make_handler(folder: Path, baseline_path: Path) -> type[BaseHTTPRequestHandler]:
    class DeltaHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 (BaseHTTPRequestHandler 규약)
            path = self.path.split("?", 1)[0]

            if path == "/api/delta":
                delta, timestamp = scan_and_update(folder, baseline_path)
                body = json.dumps(
                    {"delta": delta, "timestamp": timestamp}, ensure_ascii=False
                ).encode("utf-8")
                content_type = "application/json; charset=utf-8"
                now = datetime.now().strftime("%H:%M:%S")
                if delta > 0:
                    print(f"[{now}] 폴링 → {delta}자 감지 (누적 반영됨)", flush=True)
                else:
                    print(f"[{now}] 폴링 → 변화 없음", flush=True)
            else:
                try:
                    body = INDEX_HTML.read_bytes()
                except OSError:
                    self.send_error(404, "index.html not found")
                    return
                content_type = "text/html; charset=utf-8"
                print(f"[{datetime.now().strftime('%H:%M:%S')}] 위젯 요청 → {path}", flush=True)

            self.send_response(200)
            self.send_header("Content-Type", content_type)
            # CORS: 없으면 브라우저가 응답을 막는다.
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt: str, *args) -> None:
            pass  # 기본 접근 로그는 위에서 직접 출력한다

    return DeltaHandler


def port_in_use(port: int) -> bool:
    """해당 포트가 이미 사용 중인지 확인한다."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        return probe.connect_ex(("127.0.0.1", port)) == 0


def create_server(port: int, folder: Path, baseline_path: Path) -> HTTPServer:
    """로컬 전용 서버를 만든다.

    127.0.0.1에 명시적으로 바인딩한다. "::"에 바인딩하면 LAN의 다른 기기에도 열려서
    폴더 안의 글자가 그대로 노출된다. 로컬 전용이 목적이므로 IP를 고정한다.
    """
    return HTTPServer(("127.0.0.1", port), make_handler(folder, baseline_path))


def main() -> int:
    parser = argparse.ArgumentParser(description="글쓰기 트라커 카운터")
    parser.add_argument(
        "--folder",
        default=DEFAULT_FOLDER,
        help=f"감시할 폴더 (기본값: {DEFAULT_FOLDER})",
    )
    parser.add_argument(
        "--port", type=int, default=DEFAULT_PORT, help=f"포트 (기본값: {DEFAULT_PORT})"
    )
    parser.add_argument(
        "--baseline",
        default=None,
        help="기준점 파일 경로 (기본값: ~/.writing-tracker/ 아래 폴더별 파일). "
        "테스트는 여기에 임시 경로를 줘서 실제 기준점을 건드리지 않는다.",
    )
    args = parser.parse_args()

    folder = Path(args.folder).expanduser().resolve()
    if not folder.is_dir():
        # 집계 폴더를 아직 만들지 않은 경우(최초 실행)에는 만들어 준다.
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            print(f"폴더를 만들 수 없습니다: {folder} ({exc})", file=sys.stderr)
            return 1

    baseline_path = (
        Path(args.baseline).expanduser().resolve()
        if args.baseline
        else default_baseline_path(folder)
    )
    baseline_path.parent.mkdir(parents=True, exist_ok=True)

    # 포트 중복 여부를 먼저 확인한다 (Windows에서 두 서버가 동시에 뜨는 일이 있어
    # 명확히 알린다). 여기서 실패해야 "위젯 주소"가 출력되지 않는다.
    if port_in_use(args.port):
        print(f"포트 {args.port}에서 이미 서버가 실행 중입니다.", file=sys.stderr)
        print("→ 이미 실행 중이면 그대로 쓰고, 이 창을 닫으세요.", file=sys.stderr)
        print("→ 다른 포트로 바꾸려면: python tracker.py --port 8001", file=sys.stderr)
        print("→ 위젯 주소도 함께 바꿔야 합니다 (index.html의 SYNC_API_URLS).", file=sys.stderr)
        return 1

    try:
        server = create_server(args.port, folder, baseline_path)
    except OSError as exc:
        print(f"서버를 시작할 수 없습니다 (포트 {args.port}): {exc}", file=sys.stderr)
        return 1

    print(f"글자 수 집계 폴더: {folder}", flush=True)
    print(
        f"위젯 주소: http://localhost:{args.port}  (또는 http://127.0.0.1:{args.port})",
        flush=True,
    )
    print(f"폴링 간격: {POLL_INTERVAL_SECONDS}초  (종료: Ctrl+C)", flush=True)
    print("─" * 50, flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n종료합니다.", flush=True)
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
