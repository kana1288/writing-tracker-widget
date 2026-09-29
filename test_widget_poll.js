/**
 * 위젯 폴링 end-to-end 검증.
 * index.html의 폴링 코드를 그대로 재사용해, 가짜 DOM + 실제 Python 서버에 연결해
 * "파일 추가 → 델타 수신 → writingData 누적" 흐름을 확인한다.
 *
 *   node test_widget_poll.js
 */
const fs = require('fs');
const path = require('path');

const ROOT = __dirname;
const BASE = 'http://127.0.0.1:8000';
const FILE = path.join(ROOT, 'testFolder', 'sample1.txt');

// ── 최소 DOM 대역 ──────────────────────────────────────────
const store = {};
global.localStorage = {
  getItem: (k) => (k in store ? store[k] : null),
  setItem: (k, v) => { store[k] = String(v); },
  removeItem: (k) => { delete store[k]; },
  clear: () => { for (const k of Object.keys(store)) delete store[k]; },
};
const cache = {};
const el = () => ({
  textContent: '', innerHTML: '', className: '', style: {}, appendChild() {},
  classList: { toggle() {}, add() {}, remove() {} },
});
// DOMContentLoaded 콜백을 보관했다가 수동으로 실행한다 (폴링 시작 트리거).
// index.html의 script가 globalThis.document.addEventListener로 등록하므로
// 이 핸들러는 new Function 바깥에서 참조할 수 있도록 global에 둔다.
global.__domReady = null;
global.document = {
  getElementById: (id) => (cache[id] ||= el()),
  querySelectorAll: () => [],
  addEventListener: (evt, fn) => { if (evt === 'DOMContentLoaded') global.__domReady = fn; },
  documentElement: { style: { setProperty() {}, removeProperty() {} } },
  createElement: () => el(),
  createTextNode: () => ({}),
};

// ── index.html에서 실제 코드 추출 후 최소 심볼만 정의해 실행 ──
const html = fs.readFileSync(path.join(ROOT, 'index.html'), 'utf8');
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];

// index.html의 script를 그대로 실행한다 (심볼 재선언 없이).
const postload = `
  module.exports = {
    getCount: () => count,
    getData: () => writingData,
    getSync: () => document.getElementById('syncStatus').textContent,
    // DOMContentLoaded 전체를 돌리면 테마/퀵버튼/달력 렌더링 등 DOM이 추가로
    // 필요해지므로, 폴링 시작에 해당하는 부분만 원본과 동일하게 재현한다.
    start: () => { updateSyncStatus(); pollDelta(); setInterval(pollDelta, SYNC_INTERVAL_MS); },
  };
`;

const mod = { exports: {} };
new Function('module', 'fetch', script + postload)(mod, fetch);
const widget = mod.exports;

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const todayKey = new Date().toISOString().slice(0, 10);

let pass = 0, fail = 0;
function check(label, actual, expected) {
  const ok = actual === expected;
  console.log(`  ${ok ? '✅' : '❌'} ${label}: ${actual}${ok ? '' : ` (기대 ${expected})`}`);
  ok ? pass++ : fail++;
}

(async () => {
  console.log('\n── 위젯 폴링 end-to-end (10초 주기) ──');

  // 0) 테스트 시작 전 기준점을 현재 파일 상태와 동기화한다. 이전 실행이 파일을
  //    바꿔둔 상태일 수 있어, "처음부터 delta 0"인 상태를 보장해야 한다.
  await fetch(`${BASE}/api/delta`).then((r) => r.json());

  widget.start();   // 폴링 시작 (DOMContentLoaded의 폴링 부분)

  await sleep(11000);
  check('첫 폴링 — 변화 없음', widget.getCount(), 0);
  check('연결 상태 표시', widget.getSync(), '자동 집계 중');

  // 파일에 5자 추가 → 다음 폴링에서 누적
  fs.appendFileSync(FILE, '가나다라마', 'utf8');
  await sleep(11000);
  check('5자 추가 후 카운트', widget.getCount(), 5);
  check('localStorage 누적', widget.getData()[todayKey], 5);

  // 변화 없으면 유지
  await sleep(11000);
  check('추가 변화 없음 → 유지', widget.getCount(), 5);

  // 파일 축소 → 카운트 감소하지 않음 (Q8-A)
  fs.writeFileSync(FILE, '짧음', 'utf8');
  await sleep(11000);
  check('파일 축소 → 감소 없음', widget.getCount(), 5);

  // 원복: 원래 내용으로 되돌린다 (축소는 델타 0이므로 기준점만 갱신된다)
  fs.writeFileSync(FILE, '안녕 세상', 'utf8');
  await fetch(`${BASE}/api/delta`).then((r) => r.json());

  console.log(`\n결과: ${pass} 통과 / ${fail} 실패`);
  process.exit(fail ? 1 : 0);
})();
