'use strict';
// 端口监视单页面。数据全部来自 /api/*（port_monitor.py），本文件只负责渲染与交互。
// 配色、显示设置、本机显示参数、心跳由 web-kit 提供（/kit/kit.js，本工具目录的 web-kit/），本文件只写页面内容。

const S = { data: null, filter: 'all', q: '', sort: { k: 'port', dir: 1 }, open: {}, busy: false, stopping: null };

// ---------------- 工具 ----------------
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const pct = (x) => `${Math.round(x * 100)}%`;
const NO_ADMIN = '读不到（需要管理员权限）';

async function api(path, body) {
  const opt = body === undefined ? {} : {
    method: 'POST', body: JSON.stringify(body),
    headers: { 'Content-Type': 'application/json', 'X-Port-Monitor': '1' },
  };
  const r = await fetch(path, opt);
  let j = {};
  try { j = await r.json(); } catch (e) { /* 非 JSON */ }
  if (!r.ok) throw new Error(j.error || ('HTTP ' + r.status));
  return j;
}
let toastTimer = 0;
function toast(msg, ok = false) {
  const t = $('toast'); t.textContent = msg; t.classList.remove('hidden'); t.classList.toggle('ok', ok);
  clearTimeout(toastTimer); toastTimer = setTimeout(() => t.classList.add('hidden'), ok ? 5000 : 8000);
}
async function guard(fn) {
  try { await fn(); } catch (e) { toast(e.message); }
}

// ---------------- 配色、显示设置、本机显示参数、心跳：web-kit（/kit/kit.js）----------------
// 显示参数由 kit 读；这里只取结果画状态栏（WebKit.display.zoomOff / .text），变了时 kit 回调 renderStatus。
const DISPLAY = WebKit.display;

// ---------------- 顶栏状态 ----------------
function renderStatus() {
  const d = S.data; const out = [];
  if (S.busy) out.push('<span class="st muted">采集中…</span>');
  if (d && !d.admin) out.push('<span class="st muted opt" title="系统服务与以系统账户运行的程序，路径与命令行读不到；端口、进程名、服务信息不受影响">非管理员：部分路径读不到 <button id="elevate" title="弹出 UAC 确认；确认后以管理员权限重新启动本服务，页面自动刷新">以管理员身份重新启动</button></span>');
  if (DISPLAY.zoomOff) out.push(`<span class="st warn"><span class="dot"></span>浏览器缩放 ${pct(DISPLAY.zoomOff)} · Ctrl+0 复原</span>`);
  if (d) out.push(`<span class="st opt" title="${esc(DISPLAY.text)}"><span class="dot"></span>采集于 ${esc(d.time.slice(11))}</span>`);
  $('status').innerHTML = out.join('');
  $('refresh').disabled = S.busy;
}

// ---------------- 数据 ----------------
async function load(fresh) {
  S.busy = true; renderStatus();
  try {
    S.data = await api('/api/ports' + (fresh ? '?fresh=1' : ''));
    $('idle').textContent = `本页关闭后 ${S.data.idle_minutes} 分钟无请求，服务自动退出`;
  } finally {
    S.busy = false; renderStatus(); render();
  }
}
$('refresh').onclick = () => guard(() => load(true));

// ---------------- 筛选与排序 ----------------
const FILTERS = [['all', '全部'], ['own', '自己的工具'], ['lan', '局域网可访问'], ['tcp', 'TCP'], ['udp', 'UDP']];
const pass = {
  all: () => true, own: (r) => !!r.own, lan: (r) => r.exposure === 'lan', tcp: (r) => r.proto === 'tcp', udp: (r) => r.proto === 'udp',
};
function hay(r) {
  return [r.port, r.proto, r.name, r.pid, r.cmd, r.path, ...r.addrs.map((a) => a.addr + ' ' + a.note),
    ...r.explain.map((e) => e.text + ' ' + e.note), ...r.services.map((s) => s.name + ' ' + s.display)].join(' ').toLowerCase();
}
// 点表头排序；再点一次反向
const SORTS = {
  port: (a, b) => a.port - b.port || a.proto.localeCompare(b.proto) || a.pid - b.pid,
  proto: (a, b) => a.proto.localeCompare(b.proto) || a.port - b.port,
  proc: (a, b) => a.name.localeCompare(b.name) || a.pid - b.pid || a.port - b.port,
  exp: (a, b) => (a.exposure === b.exposure ? 0 : a.exposure === 'lan' ? -1 : 1) || a.port - b.port,
};
function rows() {
  if (!S.data) return [];
  const q = S.q.trim().toLowerCase();
  const list = S.data.rows.filter((r) => pass[S.filter](r) && (!q || hay(r).includes(q)));
  const f = SORTS[S.sort.k];
  return list.sort((a, b) => f(a, b) * S.sort.dir);
}
function renderFilters() {
  const all = S.data ? S.data.rows : [];
  $('filters').innerHTML = FILTERS.map(([k, label]) =>
    `<button data-f="${k}" class="${S.filter === k ? 'on' : ''}" role="tab" aria-selected="${S.filter === k}">${label} <span class="n">${all.filter(pass[k]).length}</span></button>`).join('');
}
$('filters').onclick = (e) => { const b = e.target.closest('[data-f]'); if (b) { S.filter = b.dataset.f; render(); } };
$('q').oninput = (e) => { S.q = e.target.value; render(); };

