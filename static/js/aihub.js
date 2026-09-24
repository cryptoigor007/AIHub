/**
 * AIHub — клиент
 * Вкладки: Агенты / Сессии, WS, карточка с историей, подтверждения дорогих действий
 */
(function () {
  "use strict";

  const tg = window.Telegram && window.Telegram.WebApp;
  if (tg) {
    tg.ready();
    tg.expand();
    tg.enableClosingConfirmation();
    const tp = tg.themeParams || {};
    const set = (k, v) => document.documentElement.style.setProperty(k, v);
    if (tp.bg_color) set("--tg-bg", tp.bg_color);
    if (tp.text_color) set("--tg-text", tp.text_color);
    if (tp.hint_color) set("--tg-hint", tp.hint_color);
    if (tp.button_color) set("--tg-button", tp.button_color);
    if (tp.button_text_color) set("--tg-button-text", tp.button_text_color);
    if (tp.secondary_bg_color) set("--tg-secondary-bg", tp.secondary_bg_color);
    if (tg.BackButton) tg.BackButton.hide();
  }

  const pathParts = location.pathname.split("/").filter(Boolean);
  let basePath = "";
  if (pathParts.length >= 2 && pathParts[0] === "p") {
    basePath = "/" + pathParts[0] + "/" + pathParts[1];
  } else if (pathParts.length >= 1) {
    basePath = "/" + pathParts.slice(0, Math.min(2, pathParts.length)).join("/");
  }

  const EXPENSIVE = new Set(["change_model", "new_session", "delete", "rollback", "bulk"]);

  const state = {
    agents: {},
    filter: "active",
    tab: "agents",
    search: "",
    ws: null,
    connected: false,
    selectedId: null,
  };

  const $ = (id) => document.getElementById(id);
  const agentList = $("agentList");
  const sessionList = $("sessionList");
  const stateEmpty = $("stateEmpty");
  const stateLoading = $("stateLoading");
  const stateError = $("stateError");
  const errorText = $("errorText");
  const dshBadge = $("dshBadge");
  const ocBadge = $("ocBadge");
  const cardOverlay = $("cardOverlay");
  const cardTitle = $("cardTitle");
  const cardBody = $("cardBody");
  const cardActions = $("cardActions");
  const confirmOverlay = $("confirmOverlay");
  const confirmText = $("confirmText");
  const filtersEl = $("filters");
  const searchBar = $("searchBar");
  const searchInput = $("searchInput");

  async function auth() {
    if (!tg || !tg.initData) {
      // Локальный тест без Telegram: пробуем /auth/dev (только ENV=development на сервере)
      try {
        const res = await fetch(basePath + "/auth/dev", {
          method: "POST",
          credentials: "include",
        });
        if (res.ok) {
          console.info("dev-сессия получена");
          return true;
        }
      } catch (e) { /* ignore */ }
      console.warn("Нет initData — UI без сессии (только public/health)");
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
        if ((data.message || "").includes("Токен бота")) {
          const tb = $("tokenBanner");
          if (tb) tb.classList.remove("hidden");
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

  let wsBackoffMs = 1000;
  const WS_BACKOFF_MAX = 30000;

  function connectWs() {
    if (state.ws && (state.ws.readyState === WebSocket.OPEN || state.ws.readyState === WebSocket.CONNECTING)) {
      return;
    }
    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    const url = proto + "//" + location.host + basePath + "/ws";
    let ws;
    try {
      ws = new WebSocket(url);
    } catch (e) {
      state.connected = false;
      setLive(false);
      setTimeout(connectWs, wsBackoffMs);
      wsBackoffMs = Math.min(wsBackoffMs * 2, WS_BACKOFF_MAX);
      return;
    }
    state.ws = ws;
    ws.onopen = () => {
      state.connected = true;
      wsBackoffMs = 1000;
      setLive(true);
      hideError();
      hideNetworkHint();
    };
    ws.onmessage = (ev) => {
      try {
        handleEvent(JSON.parse(ev.data));
      } catch (_) {}
    };
    ws.onclose = () => {
      state.connected = false;
      setLive(false);
      if (wsBackoffMs >= 8000) {
        showNetworkHint(
          "Нет связи с AIHub.\n" +
          "• Дома (Wi‑Fi Mac): Tailscale можно не включать — LAN URL: ./scripts/status.sh на Mac.\n" +
          "• Вне дома / LTE: включите Tailscale (VPN On), затем снова кнопку «AIHub»."
        );
      }
      setTimeout(connectWs, wsBackoffMs);
      wsBackoffMs = Math.min(wsBackoffMs * 2, WS_BACKOFF_MAX);
    };
    ws.onerror = () => {
      try { ws.close(); } catch (_) {}
    };
  }

  function setLive(on) {
    const title = document.querySelector(".title");
    if (title) title.setAttribute("data-live", on ? "1" : "0");
  }

  function handleEvent(msg) {
    if (msg.type === "ping") return;
    if (msg.type === "snapshot") {
      state.agents = {};
      (msg.agents || []).forEach((a) => (state.agents[a.id] = a));
      setBadge("dsh", msg.dsh_online);
      setBadge("opencode", msg.opencode_online);
      updateBanners(msg.dsh_online, msg.opencode_online);
      render();
      return;
    }
    if (msg.type === "state_update" && msg.agent) {
      state.agents[msg.agent.id] = msg.agent;
      render();
      return;
    }
    if (msg.type === "system_online" || msg.type === "system_offline") {
      setBadge(msg.system, msg.type === "system_online");
      const dsh = dshBadge.dataset.status === "online";
      const oc = ocBadge.dataset.status === "online";
      updateBanners(dsh, oc);
    }
  }


  function updateBanners(dshOnline, ocOnline) {
    const el = $("offlineBanner");
    if (!el) return;
    const parts = [];
    if (!dshOnline) parts.push("DSH offline");
    if (!ocOnline) parts.push("OpenCode offline");
    if (parts.length) {
      el.textContent = parts.join(" · ") + " — работаем с доступной системой";
      el.classList.remove("hidden");
    } else {
      el.classList.add("hidden");
    }
  }

  function setBadge(system, online) {
    const el = system === "dsh" ? dshBadge : ocBadge;
    if (el) el.dataset.status = online ? "online" : "offline";
  }

  function getFiltered() {
    let list = Object.values(state.agents);
    if (state.filter === "active") {
      list = list.filter((a) => a.status === "running" || a.status === "waiting");
    } else if (state.filter === "dsh") {
      list = list.filter((a) => a.system === "dsh");
    } else if (state.filter === "opencode") {
      list = list.filter((a) => a.system === "opencode");
    }
    if (state.search) {
      const q = state.search.toLowerCase();
      list = list.filter(
        (a) =>
          (a.title || "").toLowerCase().includes(q) ||
          (a.project || "").toLowerCase().includes(q) ||
          a.id.toLowerCase().includes(q)
      );
    }
    const roots = list.filter((a) => !a.parent_id);
    const children = {};
    list.forEach((a) => {
      if (a.parent_id) {
        if (!children[a.parent_id]) children[a.parent_id] = [];
        children[a.parent_id].push(a);
      }
    });
    return { roots, children, all: list };
  }

  async function renderSettings() {
    const panel = $("settingsPanel");
    const agentListEl = $("agentList");
    const sessionListEl = $("sessionList");
    if (agentListEl) agentListEl.classList.add("hidden");
    if (sessionListEl) sessionListEl.classList.add("hidden");
    stateEmpty.classList.add("hidden");
    if (!panel) return;
    panel.classList.remove("hidden");
    panel.innerHTML = "<p style='color:var(--tg-hint)'>Загрузка…</p>";
    try {
      const [setRes, metRes] = await Promise.all([
        fetch(basePath + "/api/settings", { credentials: "include" }),
        fetch(basePath + "/api/metrics", { credentials: "include" }),
      ]);
      const s = await setRes.json();
      const m = await metRes.json();
      const rows = [
        ["Версия", s.version],
        ["Токен бота", s.token_configured ? "задан" : "НЕ ЗАДАН"],
        ["Public URL", s.public_url || "—"],
        ["DSH порт", s.dsh_port],
        ["OpenCode порт", s.opencode_port],
        ["Kill switch", s.kill_switch ? "ВКЛ" : "выкл"],
        ["Агентов", m.agents_total],
        ["DSH", m.dsh_online ? "online" : "offline"],
        ["OpenCode", m.opencode_online ? "online" : "offline"],
        ["Circuit DSH", (m.circuit && m.circuit.dsh) || "—"],
        ["Circuit OC", (m.circuit && m.circuit.opencode) || "—"],
        ["WS clients", m.ws_subscribers],
      ];
      panel.innerHTML = rows
        .map(
          ([k, v]) =>
            `<div class="settings-row"><span class="label">${escapeHtml(String(k))}</span><span class="value">${escapeHtml(String(v))}</span></div>`
        )
        .join("");
    } catch (e) {
      panel.innerHTML = "<p>Ошибка загрузки настроек</p>";
    }
  }

  function render() {
    stateLoading.classList.add("hidden");
    const settingsPanel = $("settingsPanel");
    if (settingsPanel) settingsPanel.classList.add("hidden");
    if (state.tab === "settings") {
      renderSettings();
      return;
    }
    if (state.tab === "sessions") {
      renderSessions();
      return;
    }
    sessionList.classList.add("hidden");
    const { roots, children } = getFiltered();
    if (roots.length === 0) {
      agentList.classList.add("hidden");
      stateEmpty.classList.remove("hidden");
      stateEmpty.querySelector("p").textContent =
        state.filter === "active" ? "Нет активных агентов" : "Нет агентов";
      return;
    }
    stateEmpty.classList.add("hidden");
    agentList.classList.remove("hidden");
    agentList.innerHTML = "";
    roots.forEach((agent, i) => {
      const card = createCard(agent, children[agent.id] || []);
      agentList.appendChild(card);
      requestAnimationFrame(() => {
        setTimeout(() => card.classList.add("visible"), Math.min(i * 30, 150));
      });
    });
  }

  function renderSessions() {
    agentList.classList.add("hidden");
    const { all } = getFiltered();
    if (all.length === 0) {
      sessionList.classList.add("hidden");
      stateEmpty.classList.remove("hidden");
      stateEmpty.querySelector("p").textContent = "Сессии не найдены";
      return;
    }
    stateEmpty.classList.add("hidden");
    sessionList.classList.remove("hidden");
    const groups = {};
    all.forEach((a) => {
      const key = a.project || "(без проекта)";
      if (!groups[key]) groups[key] = [];
      groups[key].push(a);
    });
    sessionList.innerHTML = "";
    Object.keys(groups)
      .sort()
      .forEach((project) => {
        const g = document.createElement("div");
        g.className = "session-group";
        g.innerHTML = `<div class="session-group-title">${escapeHtml(project)}</div>`;
        groups[project].forEach((agent) => {
          g.appendChild(createCard(agent, []));
        });
        sessionList.appendChild(g);
        g.querySelectorAll(".agent-card").forEach((c, i) => {
          requestAnimationFrame(() =>
            setTimeout(() => c.classList.add("visible"), Math.min(i * 30, 150))
          );
        });
      });
  }

  function createCard(agent, subagents) {
    const el = document.createElement("div");
    el.className = "agent-card";
    el.dataset.id = agent.id;
    const statusLabel = {
      running: "Работает",
      waiting: "Ждёт",
      completed: "Завершён",
      failed: "Ошибка",
      unknown: "—",
    }[agent.status] || agent.status;

    let tokensStr = "";
    if (agent.tokens) {
      tokensStr = (agent.tokens.total || agent.tokens.input + agent.tokens.output) + " tok";
    }
    if (agent.cost != null) {
      tokensStr += (tokensStr ? " · " : "") + "$" + Number(agent.cost).toFixed(4);
    }
    const hasSubs = subagents.length > 0;
    const activeSubs = subagents.filter(
      (s) => s.status === "running" || s.status === "waiting"
    );
    el.innerHTML = `
      <div class="agent-card-top">
        <div class="agent-name">${escapeHtml(agent.title || agent.id)}</div>
        <span class="agent-system ${agent.system}">${agent.system}</span>
      </div>
      <div class="agent-meta">
        <span class="agent-status ${agent.status}">${statusLabel}</span>
        ${agent.project ? `<span>${escapeHtml(agent.project)}</span>` : ""}
        ${agent.last_step ? `<span class="agent-step">${escapeHtml(agent.last_step)}</span>` : ""}
        ${tokensStr ? `<span>${tokensStr}</span>` : ""}
        ${(agent.status === "running" || agent.status === "waiting") && agent.started_at ? `<span>⏱ ${formatDuration(agent.started_at)}</span>` : ""}
        ${hasSubs ? `<span>${activeSubs.length}/${subagents.length} субагентов</span>` : ""}
      </div>
      ${
        hasSubs
          ? `<div class="subagents ${activeSubs.length ? "open" : ""}">
        ${subagents
          .map(
            (s) =>
              `<div class="subagent-item">${escapeHtml(s.title || s.id)} · ${s.status}</div>`
          )
          .join("")}
      </div>`
          : ""
      }
    `;
    el.addEventListener("click", (e) => {
      if (e.target.closest(".subagents")) return;
      openCard(agent.id);
    });
    return el;
  }

  function formatDuration(iso) {
    if (!iso) return "";
    try {
      const start = new Date(iso).getTime();
      if (!start) return "";
      const sec = Math.max(0, Math.floor((Date.now() - start) / 1000));
      if (sec < 60) return sec + "с";
      if (sec < 3600) return Math.floor(sec / 60) + "м " + (sec % 60) + "с";
      return Math.floor(sec / 3600) + "ч " + Math.floor((sec % 3600) / 60) + "м";
    } catch (_) {
      return "";
    }
  }

  function haptic(type) {
    try {
      if (tg && tg.HapticFeedback) {
        if (type === "success") tg.HapticFeedback.notificationOccurred("success");
        else if (type === "error") tg.HapticFeedback.notificationOccurred("error");
        else tg.HapticFeedback.impactOccurred("light");
      }
    } catch (_) {}
  }

  function escapeHtml(s) {
    const d = document.createElement("div");
    d.textContent = s == null ? "" : String(s);
    return d.innerHTML;
  }

  async function openCard(id) {
    const agent = state.agents[id];
    if (!agent) return;
    state.selectedId = id;
    cardTitle.textContent = agent.title || agent.id;

    let historyHtml = "";
    try {
      const res = await fetch(
        basePath + "/api/agents/" + encodeURIComponent(id) + "/history",
        { credentials: "include" }
      );
      const data = await res.json();
      const hist = data.history || [];
      if (hist.length) {
        historyHtml =
          '<div class="history-block"><strong>История</strong>' +
          hist
            .slice(-20)
            .map((h) => {
              const msg =
                typeof h.message === "string"
                  ? h.message
                  : JSON.stringify(h.message || h).slice(0, 200);
              return `<div class="history-item"><div class="h-ts">${escapeHtml(
                h.ts || ""
              )}</div>${escapeHtml(msg)}</div>`;
            })
            .join("") +
          "</div>";
      }
    } catch (_) {}

    const model = (agent.meta && (agent.meta.model || agent.meta.modelID)) || "—";
    const variant = (agent.meta && agent.meta.variant) || "";
    const modelLine = variant ? model + " (" + variant + ")" : model;
    let filesHtml = "";
    const files = agent.meta && agent.meta.changed_files;
    if (files) {
      const list = Array.isArray(files) ? files : [files];
      const lines = list.slice(0, 15).map((f) => {
        if (typeof f === "string") return escapeHtml(f);
        return escapeHtml(f.path || f.file || JSON.stringify(f).slice(0, 80));
      });
      if (lines.length) {
        filesHtml = '<div class="row"><span class="label">Файлы</span><span style="font-size:12px">' + lines.join("<br>") + "</span></div>";
      }
    }
    cardBody.innerHTML = `
      <div class="row"><span class="label">Система</span><span>${agent.system.toUpperCase()}</span></div>
      <div class="row"><span class="label">Статус</span><span>${agent.status}</span></div>
      <div class="row"><span class="label">Проект</span><span>${escapeHtml(agent.project || "—")}</span></div>
      <div class="row"><span class="label">Модель</span><span>${escapeHtml(modelLine)}</span></div>
      <div class="row"><span class="label">Шаг</span><span>${escapeHtml(agent.last_step || "—")}</span></div>
      <div class="row"><span class="label">Токены</span><span>${
        agent.tokens
          ? agent.tokens.total || agent.tokens.input + agent.tokens.output
          : "—"
      }</span></div>
      <div class="row"><span class="label">Стоимость</span><span>${
        agent.cost != null ? "$" + Number(agent.cost).toFixed(4) : "—"
      }</span></div>
      <div class="row"><span class="label">ID</span><span style="font-size:11px;word-break:break-all">${escapeHtml(
        agent.id
      )}</span></div>
      ${historyHtml}
    `;

    cardActions.innerHTML = "";
    const actions = [];
    if (agent.status === "running" || agent.status === "waiting") {
      actions.push({ label: "Прервать", action: "interrupt", danger: true });
    }
    if (agent.status === "waiting") {
      actions.push({ label: "Разрешить раз", action: "approve" });
      actions.push({ label: "Всегда", action: "permission_always" });
      actions.push({ label: "Отклонить", action: "deny", danger: true });
      if (agent.meta && agent.meta.pending_question) {
        actions.push({ label: "Ответить", action: "answer_question" });
      }
    }
    actions.push({ label: "Сообщение", action: "send" });
    actions.push({ label: "Сменить модель", action: "change_model", expensive: true });
    actions.push({ label: "Переименовать", action: "rename" });
    if (agent.system === "opencode") {
      actions.push({ label: "Fork", action: "fork", expensive: true });
    }

    actions.push({ label: "Удалить", action: "delete", danger: true, expensive: true });
    if (agent.system === "dsh") {
      actions.push({ label: "Полный интерфейс", action: "full_ui", outline: true });
    }

    actions.forEach((a) => {
      const btn = document.createElement("button");
      btn.className =
        "btn" +
        (a.danger ? " btn-danger" : "") +
        (a.outline ? " btn-outline" : "");
      btn.textContent = a.label;
      btn.addEventListener("click", () => handleAction(agent, a.action, a.expensive));
      cardActions.appendChild(btn);
    });

    cardOverlay.classList.remove("hidden");
    requestAnimationFrame(() => cardOverlay.classList.add("visible"));
    if (tg && tg.BackButton) {
      tg.BackButton.show();
      tg.BackButton.onClick(closeCard);
    }
  }

  function closeCard() {
    cardOverlay.classList.remove("visible");
    setTimeout(() => cardOverlay.classList.add("hidden"), 250);
    state.selectedId = null;
    if (tg && tg.BackButton) {
      tg.BackButton.hide();
      tg.BackButton.offClick(closeCard);
    }
  }

  $("cardClose").addEventListener("click", closeCard);
  cardOverlay.addEventListener("click", (e) => {
    if (e.target === cardOverlay) closeCard();
  });

  async function handleAction(agent, action, expensive) {
    if (action === "full_ui") {
      location.href = basePath + "/dsh/";
      return;
    }

    if (action === "send") {
      const text = prompt("Сообщение агенту:");
      if (!text) return;
      await doAction(agent.id, "send", { message: text });
      return;
    }

    if (action === "answer_question") {
      const text = prompt("Ответ на вопрос агента:");
      if (text == null) return;
      await doAction(agent.id, "answer_question", {
        answer: text,
        question_id: agent.meta && agent.meta.pending_question,
      });
      return;
    }
    if (action === "permission_always") {
      const ok = await confirmAction("Разрешить это действие всегда?");
      if (!ok) return;
      await doAction(agent.id, "permission_always", {
        permission_id: agent.meta && agent.meta.pending_permission,
        _confirmed: true,
      });
      return;
    }

    if (action === "fork") {
      const ok = await confirmAction("Создать fork сессии «" + (agent.title || agent.id) + "»?");
      if (!ok) return;
      await doAction(agent.id, "fork", { _confirmed: true });
      return;
    }
    if (action === "rename") {
      const title = prompt("Новое имя сессии:", agent.title || "");
      if (!title) return;
      await doAction(agent.id, "rename", { title });
      return;
    }
    if (action === "change_model") {
      const model = prompt("Новая модель:");
      if (!model) return;
      const ok = await confirmAction(
        `Сменить модель агента «${agent.title}» на ${model}?\n⚠️ Это может увеличить расход квоты/стоимость.`
      );
      if (!ok) return;
      await doAction(agent.id, "change_model", { model, _confirmed: true });
      return;
    }

    if (expensive || EXPENSIVE.has(action) || action === "interrupt" || action === "deny") {
      const messages = {
        interrupt: `Прервать агента «${agent.title}»?`,
        deny: `Отклонить запрос агента «${agent.title}»?`,
        delete: `Удалить «${agent.title}»? Это необратимо.`,
        rollback: `Откатить изменения «${agent.title}»?`,
      };
      const ok = await confirmAction(
        messages[action] || `Подтвердите действие «${action}» для «${agent.title}».`
      );
      if (!ok) return;
      await doAction(agent.id, action, { _confirmed: true });
      return;
    }

    await doAction(agent.id, action, {});
  }

  async function doAction(agentId, action, payload) {
    try {
      const res = await fetch(
        basePath + "/api/agents/" + encodeURIComponent(agentId) + "/action",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          credentials: "include",
          body: JSON.stringify({ action, payload }),
        }
      );
      const data = await res.json();
      if (data.error === "requires_confirm" && data.message) {
        const ok = await confirmAction(data.message);
        if (!ok) return;
        payload._confirmed = true;
        return doAction(agentId, action, payload);
      }
      if (!data.ok) {
        haptic("error");
        alert(data.error || data.message || "Ошибка");
      } else {
        haptic("success");
      }
    } catch (e) {
      alert("Ошибка: " + e.message);
    }
  }

  function confirmAction(text) {
    return new Promise((resolve) => {
      confirmText.textContent = text;
      confirmOverlay.classList.remove("hidden");
      requestAnimationFrame(() => confirmOverlay.classList.add("visible"));
      const onOk = () => {
        cleanup();
        resolve(true);
      };
      const onCancel = () => {
        cleanup();
        resolve(false);
      };
      function cleanup() {
        confirmOverlay.classList.remove("visible");
        setTimeout(() => confirmOverlay.classList.add("hidden"), 200);
        $("confirmOk").removeEventListener("click", onOk);
        $("confirmCancel").removeEventListener("click", onCancel);
      }
      $("confirmOk").addEventListener("click", onOk);
      $("confirmCancel").addEventListener("click", onCancel);
    });
  }

  // Tabs
  document.querySelectorAll(".tab").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".tab").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      state.tab = btn.dataset.tab;
      if (state.tab === "sessions") {
        filtersEl.classList.add("hidden");
        searchBar.classList.remove("hidden");
      } else if (state.tab === "settings") {
        filtersEl.classList.add("hidden");
        searchBar.classList.add("hidden");
      } else {
        filtersEl.classList.remove("hidden");
        searchBar.classList.add("hidden");
        state.search = "";
        if (searchInput) searchInput.value = "";
      }
      render();
    });
  });

  document.querySelectorAll(".filter-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".filter-btn").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      state.filter = btn.dataset.filter;
      render();
    });
  });

  if (searchInput) {
    let t;
    searchInput.addEventListener("input", () => {
      clearTimeout(t);
      t = setTimeout(async () => {
        state.search = searchInput.value.trim();
        if (state.search.length >= 2) {
          try {
            const res = await fetch(
              basePath + "/api/search?q=" + encodeURIComponent(state.search),
              { credentials: "include" }
            );
            const data = await res.json();
            if (data.agents) {
              data.agents.forEach((a) => (state.agents[a.id] = a));
            }
          } catch (_) {}
        }
        render();
      }, 200);
    });
  }

  $("retryBtn").addEventListener("click", () => {
    hideError();
    stateLoading.classList.remove("hidden");
    connectWs();
  });

  function showError(msg) {
    stateLoading.classList.add("hidden");
    stateEmpty.classList.add("hidden");
    agentList.classList.add("hidden");
    sessionList.classList.add("hidden");
    stateError.classList.remove("hidden");
    errorText.textContent = msg;
  }

  function showNetworkHint(text) {
    let el = document.getElementById("net-hint");
    if (!el) {
      el = document.createElement("div");
      el.id = "net-hint";
      el.setAttribute("role", "status");
      el.style.cssText = "margin:8px 12px;padding:10px 12px;border-radius:10px;background:rgba(255,180,0,.15);border:1px solid rgba(255,180,0,.35);font-size:13px;white-space:pre-wrap;line-height:1.35";
      const root = document.getElementById("app") || document.body;
      root.insertBefore(el, root.firstChild);
    }
    el.textContent = text;
    el.hidden = false;
  }
  function hideNetworkHint() {
    const el = document.getElementById("net-hint");
    if (el) el.hidden = true;
  }
  function hideError() {
    stateError.classList.add("hidden");
  }

  (async function init() {
    const ok = await auth();
    if (!ok) return;
    connectWs();
    setTimeout(async () => {
      if (Object.keys(state.agents).length === 0) {
        try {
          const res = await fetch(basePath + "/api/agents?active_only=false", {
            credentials: "include",
          });
          const data = await res.json();
          (data.agents || []).forEach((a) => (state.agents[a.id] = a));
          render();
        } catch (_) {}
      }
    }, 2000);
  })();
})();
