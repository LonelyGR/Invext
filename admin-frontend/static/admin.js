const API_BASE = "/database/api";

/** Состояние списка пользователей (пагинация + поиск). */
let usersListState = { page: 1, pageSize: 25, search: "", activityFilter: "" };
const USERS_FILTERS_KEY = "invext_admin_users_filters";
const DEPOSITS_FILTERS_KEY = "invext_admin_deposits_filters";
const WITHDRAWALS_FILTERS_KEY = "invext_admin_withdrawals_filters";
const USERS_PRESETS_KEY = "invext_admin_users_filter_presets";
const USER_TAGS_KEY = "invext_admin_user_tags";
const SETTINGS_DRAFT_KEY = "invext_admin_settings_draft";
const SETTINGS_PRESETS_KEY = "invext_admin_settings_presets";
const DASHBOARD_RANGE_KEY = "invext_admin_dashboard_range";
const DASHBOARD_LIVE_KEY = "invext_admin_dashboard_live";
const BROADCAST_TEMPLATES_KEY = "invext_admin_broadcast_templates";

let dashboardAutoRefreshTimer = null;
let authRedirectInProgress = false;

class UnauthorizedError extends Error {
  constructor(message = "Unauthorized") {
    super(message);
    this.name = "UnauthorizedError";
  }
}

function isUnauthorizedError(err) {
  return err instanceof UnauthorizedError || err?.name === "UnauthorizedError";
}

function getUnauthorizedMemeMessage() {
  const memes = [
    "401: ты не пройдешь! (с) Гэндальф. Войди заново.",
    "Доступ denied. 401 украл твою сессию, как котлету со стола.",
    "401 Unauthorized: куки закончились, печеньки кончились, авторизация тоже.",
    "Сессия испарилась быстрее зарплаты в день релиза. Логин снова.",
    "401: сервер сделал вид, что тебя не знает. Представься еще раз.",
    "Тут охранник 401. Говорит: «бейджик покажи» (то есть залогинься).",
  ];
  return memes[Math.floor(Math.random() * memes.length)];
}

function loadSavedState(key, fallback) {
  try {
    const raw = localStorage.getItem(key);
    if (!raw) return { ...fallback };
    return { ...fallback, ...JSON.parse(raw) };
  } catch (_) {
    return { ...fallback };
  }
}

function saveState(key, value) {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch (_) {}
}

async function copyTextToClipboard(text) {
  const value = String(text || "").trim();
  if (!value) return false;
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(value);
      return true;
    }
  } catch (_) {}
  try {
    const ta = document.createElement("textarea");
    ta.value = value;
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.focus();
    ta.select();
    const ok = document.execCommand("copy");
    ta.remove();
    return Boolean(ok);
  } catch (_) {
    return false;
  }
}

function readUsersPresets() {
  try {
    const raw = localStorage.getItem(USERS_PRESETS_KEY);
    const arr = raw ? JSON.parse(raw) : [];
    if (!Array.isArray(arr)) return [];
    return arr.filter((x) => x && typeof x.name === "string" && typeof x.search === "string");
  } catch (_) {
    return [];
  }
}

function writeUsersPresets(presets) {
  try {
    localStorage.setItem(USERS_PRESETS_KEY, JSON.stringify(presets.slice(0, 8)));
  } catch (_) {}
}

function readUserTags() {
  try {
    const raw = localStorage.getItem(USER_TAGS_KEY);
    const map = raw ? JSON.parse(raw) : {};
    return map && typeof map === "object" ? map : {};
  } catch (_) {
    return {};
  }
}

function writeUserTag(userId, value) {
  const map = readUserTags();
  const v = String(value || "").trim().slice(0, 20);
  if (v) map[String(userId)] = v;
  else delete map[String(userId)];
  saveState(USER_TAGS_KEY, map);
}

function buildDateSeries(dayCount) {
  const out = [];
  const now = new Date();
  for (let i = dayCount - 1; i >= 0; i -= 1) {
    const d = new Date(now.getTime() - i * 24 * 60 * 60 * 1000);
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, "0");
    const dd = String(d.getDate()).padStart(2, "0");
    out.push(`${y}-${m}-${dd}`);
  }
  return out;
}

function renderMiniBars(labels, values, maxValue) {
  return labels
    .map((label, idx) => {
      const v = Number(values[idx] || 0);
      const h = maxValue > 0 ? Math.max(4, Math.round((v / maxValue) * 100)) : 4;
      return `<div class="mini-bar-item" title="${label}: ${v}">
        <div class="mini-bar" style="height:${h}%"></div>
      </div>`;
    })
    .join("");
}

function escapeHtmlAttr(s) {
  if (s == null || s === "") return "";
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/"/g, "&quot;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

async function apiRequest(path, options = {}) {
  const isFormData = options.body instanceof FormData;
  const headers = isFormData
    ? {}
    : {
        "Content-Type": "application/json",
      };
  const resp = await fetch(API_BASE + path, {
    credentials: "include",
    headers,
    ...options,
  });
  if (resp.status === 401) {
    // Сессия истекла — централизованно уводим на логин.
    if (!authRedirectInProgress) {
      authRedirectInProgress = true;
      showLoginView();
      const errorEl = document.getElementById("login-error");
      if (errorEl) errorEl.textContent = getUnauthorizedMemeMessage();
      setTimeout(() => {
        authRedirectInProgress = false;
      }, 250);
    }
    throw new UnauthorizedError();
  }
  const text = await resp.text();
  if (!resp.ok) {
    // Пытаемся вытащить detail из JSON; если это HTML/текст об ошибке — показываем его как есть.
    try {
      const data = JSON.parse(text);
      const detail = data.detail || data.message || JSON.stringify(data);
      throw new Error(detail);
    } catch (_) {
      throw new Error(text || `HTTP error ${resp.status}`);
    }
  }
  try {
    return text ? JSON.parse(text) : {};
  } catch (e) {
    throw new Error("Ответ сервера не является корректным JSON");
  }
}

function showLoginView() {
  document.getElementById("login-view").classList.remove("hidden");
  document.getElementById("main-view").classList.add("hidden");
}

function showMainView() {
  document.getElementById("login-view").classList.add("hidden");
  document.getElementById("main-view").classList.remove("hidden");
}

function updateBreadcrumbs(hash) {
  const map = {
    "#dashboard": "Дашборд",
    "#users": "Пользователи",
    "#deals": "Сделки",
    "#messages": "Сообщения",
    "#deposits": "Пополнения",
    "#withdrawals": "Выводы",
    "#logs": "Логи",
    "#settings": "Настройки → Финансы",
  };
  const el = document.getElementById("breadcrumbs");
  if (!el) return;
  if (hash.startsWith("#user-")) {
    el.textContent = "Пользователи → Профиль";
    return;
  }
  el.textContent = map[hash || "#dashboard"] || "Админка";
}

function setPageActions(hash) {
  const wrap = document.getElementById("page-actions");
  if (!wrap) return;
  wrap.innerHTML = "";

  const addBtn = (label, onClick) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "page-action-btn";
    btn.textContent = label;
    btn.onclick = onClick;
    wrap.appendChild(btn);
  };

  if (hash === "#users") {
    addBtn("Сбросить поиск", () => {
      usersListState.search = "";
      usersListState.activityFilter = "";
      usersListState.page = 1;
      saveState(USERS_FILTERS_KEY, {
        pageSize: usersListState.pageSize,
        search: usersListState.search,
        activityFilter: usersListState.activityFilter,
      });
      loadUsers();
    });
  } else if (hash === "#deposits") {
    addBtn("Сбросить фильтры", () => {
      localStorage.removeItem(DEPOSITS_FILTERS_KEY);
      loadDeposits(1);
    });
  } else if (hash === "#withdrawals") {
    addBtn("Сбросить фильтры", () => {
      localStorage.removeItem(WITHDRAWALS_FILTERS_KEY);
      loadWithdrawals();
    });
  } else if (hash === "#settings") {
    addBtn("Кнопка Сохранить ↓", () => {
      document.getElementById("settings-save-btn")?.scrollIntoView({ behavior: "smooth", block: "center" });
    });
  } else if (hash === "#messages") {
    addBtn("Обновить список", () => loadMessages(1));
  }
}

function initGlobalSearch() {
  const input = document.getElementById("global-search-input");
  const resultsEl = document.getElementById("global-search-results");
  if (!input || !resultsEl) return;
  let timer = null;

  const hide = () => resultsEl.classList.add("hidden");
  const show = () => resultsEl.classList.remove("hidden");

  document.addEventListener("keydown", (e) => {
    if (e.key === "/" && document.activeElement !== input) {
      e.preventDefault();
      input.focus();
      input.select();
    }
    if (e.key === "Escape") hide();
  });

  document.addEventListener("click", (e) => {
    if (!resultsEl.contains(e.target) && e.target !== input) hide();
  });

  input.addEventListener("input", () => {
    const q = input.value.trim();
    clearTimeout(timer);
    if (!q) {
      resultsEl.innerHTML = "";
      hide();
      return;
    }
    timer = setTimeout(async () => {
      try {
        const data = await apiRequest(`/search/global?q=${encodeURIComponent(q)}`);
        const blocks = [];
        if ((data.users || []).length) {
          blocks.push(`<div class="global-search-head">Пользователи</div>`);
          blocks.push(
            data.users
              .map(
                (u) =>
                  `<a class="global-search-item" href="#user-${u.id}">#${u.id} · ${u.telegram_id} · ${escapeHtmlAttr(
                    u.username || ""
                  )}</a>`
              )
              .join("")
          );
        }
        if ((data.deals || []).length) {
          blocks.push(`<div class="global-search-head">Сделки</div>`);
          blocks.push(
            data.deals
              .map(
                (d) =>
                  `<a class="global-search-item" href="#deals">Сделка #${d.number} · ${d.status}</a>`
              )
              .join("")
          );
        }
        if ((data.ledger || []).length) {
          blocks.push(`<div class="global-search-head">Транзакции</div>`);
          blocks.push(
            data.ledger
              .map(
                (l) =>
                  `<a class="global-search-item" href="#user-${l.user_id}">user #${l.user_id} · ${l.type} · ${l.amount_usdt} USDT</a>`
              )
              .join("")
          );
        }
        if (!blocks.length) {
          resultsEl.innerHTML = `<div class="global-search-item">Ничего не найдено</div>`;
        } else {
          resultsEl.innerHTML = blocks.join("");
        }
        show();
      } catch (e) {
        resultsEl.innerHTML = `<div class="global-search-item">Ошибка поиска</div>`;
        show();
      }
    }, 220);
  });
}

function ensureMessagesNavAndSection() {
  const nav = document.querySelector(".sidebar nav");
  if (nav && !nav.querySelector('a[data-section="messages"]')) {
    const dealsLink = nav.querySelector('a[data-section="deals"]');
    const link = document.createElement("a");
    link.href = "#messages";
    link.setAttribute("data-section", "messages");
    link.innerHTML = `
      <span class="nav-icon">📣</span>
      <span class="nav-label">Сообщения</span>
    `;
    if (dealsLink && dealsLink.nextSibling) {
      nav.insertBefore(link, dealsLink.nextSibling);
    } else {
      nav.appendChild(link);
    }
  }

  const content = document.querySelector("main.content");
  if (content && !document.getElementById("messages-section")) {
    const section = document.createElement("section");
    section.id = "messages-section";
    section.className = "section hidden";
    const dealsSection = document.getElementById("deals-section");
    if (dealsSection && dealsSection.nextSibling) {
      content.insertBefore(section, dealsSection.nextSibling);
    } else {
      content.appendChild(section);
    }
  }
}

async function handleLogin(event) {
  event.preventDefault();
  const token = document.getElementById("token").value.trim();
  const otpCode = document.getElementById("otp-code")?.value?.trim() || "";
  const errorEl = document.getElementById("login-error");
  errorEl.textContent = "";
  try {
    const resp = await fetch(API_BASE + "/login", {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token, otp_code: otpCode || null }),
    });
    if (!resp.ok) {
      const data = await resp.json().catch(() => ({}));
      throw new Error(data.detail || "Ошибка входа");
    }
    showMainView();
    loadDashboard();
  } catch (e) {
    errorEl.textContent = e.message;
  }
}

async function loadDashboard() {
  const section = document.getElementById("dashboard-section");
  section.innerHTML = "<h1>Дашборд</h1><p>Загрузка...</p>";
  try {
    const range = localStorage.getItem(DASHBOARD_RANGE_KEY) || "7d";
    const dayCount = range === "1d" ? 1 : range === "30d" ? 30 : 7;
    const dateOnly = (d) => {
      const y = d.getFullYear();
      const m = String(d.getMonth() + 1).padStart(2, "0");
      const dd = String(d.getDate()).padStart(2, "0");
      return `${y}-${m}-${dd}`;
    };
    const buildRange = (shiftDays = 0) => {
      const now = new Date();
      const end = new Date(now.getTime() - shiftDays * 24 * 60 * 60 * 1000);
      const start = new Date(end.getTime() - (dayCount - 1) * 24 * 60 * 60 * 1000);
      return { from: dateOnly(start), to: dateOnly(end) };
    };
    const currentRange = buildRange(0);
    const previousRange = buildRange(dayCount);
    const qs = (r, extra = "") =>
      `page=1&page_size=1&date_from=${encodeURIComponent(r.from)}&date_to=${encodeURIComponent(r.to)}${extra}`;
    const [data, ext, logsData, depCurrent, depPrev, depPaidCurrent, depPaidPrev, logsCurrent, logsPrev, depositsRange] = await Promise.all([
      apiRequest("/dashboard"),
      apiRequest(`/dashboard/extended?period_days=${dayCount}`).catch(() => null),
      apiRequest("/logs?page=1&page_size=8").catch(() => ({ items: [] })),
      apiRequest(`/deposits?${qs(currentRange)}`).catch(() => ({ total: 0 })),
      apiRequest(`/deposits?${qs(previousRange)}`).catch(() => ({ total: 0 })),
      apiRequest(`/deposits?${qs(currentRange, "&status_filter=finished")}`).catch(() => ({ total: 0 })),
      apiRequest(`/deposits?${qs(previousRange, "&status_filter=finished")}`).catch(() => ({ total: 0 })),
      apiRequest("/logs?page=1&page_size=300").catch(() => ({ items: [] })),
      apiRequest("/logs?page=2&page_size=300").catch(() => ({ items: [] })),
      apiRequest(`/deposits?page=1&page_size=500&date_from=${encodeURIComponent(currentRange.from)}&date_to=${encodeURIComponent(currentRange.to)}`).catch(() => ({ items: [] })),
    ]);
    const activeDealText = data.active_deal_number
      ? `#${data.active_deal_number} · ${data.active_deal_percent}% · инвестировано ${data.active_deal_invested_usdt} USDT`
      : "Нет активной сделки";
    const activeDealCloseText = data.active_deal_closes_at
      ? new Date(data.active_deal_closes_at).toLocaleString()
      : "—";
    const systemStatus =
      data.pending_withdrawals_count > 30
        ? { text: "Проблемы", cls: "status-expired" }
        : { text: "OK", cls: "status-paid" };
    const recentEventsHtml = (logsData.items || []).length
      ? (logsData.items || [])
          .map(
            (l) => `
          <li class="event-feed-item">
            <span class="event-feed-main">${l.action_type} · ${l.entity_type} #${l.entity_id}</span>
            <span class="event-feed-time">${new Date(l.created_at).toLocaleString()}</span>
          </li>`
          )
          .join("")
      : `<li class="event-feed-item event-feed-empty">Событий пока нет</li>`;
    const kpiDelta = (cur, prev) => {
      const c = Number(cur || 0);
      const p = Number(prev || 0);
      if (p <= 0 && c > 0) return { txt: "+100%", cls: "kpi-positive" };
      if (p <= 0 && c === 0) return { txt: "0%", cls: "kpi-neutral" };
      const pct = ((c - p) / p) * 100;
      const sign = pct > 0 ? "+" : "";
      const cls = pct > 0 ? "kpi-positive" : pct < 0 ? "kpi-negative" : "kpi-neutral";
      return { txt: `${sign}${pct.toFixed(1)}%`, cls };
    };
    const countByRange = (rows, r) =>
      (rows || []).filter((x) => {
        const dt = x.created_at ? new Date(x.created_at) : null;
        if (!dt || Number.isNaN(dt.getTime())) return false;
        const d = dateOnly(dt);
        return d >= r.from && d <= r.to;
      }).length;
    const eventsCur = countByRange(logsCurrent.items || [], currentRange);
    const eventsPrev = countByRange([...(logsCurrent.items || []), ...(logsPrev.items || [])], previousRange);
    const depDelta = kpiDelta(depCurrent.total, depPrev.total);
    const depPaidDelta = kpiDelta(depPaidCurrent.total, depPaidPrev.total);
    const eventsDelta = kpiDelta(eventsCur, eventsPrev);
    const activeRangeLabel = range === "1d" ? "День" : range === "30d" ? "Месяц" : "Неделя";
    const liveEnabled = localStorage.getItem(DASHBOARD_LIVE_KEY) === "1";
    const conversionPct = Number(ext?.deposit_to_invest_conversion_pct || 0);
    const avgCheck = Number(ext?.average_deposit_usdt || 0);
    const topByBalance = ext?.top_users_by_balance || [];
    const topReferrers = ext?.top_referrers || [];
    const dau24h = Number(ext?.dau_24h || 0);
    const anomalyAlerts = ext?.anomaly_alerts || [];
    const systemIssues = [];
    if (data.pending_withdrawals_count > 30) {
      systemIssues.push(`Высокая очередь выводов: ${data.pending_withdrawals_count}`);
    }
    for (const a of anomalyAlerts) {
      const msg = String(a?.message || "").trim();
      if (msg) systemIssues.push(msg);
    }
    const uniqueSystemIssues = [...new Set(systemIssues)];
    const computedSystemStatus =
      uniqueSystemIssues.length > 0
        ? { text: "Проблемы", cls: "status-expired" }
        : systemStatus;
    const labels = buildDateSeries(dayCount);
    const allLogRows = [...(logsCurrent.items || []), ...(logsPrev.items || []), ...(logsData.items || [])];
    const heatmapBuckets = {};
    allLogRows.forEach((l) => {
      if (!l.created_at) return;
      const dt = new Date(l.created_at);
      if (Number.isNaN(dt.getTime())) return;
      const dayKey = dateOnly(dt);
      if (dayKey < currentRange.from || dayKey > currentRange.to) return;
      const dow = dt.getDay();
      const hour = dt.getHours();
      const key = `${dow}-${hour}`;
      heatmapBuckets[key] = (heatmapBuckets[key] || 0) + 1;
    });
    const heatmapMax = Math.max(1, ...Object.values(heatmapBuckets));
    const heatmapRows = [0, 1, 2, 3, 4, 5, 6];
    const heatmapLabels = ["Вс", "Пн", "Вт", "Ср", "Чт", "Пт", "Сб"];
    const logCountByDay = {};
    allLogRows.forEach((l) => {
      if (!l.created_at) return;
      const d = new Date(l.created_at);
      if (Number.isNaN(d.getTime())) return;
      const k = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
      logCountByDay[k] = (logCountByDay[k] || 0) + 1;
    });
    const eventsSeries = labels.map((d) => logCountByDay[d] || 0);
    const depCreatedByDay = {};
    const depPaidByDay = {};
    (depositsRange.items || []).forEach((d) => {
      const src = d.created_at || d.paid_at || d.completed_at;
      if (!src) return;
      const dt = new Date(src);
      if (Number.isNaN(dt.getTime())) return;
      const key = `${dt.getFullYear()}-${String(dt.getMonth() + 1).padStart(2, "0")}-${String(dt.getDate()).padStart(2, "0")}`;
      depCreatedByDay[key] = (depCreatedByDay[key] || 0) + 1;
      if ((d.status || "").toLowerCase() === "finished" || (d.status || "").toLowerCase() === "paid") {
        depPaidByDay[key] = (depPaidByDay[key] || 0) + 1;
      }
    });
    const createdSeries = labels.map((d) => depCreatedByDay[d] || 0);
    const paidSeries = labels.map((d) => depPaidByDay[d] || 0);
    const eventsMax = Math.max(1, ...eventsSeries);
    const depMax = Math.max(1, ...createdSeries, ...paidSeries);

    section.innerHTML = `
      <h1>Дашборд</h1>
      <div class="toolbar dashboard-range-toolbar">
        <div class="range-segment">
          <button type="button" class="range-btn ${range === "1d" ? "active" : ""}" data-range="1d">День</button>
          <button type="button" class="range-btn ${range === "7d" ? "active" : ""}" data-range="7d">Неделя</button>
          <button type="button" class="range-btn ${range === "30d" ? "active" : ""}" data-range="30d">Месяц</button>
        </div>
        <label class="filter-label dashboard-live-toggle">
          Live
          <label style="display:inline-flex;align-items:center;gap:6px;">
            <input type="checkbox" id="dashboard-live-toggle" ${liveEnabled ? "checked" : ""} />
            Обновлять каждые 30с
          </label>
        </label>
      </div>
      <div class="cards-grid">
        <div class="stat-card">
          <div class="stat-label">Пользователей</div>
          <div class="stat-value">${data.users_count}</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">Общий баланс (ledger)</div>
          <div class="stat-value">${data.total_ledger_balance_usdt} <span class="stat-unit">USDT</span></div>
        </div>
        <div class="stat-card">
          <div class="stat-label">Pending выводов</div>
          <div class="stat-value">${data.pending_withdrawals_count}</div>
        </div>
        <div class="stat-card stat-wide">
          <div class="stat-label">Текущая сделка</div>
          <div class="stat-value">${activeDealText}</div>
        </div>
      </div>
      <div class="kpi-row">
        <div class="kpi-card">
          <div class="kpi-title">Депозиты (${activeRangeLabel})</div>
          <div class="kpi-value">${depCurrent.total || 0}</div>
          <div class="kpi-delta ${depDelta.cls}">к прошлому периоду: ${depDelta.txt}</div>
        </div>
        <div class="kpi-card">
          <div class="kpi-title">Оплаченные депозиты (${activeRangeLabel})</div>
          <div class="kpi-value">${depPaidCurrent.total || 0}</div>
          <div class="kpi-delta ${depPaidDelta.cls}">к прошлому периоду: ${depPaidDelta.txt}</div>
        </div>
        <div class="kpi-card">
          <div class="kpi-title">События audit (${activeRangeLabel})</div>
          <div class="kpi-value">${eventsCur}</div>
          <div class="kpi-delta ${eventsDelta.cls}">к прошлому периоду: ${eventsDelta.txt}</div>
        </div>
        <div class="kpi-card">
          <div class="kpi-title">Конверсия депозит → инвестиция</div>
          <div class="kpi-value">${conversionPct.toFixed(2)}%</div>
          <div class="kpi-delta kpi-neutral">${ext ? `${ext.converted_users_count}/${ext.deposit_users_count} пользователей` : "нет данных"}</div>
        </div>
        <div class="kpi-card">
          <div class="kpi-title">Средний чек депозита</div>
          <div class="kpi-value">${avgCheck.toFixed(2)} USDT</div>
          <div class="kpi-delta kpi-neutral">за ${activeRangeLabel.toLowerCase()}</div>
        </div>
        <div class="kpi-card">
          <div class="kpi-title">DAU (24ч)</div>
          <div class="kpi-value">${dau24h}</div>
          <div class="kpi-delta kpi-neutral">уникальных активных пользователей</div>
        </div>
      </div>
      <div class="dashboard-panels">
        <div class="panel-card">
          <h3 class="dashboard-panel-title">Алерты аномалий</h3>
          <ul class="alerts-list">
            ${
              anomalyAlerts.length
                ? anomalyAlerts
                    .map((a) => `<li class="alert-item ${a.severity === "high" ? "high" : a.severity === "medium" ? "medium" : "low"}">${escapeHtmlAttr(a.message || "")}</li>`)
                    .join("")
                : `<li class="event-feed-empty">Аномалий не обнаружено</li>`
            }
          </ul>
        </div>
        <div class="panel-card">
          <h3 class="dashboard-panel-title">Топ пользователей по балансу</h3>
          <ul class="top-list">
            ${
              topByBalance.length
                ? topByBalance
                    .map(
                      (u, idx) => `<li>
                        <span class="top-rank">#${idx + 1}</span>
                        <span class="top-name">${escapeHtmlAttr(u.username || `user_${u.user_id}`)} (${u.telegram_id})</span>
                        <span class="top-value">${u.balance_usdt} USDT</span>
                      </li>`
                    )
                    .join("")
                : `<li class="event-feed-empty">Нет данных</li>`
            }
          </ul>
        </div>
        <div class="panel-card">
          <h3 class="dashboard-panel-title">Топ рефералов</h3>
          <ul class="top-list">
            ${
              topReferrers.length
                ? topReferrers
                    .map(
                      (u, idx) => `<li>
                        <span class="top-rank">#${idx + 1}</span>
                        <span class="top-name">${escapeHtmlAttr(u.username || `user_${u.user_id}`)} (${u.telegram_id})</span>
                        <span class="top-value">${u.referrals_count} refs · ${u.referral_income_usdt} USDT</span>
                      </li>`
                    )
                    .join("")
                : `<li class="event-feed-empty">Нет данных</li>`
            }
          </ul>
        </div>
        <div class="panel-card">
          <h3 class="dashboard-panel-title">График активности (audit)</h3>
          <div class="mini-chart">
            <div class="mini-chart-bars">${renderMiniBars(labels, eventsSeries, eventsMax)}</div>
            <div class="mini-chart-legend">Диапазон: ${labels[0]} → ${labels[labels.length - 1]} · max: ${eventsMax}</div>
          </div>
        </div>
        <div class="panel-card">
          <h3 class="dashboard-panel-title">Heatmap активности (день/час)</h3>
          <div class="activity-heatmap">
            ${heatmapRows
              .map((dow) => {
                const rowCells = Array.from({ length: 24 })
                  .map((_, hour) => {
                    const count = Number(heatmapBuckets[`${dow}-${hour}`] || 0);
                    const lv = Math.min(4, Math.ceil((count / heatmapMax) * 4));
                    return `<span class="heat-cell lv-${lv}" title="${heatmapLabels[dow]} ${String(hour).padStart(2, "0")}:00 · ${count}"></span>`;
                  })
                  .join("");
                return `<div class="heat-row"><span class="heat-row-label">${heatmapLabels[dow]}</span><div class="heat-row-cells">${rowCells}</div></div>`;
              })
              .join("")}
          </div>
          <div class="mini-chart-legend">Интенсивность: 0 → ${heatmapMax} событий в слоте часа</div>
        </div>
        <div class="panel-card">
          <h3 class="dashboard-panel-title">График депозитов (создано / оплачено)</h3>
          <div class="mini-chart">
            <div class="mini-chart-bars dual">
              ${labels
                .map((label, i) => {
                  const c = createdSeries[i] || 0;
                  const p = paidSeries[i] || 0;
                  const hc = depMax > 0 ? Math.max(4, Math.round((c / depMax) * 100)) : 4;
                  const hp = depMax > 0 ? Math.max(4, Math.round((p / depMax) * 100)) : 4;
                  return `<div class="mini-bar-item dual" title="${label}: created=${c}, paid=${p}">
                    <div class="mini-bar created" style="height:${hc}%"></div>
                    <div class="mini-bar paid" style="height:${hp}%"></div>
                  </div>`;
                })
                .join("")}
            </div>
            <div class="mini-chart-legend">Created / Paid · max: ${depMax}</div>
          </div>
        </div>
      </div>
      <div class="dashboard-panels">
        <div class="panel-card">
          <h3 class="dashboard-panel-title">Быстрые действия</h3>
          <div class="quick-actions-grid">
            <button type="button" class="quick-action-btn" data-target="#users">Пользователи</button>
            <button type="button" class="quick-action-btn" data-target="#deals">Сделки</button>
            <button type="button" class="quick-action-btn" data-target="#deposits">Пополнения</button>
            <button type="button" class="quick-action-btn" data-target="#withdrawals">Выводы</button>
          </div>
        </div>
        <div class="panel-card">
          <h3 class="dashboard-panel-title">Состояние системы</h3>
          <ul class="health-list">
            <li>Статус: <span class="status-badge ${computedSystemStatus.cls}">${computedSystemStatus.text}</span></li>
            <li>Активная сделка: <strong>${data.active_deal_number ? "да" : "нет"}</strong></li>
            <li>Закрытие текущей сделки: <strong>${activeDealCloseText}</strong></li>
            <li>Ожидают вывода: <strong>${data.pending_withdrawals_count}</strong></li>
            ${
              uniqueSystemIssues.length
                ? `<li>Причины: <strong>${uniqueSystemIssues.map((x) => escapeHtmlAttr(x)).join(" • ")}</strong></li>`
                : ""
            }
          </ul>
        </div>
        <div class="panel-card">
          <h3 class="dashboard-panel-title">Последние события</h3>
          <ul class="event-feed">${recentEventsHtml}</ul>
        </div>
      </div>
    `;

    section.querySelectorAll(".quick-action-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        const target = btn.getAttribute("data-target");
        if (target) {
          location.hash = target;
        }
      });
    });
    section.querySelectorAll(".range-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        const next = btn.getAttribute("data-range");
        if (!next) return;
        localStorage.setItem(DASHBOARD_RANGE_KEY, next);
        loadDashboard();
      });
    });
    document.getElementById("dashboard-live-toggle")?.addEventListener("change", (e) => {
      const on = Boolean(e.target.checked);
      localStorage.setItem(DASHBOARD_LIVE_KEY, on ? "1" : "0");
      if (dashboardAutoRefreshTimer) {
        clearInterval(dashboardAutoRefreshTimer);
        dashboardAutoRefreshTimer = null;
      }
      if (on) {
        dashboardAutoRefreshTimer = setInterval(() => {
          if ((location.hash || "#dashboard") === "#dashboard") loadDashboard();
        }, 30000);
      }
    });
    if (dashboardAutoRefreshTimer) {
      clearInterval(dashboardAutoRefreshTimer);
      dashboardAutoRefreshTimer = null;
    }
    if (liveEnabled) {
      dashboardAutoRefreshTimer = setInterval(() => {
        if ((location.hash || "#dashboard") === "#dashboard") loadDashboard();
      }, 30000);
    }
  } catch (e) {
    if (isUnauthorizedError(e)) throw e;
    section.innerHTML = `<h1>Дашборд</h1><div class="error">${e.message}</div>`;
  }
}

