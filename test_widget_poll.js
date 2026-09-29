/**
 * 위젯 폴링 end-to-end 검증.
 * index.html의 폴링 코드를 그대로 재사용해, 가짜 DOM + 테스트 전용 Python 서버에
 * 연결해 "파일 추가 → 델타 수신 → writingData 누적" 흐름을 확인한다.
 *
 *   node test_widget_poll.js
 *
 * 프로덕션 포트(8000)·실제 baseline.json·testFolder를 쓰지 않는다. 다른 index.html
 * 탭이 떠 있어도 이 테스트는 영향받지 않는다. → tests/helpers.js 참고.
 */
const h = require('./tests/helpers');

const env = h.createEnv();
const widget = h.loadWidget(env);
const realLog = console.log;

let pass = 0, fail = 0;
function check(label, actual, expected) {
  const ok = actual === expected;
  realLog(`  ${ok ? '✅' : '❌'} ${label}: ${actual}${ok ? '' : ` (기대 ${expected})`}`);
  ok ? pass++ : fail++;
}

const todayKey = new Date().toISOString().slice(0, 10);

(async () => {
  realLog('\n── 위젯 폴링 end-to-end (10초 주기) ──');
  realLog(`   테스트 서버: ${env.base} (프로덕션 8000과 분리)`);

  h.startServer(env);
  await h.waitForServer(env);
  // 테스트 시작 전 기준점을 현재 파일 상태와 동기화한다. 이전 실행이 파일을
  // 바꿔둔 상태일 수 있어, "처음부터 delta 0"인 상태를 보장해야 한다.
  await h.syncBaseline(env);

  try {
    widget.start();   // 폴링 시작 (DOMContentLoaded의 폴링 부분)

    await h.sleep(11000);
    check('첫 폴링 — 변화 없음', widget.getCount(), 0);
    check('연결 상태 표시', widget.getSync(), '자동 집계 중');

    // 파일에 5자 추가 → 다음 폴링에서 누적
    env.append('가나다라마');
    await h.sleep(11000);
    check('5자 추가 후 카운트', widget.getCount(), 5);
    check('localStorage 누적', widget.getData()[todayKey], 5);

    // 변화 없으면 유지
    await h.sleep(11000);
    check('추가 변화 없음 → 유지', widget.getCount(), 5);

    // 파일 축소 → 카운트 감소하지 않음 (Q8-A)
    env.write('짧음');
    await h.sleep(11000);
    check('파일 축소 → 감소 없음', widget.getCount(), 5);

    // 위젯이 실제로 테스트 포트를 보고 있는지 확인
    check('테스트 전용 포트 사용',
      widget.getUrls().every((u) => u.includes(`:${env.port}/`)), true);
    check('프로덕션 포트(8000)를 쓰지 않음',
      widget.getUrls().some((u) => u.includes(':8000/')), false);
  } finally {
    h.stopServer(env);
  }

  realLog(`\n결과: ${pass} 통과 / ${fail} 실패`);
  process.exit(fail ? 1 : 0);
})();
