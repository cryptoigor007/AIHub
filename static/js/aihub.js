(function () {
  "use strict";

  const tg = window.Telegram && window.Telegram.WebApp;
  if (tg) {
    try {
      tg.ready();
      tg.expand();
      const scheme = (tg.colorScheme || "").toLowerCase();
      if (scheme === "dark") document.documentElement.classList.add("tg-dark");
      if (scheme === "light") document.documentElement.classList.add("tg-light");
      if (tg.BackButton) tg.BackButton.hide();
    } catch (_) {}
  }

  const pathParts = location.pathname.split("/").filter(Boolean);
  let basePath = "";
  if (pathParts[0] === "p" && pathParts[1]) {
    basePath = "/p/" + pathParts[1];
  } else if (pathParts.length) {
    basePath = "/" + pathParts.slice(0, Math.min(2, pathParts.length)).join("/");
  }

  const EXPENSIVE = new Set(["change_model", "new_session", "delete", "rollback", "bulk"]);
  const $ = (id) => document.getElementById(id);

  const state = {
    agents: {},
    filter: "all",
    tab: "chats",
    search: "",
    viewMode: "all", // all | pinned | archived
    selectedId: null,
    history: [],
    findQ: "",
    ws: null,
    connected: false,
    sending: false,
  };

  let wsBackoff = 1000;
  const WS_MAX = 30000;

  /* ── splash particles ─────────────────────────── */
  function runSplash(done) {
    const canvas = $("splashCanvas");
    const splash = $("splash");
    if (!canvas || !splash) { done(); return; }
    const ctx = canvas.getContext("2d");
    const W = canvas.width, H = canvas.height;
    const cx = W / 2, cy = H / 2;
    const N = 28;
    const particles = [];
    for (let i = 0; i < N; i++) {
      const a = (i / N) * Math.PI * 2;
      particles.push({
        x: cx + Math.cos(a) * (40 + Math.random() * 50),
        y: cy + Math.sin(a) * (40 + Math.random() * 50),
        tx: cx + Math.cos(a) * 18,
        ty: cy + Math.sin(a) * 18,
        r: 2 + Math.random() * 2.5,
      });
    }
    const t0 = performance.now();
    const DUR = 900;
    function frame(t) {
      const p = Math.min(1, (t - t0) / DUR);
      const e = 1 - Math.pow(1 - p, 3);
      ctx.clearRect(0, 0, W, H);
      const dark = matchMedia("(prefers-color-scheme: dark)").matches ||
        document.documentElement.classList.contains("tg-dark");
      ctx.fillStyle = dark ? "#5b6cff" : "#5b6cff";
      particles.forEach((pt) => {
        const x = pt.x + (pt.tx - pt.x) * e;
        const y = pt.y + (pt.ty - pt.y) * e;
        ctx.beginPath();
        ctx.arc(x, y, pt.r * (0.6 + 0.4 * e), 0, Math.PI * 2);
        ctx.globalAlpha = 0.5 + 0.5 * e;
        ctx.fill();
      });
      ctx.globalAlpha = 1;
      if (p < 1) requestAnimationFrame(frame);
      else {
        setTimeout(() => {
          splash.classList.add("is-out");
          setTimeout(() => { splash.classList.add("is-hidden"); done(); }, 280);
        }, 200);
      }
    }
    // hard ceiling 2.5s
    const cap = setTimeout(() => {
      splash.classList.add("is-out");
      setTimeout(() => { splash.classList.add("is-hidden"); done(); }, 280);
    }, 2500);
    requestAnimationFrame(frame);
    const _done = done;
    done = () => { clearTimeout(cap); _done(); };
  }

  /* ── utils ────────────────────────────────────── */
  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;")
      .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }
  function haptic(type) {
    try { if (tg && tg.HapticFeedback) tg.HapticFeedback.impactOccurred(type || "light"); } catch (_) {}
  }
  function toast(msg) {
    const el = $("toast");
    if (!el) return;
    el.textContent = msg;
    el.classList.remove("is-hidden");
    el.classList.add("is-on");
    clearTimeout(toast._t);
    toast._t = setTimeout(() => {
      el.classList.remove("is-on");
      setTimeout(() => el.classList.add("is-hidden"), 220);
    }, 2200);
  }
  function fmtTime(iso) {
    if (iso == null || iso === "") return "";
    let d;
    if (typeof iso === "number") {
      d = new Date(iso < 1e12 ? iso * 1000 : iso);  // сек или мс
    } else if (typeof iso === "object") {
      return fmtTime(iso.created || iso.updated || iso.ts || iso.time);
    } else {
      d = new Date(iso);
    }
    if (isNaN(d.getTime())) return "";  // не "Invalid Date"
    try {
      const now = new Date();
      const same = d.toDateString() === now.toDateString();
      return same
        ? d.toLocaleTimeString("ru", { hour: "2-digit", minute: "2-digit" })
        : d.toLocaleDateString("ru", { day: "numeric", month: "short" });
    } catch (_) { return ""; }
  }
  function groupLabel(iso) {
    if (!iso) return "Раньше";
    const d = new Date(iso);
    const now = new Date();
    const day = 86400000;
    const start = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    const diff = start - new Date(d.getFullYear(), d.getMonth(), d.getDate());
    if (diff < day) return "Сегодня";
    if (diff < 2 * day) return "Вчера";
    if (diff < 7 * day) return "7 дней";
    return "Раньше";
  }

  /* ── auth / ws ────────────────────────────────── */
  async function auth() {
    if (!tg || !tg.initData) {
      try {
        const res = await fetch(basePath + "/auth/dev", { method: "POST", credentials: "include" });
        if (res.ok) return true;
      } catch (_) {}
      return true;
    }
    try {
      const res = await fetch(basePath + "/auth", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ initData: tg.initData }),
        credentials: "include",
      });
      const data = await res.json();
      if (!data.ok) {
        if ((data.message || "").includes("Токен")) {
          const tb = $("tokenBanner");
          if (tb) tb.classList.remove("is-hidden");
        }
        showError(data.message || "Авторизация отклонена");
        return false;
      }
      return true;
    } catch (e) {
      showError("Ошибка авторизации: " + e.message);
      return false;
    }
  }

  function connectWs() {
    if (state.ws && (state.ws.readyState === 0 || state.ws.readyState === 1)) return;
    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    let ws;
    try { ws = new WebSocket(proto + "//" + location.host + basePath + "/ws"); }
    catch (_) {
      state.connected = false;
      setTimeout(connectWs, wsBackoff);
      wsBackoff = Math.min(wsBackoff * 2, WS_MAX);
      return;
    }
    state.ws = ws;
    ws.onopen = () => {
      state.connected = true;
      wsBackoff = 1000;
      $("offlineBanner")?.classList.add("is-hidden");
    };
    ws.onmessage = (ev) => {
      try { handleEvent(JSON.parse(ev.data)); } catch (_) {}
    };
    ws.onclose = () => {
      state.connected = false;
      setTimeout(connectWs, wsBackoff);
      wsBackoff = Math.min(wsBackoff * 2, WS_MAX);
    };
    ws.onerror = () => { try { ws.close(); } catch (_) {} };
  }

  function handleEvent(msg) {
    if (msg.type === "ping") return;
    if (msg.type === "snapshot") {
      state.agents = {};
      (msg.agents || []).forEach((a) => { state.agents[a.id] = a; });
      setDot("dsh", msg.dsh_online);
      setDot("opencode", msg.opencode_online);
      updateOffline(msg.dsh_online, msg.opencode_online);
      scheduleRender();
      return;
    }
    if (msg.type === "state_update" && msg.agent) {
      state.agents[msg.agent.id] = msg.agent;
      scheduleRender();
      if (state.selectedId === msg.agent.id) refreshChatHeader();
      return;
    }
    if (msg.type === "state_remove" && msg.id) {
      delete state.agents[msg.id];
      if (state.selectedId === msg.id) closeChat();
      scheduleRender();
      return;
    }
    if (msg.type === "system_online" || msg.type === "system_offline") {
      setDot(msg.system, msg.type === "system_online");
      updateOffline(
        $("dshDot")?.dataset.s === "online",
        $("ocDot")?.dataset.s === "online"
      );
    }
  }

  function setDot(sys, online) {
    const el = sys === "dsh" || sys === "DSH" ? $("dshDot") : $("ocDot");
    if (el) el.dataset.s = online ? "online" : "offline";
  }
  function updateOffline(dsh, oc) {
    const el = $("offlineBanner");
    if (!el) return;
    const parts = [];
    if (!dsh) parts.push("DSH offline");
    if (!oc) parts.push("OpenCode offline");
    if (parts.length) {
      el.textContent = parts.join(" · ");
      el.classList.remove("is-hidden");
    } else el.classList.add("is-hidden");
  }

  /* ── list / filter ────────────────────────────── */
  function getFiltered() {
    let list = Object.values(state.agents);
    if (state.filter === "dsh") list = list.filter((a) => a.system === "dsh");
    if (state.filter === "opencode") list = list.filter((a) => a.system === "opencode");
    if (state.viewMode === "pinned") list = list.filter((a) => (a.meta || {}).pinned);
    if (state.viewMode === "archived") list = list.filter((a) => (a.meta || {}).archived);
    else list = list.filter((a) => !(a.meta || {}).archived);
    if (state.search) {
      const q = state.search.toLowerCase();
      list = list.filter((a) =>
        (a.title || "").toLowerCase().includes(q) ||
        (a.project || "").toLowerCase().includes(q) ||
        (a.id || "").toLowerCase().includes(q)
      );
    }
    list.sort((a, b) => {
      const ap = (a.meta || {}).pinned ? 0 : 1;
      const bp = (b.meta || {}).pinned ? 0 : 1;
      if (ap !== bp) return ap - bp;
      return new Date(b.updated_at || 0) - new Date(a.updated_at || 0);
    });
    return list;
  }

  function showError(text) {
    $("stateLoading")?.classList.add("is-hidden");
    $("stateEmpty")?.classList.add("is-hidden");
    $("chatList")?.classList.add("is-hidden");
    $("stateError")?.classList.remove("is-hidden");
    if ($("errorText")) $("errorText").textContent = text || "Ошибка";
  }
  function hideError() {
    $("stateError")?.classList.add("is-hidden");
  }

  let _renderQueued = false;
  const _rowEls = new Map();   // id -> { el, sig }
  let _lastOrder = "";
  let _lastListSig = "";

  function scheduleRender() {
    if (_renderQueued) return;
    _renderQueued = true;
    requestAnimationFrame(() => { _renderQueued = false; render(); });
  }

  function listSignature(list) {
    let s = "";
    for (const a of list) {
      s += a.id + "|" + (a.title || "") + "|" + (a.system || "") + "|" +
           (a.status || "") + "|" + (a.updated_at || "") + "|" +
           ((a.meta || {}).pinned ? 1 : 0) + "|" +
           (a.last_step || (a.meta || {}).preview || "") + "~";
    }
    return s;
  }

  function render() {
    if (state.tab === "more") { renderMore(); return; }
    if (state.tab === "oc") { renderOcList(); return; }
    if (state.tab === "dsh") return;
    if (state.tab === "chats" && state.selectedId) return;

    const list = getFiltered();
    $("stateLoading")?.classList.add("is-hidden");
    hideError();
    const el = $("chatList");
    if (!list.length) {
      el?.classList.add("is-hidden");
      if (el) el.replaceChildren();
      _rowEls.clear(); _lastOrder = ""; _lastListSig = "";
      $("stateEmpty")?.classList.remove("is-hidden");
      return;
    }
    $("stateEmpty")?.classList.add("is-hidden");
    if (!el) return;
    el.classList.remove("is-hidden");

    const sig = listSignature(list);
    if (sig === _lastListSig) return;  // ничего не изменилось — DOM не трогаем
    _lastListSig = sig;
    renderList(el, list);
    renderDrawerHistory(list);
  }

  function renderList(el, list) {
    const seen = new Set();
    for (const a of list) {
      seen.add(a.id);
      const html = rowHtml(a);
      const entry = _rowEls.get(a.id);
      if (!entry) {
        const tmp = document.createElement("div");
        tmp.innerHTML = html;
        _rowEls.set(a.id, { el: tmp.firstElementChild, sig: html });
      } else if (entry.sig !== html) {
        // обновляем содержимое существующего узла — без пересоздания (нет мигания)
        entry.el.className = "chat-row" + ((a.meta || {}).pinned ? " is-pinned" : "");
        entry.el.innerHTML = rowInner(a);
        entry.sig = html;
      }
    }
    // удаляем исчезнувшие
    for (const [id, e] of _rowEls) {
      if (!seen.has(id)) { e.el.remove(); _rowEls.delete(id); }
    }
    // порядок меняем только если реально изменился
    const order = list.map((a) => a.id).join(",");
    if (order !== _lastOrder) {
      list.forEach((a) => {
        const e = _rowEls.get(a.id);
        if (e) el.appendChild(e.el);  // appendChild перемещает существующий узел
      });
      _lastOrder = order;
    }
  }

  function rowInner(a) {
    const sys = a.system === "dsh" ? "dsh" : "oc";
    const st = (a.status || "").toLowerCase();
    const sd = st === "running" ? "run" : st === "waiting" ? "wait" : "";
    const prev = (a.last_step || (a.meta || {}).preview || "").toString().slice(0, 80);
    return (
      '<div class="chat-body">' +
        '<div class="chat-title">' + esc(a.title || a.id) + '</div>' +
        '<div class="chat-meta">' +
          '<span class="chip chip-' + sys + '">' + (sys === "dsh" ? "DSH" : "OC") + '</span>' +
          '<i class="sd ' + sd + '"></i>' +
          '<span class="chat-time">' + esc(fmtTime(a.updated_at)) + '</span>' +
        '</div>' +
        (prev ? '<div class="chat-prev">' + esc(prev) + '</div>' : '') +
      '</div>'
    );
  }

  function rowHtml(a) {
    const pin = (a.meta || {}).pinned ? " is-pinned" : "";
    return '<div class="chat-row' + pin + '" data-id="' + esc(a.id) + '">' + rowInner(a) + '</div>';
  }

  function renderDrawerHistory(list) {
    const el = $("drawerHistory");
    if (!el) return;
    const groups = {};
    list.forEach((a) => {
      const g = groupLabel(a.updated_at);
      (groups[g] = groups[g] || []).push(a);
    });
    const order = ["Сегодня", "Вчера", "7 дней", "Раньше"];
    let html = "";
    order.forEach((g) => {
      if (!groups[g]) return;
      html += '<div class="drawer-label">' + g + '</div>';
      groups[g].forEach((a) => {
        html +=
          '<button type="button" class="drawer-item" data-id="' + esc(a.id) + '">' +
          esc((a.title || a.id).slice(0, 40)) +
          "</button>";
      });
    });
    el.innerHTML = html || '<p class="muted" style="padding:8px 14px">Пусто</p>';
  }

  /* ── chat detail ──────────────────────────────── */
  async function openChat(id) {
    state.selectedId = id;
    state.tab = "chats";
    switchView("viewChat");
    if (tg && tg.BackButton) {
      tg.BackButton.show();
      tg.BackButton.onClick(() => closeChat());
    }
    refreshChatHeader();
    $("msgList").innerHTML = '<div class="state"><div class="spin"></div></div>';
    try {
      const res = await fetch(basePath + "/api/agents/" + encodeURIComponent(id) + "/history", {
        credentials: "include",
      });
      const data = await res.json();
      state.history = data.history || [];
      renderMessages();
    } catch (e) {
      $("msgList").innerHTML = '<p class="muted">Не удалось загрузить историю</p>';
    }
    renderAgentActions();
  }

  function closeChat() {
    state.selectedId = null;
    state.history = [];
    state.findQ = "";
    $("findBar")?.classList.add("is-hidden");
    if (tg && tg.BackButton) tg.BackButton.hide();
    switchView("viewChats");
    setTab("chats");
    render();
  }

  function refreshChatHeader() {
    const a = state.agents[state.selectedId];
    if (!a) return;
    if ($("chatTitle")) $("chatTitle").textContent = a.title || a.id;
    const bits = [a.system === "dsh" ? "DSH" : "OpenCode"];
    if (a.project) bits.push(a.project);
    if (a.status) bits.push(a.status);
    if ($("chatSub")) $("chatSub").textContent = bits.join(" · ");
    const running = (a.status || "").toLowerCase() === "running";
    $("typing")?.classList.toggle("is-hidden", !running);
    const btn = $("sendBtn");
    if (btn) {
      btn.classList.toggle("is-stop", running);
      btn.querySelector(".ico-send")?.classList.toggle("is-hidden", running);
      btn.querySelector(".ico-stop")?.classList.toggle("is-hidden", !running);
    }
  }

  function renderMessages() {
    const el = $("msgList");
    if (!el) return;
    const q = (state.findQ || "").toLowerCase();
    let html = "";
    let hits = 0;
    state.history.forEach((m, i) => {
      const role = (m.role || m.type || "assistant").toLowerCase();
      const cls = role.includes("user") || role === "human" ? "user" :
        role.includes("system") ? "system" : role.includes("tool") ? "tool" : "assistant";
      let text = m.message != null ? m.message : (m.content || m.text || "");
      if (typeof text !== "string") text = JSON.stringify(text);
      let body = esc(text);
      body = body.replace(/```([\s\S]*?)```/g, function (_, code) {
        return "<pre><code>" + code + "</code></pre>";
      });
      if (q && text.toLowerCase().includes(q)) {
        hits++;
        const re = new RegExp("(" + q.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + ")", "gi");
        body = body.replace(re, "<mark>$1</mark>");
      }
      html +=
        '<div class="msg ' + cls + '" data-i="' + i + '">' +
          body +
          '<div class="msg-time">' + esc(fmtTime(m.ts || m.created_at)) + '</div>' +
          '<button type="button" class="msg-copy" data-copy="' + i + '">копировать</button>' +
        "</div>";
    });
    el.innerHTML = html || '<p class="muted">Нет сообщений</p>';
    el.scrollTop = el.scrollHeight;
    if ($("findCount")) $("findCount").textContent = q ? hits + " найдено" : "";
  }

  function renderAgentActions() {
    const a = state.agents[state.selectedId];
    const box = $("agentActs");
    if (!a || !box) return;
    const st = (a.status || "").toLowerCase();
    const acts = [];
    if (st === "running") acts.push({ label: "Стоп", action: "interrupt", danger: true });
    if (st === "waiting") {
      acts.push({ label: "Разрешить", action: "approve" });
      acts.push({ label: "Всегда", action: "permission_always" });
      acts.push({ label: "Отклонить", action: "deny", danger: true });
      if ((a.meta || {}).pending_question) {
        acts.push({ label: "Ответить", action: "answer_question" });
      }
    }
    acts.push({ label: "Модель", action: "change_model", expensive: true });
    if (a.system === "opencode") {
      acts.push({ label: "Fork", action: "fork" });
      acts.push({ label: "Revert", action: "revert" });
    }
    box.classList.remove("is-hidden");
    box.innerHTML = acts.map((x) =>
      '<button type="button" class="btn btn-sm' + (x.danger ? " btn-danger" : "") +
      '" data-act="' + x.action + '">' + esc(x.label) + "</button>"
    ).join("");
  }

  async function doAction(action, payload) {
    payload = payload || {};
    if (action === "change_model" && !payload.model) {
      const body = '<input type="text" id="modelInput" placeholder="provider/model или id" />';
      const ok = await openSheet("Сменить модель", body, [
        { label: "Отмена", value: false },
        { label: "Сменить", value: true, primary: true },
      ]);
      if (!ok) return;
      payload.model = ($("modelInput") || {}).value || "";
      if (!payload.model) return;
      payload._confirmed = true;
    }
    if (action === "answer_question" && !payload.answer && !payload.text) {
      const body = '<input type="text" id="answerInput" placeholder="Ответ…" />';
      const ok = await openSheet("Ответ агенту", body, [
        { label: "Отмена", value: false },
        { label: "Отправить", value: true, primary: true },
      ]);
      if (!ok) return;
      payload.answer = ($("answerInput") || {}).value || "";
      payload.text = payload.answer;
    }
    if (action === "revert" && !payload.message_id) {
      const last = [...state.history].reverse().find((m) => m.id || m.message_id || m.messageID);
      payload.message_id = last && (last.id || last.message_id || last.messageID);
      if (!payload.message_id) { toast("Нет message_id для revert"); return; }
    }
    if (EXPENSIVE.has(action) && !payload._confirmed) {
      const ok = await confirmSheet(
        "Подтвердите",
        "Выполнить «" + action + "»? Действие может быть необратимым или дорогим."
      );
      if (!ok) return;
      payload._confirmed = true;
    }
    try {
      const res = await fetch(
        basePath + "/api/agents/" + encodeURIComponent(state.selectedId || payload.id) + "/action",
        {
          method: "POST",
          credentials: "include",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ action, payload }),
        }
      );
      const data = await res.json();
      if (data.error === "requires_confirm") {
        const ok = await confirmSheet("Подтвердите", data.message || "Продолжить?");
        if (ok) return doAction(action, Object.assign({}, payload, { _confirmed: true }));
        return;
      }
      if (!data.ok && !data.local) toast(data.error || "Ошибка");
      else if (data.local) toast("Сохранено локально");
      else haptic("medium");
      if (action === "rename" && payload.title) {
        const a = state.agents[state.selectedId];
        if (a) a.title = payload.title;
        refreshChatHeader();
        render();
      }
    } catch (e) {
      toast(e.message || "Сеть");
    }
  }

  async function sendMessage() {
    const input = $("msgInput");
    if (!input || !state.selectedId) return;
    const text = input.value.trim();
    const a = state.agents[state.selectedId];
    const running = a && (a.status || "").toLowerCase() === "running";
    if (running) {
      await doAction("interrupt", {});
      return;
    }
    if (!text || state.sending) return;
    state.sending = true;
    input.value = "";
    autoGrow(input);
    state.history.push({ role: "user", message: text, ts: new Date().toISOString() });
    renderMessages();
    await doAction("send", { message: text, text });
    state.sending = false;
  }

  function autoGrow(ta) {
    ta.style.height = "auto";
    ta.style.height = Math.min(110, ta.scrollHeight) + "px";
  }

  /* ── meta ops ─────────────────────────────────── */
  async function metaOp(op, agentId, extra) {
    try {
      const body = Object.assign({ op, agent_id: agentId }, extra || {});
      const res = await fetch(basePath + "/api/chats/meta", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = await res.json();
      if (data.ok) {
        // optimistic local flags
        const a = state.agents[agentId];
        if (a) {
          a.meta = a.meta || {};
          if (op === "pin") a.meta.pinned = true;
          if (op === "unpin") a.meta.pinned = false;
          if (op === "archive") { a.meta.archived = true; a.meta.pinned = false; }
          if (op === "unarchive") a.meta.archived = false;
          if (op === "set_title" && extra && extra.title) a.title = extra.title;
        }
        render();
        haptic("light");
      } else toast("Не удалось");
    } catch (e) { toast(e.message); }
  }

  /* ── sheets ───────────────────────────────────── */
  function openSheet(title, bodyHtml, actions) {
    return new Promise((resolve) => {
      const sheet = $("sheet");
      $("sheetTitle").textContent = title;
      $("sheetBody").innerHTML = bodyHtml;
      const act = $("sheetActions");
      act.innerHTML = "";
      (actions || []).forEach((a) => {
        const b = document.createElement("button");
        b.type = "button";
        b.className = "btn" + (a.primary ? " btn-primary" : "") + (a.danger ? " btn-danger" : "");
        b.textContent = a.label;
        b.onclick = () => { closeSheet(); resolve(a.value); };
        act.appendChild(b);
      });
      sheet.classList.remove("is-hidden");
      requestAnimationFrame(() => sheet.classList.add("is-open"));
      sheet._resolve = resolve;
    });
  }
  function closeSheet() {
    const sheet = $("sheet");
    sheet.classList.remove("is-open");
    setTimeout(() => sheet.classList.add("is-hidden"), 220);
  }
  function confirmSheet(title, msg) {
    return openSheet(title, "<p>" + esc(msg) + "</p>", [
      { label: "Отмена", value: false },
      { label: "Да", value: true, primary: true },
    ]);
  }

  async function chatMoreMenu() {
    const a = state.agents[state.selectedId];
    if (!a) return;
    const pinned = !!(a.meta || {}).pinned;
    const archived = !!(a.meta || {}).archived;
    const choice = await openSheet("Чат", "<p>" + esc(a.title || a.id) + "</p>", [
      { label: pinned ? "Открепить" : "Закрепить", value: "pin" },
      { label: "Переименовать", value: "rename" },
      { label: archived ? "Из архива" : "В архив", value: "archive" },
      { label: "Экспорт", value: "export" },
      { label: "Удалить", value: "delete", danger: true },
      { label: "Закрыть", value: null },
    ]);
    if (choice === "pin") metaOp(pinned ? "unpin" : "pin", a.id);
    if (choice === "archive") metaOp(archived ? "unarchive" : "archive", a.id);
    if (choice === "rename") {
      const body = '<input type="text" id="renameInput" value="' + esc(a.title || "") + '" />';
      const ok = await openSheet("Название", body, [
        { label: "Отмена", value: false },
        { label: "Сохранить", value: true, primary: true },
      ]);
      if (ok) {
        const title = ($("renameInput") || {}).value || "";
        await doAction("rename", { title });
        await metaOp("set_title", a.id, { title });
      }
    }
    if (choice === "export") exportChat(a);
    if (choice === "delete") {
      const ok = await confirmSheet("Удалить?", "Сессия «" + (a.title || a.id) + "» будет удалена.");
      if (ok) {
        await doAction("delete", { _confirmed: true });
        closeChat();
      }
    }
  }

  function exportChat(a) {
    const lines = state.history.map((m) => {
      const role = m.role || m.type || "?";
      const text = m.message != null ? m.message : (m.content || m.text || "");
      return "[" + role + "] " + text;
    });
    const blob = new Blob([lines.join("\n\n")], { type: "text/plain" });
    const name = "AIHub-" + (a.title || a.id).replace(/[^\wа-яё\-]+/gi, "_").slice(0, 40) +
      "-" + new Date().toISOString().slice(0, 10) + ".txt";
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url; link.download = name; link.click();
    URL.revokeObjectURL(url);
    toast("Скачано");
  }

  /* ── more / settings ──────────────────────────── */
  async function renderMore() {
    const panel = $("morePanel");
    if (!panel) return;
    panel.innerHTML = '<div class="state"><div class="spin"></div></div>';
    try {
      const [sRes, mRes] = await Promise.all([
        fetch(basePath + "/api/settings", { credentials: "include" }),
        fetch(basePath + "/api/metrics", { credentials: "include" }),
      ]);
      const settings = await sRes.json();
      const metrics = await mRes.json();
      const killOn = !!(settings.kill_switch || metrics.kill_switch);
      panel.innerHTML =
        '<div class="card"><h3>Статус</h3>' +
        row("DSH", $("dshDot")?.dataset.s || "—") +
        row("OpenCode", $("ocDot")?.dataset.s || "—") +
        row("Kill switch", killOn ? "ВКЛ" : "выкл") +
        "</div>" +
        '<div class="card"><h3>Сеть</h3>' +
        row("Режим", settings.network_mode || "—") +
        row("PUBLIC_URL", settings.public_url || "—") +
        row("Порт", String(settings.gatekeeper_port || "—")) +
        "</div>" +
        '<div class="card"><h3>Метрики</h3>' +
        row("Агентов", String((metrics.agents_total != null) ? metrics.agents_total : Object.keys(state.agents).length)) +
        row("DSH circuit", String((metrics.circuit && metrics.circuit.dsh) || "—")) +
        row("OC circuit", String((metrics.circuit && metrics.circuit.opencode) || "—")) +
        "</div>" +
        '<div class="card"><h3>Ссылки</h3>' +
        '<button type="button" class="btn btn-block" id="openDshFull">Полный интерфейс DSH</button>' +
        '</div>' +
        '<div class="card"><h3>Опасная зона</h3>' +
        '<button type="button" class="btn btn-danger btn-block" id="killBtn">' +
        (killOn ? "Снять kill switch" : "Kill switch") + "</button></div>";
      $("openDshFull")?.addEventListener("click", () => {
        window.open(basePath + "/dsh/", "_blank");
      });
      $("killBtn")?.addEventListener("click", async () => {
        const ok = await confirmSheet(
          "Kill switch",
          killOn ? "Снять аварийное отключение?" : "Включить kill switch? Сервис станет недоступен."
        );
        if (!ok) return;
        try {
          await fetch(basePath + "/api/settings", {
            method: "POST",
            credentials: "include",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ kill_switch: !killOn }),
          });
          toast(killOn ? "Kill switch снят" : "Kill switch включён");
          renderMore();
        } catch (e) { toast(e.message || "Ошибка"); }
      });

    } catch (e) {
      panel.innerHTML = '<p class="muted">Не удалось загрузить настройки</p>';
    }
  }
  function row(k, v) {
    return '<div class="row"><span>' + esc(k) + '</span><span>' + esc(v) + "</span></div>";
  }

  /* ── DSH embed ────────────────────────────────── */
  function loadDsh() {
    const frame = $("dshFrame");
    const st = $("dshState");
    if (!frame) return;
    if (frame.dataset.loaded) return;
    frame.src = basePath + "/dsh/";
    frame.dataset.loaded = "1";
    frame.onload = () => {
      st?.classList.add("is-hidden");
      frame.classList.remove("is-hidden");
    };
    frame.onerror = () => {
      if (st) st.innerHTML = '<p>DSH недоступен</p><button type="button" class="btn" id="dshRetry">Повторить</button>';
    };
  }

  function renderOcList() {
    const el = $("ocList");
    if (!el) return;
    const list = Object.values(state.agents).filter((a) => a.system === "opencode");
    el.innerHTML = list.map((a) =>
      '<button type="button" class="drawer-item" data-id="' + esc(a.id) + '">' +
      esc((a.title || a.id).slice(0, 36)) + "</button>"
    ).join("") || '<p class="muted">Нет сессий</p>';
  }

  /* ── navigation ───────────────────────────────── */
  function switchView(id) {
    document.querySelectorAll(".view").forEach((v) => v.classList.remove("is-active"));
    $(id)?.classList.add("is-active");
  }
  function setTab(tab) {
    state.tab = tab;
    document.querySelectorAll(".tab").forEach((t) => {
      t.classList.toggle("is-on", t.dataset.tab === tab);
    });
    if (tab === "chats") {
      if (state.selectedId) switchView("viewChat");
      else { switchView("viewChats"); render(); }
    } else if (tab === "dsh") { switchView("viewDsh"); loadDsh(); }
    else if (tab === "oc") { switchView("viewOc"); renderOcList(); }
    else if (tab === "more") { switchView("viewMore"); renderMore(); }
  }

  function openDrawer(on) {
    $("drawer")?.classList.toggle("is-open", on);
    $("scrim")?.classList.toggle("is-hidden", !on);
    $("scrim")?.classList.toggle("is-open", on);
    $("drawer")?.setAttribute("aria-hidden", on ? "false" : "true");
  }

  async function newChat() {
    openDrawer(false);
    const sys = state.filter === "all" ? null : state.filter;
    let system = sys;
    if (!system) {
      const choice = await openSheet("Новый чат", "<p>Выберите систему</p>", [
        { label: "DSH", value: "dsh", primary: true },
        { label: "OpenCode", value: "opencode" },
        { label: "Отмена", value: null },
      ]);
      if (!choice) return;
      system = choice;
    }
    // create via action on a synthetic path — use sessions/new
    try {
      const res = await fetch(basePath + "/api/sessions/new", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ system }),
      });
      const data = await res.json();
      if (data.ok || data.id || data.session) {
        toast("Чат создан");
        haptic("medium");
      } else toast(data.error || "Не удалось создать");
    } catch (e) { toast(e.message); }
  }

  /* ── events ───────────────────────────────────── */
  function bind() {
    $("menuBtn")?.addEventListener("click", () => openDrawer(true));
    $("scrim")?.addEventListener("click", () => openDrawer(false));
    $("newChatBtn")?.addEventListener("click", newChat);
    $("emptyNew")?.addEventListener("click", newChat);
    $("retryBtn")?.addEventListener("click", () => { hideError(); connectWs(); render(); });
    $("goMore")?.addEventListener("click", () => { openDrawer(false); setTab("more"); });

    $("sysFilter")?.addEventListener("click", (e) => {
      const btn = e.target.closest(".seg-item");
      if (!btn) return;
      state.filter = btn.dataset.sys;
      $("sysFilter").querySelectorAll(".seg-item").forEach((b) => b.classList.toggle("is-on", b === btn));
      render();
    });

    $("tabbar")?.addEventListener("click", (e) => {
      const t = e.target.closest(".tab");
      if (!t) return;
      if (state.selectedId && t.dataset.tab !== "chats") closeChat();
      setTab(t.dataset.tab);
    });

    $("chatList")?.addEventListener("click", (e) => {
      const row = e.target.closest(".chat-row");
      if (row) openChat(row.dataset.id);
    });
    $("chatList")?.addEventListener("contextmenu", async (e) => {
      const row = e.target.closest(".chat-row");
      if (!row) return;
      e.preventDefault();
      state.selectedId = row.dataset.id;
      await chatMoreMenu();
      state.selectedId = null;
    });
    // Mobile long-press (≥500ms)
    let longPressTimer = null;
    let longPressId = null;
    $("chatList")?.addEventListener("touchstart", (e) => {
      const row = e.target.closest(".chat-row");
      if (!row) return;
      longPressId = row.dataset.id;
      longPressTimer = setTimeout(async () => {
        longPressTimer = null;
        haptic("medium");
        state.selectedId = longPressId;
        await chatMoreMenu();
        state.selectedId = null;
      }, 520);
    }, { passive: true });
    const cancelLP = () => { if (longPressTimer) { clearTimeout(longPressTimer); longPressTimer = null; } };
    $("chatList")?.addEventListener("touchend", cancelLP, { passive: true });
    $("chatList")?.addEventListener("touchmove", cancelLP, { passive: true });

    $("drawerHistory")?.addEventListener("click", (e) => {
      const b = e.target.closest("[data-id]");
      if (b) { openDrawer(false); openChat(b.dataset.id); }
    });
    $("drawer")?.querySelectorAll("[data-view]").forEach((b) => {
      b.addEventListener("click", () => {
        state.viewMode = b.dataset.view;
        openDrawer(false);
        setTab("chats");
        render();
      });
    });
    $("drawerSearch")?.addEventListener("input", (e) => {
      state.search = e.target.value.trim();
      render();
    });

    $("chatBack")?.addEventListener("click", closeChat);
    $("chatMore")?.addEventListener("click", chatMoreMenu);
    $("chatFind")?.addEventListener("click", () => {
      $("findBar")?.classList.toggle("is-hidden");
      $("findInput")?.focus();
    });
    $("findInput")?.addEventListener("input", (e) => {
      state.findQ = e.target.value.trim();
      renderMessages();
    });
    $("msgList")?.addEventListener("click", (e) => {
      const c = e.target.closest("[data-copy]");
      if (!c) return;
      const m = state.history[+c.dataset.copy];
      const text = m && (m.message != null ? m.message : (m.content || m.text || ""));
      if (text != null) navigator.clipboard?.writeText(String(text)).then(() => toast("Скопировано"));
    });
    $("agentActs")?.addEventListener("click", (e) => {
      const b = e.target.closest("[data-act]");
      if (b) doAction(b.dataset.act, {});
    });
    $("sendBtn")?.addEventListener("click", sendMessage);
    $("msgInput")?.addEventListener("input", (e) => autoGrow(e.target));
    $("msgInput")?.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendMessage(); }
    });

    $("dshExt")?.addEventListener("click", () => window.open(basePath + "/dsh/", "_blank"));
    $("ocList")?.addEventListener("click", (e) => {
      const b = e.target.closest("[data-id]");
      if (b) openChat(b.dataset.id);
    });

    $("sheet")?.addEventListener("click", (e) => {
      if (e.target === $("sheet")) { closeSheet(); if ($("sheet")._resolve) $("sheet")._resolve(null); }
    });

    // swipe from left edge → drawer
    let sx = 0;
    document.addEventListener("touchstart", (e) => { sx = e.touches[0].clientX; }, { passive: true });
    document.addEventListener("touchend", (e) => {
      const dx = e.changedTouches[0].clientX - sx;
      if (sx < 24 && dx > 60) openDrawer(true);
      if (dx < -60 && $("drawer")?.classList.contains("is-open")) openDrawer(false);
    }, { passive: true });
  }

  /* ── boot ─────────────────────────────────────── */
  async function boot() {
    bind();
    const app = $("app");
    runSplash(() => {
      app?.classList.remove("is-hidden");
    });
    const ok = await auth();
    if (!ok) return;
    // initial fetch
    try {
      const res = await fetch(basePath + "/api/agents", { credentials: "include" });
      if (res.ok) {
        const data = await res.json();
        (data.agents || []).forEach((a) => { state.agents[a.id] = a; });
      }
    } catch (_) {}
    render();
    connectWs();
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
})();