async function loadUsers() {
  const section = document.getElementById("users-section");
  const searchEl = document.getElementById("users-search");
  if (searchEl) {
    usersListState.search = searchEl.value.trim();
  }

  section.innerHTML = `
    <h1>Пользователи</h1>
    <p class="section-desc">Список пользователей, кеш баланса и текущие инвестиции. Пагинация и поиск — без бесконечной прокрутки.</p>
    <div class="panel-card">
      <div class="toolbar users-toolbar">
        <div class="search-field">
          <span class="search-field-icon">🔍</span>
          <input id="users-search" type="text" placeholder="Поиск по username / Telegram ID" value="${escapeHtmlAttr(usersListState.search)}" />
        </div>
        <button type="button" id="users-search-btn">Искать</button>
        <label class="page-size-label">Активность
          <select id="users-activity-filter" class="page-size-select" title="Фильтр по активности">
            <option value="">Все</option>
            <option value="with_balance">С балансом</option>
            <option value="with_referrals">С рефералами</option>
          </select>
        </label>
        <button type="button" id="users-save-preset-btn" class="btn-secondary-small" title="Сохранить текущий поиск как пресет">Сохранить фильтр</button>
        <select id="users-presets-select" class="page-size-select" title="Быстрый выбор сохранённого фильтра">
          <option value="">Сохранённые фильтры</option>
        </select>
        <button type="button" id="users-apply-preset-btn" class="btn-secondary-small" title="Применить выбранный фильтр">Применить фильтр</button>
        <label class="page-size-label">На странице
          <select id="users-page-size" class="page-size-select">
            <option value="25">25</option>
            <option value="50">50</option>
            <option value="100">100</option>
          </select>
        </label>
      </div>
      <div class="skeleton-line" style="width: 60%; margin-top: 8px;"></div>
      <div class="skeleton-line" style="width: 85%; margin-top: 12px;"></div>
      <div class="skeleton-line" style="width: 78%; margin-top: 12px;"></div>
    </div>
  `;

  const sizeSel = document.getElementById("users-page-size");
  if (sizeSel) sizeSel.value = String(usersListState.pageSize);

  try {
    const q = usersListState.search
      ? `&search=${encodeURIComponent(usersListState.search)}`
      : "";
    const aq = usersListState.activityFilter
      ? `&activity_filter=${encodeURIComponent(usersListState.activityFilter)}`
      : "";
    const data = await apiRequest(
      `/users?page=${usersListState.page}&page_size=${usersListState.pageSize}${q}${aq}`
    );
    const totalPages = Math.max(1, Math.ceil(data.total / data.page_size) || 1);
    if (usersListState.page > totalPages) {
      usersListState.page = totalPages;
      return loadUsers();
    }

    const tagsMap = readUserTags();
    const rows = data.items
      .map((u) => {
        const mismatch =
          Number(u.balance_usdt) !== Number(u.ledger_balance_usdt)
            ? `<div class="warning">Кэш баланса != ledger</div>`
            : "";
        return `
        <tr class="table-row-link" data-user-id="${u.id}">
          <td>${u.id}</td>
          <td>${u.telegram_id}</td>
          <td>${u.username || ""}</td>
          <td><input type="text" class="inline-tag-input" data-user-id="${u.id}" value="${escapeHtmlAttr(tagsMap[String(u.id)] || "")}" placeholder="VIP / note" title="Локальная метка пользователя (inline edit)" /></td>
          <td class="num-cell">${u.balance_usdt}</td>
          <td class="num-cell">${u.ledger_balance_usdt}${mismatch}</td>
          <td class="num-cell">${u.invested_now_usdt}</td>
          <td>
            <div class="row-actions">
              <button type="button" class="btn-secondary-small user-open-btn" data-user-id="${u.id}">Открыть</button>
              <button type="button" class="btn-secondary-small user-copy-tg-btn" data-telegram-id="${u.telegram_id}">Копировать TG ID</button>
            </div>
          </td>
        </tr>`;
      })
      .join("");
    const rowsHtml = rows || `<tr><td colspan="8"><div class="empty-state"><strong>Пользователи не найдены</strong><span>Попробуйте очистить поиск или поменять фильтры.</span></div></td></tr>`;

    const paginationHtml = `
      <div class="pagination-bar">
        <span class="pagination-info">Страница <strong>${data.page}</strong> из <strong>${totalPages}</strong> · всего пользователей: <strong>${data.total}</strong></span>
        <div class="pagination-actions">
          <button type="button" id="users-prev" class="btn-secondary-small" ${data.page <= 1 ? "disabled" : ""}>← Назад</button>
          <button type="button" id="users-next" class="btn-secondary-small" ${data.page >= totalPages ? "disabled" : ""}>Вперёд →</button>
        </div>
      </div>
    `;

    section.innerHTML = `
      <h1>Пользователи</h1>
      <p class="section-desc">Список пользователей, кеш баланса и текущие инвестиции. Пагинация и поиск — без бесконечной прокрутки.</p>
      <div class="panel-card">
        <div class="toolbar users-toolbar">
          <div class="search-field">
            <span class="search-field-icon">🔍</span>
            <input id="users-search" type="text" placeholder="Поиск по username / Telegram ID" value="${escapeHtmlAttr(usersListState.search)}" />
          </div>
          <button type="button" id="users-search-btn">Искать</button>
          <label class="page-size-label">Активность
            <select id="users-activity-filter" class="page-size-select" title="Фильтр по активности">
              <option value="">Все</option>
              <option value="with_balance">С балансом</option>
              <option value="with_referrals">С рефералами</option>
            </select>
          </label>
          <button type="button" id="users-save-preset-btn" class="btn-secondary-small" title="Сохранить текущий поиск как пресет">Сохранить фильтр</button>
          <select id="users-presets-select" class="page-size-select" title="Быстрый выбор сохранённого фильтра">
            <option value="">Сохранённые фильтры</option>
          </select>
          <button type="button" id="users-apply-preset-btn" class="btn-secondary-small" title="Применить выбранный фильтр">Применить фильтр</button>
          <label class="page-size-label">На странице
            <select id="users-page-size" class="page-size-select">
              <option value="25">25</option>
              <option value="50">50</option>
              <option value="100">100</option>
            </select>
          </label>
        </div>
        ${paginationHtml}
        <div class="table-wrapper">
          <div class="table-wrapper-inner">
            <table>
              <thead>
                <tr>
                  <th>ID</th>
                  <th>Telegram ID</th>
                  <th>Username</th>
                  <th>Метка</th>
                  <th>balance_usdt</th>
                  <th>ledger_balance</th>
                  <th>invested_now</th>
                  <th>Действие</th>
                </tr>
              </thead>
              <tbody>${rowsHtml}</tbody>
            </table>
          </div>
        </div>
        ${paginationHtml}
      </div>
    `;

    const sizeSelect = document.getElementById("users-page-size");
    const activitySelect = document.getElementById("users-activity-filter");
    if (sizeSelect) {
      sizeSelect.value = String(usersListState.pageSize);
      sizeSelect.onchange = () => {
        usersListState.pageSize = parseInt(sizeSelect.value, 10) || 25;
        usersListState.page = 1;
        localStorage.setItem(
          USERS_FILTERS_KEY,
          JSON.stringify({ pageSize: usersListState.pageSize, search: usersListState.search, activityFilter: usersListState.activityFilter || "" })
        );
        loadUsers();
      };
    }
    if (activitySelect) {
      activitySelect.value = usersListState.activityFilter || "";
      activitySelect.onchange = () => {
        usersListState.activityFilter = activitySelect.value || "";
        usersListState.page = 1;
        saveState(USERS_FILTERS_KEY, {
          pageSize: usersListState.pageSize,
          search: usersListState.search,
          activityFilter: usersListState.activityFilter,
        });
        loadUsers();
      };
    }

    document.getElementById("users-search-btn").onclick = () => {
      const v = document.getElementById("users-search")?.value?.trim() ?? "";
      usersListState.search = v;
      usersListState.page = 1;
      localStorage.setItem(
        USERS_FILTERS_KEY,
        JSON.stringify({ pageSize: usersListState.pageSize, search: usersListState.search, activityFilter: usersListState.activityFilter || "" })
      );
      loadUsers();
    };
    const presets = readUsersPresets();
    const presetsSelect = document.getElementById("users-presets-select");
    if (presetsSelect) {
      presetsSelect.innerHTML =
        `<option value="">Сохранённые фильтры</option>` +
        presets
          .map((p, idx) => `<option value="${idx}">${escapeHtmlAttr(p.name)} (${escapeHtmlAttr(p.search) || "пустой поиск"})</option>`)
          .join("");
    }
    document.getElementById("users-save-preset-btn").onclick = async () => {
      const searchValue = document.getElementById("users-search")?.value?.trim() ?? "";
      const nameResult = await openUxDialog({
        title: "Сохранить фильтр",
        message: "Название пресета (до 24 символов)",
        inputPlaceholder: "Например: VIP / Support / Test",
        confirmText: "Сохранить",
        cancelText: "Отмена",
      });
      const presetName = (nameResult.value || "").trim();
      if (!nameResult.confirmed || !presetName) return;
      const next = [{ name: presetName.slice(0, 24), search: searchValue }, ...readUsersPresets()];
      const dedup = [];
      for (const item of next) {
        if (!dedup.some((x) => x.name === item.name)) dedup.push(item);
      }
      writeUsersPresets(dedup);
      showToast("Фильтр сохранён", "success");
      loadUsers();
    };
    document.getElementById("users-apply-preset-btn").onclick = () => {
      const idx = parseInt(document.getElementById("users-presets-select")?.value || "", 10);
      if (Number.isNaN(idx)) {
        showToast("Выберите сохранённый фильтр", "info");
        return;
      }
      const preset = readUsersPresets()[idx];
      if (!preset) return;
      usersListState.search = preset.search;
      usersListState.page = 1;
      saveState(USERS_FILTERS_KEY, { pageSize: usersListState.pageSize, search: usersListState.search, activityFilter: usersListState.activityFilter || "" });
      loadUsers();
    };
    document.getElementById("users-search")?.addEventListener("keydown", (ev) => {
      if (ev.key === "Enter") {
        ev.preventDefault();
        document.getElementById("users-search-btn").click();
      }
    });

    document.getElementById("users-prev").onclick = () => {
      if (usersListState.page > 1) {
        usersListState.page -= 1;
        loadUsers();
      }
    };
    document.getElementById("users-next").onclick = () => {
      usersListState.page += 1;
      loadUsers();
    };

    section.querySelectorAll("tr.table-row-link").forEach((row) => {
      const id = row.getAttribute("data-user-id");
      row.onclick = () => {
        if (!id) return;
        location.hash = `#user-${id}`;
      };
    });
    section.querySelectorAll(".user-open-btn").forEach((btn) => {
      btn.addEventListener("click", (ev) => {
        ev.stopPropagation();
        const id = btn.getAttribute("data-user-id");
        if (!id) return;
        location.hash = `#user-${id}`;
      });
    });
    section.querySelectorAll(".user-copy-tg-btn").forEach((btn) => {
      btn.addEventListener("click", async (ev) => {
        ev.stopPropagation();
        const tid = btn.getAttribute("data-telegram-id") || "";
        const ok = await copyTextToClipboard(tid);
        showToast(ok ? "Telegram ID скопирован" : "Не удалось скопировать", ok ? "success" : "error");
      });
    });
    section.querySelectorAll(".inline-tag-input").forEach((input) => {
      input.addEventListener("click", (ev) => ev.stopPropagation());
      input.addEventListener("keydown", (ev) => {
        if (ev.key === "Enter") {
          ev.preventDefault();
          input.blur();
        }
      });
      input.addEventListener("blur", () => {
        const userId = input.getAttribute("data-user-id");
        if (!userId) return;
        writeUserTag(userId, input.value);
        showToast("Метка сохранена", "info");
      });
    });
  } catch (e) {
    section.innerHTML = `<h1>Пользователи</h1><div class="error">${e.message}</div>`;
  }
}

function switchSection(hash) {
  if ((hash || "#dashboard") !== "#dashboard" && dashboardAutoRefreshTimer) {
    clearInterval(dashboardAutoRefreshTimer);
    dashboardAutoRefreshTimer = null;
  }
  updateBreadcrumbs(hash || "#dashboard");
  setPageActions(hash || "#dashboard");
  const sections = ["dashboard", "users", "deals", "messages", "deposits", "withdrawals", "logs", "settings", "user"];
  const sidebarLinks = document.querySelectorAll(".sidebar nav a");
  sections.forEach((name) => {
    const el = document.getElementById(`${name}-section`);
    if (!el) return;
    if (hash === `#${name}` || (name === "user" && hash.startsWith("#user-"))) {
      el.classList.remove("hidden");
    } else {
      el.classList.add("hidden");
    }
  });

  sidebarLinks.forEach((link) => {
    const target = link.getAttribute("data-section");
    if (!target) return;
    if (
      hash === `#${target}` ||
      (target === "user" && hash.startsWith("#user-")) ||
      (!hash && target === "dashboard")
    ) {
      link.classList.add("active");
    } else {
      link.classList.remove("active");
    }
  });
  if (hash === "#users") {
    loadUsers();
  } else if (hash === "#dashboard" || !hash) {
    loadDashboard();
  } else if (hash === "#deals") {
    loadDeals();
  } else if (hash === "#messages") {
    loadMessages();
  } else if (hash === "#deposits") {
    loadDeposits();
  } else if (hash.startsWith("#user-")) {
    const id = hash.replace("#user-", "");
    loadUserDetail(id);
  } else if (hash === "#withdrawals") {
    loadWithdrawals();
  } else if (hash === "#logs") {
    loadLogs();
  } else if (hash === "#settings") {
    loadSettings();
  }
}

