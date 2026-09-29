/**
 * 폴링 주소 결정 로직 검증 — 테스트 격리가 프로덕션 기본값을 깨지 않았는지 확인한다.
 * 서버가 필요 없다 (주소 계산만 검증).
 *
 *   node test_widget_config.js
 */
const fs = require('fs');
const path = require('path');

const ROOT = __dirname;
const script = fs.readFileSync(path.join(ROOT, 'index.html'), 'utf8')
  .match(/<script>([\s\S]*?)<\/script>/)[1];

// resolveSyncApiUrls()만 단독 실행한다. 위젯 전체를 로드하면 DOM/localStorage
// 대역이 필요해지므로, 이 함수 하나만 잘라 쓰는 편이 목적에 맞고 가볍다.
const body = script.match(/function resolveSyncApiUrls\(\)\s*\{[\s\S]*?\n    \}/)[0];
if (!body) {
  console.error('❌ index.html에서 resolveSyncApiUrls()를 찾지 못했습니다.');
  process.exit(1);
}

function resolveUrls({ injectBase, metaContent }) {
  const store = {};
  global.localStorage = {
    getItem: (k) => (k in store ? store[k] : null),
    setItem: (k, v) => { store[k] = String(v); },
  };
  global.document = {
    // metaContent가 주어지지 않으면 querySelector가 없는 최소 DOM처럼 동작한다.
    querySelector: (sel) => (metaContent && sel.includes('sync-api-base')
      ? { content: metaContent }
      : null),
  };
  if (injectBase === undefined) delete global.__SYNC_API_BASE__;
  else global.__SYNC_API_BASE__ = injectBase;

  const fn = new Function(`${body}; return resolveSyncApiUrls();`);
  return fn();
}

let pass = 0, fail = 0;
function check(label, actual, expected) {
  const ok = JSON.stringify(actual) === JSON.stringify(expected);
  console.log(`  ${ok ? '✅' : '❌'} ${label}\n     → ${JSON.stringify(actual)}`);
  ok ? pass++ : fail++;
}

console.log('\n── 폴링 주소 결정 ──');

// 1) 프로덕션 기본값: 아무것도 주입하지 않으면 8000 (기존 동작 보존)
check('기본값 = localhost:8000 + 127.0.0.1 폴백',
  resolveUrls({}),
  ['http://localhost:8000/api/delta', 'http://127.0.0.1:8000/api/delta']);

// 2) 테스트 주입이 최우선
check('__SYNC_API_BASE__ 주입 시 그 주소 사용',
  resolveUrls({ injectBase: 'http://127.0.0.1:8123' }),
  ['http://127.0.0.1:8123/api/delta', 'http://127.0.0.1:8123/api/delta']);

// 3) 주입이 meta보다 우선
check('__SYNC_API_BASE__ > meta 우선순위',
  resolveUrls({ injectBase: 'http://127.0.0.1:8123', metaContent: 'http://localhost:9999' })[0],
  'http://127.0.0.1:8123/api/delta');

// 4) meta만으로도 지정 가능
check('meta만으로 지정 가능',
  resolveUrls({ metaContent: 'http://localhost:9000' })[0],
  'http://localhost:9000/api/delta');

// 5) /api/delta를 이미 붙여 넣어도 중복되지 않는다
check('주소에 /api/delta가 있어도 중복 안 됨',
  resolveUrls({ injectBase: 'http://127.0.0.1:8123/api/delta' })[0],
  'http://127.0.0.1:8123/api/delta');

// 6) 끝의 슬래시도 정리된다
check('끝 슬래시 제거',
  resolveUrls({ injectBase: 'http://127.0.0.1:8123///' })[0],
  'http://127.0.0.1:8123/api/delta');

// 7) 최소 DOM(querySelector 없음)에서도 죽지 않는다 — 구형 테스트 하네스 호환
check('querySelector 없는 환경에서도 기본값으로 동작',
  (() => {
    const fn = new Function(`${body}; return resolveSyncApiUrls();`);
    delete global.__SYNC_API_BASE__;
    return fn();
  })(),
  ['http://localhost:8000/api/delta', 'http://127.0.0.1:8000/api/delta']);

console.log(`\n결과: ${pass} 통과 / ${fail} 실패`);
process.exit(fail ? 1 : 0);
