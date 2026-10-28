// 로그인·가입: 입력칸을 하나씩 보여 주고 → 로 넘어간다. JS가 없으면 모든 칸이 한꺼번에 보인다.
(() => {
  const form = document.querySelector('.steps');
  if (!form) return;
  const steps = [...form.querySelectorAll('[data-step]')];
  const msg = form.querySelector('[data-msg]'), back = form.querySelector('[data-back]');
  const dots = [...form.querySelectorAll('.step-dots i')];
  form.classList.add('stepped');

  const check = input => {
    const v = input.value.trim();
    if (!v) return `${input.placeholder.replace(/ \(.+\)/, '')}을(를) 입력해 주세요`;
    if (input.type === 'email' && !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(v)) return '이메일 형식을 확인해 주세요';
    if (input.minLength > 1 && input.value.length < input.minLength) return `${input.minLength}자 이상 입력해 주세요`;
    if (input.name === 'password_confirm' && input.value !== form.password.value) return '비밀번호가 서로 달라요';
    return '';
  };

  let at = 0;
  const show = (i, note = '') => {
    at = i;
    steps.forEach((s, k) => { s.classList.toggle('on', k === i); s.classList.toggle('past', k < i); });
    dots.forEach((d, k) => d.classList.toggle('on', k <= i));
    back.hidden = i === 0;
    msg.textContent = note;
    const input = steps[i].querySelector('input');
    setTimeout(() => input.focus(), 60);
  };

  const advance = () => {
    const input = steps[at].querySelector('input');
    const err = check(input);
    if (err) { msg.textContent = err; steps[at].classList.remove('shake'); void steps[at].offsetWidth; steps[at].classList.add('shake'); return false; }
    if (at < steps.length - 1) { show(at + 1); return false; }
    return true;
  };

  form.querySelectorAll('[data-next]').forEach(b => b.addEventListener('click', advance));
  form.addEventListener('keydown', e => { if (e.key === 'Enter' && e.target.tagName === 'INPUT') { e.preventDefault(); if (advance()) form.requestSubmit(); } });
  form.addEventListener('submit', e => { if (at < steps.length - 1 || check(steps[at].querySelector('input'))) { e.preventDefault(); advance(); return; } form.classList.add('sending'); });
  back.addEventListener('click', () => show(Math.max(0, at - 1)));

  // 서버가 돌려준 오류: 가입은 그 칸에서, 로그인은 비밀번호 칸에서 다시 시작
  const firstErr = form.dataset.firstError;
  const serverMsg = msg.textContent.trim();
  if (firstErr) { const k = steps.findIndex(s => s.dataset.name === firstErr); show(Math.max(0, k), steps[k]?.dataset.error || ''); }
  else if (serverMsg && steps.length === 2) show(1, serverMsg);
  else show(0, serverMsg);
})();