async function loadDeals() {
  const section = document.getElementById("deals-section");
  section.innerHTML = `<h1>Сделки</h1><div class="panel-card"><div class="skeleton-line" style="width:72%;"></div><div class="skeleton-line" style="width:88%; margin-top:12px;"></div></div>`;
  try {
    const [deals, statusRes] = await Promise.all([
      apiRequest("/deals"),
      apiRequest("/deals/status").catch(() => ({ active_deal: null })),
    ]);
    const nowTs = Date.now();
    const calcDealProgress = (deal) => {
      const start = deal?.start_at ? new Date(deal.start_at).getTime() : null;
      const end = deal?.end_at ? new Date(deal.end_at).getTime() : null;
      if (!start || !end || end <= start) return { percent: 0, leftMs: null, label: "—" };
      const percent = Math.max(0, Math.min(100, ((nowTs - start) / (end - start)) * 100));
      const leftMs = Math.max(0, end - nowTs);
      const h = Math.floor(leftMs / 3600000);
      const m = Math.floor((leftMs % 3600000) / 60000);
      return { percent, leftMs, label: `${h}ч ${m}м` };
    };
    const calcRoiClass = (value) => (Number(value || 0) >= 0 ? "kpi-positive" : "kpi-negative");
    const statsList = await Promise.all(
      deals.map((d) => apiRequest(`/deals/${d.id}/stats`).catch(() => null))
    );
    const statsByDealId = {};
    statsList.forEach((s) => {
      if (s?.deal_id) statsByDealId[String(s.deal_id)] = s;
    });
    const dealRiskAlerts = deals
      .map((d) => {
        const s = statsByDealId[String(d.id)] || {};
        const alerts = Array.isArray(s.risk_alerts) ? s.risk_alerts : [];
        if (!alerts.length) return null;
        return {
          dealNumber: d.number,
          alerts,
          riskLevel: s.risk_level || d.risk_level || "",
          riskNote: s.risk_note || d.risk_note || "",
        };
      })
      .filter(Boolean);
    const activeDeal = statusRes.active_deal;

    const statusBlock =
      activeDeal == null
        ? `<div class="deal-status-card"><h3>Статус сделки</h3><p class="deal-status-none">Нет активной сделки</p><p class="deal-status-hint">Уведомление можно отправить только при активной сделке.</p></div>`
        : `
        <div class="deal-status-card">
          <h3>Статус сделки</h3>
          <div class="deal-status-fields">
            <div class="deal-status-row"><span class="deal-status-label">Сделка:</span> #${activeDeal.number} · ${activeDeal.status}</div>
            <div class="deal-status-row"><span class="deal-status-label">Окно:</span> ${activeDeal.start_at ? new Date(activeDeal.start_at).toLocaleString() : "—"} — ${activeDeal.end_at ? new Date(activeDeal.end_at).toLocaleString() : "—"}</div>
            <div class="deal-status-row"><span class="deal-status-label">До закрытия:</span> ${calcDealProgress(activeDeal).label}</div>
            <div class="deal-status-row"><span class="deal-status-label">Прогресс:</span> ${Math.round(calcDealProgress(activeDeal).percent)}%</div>
            <div class="deal-progress-track"><div class="deal-progress-fill" style="width:${calcDealProgress(activeDeal).percent}%;"></div></div>
            <div class="deal-status-row"><span class="deal-status-label">Уведомление о закрытии отправлено:</span> ${activeDeal.close_notification_sent ? "Да" : "Нет"}</div>
          </div>
          <div class="toolbar deal-status-toolbar">
            <button type="button" id="deal-send-notifications-btn">Отправить уведомления о сделке</button>
            <button type="button" id="deal-force-close-btn">Закрыть сделку досрочно</button>
          </div>
        </div>`;

    const rows = deals
      .map(
        (d) => {
          const p = calcDealProgress(d);
          const roi = Number(d.profit_percent ?? d.percent ?? 0);
          const stats = statsByDealId[String(d.id)] || {};
          return `
      <tr data-deal-id="${d.id}">
        <td>${d.number}</td>
        <td>${d.status}</td>
        <td>${p.label}</td>
        <td>
          <div class="deal-progress-track"><div class="deal-progress-fill" style="width:${p.percent}%;"></div></div>
          <div class="mini-hint">${Math.round(p.percent)}%</div>
        </td>
        <td>
          <input type="number" step="0.01" min="0" value="${d.profit_percent ?? d.percent ?? 0}" class="deal-percent-input" />
        </td>
        <td>
          <input type="number" step="0.01" min="0" value="${d.min_participation_usdt ?? ""}" class="deal-min-input" placeholder="min" />
          <input type="number" step="0.01" min="0" value="${d.max_participation_usdt ?? ""}" class="deal-max-input" placeholder="max" style="margin-top:6px;" />
        </td>
        <td>
          <input type="number" step="1" min="1" value="${d.max_participants ?? ""}" class="deal-max-participants-input" placeholder="—" />
        </td>
        <td>
          <select class="deal-risk-level-input">
            <option value="" ${!d.risk_level ? "selected" : ""}>—</option>
            <option value="low" ${d.risk_level === "low" ? "selected" : ""}>low</option>
            <option value="medium" ${d.risk_level === "medium" ? "selected" : ""}>medium</option>
            <option value="high" ${d.risk_level === "high" ? "selected" : ""}>high</option>
          </select>
          <input type="text" value="${escapeHtmlAttr(d.risk_note || "")}" class="deal-risk-note-input" placeholder="risk note" style="margin-top:6px;" />
          ${
            (stats.risk_alerts || []).length
              ? `<div class="mini-hint kpi-negative">${escapeHtmlAttr((stats.risk_alerts || []).join(", "))}</div>`
              : ""
          }
        </td>
        <td class="${calcRoiClass(roi)}">${roi.toFixed(2)}%</td>
        <td>${Number(stats.participants_count || 0)}</td>
        <td>${Number(stats.total_invested_usdt || 0).toLocaleString("ru-RU", { maximumFractionDigits: 2 })}</td>
        <td>${d.opened_at ? new Date(d.opened_at).toLocaleString() : ""}</td>
        <td>${d.closed_at ? new Date(d.closed_at).toLocaleString() : ""}</td>
        <td>${d.finished_at ? new Date(d.finished_at).toLocaleString() : ""}</td>
        <td>
          <div class="row-actions">
            <button class="deal-save-btn">Сохранить %</button>
            <button class="deal-clone-btn">Клонировать</button>
            <button class="deal-simulate-btn">Симуляция</button>
          </div>
        </td>
      </tr>`;
        }
      )
      .join("");

    section.innerHTML = `
      <h1>Сделки</h1>
      <p class="section-desc">Текущие и завершённые сделки, управление доходностью.</p>
      ${statusBlock}
      <div class="panel-card">
        <h2>Риск-уведомления по сделкам</h2>
        ${
          dealRiskAlerts.length
            ? `<ul class="alerts-list">${dealRiskAlerts
                .map(
                  (a) =>
                    `<li class="alert-item ${a.riskLevel === "high" ? "high" : a.riskLevel === "medium" ? "medium" : "low"}">
                      <strong>Сделка #${a.dealNumber}</strong>: ${escapeHtmlAttr(a.alerts.join(", "))}
                      ${a.riskNote ? `<div class="mini-hint">${escapeHtmlAttr(a.riskNote)}</div>` : ""}
                    </li>`
                )
                .join("")}</ul>`
            : `<div class="empty-state"><strong>Аномалий не найдено</strong><span>Риск-алерты появятся автоматически при проблемных сделках.</span></div>`
        }
      </div>
      <div class="panel-card">
        <div class="toolbar">
          <button id="deal-open-now-btn">Открыть новую сделку</button>
        </div>
        <div class="table-wrapper">
          <div class="table-wrapper-inner">
            <table>
              <thead>
                <tr>
                  <th>№</th>
                  <th>Статус</th>
                  <th>До закрытия</th>
                  <th>Прогресс</th>
                  <th>% дохода</th>
                  <th>Ограничения (USDT)</th>
                  <th>Лимит участн.</th>
                  <th>Риск</th>
                  <th>ROI</th>
                  <th>Участн.</th>
                  <th>Инвест., USDT</th>
                  <th>Открыта</th>
                  <th>Закрыта</th>
                  <th>Завершена</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>${rows}</tbody>
            </table>
          </div>
        </div>
      </div>
    `;

    const openBtn = document.getElementById("deal-open-now-btn");
    if (openBtn) {
      openBtn.onclick = async () => {
        try {
          await apiRequest("/deals/open-now", { method: "POST" });
          loadDeals();
        } catch (e) {
          showToast(e.message || "Ошибка открытия сделки", "error");
        }
      };
    }

    const sendNotifBtn = document.getElementById("deal-send-notifications-btn");
    if (sendNotifBtn) {
      sendNotifBtn.onclick = async () => {
        try {
          const res = await apiRequest("/deals/send-notifications", { method: "POST" });
          showToast(`Уведомления отправлены: ${res.sent_count} получателей.`, "success");
          loadDeals();
        } catch (e) {
          showToast(e.message || "Ошибка отправки уведомлений", "error");
        }
      };
    }

    const forceCloseBtn = document.getElementById("deal-force-close-btn");
    if (forceCloseBtn) {
      forceCloseBtn.onclick = async () => {
        const forceCloseConfirm = await openUxDialog({
          title: "Досрочное закрытие",
          message: "Вы уверены, что хотите досрочно закрыть текущую активную сделку?",
          confirmText: "Закрыть",
          cancelText: "Отмена",
        });
        if (!forceCloseConfirm.confirmed) {
          return;
        }
        try {
          await apiRequest("/deals/force-close", { method: "POST" });
          showToast("Сделка досрочно закрыта. Участникам отправлены уведомления.", "success");
          loadDeals();
        } catch (e) {
          showToast(e.message || "Ошибка досрочного закрытия сделки", "error");
        }
      };
    }

    section.querySelectorAll("button.deal-save-btn").forEach((btn) => {
      btn.onclick = async () => {
        const row = btn.closest("tr");
        if (!row) return;
        const dealId = row.getAttribute("data-deal-id");
        const input = row.querySelector("input.deal-percent-input");
        const minInput = row.querySelector("input.deal-min-input");
        const maxInput = row.querySelector("input.deal-max-input");
        const maxParticipantsInput = row.querySelector("input.deal-max-participants-input");
        const riskLevelInput = row.querySelector("select.deal-risk-level-input");
        const riskNoteInput = row.querySelector("input.deal-risk-note-input");
        if (!dealId || !input) return;
        const value = parseFloat(input.value.replace(",", "."));
        if (Number.isNaN(value)) {
          showToast("Введите корректное значение процента", "error");
          return;
        }
        const minVal = Number((minInput?.value || "").replace(",", "."));
        const maxVal = Number((maxInput?.value || "").replace(",", "."));
        const maxParticipantsVal = Number((maxParticipantsInput?.value || "").trim());
        const payload = { profit_percent: value };
        if (minInput && minInput.value.trim()) payload.min_participation_usdt = minVal;
        if (maxInput && maxInput.value.trim()) payload.max_participation_usdt = maxVal;
        if (maxParticipantsInput && maxParticipantsInput.value.trim()) payload.max_participants = maxParticipantsVal;
        if (riskLevelInput) payload.risk_level = riskLevelInput.value || "";
        if (riskNoteInput) payload.risk_note = riskNoteInput.value || "";
        try {
          await apiRequest(`/deals/${dealId}`, {
            method: "PATCH",
            body: JSON.stringify(payload),
          });
          showToast("Параметры сделки обновлены", "success");
          loadDeals();
        } catch (e) {
          showToast(e.message || "Ошибка обновления доходности", "error");
        }
      };
    });
    section.querySelectorAll("button.deal-clone-btn").forEach((btn) => {
      btn.onclick = async () => {
        const row = btn.closest("tr");
        const dealId = row?.getAttribute("data-deal-id");
        if (!dealId) return;
        try {
          await apiRequest(`/deals/${dealId}/clone`, { method: "POST" });
          showToast("Сделка клонирована в draft", "success");
          loadDeals();
        } catch (e) {
          showToast(e.message || "Ошибка клонирования сделки", "error");
        }
      };
    });
    section.querySelectorAll("button.deal-simulate-btn").forEach((btn) => {
      btn.onclick = async () => {
        const row = btn.closest("tr");
        const dealId = row?.getAttribute("data-deal-id");
        if (!dealId) return;
        const d = deals.find((x) => String(x.id) === String(dealId));
        const roi = Number(d?.profit_percent ?? d?.percent ?? 0);
        const r = await openUxDialog({
          title: "Симуляция сделки",
          message: `Введите сумму участия (USDT), ROI = ${roi.toFixed(2)}%`,
          inputPlaceholder: "100",
          confirmText: "Рассчитать",
          cancelText: "Отмена",
        });
        if (!r.confirmed) return;
        const amount = Number(String(r.value || "").replace(",", "."));
        if (!Number.isFinite(amount) || amount <= 0) return showToast("Введите сумму больше 0", "error");
        const profit = (amount * roi) / 100;
        const total = amount + profit;
        await openUxDialog({
          title: `Предпросмотр прибыли по сделке #${d?.number || dealId}`,
          message: `Сумма участия: ${amount.toFixed(2)} USDT\nОжидаемая прибыль: ${profit.toFixed(2)} USDT\nИтого к выплате: ${total.toFixed(2)} USDT`,
          confirmText: "OK",
        });
      };
    });
  } catch (e) {
    section.innerHTML = `<h1>Сделки</h1><div class="error">${e.message}</div>`;
  }
}

function wrapSelectionWithTag(textarea, openTag, closeTag) {
  const start = textarea.selectionStart || 0;
  const end = textarea.selectionEnd || 0;
  const value = textarea.value || "";
  const selected = value.slice(start, end);
  if (!selected) return;
  const next = value.slice(0, start) + openTag + selected + closeTag + value.slice(end);
  textarea.value = next;
  const pos = end + openTag.length + closeTag.length;
  textarea.focus();
  textarea.setSelectionRange(pos, pos);
}

function stripHtmlTags(html) {
  return (html || "").replace(/<[^>]*>/g, "");
}

function readBroadcastTemplates() {
  try {
    const raw = localStorage.getItem(BROADCAST_TEMPLATES_KEY);
    const arr = raw ? JSON.parse(raw) : [];
    if (!Array.isArray(arr)) return [];
    return arr.filter((x) => x && typeof x.name === "string" && typeof x.text_html === "string");
  } catch (_) {
    return [];
  }
}

function writeBroadcastTemplates(items) {
  try {
    localStorage.setItem(BROADCAST_TEMPLATES_KEY, JSON.stringify(items.slice(0, 12)));
  } catch (_) {}
}

