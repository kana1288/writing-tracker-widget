# 플랜: 파일 스캔 기반 글자 수 자동 집계

- 작성일: 2026-09-29
- 브레인스토밍: `docs/brainstorms/2026-09-29-auto-file-scan-counter.md`
- 상태: Q1–Q8 확정 → 구현 착수 가능
- 대상: `writing-tracker-widget`

---

# Goal

완료 시 아래가 참이어야 한다.

1. `python tracker.py` → 로컬 HTTP 서버가 `index.html`을 `http://localhost:8000`에 서빙.
2. `testFolder/`(또는 `--folder`) 안의 `.txt` 글자 수를 10초 주기로 스캔.
3. 직전 스캔 대비 **증가분만** 델타로 반환. 응답 `{"delta": int, "timestamp": ISO8601}`.
4. 위젯은 10초마다 `GET /api/delta` 폴링 → 델타가 있으면 **기존 `changeCount()` 재사용**해 누적.
5. Python 재시작 시 `baseline.json`에서 스냅샷 복원 → **초기화되지 않고 이어서 집계** (Q7).
6. 글자 수 = **공백 포함, 줄바꿈(`\n`/`\r`) 제외** (Q5-A).
7. 파일 글자 수 감소 시 그 파일 델타는 **0** (Q8-A). 새 파일은 전체 글자 수 합산.
8. 외부 패키지 **0건**. 표준 라이브러리만. 윈도우·맥.
9. 자동 집계 동작해도 **퀵버튼 수동 조작이 계속 동작**.

---

# Current State

단일 `index.html` (1,373줄). 순수 HTML + CSS + 바닐라 JS. 빌드·패키지·테스트·백엔드 없음. 의존성은 Google Fonts `DungGeunMo` 하나.

**데이터 원본**: `localStorage.writingData` = `{"YYYY-MM-DD": 글자수}` — 유일한 진실.

쓰기 지점 3개 (grep 확인):

| 지점 | 함수 | 경로 |
|---|---|---|
| 퀵버튼 click | `changeCount(amount)` | 수동 |
| 달력 과거 날짜 click | `editDayCount(key)` | 수동 |
| 초기화 | `DOMContentLoaded` | `= 0` |

```js
function changeCount(amount) {
  count += amount;            // ← 자동 델타도 이 경로
  if (count < 0) count = 0;   // ← 0 하한 클램프 (Q8-A와 일관)
  writingData[todayKey] = count;
  saveData();
  updateToday();
  renderCalendar();
}
```

**신규 계층 부재** (grep 실측): `fetch` 0건 · `XMLHttpRequest` 0건 · `WebSocket` 0건 · `<iframe>` 0건 · `localhost` 0건 · `baseline` 0건 · `delta` 0건 · `setInterval` 0건.
→ 전부 신규. 기존 코드 충돌·회귀 위험 없음.

**기존 결함 (이번 스코프 밖)**: B1 `calculateStreak()` 오늘 미달성 시 0으로 끊김 / B2 `WEEKLY·MONTHLY WORDS` 라벨 오류 / B3 `.DS_Store` 커밋 + `.gitattributes` 없음.

---

# Architecture

```
[PC 파일시스템]  testFolder/chapter1.txt 3,000자
        │ 10초 주기 (위젯 요청 시점)
        ▼
[tracker.py]  baseline.json 로드 → .txt 글자 수 스캔
              → delta = Σ max(0, 현재 − baseline)
              → baseline 갱신·저장
              → { "delta": 800, "timestamp": "..." }
        │ HTTP
        ▼
[index.html]  setInterval(pollDelta, 10000)
              → fetch("/api/delta") → delta > 0 → changeCount(delta)
              → 실패 시 catch, 마지막 값 유지
```

엔드포인트: `GET /api/delta` → JSON · `GET /*` → index.html

**글자 수**: `len(내용) − count("\n") − count("\r")` (유니코드 코드포인트 기준, 가변폭 처리 없음)

---

# Proposed Changes

## 변경 1: `tracker.py` 신규

