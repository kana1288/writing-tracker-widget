/**
 * 콘솔 로그 검증 — index.html의 syncLog()가 실제로 무엇을 찍는지 확인한다.
 * (fetch는 서버에 실제 연결하고, console은 캡처한다)
 *
 *   node test_widget_log.js
 */
const fs = require('fs');
const path = require('path');

const ROOT = __dirname;
const BASE = 'http://127.0.0.1:8000';
const FILE = path.join(ROOT, 'testFolder', 'sample1.txt');

const store = {};
global.localStorage = {
  getItem: (k) => (k in store ? store[k] : null),
  setItem: (k, v) => { store[k] = String(v); },
  removeItem: (k) => { delete store[k]; },
  clear: () => { for (const k of Object.keys(store)) delete store[k]; },
};
const cache = {};
const el = () => ({ textContent: '', innerHTML: '', className: '', style: {},
  appendChild() {}, classList: { toggle() {}, add() {}, remove() {} } });
global.__domReady = null;
global.document = {
  getElementById: (id) => (cache[id] ||= el()),
  querySelectorAll: () => [],
  addEventListener: (e, f) => { if (e === 'DOMContentLoaded') global.__domReady = f; },
  documentElement: { style: { setProperty() {}, removeProperty() {} } },
  createElement: () => el(),
  createTextNode: () => ({}),
};

// console 캡처
const captured = [];
const realLog = console.log, realWarn = console.warn, realError = console.error;
const cap = (level) => (...a) => { captured.push({ level, a }); };
console.log = cap('log');
console.warn = cap('warn');
console.error = cap('error');

const html = fs.readFileSync(path.join(ROOT, 'index.html'), 'utf8');
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];

const mod = { exports: {} };
new Function('module', 'fetch', script + `
  module.exports = {
    getCount: () => count,
    pollOnce: () => pollDelta(),
  };
`)(mod, fetch);
const w = mod.exports;

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const restore = () => { console.log = realLog; console.warn = realWarn; console.error = realError; };

let pass = 0, fail = 0;
const check = (label, ok, extra = '') => {
  // 캡처된 console이 아니라 원본으로 출력한다 (자기 로그가 잡히면 안 되므로)
  realLog(`  ${ok ? '✅' : '❌'} ${label}${extra ? ' ' + extra : ''}`);
  ok ? pass++ : fail++;
};

(async () => {
  await fetch(`${BASE}/api/delta`).then((r) => r.json());   // 기준점 동기화

  // 1) 변화 없음 → info 로그
  captured.length = 0;
  await w.pollOnce();
  await sleep(400);
  const noChange = captured.filter((c) => c.a[0].includes('변화 없음'));
  check('delta 0 → "변화 없음" 로그', noChange.length === 1,
    noChange[0] ? `→ ${noChange[0].a[0]}` : '(로그 없음)');

  // 2) 글자 추가 → 반영 로그 (증감 포함)
  fs.appendFileSync(FILE, '가나다라마바', 'utf8');   // +6
  captured.length = 0;
  await w.pollOnce();
  await sleep(400);
  const applied = captured.filter((c) => c.a[0].includes('반영'));
  check('delta > 0 → "반영" 로그', applied.length === 1,
    applied[0] ? `→ ${applied[0].a[0]}` : '(로그 없음)');
  check('로그에 증감 표시 포함',
    applied[0] ? /0 → 6/.test(applied[0].a[0]) : false,
    applied[0] ? `→ ${applied[0].a[0]}` : '');
  check('상세 객체에 timestamp 포함',
    applied[0] ? typeof applied[0].a[1]?.timestamp === 'string' : false);

  // 3) 로그 접두사에 타임스탬프 포함 (ko-KR 로케일은 "오후 12:20:08" 형식)
  check('타임스탬프 접두사',
    applied[0] ? /^\[[^\]]+\]\[글자수카운터\]/.test(applied[0].a[0]) : false,
    applied[0] ? `→ ${applied[0].a[0].slice(0, 32)}…` : '');

  // 4) 파일 축소 → 변화 없음 로그 (감소 없음)
  fs.writeFileSync(FILE, '짧음', 'utf8');
  captured.length = 0;
  await w.pollOnce();
  await sleep(400);
  const shrink = captured.filter((c) => c.a[0].includes('변화 없음'));
  check('파일 축소 → "변화 없음" 로그', shrink.length === 1);
  check('축소 후 카운트 유지', w.getCount() === 6, `count=${w.getCount()}`);

  // 5) 서버 죽었을 때 → error 로그 (다른 주소로 폴백 후)
  captured.length = 0;
  const origFetch = globalThis.fetch;
  // 8000 포트를 닫을 수는 없으므로, 실패를 흉내내 폴백/에러 로그를 확인한다
  const failingFetch = () => Promise.reject(new Error('ECONNREFUSED'));
  const mod2 = { exports: {} };
  new Function('module', 'fetch', script + `
    module.exports = { pollOnce: () => pollDelta() };
  `)(mod2, failingFetch);
  await mod2.exports.pollOnce();   // 첫 주소 실패 → 폴백 로그
  await sleep(300);
  const fallback = captured.filter((c) => c.a[0].includes('재시도'));
  check('연결 실패 → 폴백 warn 로그', fallback.length === 1,
    fallback[0] ? `→ ${fallback[0].a[0]}` : '(로그 없음)');
  check('폴백 로그 level=warn', fallback[0] ? fallback[0].level === 'warn' : false);

  // 두 번째 주소도 실패 → error 로그
  captured.length = 0;
  await mod2.exports.pollOnce();
  await sleep(300);
  const err = captured.filter((c) => c.a[0].includes('연결 실패'));
  check('두 번째 실패 → error 로그', err.length === 1,
    err[0] ? `→ ${err[0].a[0]}` : '(로그 없음)');
  check('error 로그 level=error', err[0] ? err[0].level === 'error' : false);

  // 원복
  fs.writeFileSync(FILE, '안녕 세상', 'utf8');
  await origFetch(`${BASE}/api/delta`).then((r) => r.json());

  restore();
  console.log(`\n결과: ${pass} 통과 / ${fail} 실패`);
  process.exit(fail ? 1 : 0);
})();