async function loadMessages(page = 1) {
  const section = document.getElementById("messages-section");
  section.innerHTML = `<h1>Сообщения</h1><div class="panel-card"><div class="skeleton-line" style="width:66%;"></div><div class="skeleton-line" style="width:84%; margin-top:12px;"></div></div>`;
  try {
    const data = await apiRequest(`/broadcasts?page=${page}&page_size=20`);
    const rows = data.items || [];
    const stats = rows.reduce(
      (acc, r) => {
        acc.total += 1;
        acc.recipients += Number(r.total_recipients || 0);
        acc.sent += Number(r.sent_count || 0);
        acc.failed += Number(r.failed_count || 0);
        if (r.status === "SENT") acc.sentCampaigns += 1;
        if (r.status === "ERROR") acc.errorCampaigns += 1;
        return acc;
      },
      { total: 0, recipients: 0, sent: 0, failed: 0, sentCampaigns: 0, errorCampaigns: 0 }
    );
    const deliveryRate = stats.recipients > 0 ? (stats.sent / stats.recipients) * 100 : 0;
    const failRate = stats.recipients > 0 ? (stats.failed / stats.recipients) * 100 : 0;
    const historyHtml = rows.length
      ? rows
          .map((r) => {
            const statusClass =
              r.status === "SENT"
                ? "status-badge status-paid"
                : r.status === "IN_PROGRESS"
                ? "status-badge status-pending"
                : "status-badge status-expired";
            const imageHtml = r.image_url
              ? `<img class="broadcast-image-preview" src="${r.image_url}" alt="broadcast image" />`
              : "";
            return `
              <div class="broadcast-item">
                <div class="broadcast-item-meta">
                  <span>#${r.id}</span>
                  <span class="${statusClass}">${r.status}</span>
                  <span>${new Date(r.created_at).toLocaleString()}</span>
                  <span>Сегмент: ${escapeHtmlAttr(r.audience_segment || "all")}</span>
                  ${r.scheduled_at ? `<span>Запланировано: ${new Date(r.scheduled_at).toLocaleString()}</span>` : ""}
                  <span>Отправлено: ${r.sent_count}/${r.total_recipients}</span>
                  <span>Ошибок: ${r.failed_count}</span>
                </div>
                <p class="broadcast-preview">${escapeHtmlAttr(stripHtmlTags(r.text_html)).slice(0, 200) || "—"}</p>
                ${imageHtml}
                <div class="toolbar" style="margin:8px 0 0;">
                  <button type="button" class="btn-secondary-small broadcast-detail-btn" data-id="${r.id}">Подробнее</button>
                  ${Number(r.failed_count || 0) > 0 ? `<button type="button" class="btn-secondary-small broadcast-retry-btn" data-id="${r.id}">Повторить failed</button>` : ""}
                </div>
              </div>
            `;
          })
          .join("")
      : `<div class="empty-state"><strong>Рассылок пока нет</strong><span>Создайте первую рассылку слева: добавьте текст и при необходимости изображение.</span></div>`;

    section.innerHTML = `
      <h1>Сообщения</h1>
      <p class="section-desc">Массовые рассылки всем пользователям через Telegram-бота.</p>
      <div class="kpi-row">
        <div class="kpi-card">
          <div class="kpi-title">Кампаний</div>
          <div class="kpi-value">${stats.total}</div>
          <div class="kpi-delta kpi-neutral">SENT: ${stats.sentCampaigns} · ERROR: ${stats.errorCampaigns}</div>
        </div>
        <div class="kpi-card">
          <div class="kpi-title">Всего доставок</div>
          <div class="kpi-value">${stats.sent}/${stats.recipients}</div>
          <div class="kpi-delta ${deliveryRate >= 90 ? "kpi-positive" : deliveryRate >= 70 ? "kpi-neutral" : "kpi-negative"}">delivery rate: ${deliveryRate.toFixed(1)}%</div>
        </div>
        <div class="kpi-card">
          <div class="kpi-title">Ошибки доставок</div>
          <div class="kpi-value">${stats.failed}</div>
          <div class="kpi-delta ${failRate <= 5 ? "kpi-positive" : failRate <= 15 ? "kpi-neutral" : "kpi-negative"}">fail rate: ${failRate.toFixed(1)}%</div>
        </div>
      </div>
      <div class="messages-layout">
        <div class="panel-card">
          <h2>Новая рассылка</h2>
          <p class="section-desc">Поддерживаются Telegram HTML-теги: &lt;b&gt;, &lt;i&gt;, &lt;u&gt;, &lt;s&gt;, &lt;code&gt;, &lt;pre&gt;, &lt;a&gt;, &lt;br&gt;. Enter создаёт перенос строки автоматически.</p>
          <div class="editor-toolbar">
            <button type="button" class="editor-btn" data-tag="b" title="Жирный текст"><b>B</b></button>
            <button type="button" class="editor-btn" data-tag="i" title="Курсив"><i>I</i></button>
            <button type="button" class="editor-btn" data-tag="u" title="Подчёркнутый"><u>U</u></button>
            <button type="button" class="editor-btn" data-tag="code" title="Моноширинный блок">Code</button>
            <button type="button" class="editor-btn" id="broadcast-link-btn" title="Добавить ссылку">Link</button>
            <button type="button" class="editor-btn" id="broadcast-br-btn" title="Перенос строки">&lt;br&gt;</button>
          </div>
          <div class="toolbar" style="margin:6px 0 10px;">
            <input id="broadcast-test-chat-id" type="number" placeholder="Telegram ID для теста" />
            <button type="button" id="broadcast-test-send-btn" class="btn-secondary-small">Тестовая отправка</button>
            <select id="broadcast-template-select" class="page-size-select">
              <option value="">Шаблоны</option>
            </select>
            <button type="button" id="broadcast-template-save-btn" class="btn-secondary-small">Сохранить шаблон</button>
            <button type="button" id="broadcast-template-apply-btn" class="btn-secondary-small">Применить шаблон</button>
          </div>
          <div id="broadcast-template-list" class="template-sort-list"></div>
          <div class="toolbar" style="margin:0 0 8px;">
            <label class="filter-label">
              Сегмент
              <select id="broadcast-audience-segment">
                <option value="all">Все пользователи</option>
                <option value="with_balance">Только с балансом</option>
                <option value="with_referrals">Только с рефералами</option>
                <option value="active_24h">Только активные за 24ч</option>
              </select>
            </label>
            <label class="filter-label">
              Отложенная отправка
              <input id="broadcast-scheduled-at" type="datetime-local" />
            </label>
          </div>
          <textarea id="broadcast-text" class="message-editor" placeholder="Введите текст рассылки..."></textarea>
          <div class="toolbar" style="margin-top:10px;">
            <input type="file" id="broadcast-image" accept=".jpg,.jpeg,.png,.webp" title="Опционально: изображение для рассылки" />
          </div>
          <div id="broadcast-preview-box" class="broadcast-preview-box empty-state">
            <strong>Превью рассылки</strong>
            <span>Введите текст, чтобы увидеть, как сообщение выглядит перед отправкой.</span>
          </div>
          <div class="toolbar">
            <button type="button" id="broadcast-send-btn" title="Критическое действие: отправка всем пользователям">Отправить всем</button>
          </div>
        </div>
        <div class="panel-card">
          <h2>История рассылок</h2>
          <div class="broadcast-history-list">${historyHtml}</div>
        </div>
      </div>
    `;

    const textarea = document.getElementById("broadcast-text");
    section.querySelectorAll(".editor-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        const tag = btn.getAttribute("data-tag");
        if (!textarea || !tag) return;
        wrapSelectionWithTag(textarea, `<${tag}>`, `</${tag}>`);
      });
    });
    document.getElementById("broadcast-link-btn")?.addEventListener("click", async () => {
      if (!textarea) return;
      const r = await openUxDialog({
        title: "Ссылка",
        message: "Введите URL (https://...)",
        inputPlaceholder: "https://example.com",
        confirmText: "Вставить",
        cancelText: "Отмена",
      });
      const url = (r.value || "").trim();
      if (!r.confirmed || !url) return;
      const start = textarea.selectionStart || 0;
      const end = textarea.selectionEnd || 0;
      const value = textarea.value || "";
      const selected = value.slice(start, end) || "ссылка";
      const next = `${value.slice(0, start)}<a href="${url}">${selected}</a>${value.slice(end)}`;
      textarea.value = next;
      textarea.focus();
    });
    document.getElementById("broadcast-br-btn")?.addEventListener("click", () => {
      if (!textarea) return;
      const start = textarea.selectionStart || 0;
      const end = textarea.selectionEnd || 0;
      const value = textarea.value || "";
      textarea.value = `${value.slice(0, start)}<br>${value.slice(end)}`;
      textarea.focus();
    });

    const sendBtn = document.getElementById("broadcast-send-btn");
    const templates = readBroadcastTemplates();
    const tplSelect = document.getElementById("broadcast-template-select");
    const tplList = document.getElementById("broadcast-template-list");
    const renderTemplateList = (items) => {
      if (!tplList) return;
      if (!items.length) {
        tplList.innerHTML = "";
        return;
      }
      tplList.innerHTML = items
        .map(
          (t, i) => `
          <div class="template-sort-item" data-idx="${i}" draggable="true" title="Перетащите для сортировки">
            <span class="template-drag-handle">⋮⋮</span>
            <span class="template-sort-name">${escapeHtmlAttr(t.name)}</span>
            <button type="button" class="btn-secondary-small template-apply-inline-btn" data-idx="${i}">Применить</button>
          </div>`
        )
        .join("");
      let dragFrom = null;
      tplList.querySelectorAll(".template-sort-item").forEach((el) => {
        el.addEventListener("dragstart", () => {
          dragFrom = Number(el.getAttribute("data-idx"));
          el.classList.add("dragging");
        });
        el.addEventListener("dragend", () => {
          el.classList.remove("dragging");
        });
        el.addEventListener("dragover", (ev) => {
          ev.preventDefault();
          el.classList.add("drag-over");
        });
        el.addEventListener("dragleave", () => {
          el.classList.remove("drag-over");
        });
        el.addEventListener("drop", () => {
          el.classList.remove("drag-over");
          const dragTo = Number(el.getAttribute("data-idx"));
          if (!Number.isInteger(dragFrom) || !Number.isInteger(dragTo) || dragFrom === dragTo) return;
          const next = [...readBroadcastTemplates()];
          const [moved] = next.splice(dragFrom, 1);
          next.splice(dragTo, 0, moved);
          writeBroadcastTemplates(next);
          showToast("Порядок шаблонов обновлён", "success");
          loadMessages(page);
        });
      });
      tplList.querySelectorAll(".template-apply-inline-btn").forEach((btn) => {
        btn.addEventListener("click", () => {
          const idx = Number(btn.getAttribute("data-idx"));
          const t = readBroadcastTemplates()[idx];
          if (!t || !textarea) return;
          textarea.value = t.text_html;
          textarea.dispatchEvent(new Event("input"));
        });
      });
    };
    if (tplSelect) {
      tplSelect.innerHTML =
        `<option value="">Шаблоны</option>` +
        templates.map((t, i) => `<option value="${i}">${escapeHtmlAttr(t.name)}</option>`).join("");
    }
    renderTemplateList(templates);
    document.getElementById("broadcast-template-save-btn")?.addEventListener("click", async () => {
      const text = (textarea?.value || "").trim();
      if (!text) {
        showToast("Нечего сохранять в шаблон", "info");
        return;
      }
      const r = await openUxDialog({
        title: "Название шаблона",
        message: "Введите название шаблона",
        inputPlaceholder: "Например: Welcome / Promo",
        confirmText: "Сохранить",
        cancelText: "Отмена",
      });
      const name = (r.value || "").trim();
      if (!r.confirmed || !name) return;
      const next = [{ name: name.slice(0, 30), text_html: text }, ...readBroadcastTemplates()];
      const dedup = [];
      for (const x of next) if (!dedup.some((d) => d.name === x.name)) dedup.push(x);
      writeBroadcastTemplates(dedup);
      showToast("Шаблон сохранён", "success");
      loadMessages(page);
    });
    document.getElementById("broadcast-template-apply-btn")?.addEventListener("click", () => {
      const idx = parseInt(document.getElementById("broadcast-template-select")?.value || "", 10);
      if (Number.isNaN(idx)) {
        showToast("Выберите шаблон", "info");
        return;
      }
      const t = readBroadcastTemplates()[idx];
      if (!t || !textarea) return;
      textarea.value = t.text_html;
      textarea.dispatchEvent(new Event("input"));
    });
    document.getElementById("broadcast-test-send-btn")?.addEventListener("click", async () => {
      const text = (textarea?.value || "").trim();
      const chatIdRaw = document.getElementById("broadcast-test-chat-id")?.value?.trim() || "";
      const imageInput = document.getElementById("broadcast-image");
      const file = imageInput?.files?.[0];
      if (!chatIdRaw || !/^\d+$/.test(chatIdRaw)) {
        showToast("Введите корректный Telegram ID для теста", "error");
        return;
      }
      if (!text) {
        showToast("Введите текст для теста", "error");
        return;
      }
      const formData = new FormData();
      formData.append("telegram_id", chatIdRaw);
      formData.append("text_html", text);
      if (file) formData.append("image", file);
      try {
        await apiRequest("/broadcasts/test-send", {
          method: "POST",
          body: formData,
        });
        showToast("Тестовое сообщение отправлено", "success");
      } catch (e) {
        showToast(e.message || "Ошибка тестовой отправки", "error");
      }
    });
    if (sendBtn) {
      const renderPreview = () => {
        const previewEl = document.getElementById("broadcast-preview-box");
        if (!previewEl) return;
        const text = (textarea?.value || "").trim();
        const imageInput = document.getElementById("broadcast-image");
        const file = imageInput?.files?.[0];
        if (!text && !file) {
          previewEl.className = "broadcast-preview-box empty-state";
          previewEl.innerHTML = `<strong>Превью рассылки</strong><span>Введите текст, чтобы увидеть, как сообщение выглядит перед отправкой.</span>`;
          return;
        }
        previewEl.className = "broadcast-preview-box";
        previewEl.innerHTML = `
          <div class="broadcast-preview-title">Превью</div>
          <div class="broadcast-preview-text">${escapeHtmlAttr(stripHtmlTags(text) || "—")}</div>
          ${file ? `<div class="broadcast-preview-file">Изображение: ${escapeHtmlAttr(file.name)}</div>` : ""}
        `;
      };
      textarea?.addEventListener("input", renderPreview);
      document.getElementById("broadcast-image")?.addEventListener("change", renderPreview);
      renderPreview();

      sendBtn.onclick = async () => {
        const text = (textarea?.value || "").trim();
        const imageInput = document.getElementById("broadcast-image");
        const file = imageInput?.files?.[0];
        const scheduledAtRaw = document.getElementById("broadcast-scheduled-at")?.value || "";
        if (!text) {
          showToast("Введите текст сообщения", "error");
          return;
        }

        const check = await openUxDialog({
          title: "Предпросмотр перед отправкой",
          message: [
            `Сегмент: ${document.getElementById("broadcast-audience-segment")?.value || "all"}`,
            `Планирование: ${scheduledAtRaw ? new Date(scheduledAtRaw).toLocaleString() : "сразу"}`,
            `Изображение: ${file ? file.name : "нет"}`,
            "",
            "Текст (фрагмент):",
            stripHtmlTags(text).slice(0, 280) || "—",
            "",
            "Подтвердить запуск рассылки?",
          ].join("\n"),
          confirmText: "Отправить",
          cancelText: "Отмена",
        });
        if (!check.confirmed) return;

        const formData = new FormData();
        formData.append("text_html", text);
        formData.append("audience_segment", document.getElementById("broadcast-audience-segment")?.value || "all");
        if (scheduledAtRaw) {
          const dt = new Date(scheduledAtRaw);
          if (!Number.isNaN(dt.getTime())) {
            formData.append("scheduled_at", dt.toISOString());
          }
        }
        if (file) formData.append("image", file);
        try {
          sendBtn.disabled = true;
          sendBtn.textContent = "Запуск рассылки...";
          await apiRequest("/broadcasts", {
            method: "POST",
            body: formData,
          });
          showToast(scheduledAtRaw ? "Рассылка запланирована" : "Рассылка создана и отправляется в фоне", "success");
          loadMessages(1);
        } catch (e) {
          showToast(e.message || "Ошибка создания рассылки", "error");
        } finally {
          sendBtn.disabled = false;
          sendBtn.textContent = "Отправить всем";
        }
      };
    }

    section.querySelectorAll(".broadcast-detail-btn").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const id = btn.getAttribute("data-id");
        if (!id) return;
        try {
          const item = await apiRequest(`/broadcasts/${id}`);
          const body = [
            `Статус: ${item.status}`,
            `Отправлено: ${item.sent_count}/${item.total_recipients}`,
            `Ошибок: ${item.failed_count}`,
            "",
            "Текст рассылки:",
            stripHtmlTags(item.text_html || "—"),
          ].join("\n");
          await openUxDialog({
            title: `Рассылка #${item.id}`,
            message: body,
            confirmText: "Закрыть",
          });
        } catch (e) {
          showToast(e.message || "Ошибка загрузки рассылки", "error");
        }
      });
    });
    section.querySelectorAll(".broadcast-retry-btn").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const id = btn.getAttribute("data-id");
        if (!id) return;
        const check = await openUxDialog({
          title: "Повтор failed доставок",
          message: `Поставить в очередь повторной отправки только FAILED доставки для рассылки #${id}?`,
          confirmText: "Повторить",
          cancelText: "Отмена",
        });
        if (!check.confirmed) return;
        try {
          await apiRequest(`/broadcasts/${id}/retry-failed`, { method: "POST" });
          showToast("Failed доставки поставлены в очередь", "success");
          loadMessages(1);
        } catch (e) {
          showToast(e.message || "Ошибка повторной отправки", "error");
        }
      });
    });
  } catch (e) {
    section.innerHTML = `<h1>Сообщения</h1><div class="error">${e.message}</div>`;
  }
}

function buildDepositsQuery(page = 1) {
  const state = {
    status_filter: document.getElementById("deposits-status-filter")?.value || "",
    date_from: document.getElementById("deposits-date-from")?.value || "",
    date_to: document.getElementById("deposits-date-to")?.value || "",
    sort: document.getElementById("deposits-sort")?.value || "created_at_desc",
    order_id_search: document.getElementById("deposits-order-id")?.value?.trim() || "",
    external_id_search: document.getElementById("deposits-external-id")?.value?.trim() || "",
    user_id_filter: document.getElementById("deposits-user-id")?.value?.trim() || "",
    amount_min: document.getElementById("deposits-amount-min")?.value?.trim() || "",
    amount_max: document.getElementById("deposits-amount-max")?.value?.trim() || "",
    currency_filter: document.getElementById("deposits-currency-filter")?.value || "",
  };
  return buildDepositsQueryFromState(page, state);
}

function buildDepositsQueryFromState(page = 1, state = {}) {
  const params = new URLSearchParams();
  params.set("page", String(page));
  params.set("page_size", "25");
  if (state.status_filter) params.set("status_filter", state.status_filter);
  if (state.date_from) params.set("date_from", state.date_from);
  if (state.date_to) params.set("date_to", state.date_to);
  if (state.order_id_search) params.set("order_id_search", state.order_id_search);
  if (state.external_id_search) params.set("external_id_search", state.external_id_search);
  if (state.user_id_filter) params.set("user_id_filter", state.user_id_filter);
  if (state.amount_min) params.set("amount_min", state.amount_min);
  if (state.amount_max) params.set("amount_max", state.amount_max);
  if (state.currency_filter) params.set("currency_filter", state.currency_filter);
  params.set("sort", state.sort || "created_at_desc");
  return params.toString();
}

function statusBadgeClass(status) {
  const s = (status || "").toLowerCase();
  if (s === "finished" || s === "paid") return "status-badge status-paid";
  if (s === "waiting" || s === "pending" || s === "partially_paid") return "status-badge status-pending";
  if (s === "expired" || s === "failed") return "status-badge status-expired";
  return "status-badge status-unknown";
}

function statusLabel(status) {
  const s = (status || "").toLowerCase();
  if (s === "finished" || s === "paid") return "Оплачен";
  if (s === "waiting" || s === "pending") return "Ожидает";
  if (s === "partially_paid") return "Частично оплачен";
  if (s === "expired") return "Истёк";
  if (s === "failed") return "Ошибка";
  return status || "—";
}

async function loadDeposits(page = 1) {
  const section = document.getElementById("deposits-section");
  section.innerHTML = "<h1>Пополнения</h1><p>Загрузка...</p>";
  try {
    const depositsState = loadSavedState(DEPOSITS_FILTERS_KEY, {
      status_filter: "",
      date_from: "",
      date_to: "",
      sort: "created_at_desc",
      order_id_search: "",
      external_id_search: "",
      user_id_filter: "",
      amount_min: "",
      amount_max: "",
      currency_filter: "",
    });
    const q = buildDepositsQueryFromState(page, depositsState);
    const data = await apiRequest(`/deposits?${q}`);
    const items = data.items || [];
    const total = data.total || 0;
    const pageSize = data.page_size || 25;
    const currentPage = data.page || 1;
    const totalPages = Math.max(1, Math.ceil(total / pageSize));

    const rows = items
      .map(
        (d) => `
      <tr class="table-row-link deposit-row" data-deposit-id="${d.id}">
        <td>${d.id}</td>
        <td><code class="order-id-cell">${(d.order_id || "").slice(0, 24)}${(d.order_id && d.order_id.length > 24) ? "…" : ""}</code></td>
        <td>${d.telegram_id}${d.username ? ` @${d.username}` : ""}</td>
        <td class="amount-positive">+${d.amount} ${d.asset}</td>
        <td><span class="${statusBadgeClass(d.status)}">${statusLabel(d.status)}</span></td>
        <td>${d.balance_credited ? '<span class="credited-yes">Да</span>' : '<span class="credited-no">Нет</span>'}</td>
        <td>${d.created_at ? new Date(d.created_at).toLocaleString() : ""}</td>
        <td>${d.paid_at ? new Date(d.paid_at).toLocaleString() : (d.completed_at ? new Date(d.completed_at).toLocaleString() : "—")}</td>
        <td>
          <div class="row-actions">
            <button type="button" class="btn-secondary-small deposit-open-btn" data-deposit-id="${d.id}">Подробнее</button>
            <button type="button" class="btn-secondary-small deposit-copy-order-btn" data-order-id="${escapeHtmlAttr(d.order_id || "")}">Копировать order_id</button>
          </div>
        </td>
      </tr>`
      )
      .join("");
    const rowsHtml = rows || `<tr><td colspan="9"><div class="empty-state"><strong>Нет пополнений по текущим фильтрам</strong><span>Расширьте диапазон дат или очистите фильтры.</span></div></td></tr>`;

    let paginationHtml = "";
    if (totalPages > 1) {
      let paginationParts = [];
      if (currentPage > 1) {
        paginationParts.push(`<button type="button" class="pagination-btn" data-page="${currentPage - 1}">← Назад</button>`);
      }
      paginationParts.push(`<span class="pagination-info">Стр. ${currentPage} из ${totalPages} (всего ${total})</span>`);
      if (currentPage < totalPages) {
        paginationParts.push(`<button type="button" class="pagination-btn" data-page="${currentPage + 1}">Вперёд →</button>`);
      }
      paginationHtml = `<div class="toolbar pagination-toolbar">${paginationParts.join(" ")}</div>`;
    }

    section.innerHTML = `
      <h1>Пополнения</h1>
      <p class="section-desc">NOWPayments (USDT BEP20). История и статус всех депозитов.</p>
      <div class="panel-card">
        <div class="toolbar filters-toolbar">
          <label class="filter-label">
            Статус
            <select id="deposits-status-filter">
              <option value="">Все</option>
              <option value="waiting">Ожидает</option>
              <option value="finished">Оплачен</option>
              <option value="partially_paid">Частично оплачен</option>
              <option value="expired">Истёк</option>
              <option value="failed">Ошибка</option>
            </select>
          </label>
          <label class="filter-label">
            User ID
            <input type="number" id="deposits-user-id" placeholder="ID пользователя" min="1" />
          </label>
          <label class="filter-label">
            Order ID
            <input type="text" id="deposits-order-id" placeholder="order_id" />
          </label>
          <label class="filter-label">
            External ID
            <input type="text" id="deposits-external-id" placeholder="external_invoice_id" />
          </label>
          <label class="filter-label">
            Валюта
            <select id="deposits-currency-filter">
              <option value="">Все</option>
              <option value="usdtbsc">USDTBSC</option>
              <option value="usdttrc20">USDTTRC20</option>
              <option value="usdt">USDT</option>
            </select>
          </label>
          <label class="filter-label">
            Сумма от
            <input type="number" id="deposits-amount-min" min="0" step="0.01" />
          </label>
          <label class="filter-label">
            Сумма до
            <input type="number" id="deposits-amount-max" min="0" step="0.01" />
          </label>
          <label class="filter-label">
            Дата от
            <input type="date" id="deposits-date-from" />
          </label>
          <label class="filter-label">
            Дата до
            <input type="date" id="deposits-date-to" />
          </label>
          <label class="filter-label">
            Сортировка
            <select id="deposits-sort">
              <option value="created_at_desc">Сначала новые</option>
              <option value="created_at_asc">Сначала старые</option>
              <option value="amount_desc">Сумма ↓</option>
              <option value="amount_asc">Сумма ↑</option>
              <option value="status">По статусу</option>
            </select>
          </label>
          <button type="button" id="deposits-apply-filters" title="Применить фильтры к списку пополнений">Применить</button>
        </div>
        ${paginationHtml}
        <div class="table-wrapper">
          <div class="table-wrapper-inner">
            <table>
              <thead>
                <tr>
                  <th>ID</th>
                  <th>Order ID</th>
                  <th>Пользователь</th>
                  <th>Сумма</th>
                  <th>Статус</th>
                  <th>Баланс начислен</th>
                  <th>Создан</th>
                  <th>Завершён</th>
                  <th>Действия</th>
                </tr>
              </thead>
              <tbody>${rowsHtml}</tbody>
            </table>
          </div>
        </div>
        ${paginationHtml}
      </div>
    `;

    const setVal = (id, val) => {
      const el = document.getElementById(id);
      if (el) el.value = val || "";
    };
    setVal("deposits-status-filter", depositsState.status_filter);
    setVal("deposits-date-from", depositsState.date_from);
    setVal("deposits-date-to", depositsState.date_to);
    setVal("deposits-sort", depositsState.sort);
    setVal("deposits-order-id", depositsState.order_id_search);
    setVal("deposits-external-id", depositsState.external_id_search);
    setVal("deposits-user-id", depositsState.user_id_filter);
    setVal("deposits-amount-min", depositsState.amount_min);
    setVal("deposits-amount-max", depositsState.amount_max);
    setVal("deposits-currency-filter", depositsState.currency_filter);

    document.getElementById("deposits-apply-filters").addEventListener("click", () => {
      const current = {
        status_filter: document.getElementById("deposits-status-filter")?.value || "",
        date_from: document.getElementById("deposits-date-from")?.value || "",
        date_to: document.getElementById("deposits-date-to")?.value || "",
        sort: document.getElementById("deposits-sort")?.value || "created_at_desc",
        order_id_search: document.getElementById("deposits-order-id")?.value?.trim() || "",
        external_id_search: document.getElementById("deposits-external-id")?.value?.trim() || "",
        user_id_filter: document.getElementById("deposits-user-id")?.value?.trim() || "",
        amount_min: document.getElementById("deposits-amount-min")?.value?.trim() || "",
        amount_max: document.getElementById("deposits-amount-max")?.value?.trim() || "",
        currency_filter: document.getElementById("deposits-currency-filter")?.value || "",
      };
      saveState(DEPOSITS_FILTERS_KEY, current);
      loadDeposits(1);
    });
    section.querySelectorAll("button.pagination-btn").forEach((btn) => {
      btn.addEventListener("click", () => loadDeposits(parseInt(btn.getAttribute("data-page"), 10)));
    });
    section.querySelectorAll("tr.deposit-row").forEach((row) => {
      row.addEventListener("click", () => {
        const id = row.getAttribute("data-deposit-id");
        if (id) openDepositDetail(id);
      });
    });
    section.querySelectorAll(".deposit-open-btn").forEach((btn) => {
      btn.addEventListener("click", (ev) => {
        ev.stopPropagation();
        const id = btn.getAttribute("data-deposit-id");
        if (id) openDepositDetail(id);
      });
    });
    section.querySelectorAll(".deposit-copy-order-btn").forEach((btn) => {
      btn.addEventListener("click", async (ev) => {
        ev.stopPropagation();
        const orderId = btn.getAttribute("data-order-id") || "";
        const ok = await copyTextToClipboard(orderId);
        showToast(ok ? "order_id скопирован" : "Не удалось скопировать", ok ? "success" : "error");
      });
    });
  } catch (e) {
    section.innerHTML = `<h1>Пополнения</h1><div class="error">${e.message}</div>`;
  }
}

