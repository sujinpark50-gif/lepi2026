import { Clipboard, Storage, openURL } from '@apps-in-toss/web-framework';

// 미니앱은 토스 도메인에서 열리므로 빌드에서는 레피 서버의 절대 주소로 부른다.
// 개발 중(npm run dev)에는 vite 프록시가 /api를 로컬 엔진으로 넘긴다.
const SERVER = (import.meta.env.VITE_LEPI_API_ORIGIN || '').replace(/\/$/, '');
const API_URL = import.meta.env.DEV ? '/api' : `${SERVER}/api`;
const PRIVACY_URL = `${SERVER || 'https://lepi2026.vercel.app'}/privacy`;
const NOTICE_KEY = 'lepi.aiNoticeSeen';
const TIMEOUT_MS = 45000;

const $ = (id) => document.getElementById(id);
const memo = $('memo');
const go = $('go');
const out = $('out');
const sheet = $('sheet');
let busy = false;

// 토스 앱 밖(일반 브라우저)에는 브릿지가 없어서 SDK 호출이 실패한다. 그때는 웹 기능으로 대신한다.
async function storageGet(key) {
  try { return await Storage.getItem(key); } catch (e) {}
  try { return window.localStorage.getItem(key); } catch (e) { return null; }
}
async function storageSet(key, value) {
  try { await Storage.setItem(key, value); return; } catch (e) {}
  try { window.localStorage.setItem(key, value); } catch (e) {}
}
async function copyText(text) {
  try { await Clipboard.setText(text); return true; } catch (e) {}
  try { await navigator.clipboard.writeText(text); return true; } catch (e) { return false; }
}
function openExternal(url) {
  try { openURL(url); } catch (e) { window.open(url, '_blank', 'noopener'); }
}

function el(tag, attrs, children) {
  const node = document.createElement(tag);
  Object.entries(attrs || {}).forEach(([k, v]) => {
    if (k === 'text') node.textContent = v;
    else if (k === 'onClick') node.addEventListener('click', v);
    else node.setAttribute(k, v);
  });
  (children || []).forEach((c) => c && node.appendChild(c));
  return node;
}

function show(...nodes) {
  out.replaceChildren(...nodes.filter(Boolean));
}

function status(text, isError) {
  return el('p', { class: isError ? 'status error' : 'status', text });
}

function renderResult(data) {
  const card = data.product_card || {};
  const body = Array.isArray(data.body) ? data.body : [];
  // 엔진은 실무 정보 줄(" · "로 이은 항목, 또는 가격 한 줄)을 마지막 문단으로 붙인다. 따로 보여 준다.
  const last = body[body.length - 1] || '';
  const hasInfo = body.length > 1 && (
    last.includes(' · ') || (Boolean(card.price) && last.includes(card.price) && last.length <= 60)
  );
  const story = hasInfo ? body.slice(0, -1) : body;

  const copyBtn = el('button', { type: 'button', class: 'btn', text: '글 복사하기' });
  copyBtn.addEventListener('click', async () => {
    const text = [data.headline, ...body].filter(Boolean).join('\n\n');
    const ok = await copyText(text);
    copyBtn.textContent = ok ? '복사했어요' : '복사하지 못했어요';
    setTimeout(() => { copyBtn.textContent = '글 복사하기'; }, 2000);
  });
  const againBtn = el('button', {
    type: 'button',
    class: 'btn btn-ghost',
    text: '다시 쓰기',
    onClick: () => { show(); memo.focus(); window.scrollTo({ top: 0, behavior: 'smooth' }); }
  });

  const top = el('div', { class: 'result-top' }, [
    el('span', { class: 'badge', text: 'AI가 쓴 글' }),
    card.name ? el('span', { class: 'product', text: card.price ? `${card.name} · ${card.price}` : card.name }) : null
  ]);

  return el('article', { class: 'result' }, [
    top,
    el('h2', { class: 'headline', text: data.headline || '' }),
    ...story.map((p) => el('p', { class: 'body', text: p })),
    hasInfo ? el('p', { class: 'info', text: last }) : null,
    el('div', { class: 'result-actions' }, [againBtn, copyBtn]),
    el('p', { class: 'check', text: '가격, 날짜 같은 사실은 올리기 전에 꼭 한 번 확인해 주세요.' })
  ]);
}