// ---------------- 渲染 ----------------
function renderSummary() {
  const d = S.data;
  if (!d) return;
  const s = d.summary;
  $('summary').innerHTML = `<b>${s.tcp}</b> 个 TCP 监听、<b>${s.udp}</b> 个 UDP，其中自己的工具 <b>${s.own}</b> 个、`
    + `局域网可访问 <b class="${s.lan ? 'warn' : ''}">${s.lan}</b> 个`;
}
const na = (v) => (v === null || v === undefined || v === '') ? '<span class="v na">—</span>'
  : v === NO_ADMIN ? `<span class="v na">${NO_ADMIN}</span>` : null;
function field(label, v, mono = true) {
  return `<span class="lh">${label}</span>` + (na(v) || `<span class="v${mono ? ' mono' : ''}">${esc(v)}</span>`);
}
function rowHtml(r) {
  const open = !!S.open[r.key];
  const first = r.explain[0];
  const addrs = r.addrs.map((a) => `<div class="addr"><span class="ip">${esc(a.addr)}</span>`
    + `<span class="tag ${a.scope}">${a.scope === 'lan' ? '局域网可访问' : '仅本机'}</span>`
    + (a.note ? `<span class="nic">${esc(a.note)}</span>` : '') + '</div>').join('');
  const extra = r.explain.length > 1 ? `<span class="more"> · 另有 ${r.explain.length - 1} 条</span>` : '';
  const act = r.stoppable
    ? `<button class="act" data-stop="${esc(r.key)}"${S.stopping ? ' disabled' : ''}>${S.stopping === r.key ? '停止中…' : '停止'}</button>` : '';
  let detail = '';
  if (open) {
    const ex = r.explain.map((e) => `<span class="tag src">${esc(e.src)}</span><span class="n">${esc(e.text)}${e.note ? `<span class="muted"> — ${esc(e.note)}</span>` : ''}</span>`).join('');
    const svc = r.services.length
      ? r.services.map((s) => `${s.display || s.name}（${s.name}，${s.state || '?'}）${s.desc ? '：' + s.desc : ''}`).join('\n') : null;
    const how = r.own ? (r.pid === S.data.self_pid ? '这是本页自己的服务，停止后本页不再可用'
      : r.own.graceful ? `调用 ${r.own.script} --stop${r.own.takes_port ? ' --port ' + r.port : ''}；8 秒内没退出再结束进程`
        : '结束进程（taskkill /T /F）；该脚本不支持 --stop') : null;
    detail = `<div class="detail" data-detail>
      <span class="lh">它在做什么</span><div class="ex">${ex}</div>
      ${field('命令行', r.cmd)}
      ${field('路径', r.path)}
      ${field('启动时间', r.start)}
      ${field('父进程', r.ppid ? `PID ${r.ppid}` : null)}
      ${r.proto === 'tcp' ? field('已建立连接', `${r.est} 个（连到本端口）`, false) : ''}
      ${svc ? `<span class="lh">服务</span><span class="v" style="white-space:pre-line">${esc(svc)}</span>` : ''}
      ${how ? field('停止方式', how, false) : ''}
    </div>`;
  }
  return `<div class="row${open ? ' open' : ''}" data-key="${esc(r.key)}">
    <div class="port">${r.port}<span class="p2">${r.proto}</span></div>
    <div class="proto">${r.proto}</div>
    <div class="c-proc"><div class="pname">${esc(r.name)}<span class="pid">PID ${r.pid}</span></div><div class="addrs">${addrs}</div></div>
    <div class="c-what"><div class="what">${r.own ? '<span class="tag own">自己的工具</span>' : ''}${esc(first.text)}</div>
      <div class="note"><span class="tag src">${esc(first.src)}</span>${esc(first.note)}${extra}</div></div>
    <div class="acts">${act}</div>
    ${detail}
  </div>`;
}
function theadHtml() {
  const h = (k, label, cls) => `<span class="${cls}${S.sort.k === k ? ' on' + (S.sort.dir < 0 ? ' desc' : '') : ''}" data-sort="${k}" title="按${label}排序">${label}</span>`;
  return `<div class="thead">${h('port', '端口', 'h-port')}${h('proto', '协议', 'h-proto')}`
    + `<span class="h-proc"><span data-sort="proc" class="${S.sort.k === 'proc' ? 'on' + (S.sort.dir < 0 ? ' desc' : '') : ''}">进程</span> · `
    + `<span data-sort="exp" class="${S.sort.k === 'exp' ? 'on' + (S.sort.dir < 0 ? ' desc' : '') : ''}">监听地址</span></span>`
    + '<span class="h-what">它在做什么（来源）</span><span class="h-act"></span></div>';
}
function render() {
  renderFilters(); renderSummary();
  const L = $('list');
  if (!S.data) return;
  const list = rows();
  $('shown').textContent = `显示 ${list.length} / ${S.data.rows.length} 行`;
  const top = L.scrollTop;
  L.innerHTML = theadHtml() + (list.length ? list.map(rowHtml).join('') : '<div class="empty">没有符合条件的端口</div>');
  L.scrollTop = top;
}
// 以管理员身份重新启动：UAC 确认后新进程接替同一端口，等它起来（PID 变了）再刷新页面
$('status').addEventListener('click', async (e) => {
  if (e.target.id !== 'elevate') return;
  const before = (await fetch('/api/ping').then((r) => r.json()).catch(() => ({}))).pid;
  try { await api('/api/elevate', {}); } catch (err) { toast(err.message); return; }
  e.target.disabled = true; e.target.textContent = '正在以管理员身份重启…';
  for (let i = 0; i < 40; i++) {
    await new Promise((ok) => setTimeout(ok, 500));
    const p = await fetch('/api/ping').then((r) => r.json()).catch(() => null);
    if (p && p.pid !== before) { location.reload(); return; }
  }
  toast('管理员进程没有起来，看 var/web.log');
});