function closeDepositModal() {
  const modal = document.getElementById("deposit-detail-modal");
  if (modal) {
    modal.classList.add("hidden");
    modal.setAttribute("aria-hidden", "true");
  }
}

async function openDepositDetail(id) {
  const modal = document.getElementById("deposit-detail-modal");
  const bodyEl = document.getElementById("deposit-detail-body");
  const idEl = document.getElementById("modal-deposit-id");
  if (!modal || !bodyEl || !idEl) return;
  idEl.textContent = id;
  bodyEl.innerHTML = "<p>Загрузка...</p>";
  modal.classList.remove("hidden");
  modal.setAttribute("aria-hidden", "false");
  try {
    const d = await apiRequest(`/deposits/${id}`);
    const invoiceUrlHtml = d.invoice_url
      ? `<a href="${d.invoice_url}" target="_blank" rel="noopener">${d.invoice_url.slice(0, 50)}…</a>`
      : "—";
    const timelineItems = [];
    if (d.created_at) timelineItems.push({ label: "Создано", value: new Date(d.created_at).toLocaleString(), cls: "done" });
    if (d.paid_at) timelineItems.push({ label: "Оплачено", value: new Date(d.paid_at).toLocaleString(), cls: "done" });
    if (d.completed_at) timelineItems.push({ label: "Завершено", value: new Date(d.completed_at).toLocaleString(), cls: "done" });
    if (!timelineItems.length) timelineItems.push({ label: "Ожидание", value: "События отсутствуют", cls: "pending" });
    const timelineHtml = timelineItems
      .map((x) => `<li class="tx-timeline-item ${x.cls}"><span class="tx-timeline-dot"></span><span class="tx-timeline-label">${x.label}</span><span class="tx-timeline-time">${x.value}</span></li>`)
      .join("");
    let webhookHtml = "";
    if (d.raw_webhook_payloads && d.raw_webhook_payloads.length > 0) {
      webhookHtml = `
        <dt>Webhook payloads</dt>
        <dd><pre class="raw-json">${d.raw_webhook_payloads.map((p) => JSON.stringify(p, null, 2)).join("\n\n---\n\n")}</pre></dd>
      `;
    }
    bodyEl.innerHTML = `
      <dl class="detail-dl">
        <dt>Order ID</dt>
        <dd><code>${d.order_id || "—"}</code></dd>
        <dt>External invoice ID</dt>
        <dd>${d.external_invoice_id || "—"}</dd>
        <dt>Ссылка на оплату</dt>
        <dd>${invoiceUrlHtml}</dd>
        <dt>Провайдер / сеть</dt>
        <dd>${d.provider || "nowpayments"} / ${d.network || "BSC"}</dd>
        <dt>Пользователь</dt>
        <dd>${d.telegram_id}${d.username ? ` @${d.username}` : ""} <a href="#user-${d.user_id}" class="link-user">Перейти к пользователю</a></dd>
        <dt>Сумма</dt>
        <dd class="amount-positive">+${d.amount} ${d.asset} (${d.pay_currency || "usdtbsc"})</dd>
        <dt>Ожидалось к оплате</dt>
        <dd>${d.expected_amount != null ? `${d.expected_amount} ${d.pay_currency || ""}` : "—"}</dd>
        <dt>Фактически оплачено</dt>
        <dd>${d.actually_paid_amount != null ? `${d.actually_paid_amount} ${d.pay_currency || ""}` : "—"}</dd>
        <dt>Комиссия (оценка)</dt>
        <dd>${d.estimated_fee_amount != null ? `${d.estimated_fee_amount} ${d.pay_currency || ""}` : "—"}</dd>
        <dt>Статус</dt>
        <dd><span class="${statusBadgeClass(d.status)}">${statusLabel(d.status)}</span></dd>
        <dt>Баланс начислен</dt>
        <dd>${d.balance_credited ? '<span class="credited-yes">Да</span>' : '<span class="credited-no">Нет</span>'}</dd>
        <dt>Создан</dt>
        <dd>${d.created_at ? new Date(d.created_at).toLocaleString() : "—"}</dd>
        <dt>Завершён</dt>
        <dd>${d.completed_at ? new Date(d.completed_at).toLocaleString() : (d.paid_at ? new Date(d.paid_at).toLocaleString() : "—")}</dd>
        <dt>Timeline</dt>
        <dd><ul class="tx-timeline">${timelineHtml}</ul></dd>
        ${webhookHtml}
      </dl>
    `;
    modal.querySelector(".link-user")?.addEventListener("click", () => {
      closeDepositModal();
    });
  } catch (e) {
    bodyEl.innerHTML = `<div class="error">${e.message}</div>`;
  }
}

document.getElementById("modal-deposit-close")?.addEventListener("click", closeDepositModal);
document.getElementById("deposit-detail-modal")?.addEventListener("click", (e) => {
  if (e.target.id === "deposit-detail-modal") closeDepositModal();
});

async function loadUserDetail(userId) {
  const section = document.getElementById("user-section");
  section.innerHTML = "<h1>Пользователь</h1><p>Загрузка...</p>";
  try {
    const [detail, ledger] = await Promise.all([
      apiRequest(`/users/${userId}`),
      apiRequest(`/users/${userId}/ledger`),
    ]);
    const u = detail.user;
    const investments = Array.isArray(detail.investments) ? detail.investments : [];
    const invTotals = investments.reduce(
      (acc, i) => {
        const amt = Number(i.amount || 0);
        const profit = Number(i.profit_amount || 0);
        acc.amount += Number.isFinite(amt) ? amt : 0;
        acc.profit += Number.isFinite(profit) ? profit : 0;
        const s = String(i.deal_status || "").toLowerCase();
        if (s === "active") acc.active += 1;
        if (s === "closed") acc.closed += 1;
        if (s === "completed") acc.completed += 1;
        return acc;
      },
      { amount: 0, profit: 0, active: 0, closed: 0, completed: 0 }
    );
    const invRows = investments
      .map(
        (i) => `
        <tr data-invest-status="${escapeHtmlAttr(String(i.deal_status || "").toLowerCase())}">
          <td>${i.deal_number}</td>
          <td>${i.deal_status}</td>
          <td>${i.amount}</td>
          <td>${i.profit_amount || ""}</td>
          <td>${i.payout_at ? new Date(i.payout_at).toLocaleString() : "—"}</td>
          <td>${new Date(i.created_at).toLocaleString()}</td>
        </tr>`
      )
      .join("");
    const wRows = detail.withdrawals
      .map(
        (w) => `
        <tr>
          <td>${w.id}</td>
          <td>${w.amount}</td>
          <td>${w.currency}</td>
          <td class="cell-address">${escapeHtmlAttr(w.address || "")} <button type="button" class="btn-secondary-small copy-address-btn" data-address="${escapeHtmlAttr(w.address || "")}">Копировать</button></td>
          <td>${w.status}</td>
          <td>${new Date(w.created_at).toLocaleString()}</td>
        </tr>`
      )
      .join("");
    const referralsRows = (detail.referrals_preview || [])
      .map(
        (r) => `
        <tr>
          <td>${r.id}</td>
          <td>${r.telegram_id}</td>
          <td>${r.username || ""}</td>
          <td class="num-cell">${r.balance_usdt}</td>
          <td><a href="#user-${r.id}" class="btn-secondary-small">Открыть</a></td>
        </tr>`
      )
      .join("");
    const actionsRows = (detail.recent_actions || [])
      .map(
        (a) => `
        <tr>
          <td>${a.ts ? new Date(a.ts).toLocaleString() : ""}</td>
          <td>${a.source || ""}</td>
          <td>${a.title || ""}</td>
          <td class="num-cell">${a.amount == null ? "—" : a.amount}</td>
        </tr>`
      )
      .join("");

    const ledgerRows = ledger.items
      .map((tx) => {
        const negative = tx.type === "WITHDRAW" || tx.type === "INVEST";
        const cls = negative ? "amount-negative" : "amount-positive";
        const sign = negative ? "-" : "+";
        const comment = tx.comment || "";
        const deal = tx.deal_id ? `#${tx.deal_id}` : "";
        return `
        <tr>
          <td>${new Date(tx.created_at).toLocaleString()}</td>
          <td>${tx.type}</td>
          <td class="${cls}">${sign}${tx.amount_usdt}</td>
          <td>${deal}</td>
          <td>${comment}</td>
        </tr>`;
      })
      .join("");

    const mismatch =
      Number(u.balance_usdt) !== Number(u.ledger_balance_usdt)
        ? `<div class="warning">Кэш баланса != ledger</div>`
        : "";

    section.innerHTML = `
      <h1>Пользователь #${u.id}</h1>
      <p class="section-desc">Карточка пользователя, его операции и заявки на вывод.</p>
      <div class="panel-card">
        <div class="toolbar">
          <div>
            <div>Telegram ID: <strong>${u.telegram_id}</strong></div>
            <div>Username: <strong>${u.username || ""}</strong></div>
            <div>Статус: <strong>${u.is_blocked ? "Заблокирован" : "Активен"}</strong>${u.blocked_reason ? ` · ${escapeHtmlAttr(u.blocked_reason)}` : ""}</div>
            <div>Referrer: <strong>${detail.referrer ? `#${detail.referrer.id} (${detail.referrer.telegram_id})` : "—"}</strong></div>
            <div>Referrals count: <strong>${detail.referrals_count || 0}</strong></div>
            <div class="user-balance-split">
              <div class="user-balance-tile">
                <div class="user-balance-title">Баланс (users.balance_usdt)</div>
                <div class="user-balance-value" id="user-balance-usdt">${u.balance_usdt}</div>
              </div>
              <div class="user-balance-tile">
                <div class="user-balance-title">Баланс по ledger</div>
                <div class="user-balance-value" id="user-ledger-balance">${u.ledger_balance_usdt}</div>
              </div>
            </div>
            ${mismatch}
          </div>
          <div class="toolbar-actions">
            <div class="balance-adjust-form">
              <label>
                Коррекция баланса (USDT)
                <input type="number" id="balance-adjust-amount" step="0.01" />
              </label>
              <label>
                Комментарий
                <input type="text" id="balance-adjust-comment" placeholder="Причина корректировки" />
              </label>
              <button type="button" id="balance-adjust-apply-btn">Начислить / списать</button>
              <button type="button" id="user-block-toggle-btn" class="btn-secondary-small">${u.is_blocked ? "Разблокировать" : "Заблокировать"}</button>
            </div>
            <div class="toolbar" style="gap:8px;">
              <button id="ledger-export-btn">Экспорт CSV</button>
              <button id="ledger-export-xls-btn" class="btn-secondary-small">Экспорт Excel</button>
            </div>
          </div>
        </div>
        <h2>Ledger</h2>
        <div class="table-wrapper">
          <div class="table-wrapper-inner">
            <table>
              <thead>
                <tr>
                  <th>Дата</th>
                  <th>Тип</th>
                  <th>Сумма</th>
                  <th>Сделка</th>
                  <th>Комментарий</th>
                </tr>
              </thead>
              <tbody>${ledgerRows}</tbody>
            </table>
          </div>
        </div>
        <h2>История действий пользователя</h2>
        <div class="table-wrapper">
          <div class="table-wrapper-inner">
            <table>
              <thead>
                <tr>
                  <th>Дата</th>
                  <th>Источник</th>
                  <th>Событие</th>
                  <th>Сумма</th>
                </tr>
              </thead>
              <tbody>${actionsRows || `<tr><td colspan="4"><div class="empty-state"><strong>Нет действий</strong><span>Для пользователя пока нет событий.</span></div></td></tr>`}</tbody>
            </table>
          </div>
        </div>
        <h2>Инвестиции</h2>
        <div class="toolbar" style="margin-bottom:8px;">
          <label class="filter-label">
            Статус
            <select id="user-invest-filter">
              <option value="">Все</option>
              <option value="active">Только active</option>
              <option value="closed">Только closed</option>
              <option value="completed">Только completed</option>
            </select>
          </label>
          <span class="pagination-info">Сделок: ${investments.length} · active: ${invTotals.active} · completed: ${invTotals.completed}</span>
          <span class="pagination-info">Сумма: ${invTotals.amount.toLocaleString("ru-RU", { maximumFractionDigits: 2 })} USDT · Профит: ${invTotals.profit.toLocaleString("ru-RU", { maximumFractionDigits: 2 })} USDT</span>
        </div>
        <div class="table-wrapper">
          <div class="table-wrapper-inner">
            <table>
              <thead>
                <tr>
                  <th>Сделка</th>
                  <th>Статус</th>
                  <th>Сумма</th>
                  <th>Профит</th>
                  <th>Выплата</th>
                  <th>Создано</th>
                </tr>
              </thead>
              <tbody>${invRows || `<tr><td colspan="6"><div class="empty-state"><strong>Нет инвестиций</strong><span>Пользователь еще не участвовал в сделках.</span></div></td></tr>`}</tbody>
            </table>
          </div>
        </div>
        <h2>Заявки на вывод</h2>
        <div class="table-wrapper">
          <div class="table-wrapper-inner">
            <table>
              <thead>
                <tr>
                  <th>ID</th>
                  <th>Сумма</th>
                  <th>Валюта</th>
                  <th>Кошелек</th>
                  <th>Статус</th>
                  <th>Создано</th>
                </tr>
              </thead>
              <tbody>${wRows}</tbody>
            </table>
          </div>
        </div>
        <h2>Реферальная структура (preview)</h2>
        <div class="table-wrapper">
          <div class="table-wrapper-inner">
            <table>
              <thead>
                <tr>
                  <th>User ID</th>
                  <th>Telegram ID</th>
                  <th>Username</th>
                  <th>Баланс</th>
                  <th>Профиль</th>
                </tr>
              </thead>
              <tbody>${referralsRows || `<tr><td colspan="5"><div class="empty-state"><strong>Рефералов пока нет</strong><span>Список заполнится после появления приглашённых пользователей.</span></div></td></tr>`}</tbody>
            </table>
          </div>
        </div>
      </div>
    `;

    const exportBtn = document.getElementById("ledger-export-btn");
    if (exportBtn) {
      exportBtn.onclick = () => {
        window.location.href = `${API_BASE}/ledger/${userId}/export`;
      };
    }
    const exportXlsBtn = document.getElementById("ledger-export-xls-btn");
    if (exportXlsBtn) {
      exportXlsBtn.onclick = () => {
        window.location.href = `${API_BASE}/ledger/${userId}/export?format=xls`;
      };
    }

    const adjustBtn = document.getElementById("balance-adjust-apply-btn");
    if (adjustBtn) {
      adjustBtn.onclick = async () => {
        const amountInput = document.getElementById("balance-adjust-amount");
        const commentInput = document.getElementById("balance-adjust-comment");
        if (!amountInput) return;
        const raw = amountInput.value;
        const amount = parseFloat(raw.replace(",", "."));
        if (!raw || Number.isNaN(amount) || amount === 0) {
          showToast("Введите ненулевую сумму корректировки (можно со знаком - для списания).", "error");
          return;
        }
        try {
          await apiRequest(`/users/${userId}/ledger-adjust`, {
            method: "POST",
            body: JSON.stringify({
              amount_usdt: raw,
              comment: commentInput ? commentInput.value : null,
            }),
          });
          showToast("Запрос на корректировку отправлен администраторам в бота. Итоговый баланс изменится после подтверждения.", "info");
          loadUserDetail(userId);
        } catch (e) {
          showToast(e.message || "Ошибка корректировки баланса", "error");
        }
      };
    }
    const blockBtn = document.getElementById("user-block-toggle-btn");
    if (blockBtn) {
      blockBtn.onclick = async () => {
        const targetBlocked = !Boolean(u.is_blocked);
        let reason = "";
        if (targetBlocked) {
          const rs = await openUxDialog({
            title: "Блокировка пользователя",
            message: "Укажите причину блокировки (необязательно):",
            inputPlaceholder: "Причина",
            confirmText: "Заблокировать",
            cancelText: "Отмена",
          });
          if (!rs.confirmed) return;
          reason = (rs.value || "").trim();
        } else {
          const rs = await openUxDialog({
            title: "Разблокировка пользователя",
            message: "Снять блокировку с пользователя?",
            confirmText: "Разблокировать",
            cancelText: "Отмена",
          });
          if (!rs.confirmed) return;
        }
        try {
          await apiRequest(`/users/${userId}/block`, {
            method: "POST",
            body: JSON.stringify({
              is_blocked: targetBlocked,
              reason,
            }),
          });
          showToast(targetBlocked ? "Пользователь заблокирован" : "Пользователь разблокирован", "success");
          loadUserDetail(userId);
        } catch (e) {
          showToast(e.message || "Ошибка изменения статуса пользователя", "error");
        }
      };
    }
    section.querySelectorAll(".copy-address-btn").forEach((btn) => {
      btn.addEventListener("click", async (ev) => {
        ev.preventDefault();
        const addr = btn.getAttribute("data-address") || "";
        const ok = await copyTextToClipboard(addr);
        showToast(ok ? "Адрес скопирован" : "Не удалось скопировать адрес", ok ? "success" : "error");
      });
    });
    const invFilter = document.getElementById("user-invest-filter");
    if (invFilter) {
      const applyInvFilter = () => {
        const v = (invFilter.value || "").toLowerCase();
        section.querySelectorAll("tr[data-invest-status]").forEach((tr) => {
          const s = (tr.getAttribute("data-invest-status") || "").toLowerCase();
          tr.style.display = !v || s === v ? "" : "none";
        });
      };
      invFilter.addEventListener("change", applyInvFilter);
      applyInvFilter();
    }

  } catch (e) {
    section.innerHTML = `<h1>Пользователь</h1><div class="error">${e.message}</div>`;
  }
}

function withdrawalStatusBadge(status) {
  const s = (status || "").toUpperCase();
  if (s === "PENDING") return "status-badge status-pending";
  if (s === "APPROVED") return "status-badge status-paid";
  if (s === "REJECTED") return "status-badge status-expired";
  return "status-badge status-unknown";
}

function getWithdrawalRiskFlags(w) {
  const flags = [];
  const amount = Number(w.amount || 0);
  const addr = String(w.address || "");
  if (amount >= 5000) flags.push("HIGH_AMOUNT");
  if (!addr || addr.length < 20) flags.push("SHORT_ADDRESS");
  if (w.currency === "USDT" && !/^0x[a-fA-F0-9]{40}$/.test(addr) && !/^T[1-9A-HJ-NP-Za-km-z]{33}$/.test(addr)) {
    flags.push("ADDRESS_FORMAT");
  }
  return flags;
}

async function loadWithdrawals() {
  const section = document.getElementById("withdrawals-section");
  section.innerHTML = "<h1>Выводы</h1><p>Загрузка...</p>";
  try {
    const saved = loadSavedState(WITHDRAWALS_FILTERS_KEY, { status: "PENDING" });
    const statusParam = document.getElementById("withdrawals-status-filter")?.value || saved.status || "PENDING";
    const amountMin = document.getElementById("withdrawals-amount-min")?.value?.trim() || saved.amount_min || "";
    const amountMax = document.getElementById("withdrawals-amount-max")?.value?.trim() || saved.amount_max || "";
    const currency = document.getElementById("withdrawals-currency-filter")?.value || saved.currency_filter || "";
    const wParams = new URLSearchParams();
    wParams.set("status", statusParam);
    if (amountMin) wParams.set("amount_min", amountMin);
    if (amountMax) wParams.set("amount_max", amountMax);
    if (currency) wParams.set("currency_filter", currency);
    const data = await apiRequest(`/withdrawals?${wParams.toString()}`);
    const hasPending = (data.items || []).some((w) => w.status === "PENDING");
    const rows = data.items
      .map(
        (w) => `
      <tr>
        <td>${w.status === "PENDING" ? `<input type="checkbox" class="withdrawal-select" value="${w.id}" title="Выбрать для массового действия" />` : ""}</td>
        <td>${w.id}</td>
        <td>${w.telegram_id}</td>
        <td>${w.username || ""}</td>
        <td class="amount-negative">−${w.amount} ${w.currency}</td>
        <td class="cell-address">${escapeHtmlAttr(w.address || "")} <button type="button" class="btn-secondary-small copy-address-btn" data-address="${escapeHtmlAttr(w.address || "")}">Копировать</button></td>
        <td><span class="${withdrawalStatusBadge(w.status)}">${w.status}</span></td>
        <td>${
          getWithdrawalRiskFlags(w).length
            ? getWithdrawalRiskFlags(w).map((f) => `<span class="risk-flag">${f}</span>`).join(" ")
            : '<span class="risk-flag risk-ok">OK</span>'
        }</td>
        <td>
          <button type="button" class="btn-secondary-small withdrawal-detail-btn" data-id="${w.id}">Подробнее</button>
          ${w.status === "PENDING" ? `<button data-id="${w.id}" data-action="approve" class="btn-approve">Подтвердить</button> <button data-id="${w.id}" data-action="reject" class="btn-reject">Отклонить</button>` : ""}
        </td>
      </tr>`
      )
      .join("");
    const rowsHtml = rows || `<tr><td colspan="9"><div class="empty-state"><strong>Нет заявок на вывод</strong><span>Смените статус в фильтре или зайдите позже.</span></div></td></tr>`;
    section.innerHTML = `
      <h1>Выводы</h1>
      <p class="section-desc">Управление заявками на вывод средств.</p>
      <div class="panel-card">
        <div class="toolbar filters-toolbar">
          <label class="filter-label">
            Статус
            <select id="withdrawals-status-filter">
              <option value="PENDING" ${statusParam === "PENDING" ? "selected" : ""}>Ожидают</option>
              <option value="APPROVED" ${statusParam === "APPROVED" ? "selected" : ""}>Подтверждённые</option>
              <option value="REJECTED" ${statusParam === "REJECTED" ? "selected" : ""}>Отклонённые</option>
            </select>
          </label>
          <label class="filter-label">
            Валюта
            <select id="withdrawals-currency-filter">
              <option value="">Все</option>
              <option value="USDT" ${currency === "USDT" ? "selected" : ""}>USDT</option>
              <option value="BTC" ${currency === "BTC" ? "selected" : ""}>BTC</option>
              <option value="ETH" ${currency === "ETH" ? "selected" : ""}>ETH</option>
            </select>
          </label>
          <label class="filter-label">
            Сумма от
            <input type="number" id="withdrawals-amount-min" min="0" step="0.01" value="${escapeHtmlAttr(amountMin)}" />
          </label>
          <label class="filter-label">
            Сумма до
            <input type="number" id="withdrawals-amount-max" min="0" step="0.01" value="${escapeHtmlAttr(amountMax)}" />
          </label>
          <button type="button" id="withdrawals-apply-filters" title="Обновить список по выбранному статусу">Применить</button>
          ${hasPending ? `<button type="button" id="withdrawals-bulk-approve" class="btn-approve" title="Подтвердить выбранные заявки">Подтвердить выбранные</button>
          <button type="button" id="withdrawals-bulk-reject" class="btn-reject" title="Отклонить выбранные заявки">Отклонить выбранные</button>` : ""}
        </div>
        <div class="table-wrapper">
          <div class="table-wrapper-inner">
            <table>
              <thead>
                <tr>
                  <th>✓</th>
                  <th>ID</th>
                  <th>Telegram ID</th>
                  <th>Username</th>
                  <th>Сумма</th>
                  <th>Кошелек</th>
                  <th>Статус</th>
                  <th>Риск</th>
                  <th>Действия</th>
                </tr>
              </thead>
              <tbody>${rowsHtml}</tbody>
            </table>
          </div>
        </div>
      </div>
    `;

    document.getElementById("withdrawals-apply-filters")?.addEventListener("click", () => {
      const status = document.getElementById("withdrawals-status-filter")?.value || "PENDING";
      const amount_min = document.getElementById("withdrawals-amount-min")?.value?.trim() || "";
      const amount_max = document.getElementById("withdrawals-amount-max")?.value?.trim() || "";
      const currency_filter = document.getElementById("withdrawals-currency-filter")?.value || "";
      saveState(WITHDRAWALS_FILTERS_KEY, { status, amount_min, amount_max, currency_filter });
      loadWithdrawals();
    });
    section.querySelectorAll(".copy-address-btn").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const addr = btn.getAttribute("data-address") || "";
        const ok = await copyTextToClipboard(addr);
        showToast(ok ? "Адрес скопирован" : "Не удалось скопировать адрес", ok ? "success" : "error");
      });
    });
    section.querySelectorAll(".withdrawal-detail-btn").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const id = btn.getAttribute("data-id");
        if (!id) return;
        try {
          const w = await apiRequest(`/withdrawals/${id}`);
          const flags = getWithdrawalRiskFlags(w);
          const timeline = [
            `Создано: ${w.created_at ? new Date(w.created_at).toLocaleString() : "—"}`,
            `Статус: ${w.status}`,
            `Решение: ${w.decided_at ? new Date(w.decided_at).toLocaleString() : "—"}`,
          ].join("\n");
          const body = [
            `ID: ${w.id}`,
            `User: ${w.user_id} (${w.telegram_id}${w.username ? ` @${w.username}` : ""})`,
            `Сумма: ${w.amount} ${w.currency}`,
            `Кошелек: ${w.address}`,
            `Risk: ${flags.length ? flags.join(", ") : "OK"}`,
            "",
            timeline,
          ].join("\n");
          await openUxDialog({
            title: `Вывод #${w.id}`,
            message: body,
            confirmText: "Закрыть",
          });
        } catch (e) {
          showToast(e.message || "Ошибка загрузки вывода", "error");
        }
      });
    });
    const runBulkWithdrawalAction = async (action) => {
      const selectedIds = Array.from(section.querySelectorAll(".withdrawal-select:checked")).map((el) => el.value);
      if (!selectedIds.length) {
        showToast("Выберите хотя бы одну заявку", "info");
        return;
      }
      const check = await openUxDialog({
        title: "Массовое действие",
        message: `${action === "approve" ? "Подтвердить" : "Отклонить"} выбранные заявки: ${selectedIds.length} шт.?`,
        confirmText: action === "approve" ? "Подтвердить" : "Отклонить",
        cancelText: "Отмена",
      });
      if (!check.confirmed) return;
      let ok = 0;
      const appliedIds = [];
      for (const id of selectedIds) {
        try {
          await apiRequest(`/withdrawals/${id}/${action}`, { method: "POST" });
          ok += 1;
          appliedIds.push(id);
        } catch (_) {}
      }
      const inverseAction = action === "approve" ? "reject" : "approve";
      showToast(
        `Готово: ${ok}/${selectedIds.length}`,
        ok === selectedIds.length ? "success" : "info",
        appliedIds.length
          ? {
              label: "Undo",
              onClick: async () => {
                let rollbackOk = 0;
                for (const id of appliedIds) {
                  try {
                    await apiRequest(`/withdrawals/${id}/${inverseAction}`, { method: "POST" });
                    rollbackOk += 1;
                  } catch (_) {}
                }
                showToast(`Откат: ${rollbackOk}/${appliedIds.length}`, rollbackOk === appliedIds.length ? "success" : "info");
                loadWithdrawals();
              },
            }
          : null
      );
      loadWithdrawals();
    };
    document.getElementById("withdrawals-bulk-approve")?.addEventListener("click", () => runBulkWithdrawalAction("approve"));
    document.getElementById("withdrawals-bulk-reject")?.addEventListener("click", () => runBulkWithdrawalAction("reject"));
    section.querySelectorAll("button[data-id]").forEach((btn) => {
      btn.onclick = async () => {
        const id = btn.getAttribute("data-id");
        const action = btn.getAttribute("data-action");
        try {
          await apiRequest(`/withdrawals/${id}/${action}`, {
            method: "POST",
          });
          loadWithdrawals();
        } catch (e) {
          showToast(e.message || "Ошибка обработки вывода", "error");
        }
      };
    });
  } catch (e) {
    section.innerHTML = `<h1>Выводы</h1><div class="error">${e.message}</div>`;
  }
}

