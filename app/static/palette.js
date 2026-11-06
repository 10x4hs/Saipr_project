/* 참가자 색 — app/services/palette.py 와 똑같은 목록·규칙(PALETTE[id % 길이])을 쓴다.
 * 같은 사람은 레이스 트랙 · 순위 · 리더의 '지금 읽는 중' 칩에서 모두 같은 색이어야 하므로
 * 색이 필요한 화면은 이 파일을 불러 colorFor(userId)만 쓴다.
 *
 *   <script src="/static/palette.js"></script>
 *   el.style.setProperty('--c', colorFor(friend.user_id));
 *
 * 앱의 다른 스크립트(presence.js 등)가 모두 일반 <script>라서 전역 window.colorFor 와
 * window.HaedokPalette = { PALETTE, colorFor } 로 내보낸다(ES 모듈에서도 import '/static/palette.js' 후 같은 전역을 쓴다).
 * 목록을 바꾸면 palette.py 도 같이 바꾼다(tests/test_palette.py 가 확인한다).
 */
(function (root) {
  const PALETTE = [
    '#E8603C', // 주홍
    '#2F80ED', // 파랑
    '#1FA463', // 초록
    '#9B51E0', // 보라
    '#E0457B', // 분홍
    '#C9920A', // 겨자
    '#0E9AA7', // 청록
    '#5B6CD9', // 남색
  ];
  function colorFor(userId) {
    const n = Math.abs(Math.trunc(Number(userId))) || 0;
    return PALETTE[n % PALETTE.length];
  }
  root.HaedokPalette = { PALETTE, colorFor };
  root.colorFor = colorFor;
})(typeof window !== 'undefined' ? window : globalThis);
