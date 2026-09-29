/**
 * 콘솔 로그 검증 — index.html의 syncLog()가 실제로 무엇을 찍는지 확인한다.
 * (fetch는 테스트 전용 서버에 연결하고, console은 캡처한다)
 *
 *   node test_widget_log.js
 *
 * 프로덕션 포트(8000)와 실제 baseline.json을 쓰지 않는다. 다른 index.html 탭이
 * 떠 있어도 이 테스트는 영향받지 않는다. → tests/helpers.js 참고.
 */
const h = require('./tests/helpers');

const env = h.createEnv();
const realLog = console.log;
const realWarn = console.warn;
const realError = console.error;

// console 캡처
const captured = [];
const cap = (level) => (...a) => { captured.push({ level, a }); };

const w = h.loadWidget(env);
const wFail = h.loadWidgetWithFailingFetch(env);
const runner = h.makeRunner(realLog);

(async () => {
  h.startServer(env);
  await h.waitForServer(env);
  await h.syncBaseline(env);

  console.log = cap('log');
  console.warn = cap('warn');
  console.error = cap('error');

  try {
    // 1) 변화 없음 → info 로그
    captured.length = 0;
    await w.pollOnce();
    await h.sleep(400);
    const noChange = captured.filter((c) => c.a[0].includes('변화 없음'));
    runner.check('delta 0 → "변화 없음" 로그', noChange.length === 1,
      noChange[0] ? `→ ${noChange[0].a[0]}` : '(로그 없음)');

    // 2) 글자 추가 → 반영 로그 (증감 포함)
    env.append('가나다라마바');   // +6
    captured.length = 0;
    await w.pollOnce();
    await h.sleep(400);
    const applied = captured.filter((c) => c.a[0].includes('반영'));
    runner.check('delta > 0 → "반영" 로그', applied.length === 1,
      applied[0] ? `→ ${applied[0].a[0]}` : '(로그 없음)');
    runner.check('로그에 증감 표시 포함',
      applied[0] ? /0 → 6/.test(applied[0].a[0]) : false,
      applied[0] ? `→ ${applied[0].a[0]}` : '');
    runner.check('상세 객체에 timestamp 포함',
      applied[0] ? typeof applied[0].a[1]?.timestamp === 'string' : false);

    // 3) 로그 접두사에 타임스탬프 포함 (ko-KR 로케일은 "오후 12:20:08" 형식)
    runner.check('타임스탬프 접두사',
      applied[0] ? /^\[[^\]]+\]\[글자수카운터\]/.test(applied[0].a[0]) : false,
      applied[0] ? `→ ${applied[0].a[0].slice(0, 32)}…` : '');

    // 4) 파일 축소 → 변화 없음 로그 (감소 없음)
    env.write('짧음');
    captured.length = 0;
    await w.pollOnce();
    await h.sleep(400);
    const shrink = captured.filter((c) => c.a[0].includes('변화 없음'));
    runner.check('파일 축소 → "변화 없음" 로그', shrink.length === 1);
    runner.check('축소 후 카운트 유지', w.getCount() === 6, `count=${w.getCount()}`);

    // 5) 서버 죽었을 때 → 폴백/에러 로그
    captured.length = 0;
    await wFail.pollOnce();   // 첫 주소 실패 → 폴백 로그
    await h.sleep(300);
    const fallback = captured.filter((c) => c.a[0].includes('재시도'));
    runner.check('연결 실패 → 폴백 warn 로그', fallback.length === 1,
      fallback[0] ? `→ ${fallback[0].a[0]}` : '(로그 없음)');
    runner.check('폴백 로그 level=warn', fallback[0] ? fallback[0].level === 'warn' : false);

    // 두 번째 주소도 실패 → error 로그
    captured.length = 0;
    await wFail.pollOnce();
    await h.sleep(300);
    const err = captured.filter((c) => c.a[0].includes('연결 실패'));
    runner.check('두 번째 실패 → error 로그', err.length === 1,
      err[0] ? `→ ${err[0].a[0]}` : '(로그 없음)');
    runner.check('error 로그 level=error', err[0] ? err[0].level === 'error' : false);

    // 6) 위젯이 테스트 전용 포트를 바라보는지 확인
    const urls = w.getUrls();
    runner.check('테스트 전용 포트 사용',
      urls.every((u) => u.includes(`:${env.port}/`)), `→ ${urls[0]}`);
    runner.check('프로덕션 포트(8000)를 쓰지 않음',
      !urls.some((u) => u.includes(':8000/')));

  } finally {
    console.log = realLog;
    console.warn = realWarn;
    console.error = realError;
    h.stopServer(env);
  }

  process.exit(runner.finish(realLog) ? 1 : 0);
})();