async function loadSettings() {
  const section = document.getElementById("settings-section");
  section.innerHTML = `<h1>Настройки</h1><div class="panel-card"><div class="skeleton-line" style="width:68%;"></div><div class="skeleton-line" style="width:92%; margin-top:12px;"></div></div>`;
  try {
    const [s, defaults, history, dangerSummary] = await Promise.all([
      apiRequest("/system-settings"),
      apiRequest("/system-settings/defaults").catch(() => null),
      apiRequest("/system-settings/history?page=1&page_size=8").catch(() => ({ items: [] })),
      apiRequest("/maintenance/reset-data/summary?keep_settings=true").catch(() => null),
    ]);
    const initialModes = {
      deposit:
        Number(s.min_deposit_usdt) === Number(s.max_deposit_usdt) ? "fixed" : "range",
      withdraw:
        Number(s.min_withdraw_usdt) === Number(s.max_withdraw_usdt) ? "fixed" : "range",
      invest:
        Number(s.min_invest_usdt) === Number(s.max_invest_usdt) ? "fixed" : "range",
    };
    section.innerHTML = `
      <h1>Финансовые настройки</h1>
      <p class="section-desc">Настройка режимов лимитов отдельно для депозитов, выводов и инвестиций. В режиме «Фиксированная сумма» будет сохранено как min = max.</p>
      <div class="toolbar" style="margin-bottom: 10px;">
        <label class="filter-label" title="Автосохранение черновика настроек в браузере">
          Черновик
          <label style="display:inline-flex;align-items:center;gap:6px;">
            <input type="checkbox" id="settings-autosave-toggle" />
            Автосохранять
          </label>
        </label>
        <button type="button" id="settings-draft-clear-btn" class="btn-secondary-small" title="Удалить сохранённый черновик">Удалить черновик</button>
        <button type="button" id="settings-save-preset-btn" class="btn-secondary-small" title="Сохранить текущие настройки как пресет">Сохранить пресет</button>
        <button type="button" id="settings-apply-preset-btn" class="btn-secondary-small" title="Применить ранее сохранённый пресет">Применить пресет</button>
        <button type="button" id="settings-reset-defaults-btn" class="btn-secondary-small" title="Сбросить настройки к значениям по умолчанию">Сброс к дефолту</button>
      </div>
      <div class="settings-card">
        <div class="settings-header">
          <h2>Лимиты операций</h2>
          <p>Выберите режим для каждой операции: фиксированная сумма или диапазон.</p>
        </div>
        <div class="settings-field" style="margin-bottom:12px;">
          <div class="settings-label">Контакт саппорта (Telegram)</div>
          <input type="text" id="support_contact" class="settings-input" value="${escapeHtmlAttr(s.support_contact || "")}" placeholder="@support_username или https://t.me/support_username" />
          <div class="settings-hint">Используется в кнопке 🆘 Саппорт в боте</div>
        </div>
        <form id="settings-form" class="settings-form">
          <div class="settings-limit-grid">
            <div class="settings-limit-card" data-entity="deposit">
              <div class="settings-limit-card-head">
                <div>
                  <div class="settings-label">Лимиты депозита</div>
                  <div class="settings-hint">Настройка минимальной/максимальной суммы пополнения</div>
                </div>
                <label class="switch settings-inline-switch">
                  <input type="checkbox" id="allow_deposits" ${s.allow_deposits ? "checked" : ""} />
                  <span class="switch-slider"></span>
                </label>
              </div>
              <div class="settings-inline-hint">Разрешить пополнения</div>
              <div class="limit-mode-segment" id="mode_segment_deposit">
                <button type="button" class="limit-mode-btn" data-entity="deposit" data-mode="fixed">Фиксированная сумма</button>
                <button type="button" class="limit-mode-btn" data-entity="deposit" data-mode="range">Диапазон</button>
              </div>
              <input type="hidden" id="mode_deposit" value="${initialModes.deposit}" />
              <div id="deposit_fixed_panel" class="limit-fields ${initialModes.deposit === "fixed" ? "" : "hidden"}">
                <div class="settings-field">
                  <div class="settings-label">Сумма депозита (USDT)</div>
                  <input type="number" step="0.01" min="0" id="fixed_deposit_usdt" class="settings-input" value="${s.min_deposit_usdt}" />
                </div>
              </div>
              <div id="deposit_range_panel" class="limit-fields ${initialModes.deposit === "range" ? "" : "hidden"}">
                <div class="settings-field">
                  <div class="settings-label">Мин. депозит (USDT)</div>
                  <input type="number" step="0.01" min="0" id="min_deposit_usdt" class="settings-input" value="${s.min_deposit_usdt}" />
                </div>
                <div class="settings-field">
                  <div class="settings-label">Макс. депозит (USDT)</div>
                  <input type="number" step="0.01" min="0" id="max_deposit_usdt" class="settings-input" value="${s.max_deposit_usdt}" />
                </div>
              </div>
              <div class="limit-summary" id="summary_deposit"></div>
            </div>

            <div class="settings-limit-card" data-entity="withdraw">
              <div class="settings-limit-card-head">
                <div>
                  <div class="settings-label">Лимиты вывода</div>
                  <div class="settings-hint">Настройка минимальной/максимальной суммы вывода</div>
                </div>
                <label class="switch settings-inline-switch">
                  <input type="checkbox" id="allow_withdrawals" ${s.allow_withdrawals !== false ? "checked" : ""} />
                  <span class="switch-slider"></span>
                </label>
              </div>
              <div class="settings-inline-hint">Разрешить выводы</div>
              <div class="limit-mode-segment" id="mode_segment_withdraw">
                <button type="button" class="limit-mode-btn" data-entity="withdraw" data-mode="fixed">Фиксированная сумма</button>
                <button type="button" class="limit-mode-btn" data-entity="withdraw" data-mode="range">Диапазон</button>
              </div>
              <input type="hidden" id="mode_withdraw" value="${initialModes.withdraw}" />
              <div id="withdraw_fixed_panel" class="limit-fields ${initialModes.withdraw === "fixed" ? "" : "hidden"}">
                <div class="settings-field">
                  <div class="settings-label">Сумма вывода (USDT)</div>
                  <input type="number" step="0.01" min="0" id="fixed_withdraw_usdt" class="settings-input" value="${s.min_withdraw_usdt}" />
                </div>
              </div>
              <div id="withdraw_range_panel" class="limit-fields ${initialModes.withdraw === "range" ? "" : "hidden"}">
                <div class="settings-field">
                  <div class="settings-label">Мин. вывод (USDT)</div>
                  <input type="number" step="0.01" min="0" id="min_withdraw_usdt" class="settings-input" value="${s.min_withdraw_usdt}" />
                </div>
                <div class="settings-field">
                  <div class="settings-label">Макс. вывод (USDT)</div>
                  <input type="number" step="0.01" min="0" id="max_withdraw_usdt" class="settings-input" value="${s.max_withdraw_usdt}" />
                </div>
              </div>
              <div class="limit-summary" id="summary_withdraw"></div>
            </div>

            <div class="settings-limit-card" data-entity="invest">
              <div class="settings-limit-card-head">
                <div>
                  <div class="settings-label">Лимиты инвестиций</div>
                  <div class="settings-hint">Настройка суммы участия в сделке</div>
                </div>
                <label class="switch settings-inline-switch">
                  <input type="checkbox" id="allow_investments" ${s.allow_investments !== false ? "checked" : ""} />
                  <span class="switch-slider"></span>
                </label>
              </div>
              <div class="settings-inline-hint">Разрешить участие в сделках</div>
              <div class="limit-mode-segment" id="mode_segment_invest">
                <button type="button" class="limit-mode-btn" data-entity="invest" data-mode="fixed">Фиксированная сумма</button>
                <button type="button" class="limit-mode-btn" data-entity="invest" data-mode="range">Диапазон</button>
              </div>
              <input type="hidden" id="mode_invest" value="${initialModes.invest}" />
              <div id="invest_fixed_panel" class="limit-fields ${initialModes.invest === "fixed" ? "" : "hidden"}">
                <div class="settings-field">
                  <div class="settings-label">Сумма инвестиции (USDT)</div>
                  <input type="number" step="0.01" min="0" id="fixed_invest_usdt" class="settings-input" value="${s.min_invest_usdt}" />
                </div>
              </div>
              <div id="invest_range_panel" class="limit-fields ${initialModes.invest === "range" ? "" : "hidden"}">
                <div class="settings-field">
                  <div class="settings-label">Мин. инвестиция (USDT)</div>
                  <input type="number" step="0.01" min="0" id="min_invest_usdt" class="settings-input" value="${s.min_invest_usdt}" />
                </div>
                <div class="settings-field">
                  <div class="settings-label">Макс. инвестиция (USDT)</div>
                  <input type="number" step="0.01" min="0" id="max_invest_usdt" class="settings-input" value="${s.max_invest_usdt}" />
                </div>
              </div>
              <div class="limit-summary" id="summary_invest"></div>
            </div>
          </div>
          <div class="settings-footer">
            <div class="settings-updated-at">
              Последнее обновление: ${s.updated_at ? new Date(s.updated_at).toLocaleString() : "—"}
            </div>
            <button type="submit" id="settings-save-btn" class="btn-primary-wide">
              <span class="btn-label">Сохранить</span>
            </button>
          </div>
        </form>
      </div>
      <div class="panel-card bulk-credit-card">
        <div class="bulk-credit-header">
          <h2>Массовые действия с балансом</h2>
          <p class="section-desc">Операции применяются сразу ко всем пользователям. Используйте только при необходимости.</p>
        </div>
        <div class="bulk-credit-row">
          <label class="bulk-credit-label">Сумма (USDT)</label>
          <input type="number" step="0.01" min="0" id="bulk-credit-amount" class="settings-input bulk-credit-input" placeholder="100" />
          <label class="bulk-credit-label">Комментарий в ledger</label>
          <input type="text" id="bulk-credit-comment" class="settings-input bulk-credit-input" placeholder="Необязательно" />
          <button type="button" id="bulk-credit-btn" class="btn-bulk-credit">Зачислить всем</button>
          <button type="button" id="bulk-reset-btn" class="btn-reject">Обнулить баланс всем</button>
        </div>
      </div>
      <div class="panel-card danger-zone-card">
        <div class="danger-zone-header">
          <div class="danger-zone-icon">⚠️</div>
          <div>
            <h2>Опасная зона</h2>
            <p class="section-desc">Необратимые действия. Перед запуском внимательно проверьте среду и последствия.</p>
          </div>
        </div>
        <div class="danger-zone-env">
          <span class="env-label">Среда:</span>
          <span class="env-badge ${(dangerSummary?.environment || "TEST") === "PRODUCTION" ? "prod" : "safe"}">${escapeHtmlAttr(dangerSummary?.environment || "TEST")}</span>
          <span class="env-db">БД: <strong>${escapeHtmlAttr(dangerSummary?.database || "unknown-db")}</strong></span>
        </div>
        <div class="danger-zone-note">
          <div><strong>Будут удалены:</strong></div>
          <ul class="danger-list">
            ${
              (dangerSummary?.items || [])
                .map((x) => `<li>${escapeHtmlAttr(x.title)} — <strong>${Number(x.rows || 0).toLocaleString("ru-RU")}</strong></li>`)
                .join("") || "<li>Нет данных preview</li>"
            }
          </ul>
          <div style="margin-top:8px;"><strong>Сохранятся:</strong></div>
          <ul class="danger-list">
            ${(dangerSummary?.will_keep || ["Схема БД", "Финансовые настройки", "Системные конфиги"])
              .filter((x) => x && x !== "—")
              .map((x) => `<li>${escapeHtmlAttr(x)}</li>`)
              .join("")}
          </ul>
          <div class="danger-total">Итого к удалению: ${Number(dangerSummary?.total_rows || 0).toLocaleString("ru-RU")} записей</div>
          <div class="danger-backup-state">
            Backup: ${
              dangerSummary?.backup_available
                ? `доступен · последний: ${dangerSummary?.last_backup_at ? new Date(dangerSummary.last_backup_at).toLocaleString() : "—"}`
                : "недоступен в UI (используйте pg_dump)"
            }
          </div>
        </div>
        <div class="toolbar danger-zone-toolbar danger-zone-actions">
          <button type="button" id="db-dry-run-btn" class="btn-secondary-small">Предпросмотр очистки</button>
          <button type="button" id="db-backup-btn" class="btn-secondary-small">Сделать backup</button>
          <button type="button" id="db-clear-logs-btn" class="btn-secondary-small">Очистить только логи</button>
          <button type="button" id="db-clear-broadcasts-btn" class="btn-secondary-small">Очистить только рассылки</button>
          <button type="button" id="db-clear-deals-btn" class="btn-secondary-small">Очистить только сделки</button>
          <button type="button" id="db-clear-payments-btn" class="btn-secondary-small">Очистить только платежи</button>
        </div>
        <div class="danger-confirm">
          <label><input type="checkbox" id="dz-check-irrev" /> Я понимаю, что действие необратимо</label>
          <label><input type="checkbox" id="dz-check-env" /> Я проверил, что это не production</label>
          <label>Введите подтверждение: <code>${escapeHtmlAttr(dangerSummary?.environment || "TEST")}</code>
            <input type="text" id="dz-confirm-input" class="settings-input" placeholder="${escapeHtmlAttr(dangerSummary?.environment || "TEST")}" />
          </label>
        </div>
        <div class="toolbar danger-zone-toolbar">
          <button type="button" id="db-reset-btn" class="btn-danger-wide" disabled>
            <span class="btn-label">Безвозвратно удалить данные</span>
          </button>
        </div>
      </div>
      <div class="panel-card">
        <h2>История изменений настроек</h2>
        ${
          (history?.items || []).length
            ? `<div class="table-wrap"><table><thead><tr><th>ID</th><th>Источник</th><th>Изменения</th><th>Время</th></tr></thead><tbody>${
                (history.items || [])
                  .map((h) => {
                    const keys = Object.keys(h.changes || {});
                    return `<tr>
                      <td>${h.id}</td>
                      <td>${escapeHtmlAttr(h.source || "manual")}</td>
                      <td title="${escapeHtmlAttr(keys.join(", "))}">${escapeHtmlAttr(keys.slice(0, 4).join(", ") || "—")}${keys.length > 4 ? ` +${keys.length - 4}` : ""}</td>
                      <td>${h.created_at ? new Date(h.created_at).toLocaleString() : "—"}</td>
                    </tr>`;
                  })
                  .join("")
              }</tbody></table></div>`
            : `<div class="empty-state"><strong>Пока нет версий</strong><span>После первого сохранения появится история изменений настроек.</span></div>`
        }
      </div>
    `;

    const form = document.getElementById("settings-form");
    const draftToggle = document.getElementById("settings-autosave-toggle");
    const clearDraftBtn = document.getElementById("settings-draft-clear-btn");
    const savePresetBtn = document.getElementById("settings-save-preset-btn");
    const applyPresetBtn = document.getElementById("settings-apply-preset-btn");
    const resetDefaultsBtn = document.getElementById("settings-reset-defaults-btn");
    const draftRaw = localStorage.getItem(SETTINGS_DRAFT_KEY);
    const draft = draftRaw ? loadSavedState(SETTINGS_DRAFT_KEY, {}) : null;
    if (draftToggle) draftToggle.checked = Boolean(draft?.enabled);
    const formatAmount = (num) => {
      const n = Number(num);
      if (!Number.isFinite(n)) return "—";
      return `${n.toLocaleString("ru-RU", { maximumFractionDigits: 2 })} USDT`;
    };
    const setMode = (entity, mode) => {
      const modeInput = document.getElementById(`mode_${entity}`);
      if (modeInput) modeInput.value = mode;
      const fixedPanel = document.getElementById(`${entity}_fixed_panel`);
      const rangePanel = document.getElementById(`${entity}_range_panel`);
      if (fixedPanel) fixedPanel.classList.toggle("hidden", mode !== "fixed");
      if (rangePanel) rangePanel.classList.toggle("hidden", mode !== "range");
      section
        .querySelectorAll(`.limit-mode-btn[data-entity="${entity}"]`)
        .forEach((btn) => btn.classList.toggle("active", btn.getAttribute("data-mode") === mode));
      updateSummaries();
    };
    const getParsedValue = (id, label) => {
      const input = document.getElementById(id);
      const raw = (input?.value || "").trim().replace(",", ".");
      const num = parseFloat(raw);
      if (Number.isNaN(num) || num <= 0) {
        throw new Error(`Поле "${label}" должно быть числом больше 0`);
      }
      return num;
    };
    const updateSummaries = () => {
      const entities = [
        {
          key: "deposit",
          title: "депозита",
          minId: "min_deposit_usdt",
          maxId: "max_deposit_usdt",
          fixedId: "fixed_deposit_usdt",
        },
        {
          key: "withdraw",
          title: "вывода",
          minId: "min_withdraw_usdt",
          maxId: "max_withdraw_usdt",
          fixedId: "fixed_withdraw_usdt",
        },
        {
          key: "invest",
          title: "инвестиций",
          minId: "min_invest_usdt",
          maxId: "max_invest_usdt",
          fixedId: "fixed_invest_usdt",
        },
      ];
      for (const e of entities) {
        const mode = document.getElementById(`mode_${e.key}`)?.value || "range";
        const summaryEl = document.getElementById(`summary_${e.key}`);
        if (!summaryEl) continue;
        if (mode === "fixed") {
          const val = parseFloat((document.getElementById(e.fixedId)?.value || "").replace(",", "."));
          summaryEl.textContent = `Текущий режим: фиксированная сумма ${formatAmount(val)}.`;
        } else {
          const minVal = parseFloat((document.getElementById(e.minId)?.value || "").replace(",", "."));
          const maxVal = parseFloat((document.getElementById(e.maxId)?.value || "").replace(",", "."));
          summaryEl.textContent = `Текущий режим: диапазон от ${formatAmount(minVal)} до ${formatAmount(maxVal)}.`;
        }
      }
    };

    const buildSettingsPayload = () => {
      const payloadValues = {};
      const entities = [
        {
          key: "deposit",
          minField: "min_deposit_usdt",
          maxField: "max_deposit_usdt",
          fixedField: "fixed_deposit_usdt",
          title: "депозит",
        },
        {
          key: "withdraw",
          minField: "min_withdraw_usdt",
          maxField: "max_withdraw_usdt",
          fixedField: "fixed_withdraw_usdt",
          title: "вывод",
        },
        {
          key: "invest",
          minField: "min_invest_usdt",
          maxField: "max_invest_usdt",
          fixedField: "fixed_invest_usdt",
          title: "инвестиция",
        },
      ];

      for (const item of entities) {
        const mode = document.getElementById(`mode_${item.key}`)?.value || "range";
        if (mode === "fixed") {
          const fixed = getParsedValue(item.fixedField, `${item.title} (фикс.)`);
          payloadValues[item.minField] = fixed;
          payloadValues[item.maxField] = fixed;
        } else {
          const min = getParsedValue(item.minField, `${item.title} min`);
          const max = getParsedValue(item.maxField, `${item.title} max`);
          if (min > max) {
            throw new Error(`Для "${item.title}" минимум не может быть больше максимума`);
          }
          payloadValues[item.minField] = min;
          payloadValues[item.maxField] = max;
        }
      }
      payloadValues.allow_deposits = Boolean(document.getElementById("allow_deposits")?.checked);
      payloadValues.allow_investments = Boolean(document.getElementById("allow_investments")?.checked);
      payloadValues.allow_withdrawals = Boolean(document.getElementById("allow_withdrawals")?.checked);
      payloadValues.support_contact = String(document.getElementById("support_contact")?.value || "").trim();
      return payloadValues;
    };

    const updateSettingsSaveState = () => {
      const saveBtn = document.getElementById("settings-save-btn");
      if (!saveBtn) return;
      try {
        buildSettingsPayload();
        saveBtn.disabled = false;
      } catch (_) {
        saveBtn.disabled = true;
      }
    };

    section.querySelectorAll(".limit-mode-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        const entity = btn.getAttribute("data-entity");
        const mode = btn.getAttribute("data-mode");
        if (!entity || !mode) return;
        setMode(entity, mode);
      });
    });
    [
      "support_contact",
      "fixed_deposit_usdt",
      "min_deposit_usdt",
      "max_deposit_usdt",
      "fixed_withdraw_usdt",
      "min_withdraw_usdt",
      "max_withdraw_usdt",
      "fixed_invest_usdt",
      "min_invest_usdt",
      "max_invest_usdt",
    ].forEach((id) => {
      document.getElementById(id)?.addEventListener("input", () => {
        updateSummaries();
        updateSettingsSaveState();
      });
    });
    ["allow_deposits", "allow_investments", "allow_withdrawals"].forEach((id) => {
      document.getElementById(id)?.addEventListener("change", updateSettingsSaveState);
    });
    setMode("deposit", initialModes.deposit);
    setMode("withdraw", initialModes.withdraw);
    setMode("invest", initialModes.invest);
    updateSummaries();
    updateSettingsSaveState();

    const applyDraft = (payload) => {
      if (!payload || typeof payload !== "object") return;
      const setInput = (id, v) => {
        const el = document.getElementById(id);
        if (!el || v == null) return;
        if (el.type === "checkbox") el.checked = Boolean(v);
        else el.value = String(v);
      };
      if (payload.modes) {
        if (payload.modes.deposit) setMode("deposit", payload.modes.deposit);
        if (payload.modes.withdraw) setMode("withdraw", payload.modes.withdraw);
        if (payload.modes.invest) setMode("invest", payload.modes.invest);
      }
      [
        "fixed_deposit_usdt","min_deposit_usdt","max_deposit_usdt",
        "fixed_withdraw_usdt","min_withdraw_usdt","max_withdraw_usdt",
        "fixed_invest_usdt","min_invest_usdt","max_invest_usdt",
        "allow_deposits","allow_investments","allow_withdrawals","support_contact",
      ].forEach((id) => setInput(id, payload[id]));
      updateSummaries();
      updateSettingsSaveState();
    };
    const collectCurrentFormState = () => {
      const payload = {
        modes: {
          deposit: document.getElementById("mode_deposit")?.value || "range",
          withdraw: document.getElementById("mode_withdraw")?.value || "range",
          invest: document.getElementById("mode_invest")?.value || "range",
        },
      };
      [
        "support_contact",
        "fixed_deposit_usdt","min_deposit_usdt","max_deposit_usdt",
        "fixed_withdraw_usdt","min_withdraw_usdt","max_withdraw_usdt",
        "fixed_invest_usdt","min_invest_usdt","max_invest_usdt",
      ].forEach((id) => {
        payload[id] = document.getElementById(id)?.value ?? "";
      });
      payload.allow_deposits = Boolean(document.getElementById("allow_deposits")?.checked);
      payload.allow_investments = Boolean(document.getElementById("allow_investments")?.checked);
      payload.allow_withdrawals = Boolean(document.getElementById("allow_withdrawals")?.checked);
      payload.support_contact = String(document.getElementById("support_contact")?.value || "").trim();
      return payload;
    };
    const readSettingsPresets = () => {
      try {
        const raw = localStorage.getItem(SETTINGS_PRESETS_KEY);
        const list = raw ? JSON.parse(raw) : [];
        return Array.isArray(list) ? list : [];
      } catch (_) {
        return [];
      }
    };
    const writeSettingsPresets = (list) => {
      try {
        localStorage.setItem(SETTINGS_PRESETS_KEY, JSON.stringify(Array.isArray(list) ? list : []));
      } catch (_) {}
    };
    if (draft?.enabled && draft?.payload) {
      applyDraft(draft.payload);
      showToast("Черновик настроек восстановлен", "info");
    }

    let autosaveTimer = null;
    const saveDraftMaybe = () => {
      if (!draftToggle?.checked) return;
      clearTimeout(autosaveTimer);
      autosaveTimer = setTimeout(() => {
        const payload = collectCurrentFormState();
        saveState(SETTINGS_DRAFT_KEY, { enabled: true, payload, saved_at: new Date().toISOString() });
      }, 300);
    };
    clearDraftBtn?.addEventListener("click", () => {
      localStorage.removeItem(SETTINGS_DRAFT_KEY);
      if (draftToggle) draftToggle.checked = false;
      showToast("Черновик удалён", "info");
    });
    draftToggle?.addEventListener("change", () => {
      if (!draftToggle.checked) localStorage.removeItem(SETTINGS_DRAFT_KEY);
      else saveDraftMaybe();
    });
    savePresetBtn?.addEventListener("click", async () => {
      const prompt = await openUxDialog({
        title: "Сохранить пресет настроек",
        message: "Введите название пресета",
        inputPlaceholder: "Например: Прод-лимиты",
        confirmText: "Сохранить",
        cancelText: "Отмена",
      });
      if (!prompt.confirmed) return;
      const name = (prompt.value || "").trim().slice(0, 60);
      if (!name) return showToast("Введите название пресета", "error");
      const all = readSettingsPresets();
      const next = [{ name, payload: collectCurrentFormState(), created_at: new Date().toISOString() }, ...all].slice(0, 20);
      writeSettingsPresets(next);
      showToast("Пресет сохранён", "success");
    });
    applyPresetBtn?.addEventListener("click", async () => {
      const list = readSettingsPresets();
      if (!list.length) return showToast("Нет сохранённых пресетов", "info");
      const text = list.map((p, i) => `${i + 1}. ${p.name}`).join("\n");
      const pick = await openUxDialog({
        title: "Применить пресет",
        message: `Выберите номер пресета:\n${text}`,
        inputPlaceholder: "1",
        confirmText: "Применить",
        cancelText: "Отмена",
      });
      if (!pick.confirmed) return;
      const idx = Number((pick.value || "").trim()) - 1;
      if (!Number.isInteger(idx) || idx < 0 || idx >= list.length) {
        return showToast("Неверный номер пресета", "error");
      }
      applyDraft(list[idx].payload || {});
      showToast(`Пресет "${list[idx].name}" применён`, "success");
    });
    resetDefaultsBtn?.addEventListener("click", async () => {
      const confirmReset = await openUxDialog({
        title: "Сброс к дефолту",
        message: "Сбросить финансовые настройки к значениям по умолчанию?",
        confirmText: "Сбросить",
        cancelText: "Отмена",
      });
      if (!confirmReset.confirmed) return;
      try {
        if (defaults) {
          await apiRequest("/system-settings/bulk", {
            method: "PUT",
            body: JSON.stringify(defaults),
          });
        } else {
          await apiRequest("/system-settings/reset-defaults", { method: "POST" });
        }
        showToast("Настройки сброшены к значениям по умолчанию", "success");
        localStorage.removeItem(SETTINGS_DRAFT_KEY);
        loadSettings();
      } catch (e) {
        showToast(e.message || "Ошибка сброса", "error");
      }
    });
    form?.querySelectorAll("input, select, textarea").forEach((el) => {
      el.addEventListener("input", saveDraftMaybe);
      el.addEventListener("change", saveDraftMaybe);
    });

    if (form) {
      form.onsubmit = async (e) => {
        e.preventDefault();
        const saveBtn = document.getElementById("settings-save-btn");
        const originalText = saveBtn ? saveBtn.innerHTML : "";
        try {
          const payloadValues = buildSettingsPayload();
          const before = {
            min_deposit_usdt: Number(s.min_deposit_usdt),
            max_deposit_usdt: Number(s.max_deposit_usdt),
            min_withdraw_usdt: Number(s.min_withdraw_usdt),
            max_withdraw_usdt: Number(s.max_withdraw_usdt),
            min_invest_usdt: Number(s.min_invest_usdt),
            max_invest_usdt: Number(s.max_invest_usdt),
            allow_deposits: Boolean(s.allow_deposits),
            allow_investments: Boolean(s.allow_investments),
            allow_withdrawals: Boolean(s.allow_withdrawals !== false),
            support_contact: String(s.support_contact || ""),
          };
          const labels = {
            min_deposit_usdt: "Мин. депозит",
            max_deposit_usdt: "Макс. депозит",
            min_withdraw_usdt: "Мин. вывод",
            max_withdraw_usdt: "Макс. вывод",
            min_invest_usdt: "Мин. инвестиция",
            max_invest_usdt: "Макс. инвестиция",
            allow_deposits: "Пополнения",
            allow_investments: "Участие в сделках",
            allow_withdrawals: "Выводы",
            support_contact: "Саппорт",
          };
          const changedLines = Object.keys(before)
            .filter((k) => String(before[k]) !== String(payloadValues[k]))
            .map((k) => `${labels[k]}: ${before[k]} → ${payloadValues[k]}`);
          if (!changedLines.length) {
            showToast("Изменений нет", "info");
            return;
          }
          const confirmChanges = await openUxDialog({
            title: "Проверка перед сохранением",
            message: changedLines.join("\n"),
            confirmText: "Сохранить",
            cancelText: "Отмена",
          });
          if (!confirmChanges.confirmed) return;

          if (saveBtn) {
            saveBtn.disabled = true;
            saveBtn.innerHTML = '<span class="btn-spinner"></span><span>Сохранение…</span>';
          }

          await apiRequest("/system-settings/bulk", {
            method: "PUT",
            body: JSON.stringify(payloadValues),
          });
          localStorage.removeItem(SETTINGS_DRAFT_KEY);
          if (draftToggle) draftToggle.checked = false;
          showToast("Настройки успешно обновлены");
          loadSettings();
        } catch (e) {
          showToast(e.message || "Ошибка сохранения настроек", "error");
        } finally {
          if (saveBtn) {
            saveBtn.disabled = false;
            saveBtn.innerHTML = originalText;
          }
        }
      };
    }

    const bulkCreditBtn = document.getElementById("bulk-credit-btn");
    if (bulkCreditBtn) {
      bulkCreditBtn.onclick = async () => {
        const amtRaw = document.getElementById("bulk-credit-amount")?.value?.trim();
        const comment = document.getElementById("bulk-credit-comment")?.value?.trim() ?? "";
        const amt = parseFloat((amtRaw || "").replace(",", "."));
        if (!amtRaw || Number.isNaN(amt) || amt <= 0) {
          showToast("Укажите сумму больше 0", "error");
          return;
        }
        const first = await openUxDialog({
          title: "Массовое начисление",
          message: `Всем пользователям будет зачислено ${amt} USDT каждому (ledger DEPOSIT). Продолжить?`,
          confirmText: "Продолжить",
          cancelText: "Отмена",
        });
        if (!first.confirmed) return;
        const phrase = await openUxDialog({
          title: "Подтверждение",
          message: "Введите код подтверждения: BULK_CREDIT",
          confirmText: "Подтвердить",
          cancelText: "Отмена",
          inputPlaceholder: "BULK_CREDIT",
        });
        if (!phrase.confirmed || (phrase.value || "").trim().toUpperCase() !== "BULK_CREDIT") {
          showToast("Операция отменена.", "info");
          return;
        }
        try {
          bulkCreditBtn.disabled = true;
          bulkCreditBtn.textContent = "Обработка…";
          const res = await apiRequest("/users/bulk-ledger-credit", {
            method: "POST",
            body: JSON.stringify({
              amount_usdt: String(amt),
              comment: comment || undefined,
              confirm: "BULK_CREDIT",
            }),
          });
          showToast(
            `Зачислено: ${res.users_affected} польз. × ${res.amount_usdt} USDT (всего ${res.total_usdt_credited} USDT)`
          );
          loadSettings();
          loadDashboard();
        } catch (e) {
          showToast(e.message || "Ошибка", "error");
        } finally {
          bulkCreditBtn.disabled = false;
          bulkCreditBtn.textContent = "Зачислить всем";
        }
      };
    }

    const bulkResetBtn = document.getElementById("bulk-reset-btn");
    if (bulkResetBtn) {
      bulkResetBtn.onclick = async () => {
        const first = await openUxDialog({
          title: "Массовое обнуление баланса",
          message: "Будет удалён только ledger у всех пользователей и баланс станет 0. Остальные данные не затрагиваются. Продолжить?",
          confirmText: "Обнулить всем",
          cancelText: "Отмена",
        });
        if (!first.confirmed) return;
        const phrase = await openUxDialog({
          title: "Подтверждение",
          message: "Введите код подтверждения: RESET_ALL_BALANCES",
          confirmText: "Подтвердить",
          cancelText: "Отмена",
          inputPlaceholder: "RESET_ALL_BALANCES",
        });
        if (!phrase.confirmed || (phrase.value || "").trim().toUpperCase() !== "RESET_ALL_BALANCES") {
          showToast("Операция отменена.", "info");
          return;
        }
        try {
          bulkResetBtn.disabled = true;
          bulkResetBtn.textContent = "Сброс…";
          const res = await apiRequest("/users/bulk-ledger-reset", {
            method: "POST",
            body: JSON.stringify({ confirm: "RESET_ALL_BALANCES" }),
          });
          showToast(
            `Баланс обнулён у ${res.users_affected} пользователей. Удалено записей ledger: ${res.deleted_ledger_rows}`
          );
          loadSettings();
          loadDashboard();
        } catch (e) {
          showToast(e.message || "Ошибка обнуления баланса", "error");
        } finally {
          bulkResetBtn.disabled = false;
          bulkResetBtn.textContent = "Обнулить баланс всем";
        }
      };
    }

    const resetBtn = document.getElementById("db-reset-btn");
    const dryRunBtn = document.getElementById("db-dry-run-btn");
    const backupBtn = document.getElementById("db-backup-btn");
    const clearLogsBtn = document.getElementById("db-clear-logs-btn");
    const clearBroadcastsBtn = document.getElementById("db-clear-broadcasts-btn");
    const clearDealsBtn = document.getElementById("db-clear-deals-btn");
    const clearPaymentsBtn = document.getElementById("db-clear-payments-btn");
    const dzCheckIrrev = document.getElementById("dz-check-irrev");
    const dzCheckEnv = document.getElementById("dz-check-env");
    const dzConfirmInput = document.getElementById("dz-confirm-input");
    const expectedConfirm = String(dangerSummary?.environment || "TEST").trim().toUpperCase();
    const updateDangerState = () => {
      if (!resetBtn) return;
      const okPhrase = ((dzConfirmInput?.value || "").trim().toUpperCase() === expectedConfirm);
      const okChecks = Boolean(dzCheckIrrev?.checked) && Boolean(dzCheckEnv?.checked);
      resetBtn.disabled = !(okPhrase && okChecks);
    };
    [dzCheckIrrev, dzCheckEnv, dzConfirmInput].forEach((el) => {
      el?.addEventListener("change", updateDangerState);
      el?.addEventListener("input", updateDangerState);
    });
    updateDangerState();
    if (dryRunBtn) {
      dryRunBtn.onclick = async () => {
        try {
          dryRunBtn.disabled = true;
          dryRunBtn.textContent = "Расчёт…";
          const res = await apiRequest("/maintenance/reset-data", {
            method: "POST",
            body: JSON.stringify({ confirm: "RESET", keep_settings: true, dry_run: true }),
          });
          const top = (res.items || [])
            .slice(0, 8)
            .map((x) => `${x.title}: ${x.rows}`)
            .join("\n");
          await openUxDialog({
            title: "Dry-run: предпросмотр очистки",
            message: `Будут очищены таблицы: ${(res.tables_cleared || []).length}\nИтого записей: ${res.total_rows}\n\n${top}`,
            confirmText: "ОК",
          });
        } catch (e) {
          showToast(e.message || "Ошибка dry-run", "error");
        } finally {
          dryRunBtn.disabled = false;
          dryRunBtn.textContent = "Предпросмотр очистки";
        }
      };
    }
    if (backupBtn) {
      backupBtn.onclick = async () => {
        try {
          backupBtn.disabled = true;
          backupBtn.textContent = "Экспорт…";
          const resp = await fetch(`${API_BASE}/maintenance/backup`, {
            method: "POST",
            credentials: "include",
          });
          if (!resp.ok) {
            const txt = await resp.text();
            throw new Error(txt || "Ошибка backup");
          }
          const blob = await resp.blob();
          const cd = resp.headers.get("content-disposition") || "";
          const m = cd.match(/filename="([^"]+)"/i);
          const fileName = m?.[1] || `invext_backup_${Date.now()}.json`;
          const url = URL.createObjectURL(blob);
          const a = document.createElement("a");
          a.href = url;
          a.download = fileName;
          document.body.appendChild(a);
          a.click();
          a.remove();
          URL.revokeObjectURL(url);
          showToast("Backup экспортирован", "success");
          loadSettings();
        } catch (e) {
          showToast(e.message || "Ошибка backup", "error");
        } finally {
          backupBtn.disabled = false;
          backupBtn.textContent = "Сделать backup";
        }
      };
    }
    if (clearLogsBtn) {
      clearLogsBtn.onclick = async () => {
        const first = await openUxDialog({
          title: "Очистить только логи",
          message: "Будут удалены только логи админки и лог входов. Финансовые и пользовательские данные не затрагиваются.",
          confirmText: "Продолжить",
          cancelText: "Отмена",
        });
        if (!first.confirmed) return;
        const phrase = await openUxDialog({
          title: "Подтверждение",
          message: "Введите код подтверждения: CLEAR_LOGS",
          confirmText: "Очистить логи",
          cancelText: "Отмена",
          inputPlaceholder: "CLEAR_LOGS",
        });
        if (!phrase.confirmed || (phrase.value || "").trim().toUpperCase() !== "CLEAR_LOGS") {
          showToast("Очистка логов отменена.", "info");
          return;
        }
        try {
          clearLogsBtn.disabled = true;
          clearLogsBtn.textContent = "Очистка…";
          const res = await apiRequest("/maintenance/clear-logs", {
            method: "POST",
            body: JSON.stringify({ confirm: "CLEAR_LOGS" }),
          });
          showToast(`Логи очищены: ${res.total_rows_cleared} записей`, "success");
          if (location.hash === "#logs") loadLogs();
        } catch (e) {
          showToast(e.message || "Ошибка очистки логов", "error");
        } finally {
          clearLogsBtn.disabled = false;
          clearLogsBtn.textContent = "Очистить только логи";
        }
      };
    }
    if (clearBroadcastsBtn) {
      clearBroadcastsBtn.onclick = async () => {
        const first = await openUxDialog({
          title: "Очистить только рассылки",
          message: "Будут удалены истории рассылок и доставки. Пользователи и финансы не затрагиваются.",
          confirmText: "Продолжить",
          cancelText: "Отмена",
        });
        if (!first.confirmed) return;
        const phrase = await openUxDialog({
          title: "Подтверждение",
          message: "Введите код подтверждения: CLEAR_BROADCASTS",
          confirmText: "Очистить рассылки",
          cancelText: "Отмена",
          inputPlaceholder: "CLEAR_BROADCASTS",
        });
        if (!phrase.confirmed || (phrase.value || "").trim().toUpperCase() !== "CLEAR_BROADCASTS") {
          showToast("Очистка рассылок отменена.", "info");
          return;
        }
        try {
          clearBroadcastsBtn.disabled = true;
          clearBroadcastsBtn.textContent = "Очистка…";
          const res = await apiRequest("/maintenance/clear-broadcasts", {
            method: "POST",
            body: JSON.stringify({ confirm: "CLEAR_BROADCASTS" }),
          });
          showToast(`Рассылки очищены: ${res.total_rows_cleared} записей`, "success");
          if (location.hash === "#messages") loadMessages();
        } catch (e) {
          showToast(e.message || "Ошибка очистки рассылок", "error");
        } finally {
          clearBroadcastsBtn.disabled = false;
          clearBroadcastsBtn.textContent = "Очистить только рассылки";
        }
      };
    }
    if (clearDealsBtn) {
      clearDealsBtn.onclick = async () => {
        const first = await openUxDialog({
          title: "Очистить только сделки",
          message: "Будут удалены сделки, участия и реферальные начисления по сделкам. Пользователи, платежи и леджер не затрагиваются.",
          confirmText: "Продолжить",
          cancelText: "Отмена",
        });
        if (!first.confirmed) return;
        const phrase = await openUxDialog({
          title: "Подтверждение",
          message: "Введите код подтверждения: CLEAR_DEALS",
          confirmText: "Очистить сделки",
          cancelText: "Отмена",
          inputPlaceholder: "CLEAR_DEALS",
        });
        if (!phrase.confirmed || (phrase.value || "").trim().toUpperCase() !== "CLEAR_DEALS") {
          showToast("Очистка сделок отменена.", "info");
          return;
        }
        try {
          clearDealsBtn.disabled = true;
          clearDealsBtn.textContent = "Очистка…";
          const res = await apiRequest("/maintenance/clear-deals", {
            method: "POST",
            body: JSON.stringify({ confirm: "CLEAR_DEALS" }),
          });
          showToast(`Сделки очищены: ${res.total_rows_cleared} записей`, "success");
          if (location.hash === "#deals") loadDeals();
          if (location.hash === "#dashboard") loadDashboard();
        } catch (e) {
          showToast(e.message || "Ошибка очистки сделок", "error");
        } finally {
          clearDealsBtn.disabled = false;
          clearDealsBtn.textContent = "Очистить только сделки";
        }
      };
    }
    if (clearPaymentsBtn) {
      clearPaymentsBtn.onclick = async () => {
        const first = await openUxDialog({
          title: "Очистить только платежи",
          message: "Будут удалены платежи и связанные вебхуки. Пользователи, сделки и леджер не затрагиваются.",
          confirmText: "Продолжить",
          cancelText: "Отмена",
        });
        if (!first.confirmed) return;
        const phrase = await openUxDialog({
          title: "Подтверждение",
          message: "Введите код подтверждения: CLEAR_PAYMENTS",
          confirmText: "Очистить платежи",
          cancelText: "Отмена",
          inputPlaceholder: "CLEAR_PAYMENTS",
        });
        if (!phrase.confirmed || (phrase.value || "").trim().toUpperCase() !== "CLEAR_PAYMENTS") {
          showToast("Очистка платежей отменена.", "info");
          return;
        }
        try {
          clearPaymentsBtn.disabled = true;
          clearPaymentsBtn.textContent = "Очистка…";
          const res = await apiRequest("/maintenance/clear-payments", {
            method: "POST",
            body: JSON.stringify({ confirm: "CLEAR_PAYMENTS" }),
          });
          showToast(`Платежи очищены: ${res.total_rows_cleared} записей`, "success");
          if (location.hash === "#deposits") loadDeposits();
          if (location.hash === "#dashboard") loadDashboard();
        } catch (e) {
          showToast(e.message || "Ошибка очистки платежей", "error");
        } finally {
          clearPaymentsBtn.disabled = false;
          clearPaymentsBtn.textContent = "Очистить только платежи";
        }
      };
    }
    if (resetBtn) {
      resetBtn.onclick = async () => {
        const firstConfirm = await openUxDialog({
          title: "Финальное подтверждение удаления",
          message: `Будут удалены тестовые данные. Среда: ${expectedConfirm}. Это действие безвозвратно.`,
          confirmText: "Безвозвратно удалить данные",
          cancelText: "Отмена",
        });
        if (!firstConfirm.confirmed) return;

        const phrase = await openUxDialog({
          title: "Подтверждение",
          message: "Для подтверждения введите слово RESET",
          confirmText: "Подтвердить",
          cancelText: "Отмена",
          inputPlaceholder: "RESET",
        });
        if (!phrase.confirmed || (phrase.value || "").trim().toUpperCase() !== "RESET") {
          showToast("Очистка отменена: подтверждение не пройдено.", "info");
          return;
        }

        try {
          resetBtn.disabled = true;
          resetBtn.innerHTML = '<span class="btn-spinner"></span><span>Очистка…</span>';
          await apiRequest("/maintenance/reset-data", {
            method: "POST",
            body: JSON.stringify({ confirm: "RESET", keep_settings: true }),
          });
          showToast("База очищена. Тестовые данные удалены.");
          loadDashboard();
          if (location.hash === "#users") loadUsers();
          if (location.hash === "#deals") loadDeals();
          if (location.hash === "#deposits") loadDeposits();
          if (location.hash === "#withdrawals") loadWithdrawals();
          if (location.hash === "#logs") loadLogs();
        } catch (e) {
          showToast(e.message || "Ошибка очистки базы", "error");
        } finally {
          updateDangerState();
          resetBtn.innerHTML = '<span class="btn-label">Безвозвратно удалить данные</span>';
        }
      };
    }
  } catch (e) {
    section.innerHTML = `<h1>Настройки</h1><div class="error">${e.message}</div>`;
  }
}