```python
def count_characters(text: str) -> int:
    """Q5-A: 공백 포함, 줄바꿈 제외. 유니코드 코드포인트 수."""
    return len(text) - text.count("\n") - text.count("\r")


def scan_folder(folder: Path) -> dict[str, int]:
    result: dict[str, int] = {}
    for path in sorted(folder.rglob("*")):
        if path.suffix.lower() != ".txt" or not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue          # 읽을 수 없는 파일은 skip
        result[path.relative_to(folder).as_posix()] = count_characters(text)
    return result


def compute_delta(current: dict[str, int], baseline: dict[str, int]) -> int:
    """Q8-A: 감소는 0, 삭제된 파일은 미반영, 새 파일은 전체."""
    total = 0
    for name, size in current.items():
        previous = baseline.get(name, 0)
        if size > previous:
            total += size - previous
    return total
```

`baseline.json` 구조: `{"files": {"rel/path.txt": 3000}, "updatedAt": "ISO8601"}`.
로드 실패(없음/손상) 시 `{}` → 첫 스캔 델타 0 (과대 집계 방지). 구형 bare dict 형식도 수용.

HTTP 서버: `HTTPServer(("127.0.0.1", 8000))` — **명시적 `127.0.0.1`**. `("localhost", ...)`는 DNS 리졸브에 따라 LAN IP에 바인딩될 수 있어 로컬 전용 의도와 어긋남.
CORS 헤더 `Access-Control-Allow-Origin: *` 필수 (S3).

## 변경 2: `index.html` — 폴링 추가

`DOMContentLoaded` 핸들러 내부, `renderCalendar()` 다음:

```js
let serverReachable = true;
let failCount = 0;

function pollDelta() {
  fetch("/api/delta")
    .then((res) => res.json())
    .then((data) => {
      serverReachable = true; failCount = 0; updateSyncStatus();
      if (data.delta > 0) changeCount(data.delta);   // ← 기존 경로 재사용
    })
    .catch(() => {
      failCount++;
      if (failCount >= 3) { serverReachable = false; updateSyncStatus(); }
    });
}
// 시작: pollDelta(); setInterval(pollDelta, 10000);
```

- `changeCount()` **본문 수정 0줄**. 호출만 추가 → 수동 경로 회귀 없음
- `setInterval`이 프로젝트에 처음 도입됨. 서버 죽어도 `catch`로 흡수, Promise rejection 누적 안 됨
- 연속 3회 실패 후에만 "카운터 연결 안 됨" 표시 (10초마다 깜빡임 방지)

## 변경 3: `testFolder/` + 샘플

검증 목적: Q5-A 선택 근거가 "직접 세어 맞춰볼 수 있다"이므로 기대값이 손으로 계산 가능해야 한다.

| 파일 | 내용 | 기대 글자 수 |
|---|---|---|
| `sample1.txt` | `안녕 세상` | 5 |
| `sample2.txt` | `가나다\n라마바` | 6 |
| `nested/deep.txt` | `12345` | 5 |

## 변경 4: `.gitignore` 신규

```
baseline.json
```

`baseline.json`은 실행환경 상태 파일이므로 커밋하지 않는다. 샘플 `.txt`는 커밋한다(검증 fixtures).

---

# Tests

테스트 인프라 없음 → 신규 생성. `unittest`(표준 라이브러리)로 외부 의존성 0 유지.

## 단위: `test_tracker.py`

| 테스트 | 검증 |
|---|---|
| `count_characters_includes_space` | `"안녕 세상"` → 5 |
| `count_characters_excludes_newline` | `"가나다\n라마바"` → 6 |
| `count_characters_crlf` | `"a\r\nb"` → 2 |
| `compute_delta_new_file` | baseline `{}` → 파일 전체 |
| `compute_delta_growth` | 3000 → 3800 → 800 |
| `compute_delta_shrink_is_zero` | 3000 → 2000 → **0** (Q8-A) |
| `compute_delta_deleted_file_is_zero` | 삭제된 파일 → **0** (Q8-A) |
| `load_baseline_missing` | 없음 → `{}` |
| `load_baseline_corrupted` | 잘못된 JSON → `{}` |
| `load_baseline_legacy_bare_dict` | 구형 형식 수용 |
| `scan_folder_nested` | 하위 폴더 포함 |
| `scan_folder_skips_unreadable` | 비UTF8 파일 skip |
| `scan_folder_uppercase_extension` | `.TXT` 포함 (Q4 실효성) |

## 통합: `test_http.py`