function render(data) {
  if (data.error) return show(status(data.error, true));
  if (data.status === 'READY') return show(renderResult(data));
  if (data.status === 'NEED_MORE_INFO') {
    const questions = Array.isArray(data.questions) ? data.questions : [];
    return show(el('div', { class: 'status' }, [
      el('p', { text: '이야기를 쓰려면 조금만 더 알려 주세요. 메모에 답을 덧붙여 다시 눌러 주세요.', style: 'margin:0' }),
      questions.length ? el('ul', {}, questions.map((q) => el('li', { text: q }))) : null
    ]));
  }
  if (data.status === 'NO_STORY_FOUND') {
    return show(status('메모에서 아직 이야기를 찾지 못했어요. 이 상품을 고른 이유나 있었던 일을 한두 줄 덧붙여 다시 눌러 주세요.'));
  }
  show(status('이야기를 입히는 중 오류가 발생했어요. 잠시 뒤 다시 시도해 주세요.', true));
}

async function generate() {
  if (busy) return;
  const text = memo.value.trim();
  if (!text) { show(status('상품 메모를 입력해 주세요.', true)); return; }

  busy = true;
  go.disabled = true;
  go.setAttribute('aria-busy', 'true');
  const waitNote = status('메모를 읽고 있어요');
  show(waitNote);
  const stages = [
    setTimeout(() => { waitNote.textContent = '이야기를 찾고 있어요'; }, 5000),
    setTimeout(() => { waitNote.textContent = '글로 정리하고 있어요. 조금만 기다려 주세요'; }, 12000)
  ];
  const ctrl = new AbortController();
  let timedOut = false;
  const timer = setTimeout(() => { timedOut = true; ctrl.abort(); }, TIMEOUT_MS);

  let data;
  try {
    const r = await fetch(API_URL, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text }),
      signal: ctrl.signal
    });
    const json = await r.json().catch(() => ({}));
    data = r.ok && json.status ? json : { error: json.error || '이야기를 입히는 중 오류가 발생했어요. 잠시 뒤 다시 시도해 주세요.' };
  } catch (e) {
    // 자동으로 다시 부르지 않는다(앱인토스: 실패 직후 무제한 재시도 금지).
    data = { error: timedOut ? '시간이 너무 오래 걸리고 있어요. 잠시 뒤 다시 시도해 주세요.' : '연결이 잠시 끊겼어요. 잠시 뒤 다시 시도해 주세요.' };
  }
  stages.forEach(clearTimeout);
  clearTimeout(timer);
  busy = false;
  go.disabled = false;
  go.setAttribute('aria-busy', 'false');
  render(data);
}

// 처음 쓸 때 한 번 AI 사용을 알린다. 앱에 들어오자마자가 아니라 첫 생성 버튼을 누를 때 띄운다.
function askNotice() {
  return new Promise((resolve) => {
    sheet.hidden = false;
    $('sheet-ok').focus();
    const done = (ok) => {
      sheet.hidden = true;
      $('sheet-ok').removeEventListener('click', yes);
      $('sheet-cancel').removeEventListener('click', no);
      resolve(ok);
    };
    const yes = () => done(true);
    const no = () => done(false);
    $('sheet-ok').addEventListener('click', yes);
    $('sheet-cancel').addEventListener('click', no);
  });
}

go.addEventListener('click', async () => {
  if (busy) return;
  if (!(await storageGet(NOTICE_KEY))) {
    if (!(await askNotice())) return;
    await storageSet(NOTICE_KEY, '1');
  }
  generate();
});

memo.addEventListener('input', () => {
  $('count').textContent = `${memo.value.length} / 500`;
});

$('privacy').addEventListener('click', () => openExternal(PRIVACY_URL));