function showToast(message, type = "success", action = null) {
  const existing = document.querySelector(".toast");
  if (existing) {
    existing.remove();
  }
  const icon = type === "error" ? "⚠️" : type === "info" ? "ℹ️" : "✅";
  const el = document.createElement("div");
  el.className = "toast";
  el.innerHTML = `
    <span class="toast-icon">${icon}</span>
    <span class="toast-message">${message}</span>
    ${action?.label ? `<button type="button" class="toast-action-btn">${escapeHtmlAttr(action.label)}</button>` : ""}
  `;
  document.body.appendChild(el);
  if (action?.label && typeof action.onClick === "function") {
    el.querySelector(".toast-action-btn")?.addEventListener("click", () => {
      action.onClick();
      el.remove();
    });
  }
  setTimeout(() => {
    el.classList.add("toast-hide");
    el.style.opacity = "0";
    setTimeout(() => el.remove(), 300);
  }, 2500);
}

function ensureUxDialogStyles() {
  if (document.getElementById("ux-dialog-styles")) return;
  const style = document.createElement("style");
  style.id = "ux-dialog-styles";
  style.textContent = `
    .ux-dialog-backdrop { position: fixed; inset: 0; background: rgba(0,0,0,.5); display:flex; align-items:center; justify-content:center; z-index: 9999; }
    .ux-dialog { width: min(92vw, 460px); background: #12131a; color: #eaeaf2; border: 1px solid #2a2d3a; border-radius: 14px; box-shadow: 0 14px 50px rgba(0,0,0,.45); padding: 18px; }
    .ux-dialog-title { margin: 0 0 8px 0; font-size: 18px; font-weight: 700; }
    .ux-dialog-message { margin: 0 0 14px 0; white-space: pre-wrap; line-height: 1.4; color: #d4d7e5; }
    .ux-dialog-input { width: 100%; box-sizing: border-box; margin-bottom: 14px; border:1px solid #3a3f52; background:#0f1118; color:#f0f2ff; border-radius:10px; padding:10px 12px; }
    .ux-dialog-actions { display:flex; justify-content:flex-end; gap:10px; }
    .ux-btn { border: 1px solid #3a3f52; background: #1a1e2b; color: #f0f2ff; border-radius: 10px; padding: 9px 14px; cursor: pointer; }
    .ux-btn-primary { background: #8a4b18; border-color: #a35b1f; }
  `;
  document.head.appendChild(style);
}