| 테스트 | 검증 |
|---|---|
| `api_delta_json_shape` | `delta` int, `timestamp` str |
| `api_delta_cors_header` | `Access-Control-Allow-Origin: *` |
| `api_delta_timestamp_iso8601` | `datetime.fromisoformat()` 성공 |
| `root_serves_index_html` | `/` → index.html |
| `delta_persists_across_restart` | 스캔 → 저장 → 재시작 → 델타 0 (Q7) |
| `delta_accumulates_after_restart` | 재시작 후 증가분만 반영 (Q7 핵심) |

## 수동 검증

1. `python tracker.py --folder testFolder` 실행
2. `http://localhost:8000` → 위젯 렌더링 확인
3. `sample1.txt`에 문자 추가·저장 → 10초 이내 카운트 증가
4. Python 종료 → 재시작 → **카운트 유지, 델타 0**
5. 재시작 후 `sample1.txt`에 더 추가 → **추가분만** 반영
6. `sample1.txt`을 짧게 만들기 → 카운트 **감소 없음** (Q8-A)
7. 퀵버튼 클릭 → 수동 조작 여전히 동작
8. Python 종료 상태에서 위젯 → 카운트 유지 + "연결 안 됨" 표시

---

# Risks

| 종류 | 내용 | 대응 |
|---|---|---|
| 보안 | CORS `*`로 로컬 서버 개방 | **`127.0.0.1` 명시 바인딩** — `localhost`는 LAN IP로 리졸브될 수 있음 |
| 보안 | 폴더 내 모든 `.txt`가 집계 대상 | 사용자가 직접 지정. 기본값은 프로젝트 내 `testFolder` |
| 보안 | 폴더 경로가 브라우저에 노출 안 됨 | ✅ Q5 설계가 이걸 회피 |
| 회귀 | 자동 델타가 수동 경로 오염 | `changeCount()` **수정 0줄**, 호출만 추가. 순수 가산이라 순서 무관 |
| 회귀 | `file://`로 열면 폴링 무동작 | 서버가 살아도 브라우저가 로컬 파일의 네트워크 접근을 블록. 안내 필요 |
| 회귀 | 포트 8000 사용 중 | `OSError` 잡아 명확한 메시지 + 종료 |
| 회귀 | 에디터 임시 파일(`.sample.txt` 등) 집계 오염 | `rglob("*")` + suffix `.txt` 검사라 임시 파일도 잡힘 → **`.` 접두 파일 제외** 필요 (구현 시 반영) |
| lifecycle | 서버 중지 중 위젯 → `count`는 마지막 값 유지 | Q6-B 결정의 부수 결과. 문서화 |
| 데이터 | `baseline.json` 손상 | `{}` 폴백 → 델타 0. 과대 집계보다 안전 |

---

# Rollback

- `tracker.py`, `testFolder/`, `.gitignore` → **삭제만으로 원상 복구**
- `index.html` → 폴링 블록(`pollDelta`/`serverReachable`/`failCount`/`updateSyncStatus`/상태 표시 요소 + `setInterval` 시작)만 삭제하면 완전 복구. 기존 함수 **0줄 수정**
- `baseline.json`은 상태 파일이라 복구 대상 아님

---

# Verification

- Plan에 명시된 단위 13건 + 통합 6건 + 수동 8단계 통과
- `changeCount()` diff 0줄 확인 (`git diff` 로 함수 본문 무변경 검증)
- `testFolder` 샘플 기대값(5/6/5)이 Python 출력과 일치 확인 — Q5-A 검증 가능성의 직접 증명
- Q8-A: 파일 축소 후 카운트 감소 없음 확인
- Q7: 재시작 후 델타 0 + 증가분만 반영 확인
- Windows에서 실행 확인 (개발 환경 실제 OS)

---

# 후속 (이번 스코프 밖)

| 항목 | 트리거 |
|---|---|
| B1 `calculateStreak()` 오늘 미달성 시 끊김 | 별도 요청 |
| B2 `WEEKLY/MONTHLY WORDS` → `CHARACTERS` 라벨 정정 | 별도 요청 |
| B3 `.gitattributes` + `.DS_Store` 제거 | 별도 요청 |
| `.docx` 지원 | 폴더가 `.docx` 중심이 되면 |
