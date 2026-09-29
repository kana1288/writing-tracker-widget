/**
 * JS 테스트 공용 헬퍼 — 테스트 전용 서버를 띄우고, 위젯 코드를 그 서버에 연결한다.
 *
 * 왜 필요한가:
 *   /api/delta는 "최초 1회 폴링만 가져갈 수 있는" 일회성 자원이다. 그래서 테스트가
 *   프로덕션 포트(8000)와 실제 baseline.json을 공유하면, 실제로 떠 있는 위젯 탭이
 *   테스트가 만든 글자 수를 먼저 가져가 버린다(카운트 0으로 관측). 그래서 테스트는
 *   아래 세 가지를 모두 물리적으로 분리한다.
 *
 *   1) 포트      : TEST_PORT (기본 8123). 8000은 절대 쓰지 않는다.
 *   2) 기준점     : 임시 디렉터리의 baseline-<pid>.json. 저장소의 baseline.json과 무관.
 *   3) 픽스처 폴더 : 임시 디렉터리의 txt 파일들. testFolder/를 건드리지 않는다.
 *
 * 덕분에 다른 index.html 탭이 몇 개 열려 있어도 테스트는 영향을 받지 않는다.
 */
const fs = require('fs');
const os = require('os');
const path = require('path');
const { spawn } = require('child_process');

const ROOT = path.join(__dirname, '..');
const TEST_PORT = Number(process.env.WTW_TEST_PORT || 8123);
const BASE = `http://127.0.0.1:${TEST_PORT}`;

// ── 테스트 환경 하나를 만드는 함수 ─────────────────────────────
function createEnv(sampleText = '안녕 세상') {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'wtw-test-'));
  return {
    dir,
    baseline: path.join(dir, `baseline-${process.pid}.json`),
    file: path.join(dir, 'sample1.txt'),
    port: TEST_PORT,
    base: BASE,
    write: (text) => fs.writeFileSync(dir + '/sample1.txt', text, 'utf8'),
    append: (text) => fs.appendFileSync(dir + '/sample1.txt', text, 'utf8'),
    cleanup: () => {
      try { fs.rmSync(dir, { recursive: true, force: true }); } catch (_) {}
    },
  };
}

// 픽스처 폴더를 인자로 넘기고 서버를 백그라운드로 띄운다.
function startServer(env) {
  fs.writeFileSync(env.file, '안녕 세상', 'utf8');
  const proc = spawn(
    'python3',
    [path.join(ROOT, 'tracker.py'),
     '--port', String(env.port),
     '--folder', env.dir,
     '--baseline', env.baseline],
    { cwd: ROOT, stdio: ['ignore', 'pipe', 'pipe'] }
  );
  proc.stdout.on('data', () => {});
  proc.stderr.on('data', () => {});
  env.proc = proc;
  return proc;
}

// 포트가 열릴 때까지 기다린다 (최대 timeout ms).
async function waitForServer(env, timeout = 8000) {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    try {
      const res = await fetch(`${env.base}/api/delta`);
      if (res.ok) return true;
    } catch (_) { /* 아직 안 뜸 — 재시도 */ }
    await new Promise((r) => setTimeout(r, 150));
  }
  throw new Error(`테스트 서버가 ${env.port}에서 뜨지 않았습니다`);
}

function stopServer(env) {
  if (env.proc && !env.proc.killed) {
    try { env.proc.kill('SIGTERM'); } catch (_) {}
  }
  env.cleanup();
}

// 기준점을 현재 파일 상태와 동기화한다 ("처음부터 delta 0" 보장).
async function syncBaseline(env) {
  await fetch(`${env.base}/api/delta`).then((r) => r.json());
}

// ── 최소 DOM 대역 + 위젯 코드 로더 ─────────────────────────────
// index.html의 폴링 코드만 재사용한다. DOMContentLoaded 전체를 돌리면 테마/퀵버튼/
// 달력 렌더링까지 필요해지므로, 폴링 시작에 해당하는 부분만 원본과 같게 재현한다.
function loadWidget(env) {
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
  global.document = {
    getElementById: (id) => (cache[id] ||= el()),
    querySelectorAll: () => [],
    addEventListener: () => {},
    documentElement: { style: { setProperty() {}, removeProperty() {} } },
    createElement: () => el(),
    createTextNode: () => ({}),
  };
  // 이게 핵심: 테스트 전용 포트를 위젯 코드에 주입한다.
  global.__SYNC_API_BASE__ = env.base;

  const html = fs.readFileSync(path.join(ROOT, 'index.html'), 'utf8');
  const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];
  const mod = { exports: {} };
  new Function('module', 'fetch', script + `
    module.exports = {
      getCount: () => count,
      getData: () => writingData,
      getSync: () => document.getElementById('syncStatus').textContent,
      getUrls: () => SYNC_API_URLS,
      pollOnce: () => pollDelta(),
      start: () => { updateSyncStatus(); pollDelta(); setInterval(pollDelta, SYNC_INTERVAL_MS); },
    };
  `)(mod, fetch);
  return mod.exports;
}

// 위젯 코드를 '실패하는 fetch'로 다시 만들어 폴백/에러 경로를 검증한다.
function loadWidgetWithFailingFetch(env) {
  const script = fs.readFileSync(path.join(ROOT, 'index.html'), 'utf8')
    .match(/<script>([\s\S]*?)<\/script>/)[1];
  const mod = { exports: {} };
  new Function('module', 'fetch', script + `
    module.exports = { pollOnce: () => pollDelta() };
  `)(mod, () => Promise.reject(new Error('ECONNREFUSED')));
  return mod.exports;
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// 통과/실패를 세면서 결과를 정리해 주는 러너.
function makeRunner(realLog) {
  let pass = 0, fail = 0;
  return {
    check(label, ok, extra = '') {
      realLog(`  ${ok ? '✅' : '❌'} ${label}${extra ? ' ' + extra : ''}`);
      ok ? pass++ : fail++;
    },
    finish(realLog2) {
      realLog2(`\n결과: ${pass} 통과 / ${fail} 실패`);
      return fail;
    },
  };
}

module.exports = {
  ROOT, TEST_PORT, BASE,
  createEnv, startServer, waitForServer, stopServer, syncBaseline,
  loadWidget, loadWidgetWithFailingFetch,
  sleep, makeRunner,
};