function openUxDialog({ title, message, confirmText = "OK", cancelText = null, inputPlaceholder = "" }) {
  ensureUxDialogStyles();
  return new Promise((resolve) => {
    const backdrop = document.createElement("div");
    backdrop.className = "ux-dialog-backdrop";

    const dialog = document.createElement("div");
    dialog.className = "ux-dialog";
    dialog.innerHTML = `
      <h3 class="ux-dialog-title"></h3>
      <p class="ux-dialog-message"></p>
      ${inputPlaceholder ? '<input class="ux-dialog-input" type="text" />' : ""}
      <div class="ux-dialog-actions"></div>
    `;

    const titleEl = dialog.querySelector(".ux-dialog-title");
    const msgEl = dialog.querySelector(".ux-dialog-message");
    titleEl.textContent = title || "Подтверждение";
    msgEl.textContent = message || "";

    const actions = dialog.querySelector(".ux-dialog-actions");
    const input = dialog.querySelector(".ux-dialog-input");
    if (input) input.placeholder = inputPlaceholder;

    const close = (confirmed) => {
      const value = input ? input.value : "";
      backdrop.remove();
      resolve({ confirmed, value });
    };

    if (cancelText) {
      const cancelBtn = document.createElement("button");
      cancelBtn.className = "ux-btn";
      cancelBtn.type = "button";
      cancelBtn.textContent = cancelText;
      cancelBtn.onclick = () => close(false);
      actions.appendChild(cancelBtn);
    }

    const okBtn = document.createElement("button");
    okBtn.className = "ux-btn ux-btn-primary";
    okBtn.type = "button";
    okBtn.textContent = confirmText;
    okBtn.onclick = () => close(true);
    actions.appendChild(okBtn);

    backdrop.addEventListener("click", (e) => {
      if (e.target === backdrop && cancelText) close(false);
    });
    dialog.addEventListener("keydown", (e) => {
      if (e.key === "Enter") close(true);
      if (e.key === "Escape" && cancelText) close(false);
    });

    backdrop.appendChild(dialog);
    document.body.appendChild(backdrop);
    if (input) input.focus();
    else okBtn.focus();
  });
}

async function loadLogs() {
  const section = document.getElementById("logs-section");
  section.innerHTML = "<h1>Логи</h1><p>Загрузка...</p>";
  try {
    const [data, loginEvents, twoFa] = await Promise.all([
      apiRequest("/logs?page=1&page_size=100"),
      apiRequest("/security/login-events?page=1&page_size=20").catch(() => ({ items: [] })),
      apiRequest("/security/2fa/status").catch(() => ({ enabled: false })),
    ]);
    const items = data.items || [];
    const actionOptions = [...new Set(items.map((x) => x.action_type).filter(Boolean))].sort();
    const entityOptions = [...new Set(items.map((x) => x.entity_type).filter(Boolean))].sort();

    const renderLogsTable = () => {
      const q = (document.getElementById("logs-search")?.value || "").trim().toLowerCase();
      const action = document.getElementById("logs-action-filter")?.value || "";
      const entity = document.getElementById("logs-entity-filter")?.value || "";
      const range = document.getElementById("logs-range-filter")?.value || "all";
      const now = Date.now();
      const maxAgeMs =
        range === "1d" ? 24 * 60 * 60 * 1000 :
        range === "7d" ? 7 * 24 * 60 * 60 * 1000 :
        range === "30d" ? 30 * 24 * 60 * 60 * 1000 : null;

      const filtered = items.filter((l) => {
        if (action && l.action_type !== action) return false;
        if (entity && l.entity_type !== entity) return false;
        if (maxAgeMs != null) {
          const ts = new Date(l.created_at).getTime();
          if (!Number.isFinite(ts) || now - ts > maxAgeMs) return false;
        }
        if (!q) return true;
        const hay = `${l.id} ${l.action_type} ${l.entity_type} ${l.entity_id}`.toLowerCase();
        return hay.includes(q);
      });

      const rows = filtered
        .map(
          (l) => `
        <tr>
          <td>${l.id}</td>
          <td>${l.action_type}</td>
          <td>${l.entity_type}</td>
          <td>${l.entity_id}</td>
          <td>${new Date(l.created_at).toLocaleString()}</td>
        </tr>`
        )
        .join("");
      const rowsHtml = rows || `<tr><td colspan="5"><div class="empty-state"><strong>Совпадений не найдено</strong><span>Измени фильтры или поисковый запрос.</span></div></td></tr>`;
      const summaryEl = document.getElementById("logs-summary");
      if (summaryEl) {
        summaryEl.textContent = `Показано: ${filtered.length} из ${items.length}`;
      }
      const tbody = document.getElementById("logs-tbody");
      if (tbody) tbody.innerHTML = rowsHtml;
    };

    section.innerHTML = `
      <h1>Логи</h1>
      <p class="section-desc">Действия админов в системе.</p>
      <div class="panel-card">
        <h2>Безопасность: 2FA</h2>
        <div class="toolbar">
          <span class="pagination-info">Текущий статус: <strong>${twoFa.enabled ? "Включено" : "Выключено"}</strong></span>
          <button type="button" id="2fa-setup-btn" class="btn-secondary-small">Сгенерировать секрет</button>
          <button type="button" id="2fa-enable-btn" class="btn-secondary-small">Включить 2FA</button>
          <button type="button" id="2fa-disable-btn" class="btn-secondary-small">Выключить 2FA</button>
        </div>
      </div>
      <div class="panel-card">
        <h2>Лог входов</h2>
        <div class="table-wrapper">
          <div class="table-wrapper-inner">
            <table>
              <thead>
                <tr>
                  <th>ID</th>
                  <th>Статус</th>
                  <th>IP</th>
                  <th>User-Agent</th>
                  <th>Причина</th>
                  <th>Дата</th>
                </tr>
              </thead>
              <tbody>
                ${(loginEvents.items || []).map((e) => `
                  <tr>
                    <td>${e.id}</td>
                    <td><span class="status-badge ${e.success ? "status-paid" : "status-expired"}">${e.success ? "SUCCESS" : "FAILED"}</span></td>
                    <td>${escapeHtmlAttr(e.ip_address || "—")}</td>
                    <td class="cell-address">${escapeHtmlAttr(e.user_agent || "—")}</td>
                    <td>${escapeHtmlAttr(e.reason || "—")}</td>
                    <td>${e.created_at ? new Date(e.created_at).toLocaleString() : "—"}</td>
                  </tr>
                `).join("") || `<tr><td colspan="6"><div class="empty-state"><strong>Событий входа пока нет</strong><span>Лог появится после попыток входа в админку.</span></div></td></tr>`}
              </tbody>
            </table>
          </div>
        </div>
      </div>
      <div class="panel-card">
        <div class="toolbar filters-toolbar">
          <label class="filter-label">
            Поиск
            <input id="logs-search" type="text" placeholder="ID / action / entity" />
          </label>
          <label class="filter-label">
            Action
            <select id="logs-action-filter">
              <option value="">Все</option>
              ${actionOptions.map((x) => `<option value="${escapeHtmlAttr(x)}">${escapeHtmlAttr(x)}</option>`).join("")}
            </select>
          </label>
          <label class="filter-label">
            Entity
            <select id="logs-entity-filter">
              <option value="">Все</option>
              ${entityOptions.map((x) => `<option value="${escapeHtmlAttr(x)}">${escapeHtmlAttr(x)}</option>`).join("")}
            </select>
          </label>
          <label class="filter-label">
            Период
            <select id="logs-range-filter">
              <option value="all">Все время</option>
              <option value="1d">24 часа</option>
              <option value="7d">7 дней</option>
              <option value="30d">30 дней</option>
            </select>
          </label>
          <button type="button" id="logs-reset-btn" class="btn-secondary-small">Сбросить</button>
          <span id="logs-summary" class="pagination-info"></span>
        </div>
        <div class="table-wrapper">
          <div class="table-wrapper-inner">
            <table>
              <thead>
                <tr>
                  <th>ID</th>
                  <th>Действие</th>
                  <th>Тип сущности</th>
                  <th>Entity ID</th>
                  <th>Дата</th>
                </tr>
              </thead>
              <tbody id="logs-tbody"></tbody>
            </table>
          </div>
        </div>
      </div>
    `;
    ["logs-search", "logs-action-filter", "logs-entity-filter", "logs-range-filter"].forEach((id) => {
      document.getElementById(id)?.addEventListener("input", renderLogsTable);
      document.getElementById(id)?.addEventListener("change", renderLogsTable);
    });
    document.getElementById("logs-reset-btn")?.addEventListener("click", () => {
      const set = (id, val = "") => {
        const el = document.getElementById(id);
        if (el) el.value = val;
      };
      set("logs-search", "");
      set("logs-action-filter", "");
      set("logs-entity-filter", "");
      set("logs-range-filter", "all");
      renderLogsTable();
    });
    document.getElementById("2fa-setup-btn")?.addEventListener("click", async () => {
      try {
        const data = await apiRequest("/security/2fa/setup", { method: "POST" });
        await openUxDialog({
          title: "2FA секрет сгенерирован",
          message: `Секрет: ${data.secret}\n\nДобавьте в Google Authenticator/1Password.\n\nURI:\n${data.otpauth_url}`,
          confirmText: "Закрыть",
        });
        loadLogs();
      } catch (e) {
        showToast(e.message || "Ошибка генерации 2FA", "error");
      }
    });
    document.getElementById("2fa-enable-btn")?.addEventListener("click", async () => {
      const r = await openUxDialog({
        title: "Включить 2FA",
        message: "Введите текущий OTP-код из приложения",
        inputPlaceholder: "123456",
        confirmText: "Включить",
        cancelText: "Отмена",
      });
      if (!r.confirmed) return;
      try {
        await apiRequest("/security/2fa/enable", {
          method: "POST",
          body: JSON.stringify({ otp_code: r.value || "" }),
        });
        showToast("2FA включена", "success");
        loadLogs();
      } catch (e) {
        showToast(e.message || "Ошибка включения 2FA", "error");
      }
    });
    document.getElementById("2fa-disable-btn")?.addEventListener("click", async () => {
      const r = await openUxDialog({
        title: "Выключить 2FA",
        message: "Введите текущий OTP-код для подтверждения",
        inputPlaceholder: "123456",
        confirmText: "Выключить",
        cancelText: "Отмена",
      });
      if (!r.confirmed) return;
      try {
        await apiRequest("/security/2fa/disable", {
          method: "POST",
          body: JSON.stringify({ otp_code: r.value || "" }),
        });
        showToast("2FA выключена", "success");
        loadLogs();
      } catch (e) {
        showToast(e.message || "Ошибка выключения 2FA", "error");
      }
    });
    renderLogsTable();
  } catch (e) {
    section.innerHTML = `<h1>Логи</h1><div class="error">${e.message}</div>`;
  }
}

window.addEventListener("hashchange", () => {
  switchSection(location.hash);
});

document.addEventListener("DOMContentLoaded", () => {
  ensureMessagesNavAndSection();
  initGlobalSearch();
  try {
    const savedUsers = JSON.parse(localStorage.getItem(USERS_FILTERS_KEY) || "{}");
    usersListState = {
      ...usersListState,
      pageSize: Number(savedUsers.pageSize) || usersListState.pageSize,
      search: typeof savedUsers.search === "string" ? savedUsers.search : usersListState.search,
      activityFilter: typeof savedUsers.activityFilter === "string" ? savedUsers.activityFilter : usersListState.activityFilter,
    };
  } catch (_) {}
  document
    .getElementById("login-form")
    .addEventListener("submit", handleLogin);

  // Пытаемся сразу загрузить дашборд (если уже есть cookie).
  loadDashboard()
    .then(() => {
      showMainView();
      switchSection(location.hash || "#dashboard");
    })
    .catch(() => {
    showLoginView();
  });
});