$('list').addEventListener('click', (e) => {
  const sh = e.target.closest('[data-sort]');
  if (sh) {
    const k = sh.dataset.sort;
    S.sort = { k, dir: S.sort.k === k ? -S.sort.dir : 1 };
    render(); return;
  }
  const st = e.target.closest('[data-stop]');
  if (st) { askStop(st.dataset.stop); return; }
  if (e.target.closest('[data-detail]')) return;           // 详情里可以选中复制文字
  const row = e.target.closest('.row');
  if (!row) return;
  if (getSelection().toString()) return;
  S.open[row.dataset.key] = !S.open[row.dataset.key];
  render();
});

// ---------------- 停止（只对自己的工具）----------------
function askStop(key) {
  const r = S.data.rows.find((x) => x.key === key);
  if (!r || !r.own) return;
  const self = r.pid === S.data.self_pid;
  const how = self ? '这是本页自己的服务：停止后本页不再可用。'
    : r.own.graceful ? `先调用工具自己的 <code>--stop</code>（${esc(r.own.script)}），8 秒内没退出再结束进程。`
      : '该脚本不支持 <code>--stop</code>，将直接结束进程（taskkill /T /F）。';
  $('confirm-body').innerHTML = `<p>停止 <span style="color:var(--ink)">${esc(r.own.label)}</span></p>
    <p class="mono" style="font-size:12px">${esc(r.name)} · PID ${r.pid} · ${r.proto.toUpperCase()} ${r.port}</p><p>${how}</p>`;
  $('confirm-ok').onclick = () => { $('confirm').close(); doStop(r); };
  $('confirm').showModal();
}
async function doStop(r) {
  S.stopping = r.key; render();
  try {
    const res = await api('/api/stop', { pid: r.pid, port: r.port });
    if (res.method === 'self') { toast('本服务已停止，本页不再可用', true); return; }
    toast((res.stopped ? `已停止（${res.method === 'graceful' ? '工具自己的 --stop' : '结束进程'}）` : '没能停止') + (res.notes.length ? '\n' + res.notes.join('\n') : ''), res.stopped);
    await load(true);
  } catch (e) { toast(e.message); } finally { S.stopping = null; render(); }
}

// ---------------- 弹窗 ----------------
$('help-open').onclick = () => $('help').showModal();
document.querySelectorAll('dialog').forEach((d) => {
  d.addEventListener('click', (e) => { if (e.target === d || e.target.closest('[data-close]')) d.close(); });
});


WebKit.init({ header: 'X-Port-Monitor', onDisplay: renderStatus, onError: (m) => toast(m) });
guard(() => load(false));
