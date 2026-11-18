/* ARIA panel — chat UI, SSE over fetch, localStorage history */
(() => {
  const $ = (id) => document.getElementById(id);
  const logEl = $('log');
  const emptyEl = $('empty');
  const inputEl = $('input');
  const sendEl = $('send');
  const dotEl = $('dot');
  const bannerEl = $('banner');
  const modelEl = $('model');

  const HKEY = 'aria.history.v1';
  const MKEY = 'aria.model.v1';

  /** @type {{role:'user'|'assistant', content:string, traces?:Array}[]} */
  let history = load();
  let streaming = false;
  let abort = null;

  function load() {
    try {
      const raw = JSON.parse(localStorage.getItem(HKEY) || '[]');
      return Array.isArray(raw) ? raw : [];
    } catch { return []; }
  }
  function save() {
    try { localStorage.setItem(HKEY, JSON.stringify(history.slice(-60))); } catch {}
  }

  // ---------- rendering ----------
  function esc(s) {
    return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }
  function inline(s) {
    return esc(s)
      .replace(/`([^`\n]+)`/g, '<code>$1</code>')
      .replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>');
  }

  function scrollDown(force) {
    const near = logEl.scrollHeight - logEl.scrollTop - logEl.clientHeight < 140;
    if (force || near) logEl.scrollTop = logEl.scrollHeight;
  }

  function clearLog() {
    [...logEl.children].forEach((c) => { if (c !== emptyEl) c.remove(); });
  }

  function renderAll() {
    clearLog();
    emptyEl.classList.toggle('hidden', history.length > 0);
    history.forEach((m) => paint(m));
    scrollDown(true);
  }

  function paint(m) {
    const wrap = document.createElement('div');
    wrap.className = 'msg ' + m.role;

    const traceBox = document.createElement('div');
    traceBox.className = 'trace';
    (m.traces || []).forEach((t) => traceBox.appendChild(traceRow(t)));

    const body = document.createElement('div');
    body.className = 'body';
    body.innerHTML = inline(m.content || '');

    if (m.role === 'user') {
      wrap.appendChild(body);
    } else {
      if (m.traces && m.traces.length) wrap.appendChild(traceBox);
      wrap.appendChild(body);
    }
    logEl.appendChild(wrap);
    return { wrap, body, traceBox };
  }

  function traceRow(t) {
    const row = document.createElement('div');
    row.className = 'row';
    const name = document.createElement('span');
    name.className = 'tname';
    name.textContent = t.name;
    row.appendChild(name);

    if (t.args && Object.keys(t.args).length) {
      const a = document.createElement('span');
      a.className = 'targs';
      a.textContent = shortArgs(t.args);
      row.appendChild(a);
    }
    if (t.result !== undefined) {
      const r = document.createElement('span');
      r.className = 'tres' + (t.ok === false ? ' bad' : '');
      r.textContent = (t.ok === false ? '✕ ' : '✓ ') + t.result;
      row.appendChild(r);
    }
    return row;
  }

  function shortArgs(args) {
    return Object.entries(args)
      .map(([k, v]) => k + '=' + (typeof v === 'object' ? JSON.stringify(v) : v))
      .join(' ')
      .slice(0, 220);
  }

  // ---------- chat ----------
  async function send() {
    const text = inputEl.value.trim();
    if (!text || streaming) return;

    const userMsg = { role: 'user', content: text };
    history.push(userMsg);
    save();
    emptyEl.classList.add('hidden');
    paint(userMsg);
    inputEl.value = '';
    autoresize();
    scrollDown(true);

    const assistant = { role: 'assistant', content: '', traces: [] };
    history.push(assistant);
    const view = paint(assistant);
    view.body.classList.add('cursor');
    scrollDown(true);

    streaming = true;
    setBusy(true);
    abort = new AbortController();

    try {
      const res = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          model: modelEl.value || undefined,
          messages: history.slice(0, -1).map((m) => ({ role: m.role, content: m.content })),
        }),
        signal: abort.signal,
      });
      if (!res.ok) throw new Error('panel server: HTTP ' + res.status);

      const reader = res.body.getReader();
      const dec = new TextDecoder();
      let buf = '';

      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        let cut;
        while ((cut = buf.indexOf('\n\n')) >= 0) {
          const frame = buf.slice(0, cut);
          buf = buf.slice(cut + 2);
          const line = frame.split('\n').find((l) => l.startsWith('data: '));
          if (!line) continue;
          let evt;
          try { evt = JSON.parse(line.slice(6)); } catch { continue; }
          handleEvent(evt, assistant, view);
        }
      }
    } catch (err) {
      if (err.name !== 'AbortError') {
        assistant.content += (assistant.content ? '\n\n' : '') + '⚠ ' + err.message;
        view.wrap.classList.add('error');
      }
    } finally {
      streaming = false;
      setBusy(false);
      abort = null;
      view.body.classList.remove('cursor');
      view.body.innerHTML = inline(assistant.content || '_(no reply)_');
      pruneEmptyTraces(assistant, view);
      save();
      scrollDown();
    }
  }

  function handleEvent(evt, assistant, view) {
    if (evt.t === 'delta') {
      assistant.content += evt.text;
      view.body.textContent = assistant.content;
      scrollDown();
    } else if (evt.t === 'tool') {
      const t = { name: evt.name, args: evt.args || {} };
      assistant.traces.push(t);
      if (!view.traceBox.parentNode) view.wrap.insertBefore(view.traceBox, view.body);
      view.traceBox.appendChild(traceRow(t));
      scrollDown();
    } else if (evt.t === 'tool_result') {
      const t = [...assistant.traces].reverse().find((x) => x.name === evt.name && x.result === undefined);
      if (t) {
        t.ok = evt.ok;
        t.result = (evt.preview || '').replace(/\s+/g, ' ').slice(0, 180);
        view.traceBox.replaceChildren(...assistant.traces.map(traceRow));
      }
      scrollDown();
    } else if (evt.t === 'reset') {
      assistant.content = '';
      view.body.textContent = '';
      view.wrap.classList.remove('error');
    } else if (evt.t === 'error') {
      assistant.content = evt.replace
        ? '⚠ ' + evt.message
        : assistant.content + (assistant.content ? '\n\n' : '') + '⚠ ' + evt.message;
      view.wrap.classList.add('error');
      view.body.textContent = assistant.content;
    }
  }

  function pruneEmptyTraces(assistant, view) {
    assistant.traces = (assistant.traces || []).filter((t) => t.result !== undefined || t.name);
    if (!assistant.traces.length && view.traceBox.parentNode) view.traceBox.remove();
  }

  function setBusy(busy) {
    sendEl.disabled = false;
    sendEl.innerHTML = busy
      ? '<svg viewBox="0 0 24 24" width="14" height="14"><rect x="6" y="6" width="12" height="12" rx="2" fill="currentColor"/></svg>'
      : '<svg viewBox="0 0 24 24" width="16" height="16"><path d="M3 20.5 21 12 3 3.5 3 10l12 2-12 2z" fill="currentColor"/></svg>';
  }

  // ---------- health / models ----------
  async function health() {
    try {
      const r = await fetch('/api/health', { cache: 'no-store' });
      const j = await r.json();
      dotEl.className = 'dot ' + (j.live ? 'live' : 'dead');
      dotEl.title = j.live ? 'Live connected (port 9877)' : 'Live not reachable';
      bannerEl.classList.toggle('hidden', !!j.live);
    } catch {
      dotEl.className = 'dot dead';
      dotEl.title = 'Panel server unreachable';
    }
  }

  async function loadConfig() {
    const saved = localStorage.getItem(MKEY);
    try {
      const r = await fetch('/api/config', { cache: 'no-store' });
      const j = await r.json();
      const list = Array.from(new Set([j.model, ...(j.models || [])]));
      modelEl.innerHTML = '';
      list.forEach((m) => {
        const o = document.createElement('option');
        o.value = m;
        o.textContent = m;
        modelEl.appendChild(o);
      });
      modelEl.value = list.includes(saved) ? saved : j.model;
    } catch {
      modelEl.innerHTML = '<option>auto/chat</option>';
    }
  }

  // ---------- input plumbing ----------
  function autoresize() {
    inputEl.style.height = 'auto';
    inputEl.style.height = Math.min(inputEl.scrollHeight, 132) + 'px';
  }

  inputEl.addEventListener('input', autoresize);
  inputEl.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  });
  sendEl.addEventListener('click', () => {
    if (streaming && abort) abort.abort();
    else send();
  });
  $('new').addEventListener('click', () => {
    if (streaming && abort) abort.abort();
    history = [];
    save();
    clearLog();
    emptyEl.classList.remove('hidden');
    inputEl.focus();
  });
  $('retry').addEventListener('click', health);
  modelEl.addEventListener('change', () => localStorage.setItem(MKEY, modelEl.value));
  document.addEventListener('keydown', (e) => {
    if (e.ctrlKey && e.key.toLowerCase() === 'k') { e.preventDefault(); $('new').click(); }
  });
  logEl.addEventListener('click', (e) => {
    const b = e.target.closest('.chips button');
    if (!b) return;
    inputEl.value = b.dataset.q;
    autoresize();
    send();
  });

  // ---------- boot ----------
  renderAll();
  loadConfig();
  health();
  setInterval(health, 5000);
  inputEl.focus();

  // Tell the launcher how tall the browser's own title bar is, so it can shift
  // the window up by exactly that much and leave a clean edge-to-edge panel.
  const reportFrame = () => {
    const chrome = Math.max(0, Math.round((window.outerHeight || 0) - (window.innerHeight || 0)));
    fetch('/api/frame', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ chrome }),
    }).catch(() => {});
  };
  setTimeout(reportFrame, 300);
  window.addEventListener('resize', () => setTimeout(reportFrame, 120));
})();
