const API_BASE = "/database/api";

/** Состояние списка пользователей (пагинация + поиск). */
let usersListState = { page: 1, pageSize: 25, search: "" };

function escapeHtmlAttr(s) {
  if (s == null || s === "") return "";
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/"/g, "&quot;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

async function apiRequest(path, options = {}) {
  const resp = await fetch(API_BASE + path, {
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
    },
    ...options,
  });
  if (resp.status === 401) {
    // Сессия истекла — показываем логин.
    showLoginView();
    throw new Error("Unauthorized");
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

async function handleLogin(event) {
  event.preventDefault();
  const token = document.getElementById("token").value.trim();
  const errorEl = document.getElementById("login-error");
  errorEl.textContent = "";
  try {
    const resp = await fetch(API_BASE + "/login", {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token }),
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
    const data = await apiRequest("/dashboard");
    const activeDealText = data.active_deal_number
      ? `#${data.active_deal_number} · ${data.active_deal_percent}% · инвестировано ${data.active_deal_invested_usdt} USDT`
      : "Нет активной сделки";
    const activeDealCloseText = data.active_deal_closes_at
      ? new Date(data.active_deal_closes_at).toLocaleString()
      : "—";

    section.innerHTML = `
      <h1>Дашборд</h1>
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
            <li>Активная сделка: <strong>${data.active_deal_number ? "да" : "нет"}</strong></li>
            <li>Закрытие текущей сделки: <strong>${activeDealCloseText}</strong></li>
            <li>Ожидают вывода: <strong>${data.pending_withdrawals_count}</strong></li>
          </ul>
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
  } catch (e) {
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
        <label class="page-size-label">На странице
          <select id="users-page-size" class="page-size-select">
            <option value="25">25</option>
            <option value="50">50</option>
            <option value="100">100</option>
          </select>
        </label>
      </div>
      <p>Загрузка...</p>
    </div>
  `;

  const sizeSel = document.getElementById("users-page-size");
  if (sizeSel) sizeSel.value = String(usersListState.pageSize);

  try {
    const q = usersListState.search
      ? `&search=${encodeURIComponent(usersListState.search)}`
      : "";
    const data = await apiRequest(
      `/users?page=${usersListState.page}&page_size=${usersListState.pageSize}${q}`
    );
    const totalPages = Math.max(1, Math.ceil(data.total / data.page_size) || 1);
    if (usersListState.page > totalPages) {
      usersListState.page = totalPages;
      return loadUsers();
    }

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
          <td>${u.balance_usdt}</td>
          <td>${u.ledger_balance_usdt}${mismatch}</td>
          <td>${u.invested_now_usdt}</td>
        </tr>`;
      })
      .join("");

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
                  <th>balance_usdt</th>
                  <th>ledger_balance</th>
                  <th>invested_now</th>
                </tr>
              </thead>
              <tbody>${rows}</tbody>
            </table>
          </div>
        </div>
        ${paginationHtml}
      </div>
    `;

    const sizeSelect = document.getElementById("users-page-size");
    if (sizeSelect) {
      sizeSelect.value = String(usersListState.pageSize);
      sizeSelect.onchange = () => {
        usersListState.pageSize = parseInt(sizeSelect.value, 10) || 25;
        usersListState.page = 1;
        loadUsers();
      };
    }

    document.getElementById("users-search-btn").onclick = () => {
      const v = document.getElementById("users-search")?.value?.trim() ?? "";
      usersListState.search = v;
      usersListState.page = 1;
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
  } catch (e) {
    section.innerHTML = `<h1>Пользователи</h1><div class="error">${e.message}</div>`;
  }
}

function switchSection(hash) {
  const sections = ["dashboard", "users", "deals", "deposits", "withdrawals", "logs", "settings", "user"];
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
  section.innerHTML = "<h1>Сделки</h1><p>Загрузка...</p>";
  try {
    const [deals, statusRes] = await Promise.all([
      apiRequest("/deals"),
      apiRequest("/deals/status").catch(() => ({ active_deal: null })),
    ]);
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
            <div class="deal-status-row"><span class="deal-status-label">Уведомление о закрытии отправлено:</span> ${activeDeal.close_notification_sent ? "Да" : "Нет"}</div>
          </div>
          <div class="toolbar deal-status-toolbar">
            <button type="button" id="deal-send-notifications-btn">Отправить уведомления о сделке</button>
            <button type="button" id="deal-force-close-btn">Закрыть сделку досрочно</button>
          </div>
        </div>`;

    const rows = deals
      .map(
        (d) => `
      <tr data-deal-id="${d.id}">
        <td>${d.number}</td>
        <td>${d.status}</td>
        <td>
          <input type="number" step="0.01" min="0" value="${d.profit_percent ?? d.percent ?? 0}" class="deal-percent-input" />
        </td>
        <td>${d.opened_at ? new Date(d.opened_at).toLocaleString() : ""}</td>
        <td>${d.closed_at ? new Date(d.closed_at).toLocaleString() : ""}</td>
        <td>${d.finished_at ? new Date(d.finished_at).toLocaleString() : ""}</td>
        <td>
          <div class="row-actions">
            <button class="deal-save-btn">Сохранить %</button>
          </div>
        </td>
      </tr>`
      )
      .join("");

    section.innerHTML = `
      <h1>Сделки</h1>
      <p class="section-desc">Текущие и завершённые сделки, управление доходностью.</p>
      ${statusBlock}
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
                  <th>% дохода</th>
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
        if (!dealId || !input) return;
        const value = parseFloat(input.value.replace(",", "."));
        if (Number.isNaN(value)) {
          showToast("Введите корректное значение процента", "error");
          return;
        }
        try {
          await apiRequest(`/deals/${dealId}`, {
            method: "PATCH",
            body: JSON.stringify({ profit_percent: value }),
          });
          showToast("Доходность сделки обновлена", "success");
          loadDeals();
        } catch (e) {
          showToast(e.message || "Ошибка обновления доходности", "error");
        }
      };
    });
  } catch (e) {
    section.innerHTML = `<h1>Сделки</h1><div class="error">${e.message}</div>`;
  }
}

function buildDepositsQuery(page = 1) {
  const statusEl = document.getElementById("deposits-status-filter");
  const dateFromEl = document.getElementById("deposits-date-from");
  const dateToEl = document.getElementById("deposits-date-to");
  const sortEl = document.getElementById("deposits-sort");
  const orderIdEl = document.getElementById("deposits-order-id");
  const externalIdEl = document.getElementById("deposits-external-id");
  const userIdEl = document.getElementById("deposits-user-id");
  const params = new URLSearchParams();
  params.set("page", String(page));
  params.set("page_size", "25");
  if (statusEl && statusEl.value) params.set("status_filter", statusEl.value);
  if (dateFromEl && dateFromEl.value) params.set("date_from", dateFromEl.value);
  if (dateToEl && dateToEl.value) params.set("date_to", dateToEl.value);
  if (orderIdEl && orderIdEl.value.trim()) params.set("order_id_search", orderIdEl.value.trim());
  if (externalIdEl && externalIdEl.value.trim()) params.set("external_id_search", externalIdEl.value.trim());
  if (userIdEl && userIdEl.value.trim()) params.set("user_id_filter", userIdEl.value.trim());
  params.set("sort", sortEl ? sortEl.value : "created_at_desc");
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
    const q = buildDepositsQuery(page);
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
      </tr>`
      )
      .join("");

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
          <button type="button" id="deposits-apply-filters">Применить</button>
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
                </tr>
              </thead>
              <tbody>${rows}</tbody>
            </table>
          </div>
        </div>
        ${paginationHtml}
      </div>
    `;

    document.getElementById("deposits-apply-filters").addEventListener("click", () => loadDeposits(1));
    section.querySelectorAll("button.pagination-btn").forEach((btn) => {
      btn.addEventListener("click", () => loadDeposits(parseInt(btn.getAttribute("data-page"), 10)));
    });
    section.querySelectorAll("tr.deposit-row").forEach((row) => {
      row.addEventListener("click", () => {
        const id = row.getAttribute("data-deposit-id");
        if (id) openDepositDetail(id);
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
        <dt>Статус</dt>
        <dd><span class="${statusBadgeClass(d.status)}">${statusLabel(d.status)}</span></dd>
        <dt>Баланс начислен</dt>
        <dd>${d.balance_credited ? '<span class="credited-yes">Да</span>' : '<span class="credited-no">Нет</span>'}</dd>
        <dt>Создан</dt>
        <dd>${d.created_at ? new Date(d.created_at).toLocaleString() : "—"}</dd>
        <dt>Завершён</dt>
        <dd>${d.completed_at ? new Date(d.completed_at).toLocaleString() : (d.paid_at ? new Date(d.paid_at).toLocaleString() : "—")}</dd>
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
    const invRows = detail.investments
      .map(
        (i) => `
        <tr>
          <td>${i.deal_number}</td>
          <td>${i.deal_status}</td>
          <td>${i.amount}</td>
          <td>${i.profit_amount || ""}</td>
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
          <td>${w.address}</td>
          <td>${w.status}</td>
          <td>${new Date(w.created_at).toLocaleString()}</td>
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
            <div>balance_usdt: <strong id="user-balance-usdt">${u.balance_usdt}</strong></div>
            <div>ledger_balance: <strong id="user-ledger-balance">${u.ledger_balance_usdt}</strong> ${mismatch}</div>
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
            </div>
            <button id="ledger-export-btn">Экспорт CSV</button>
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
        <h2>Инвестиции</h2>
        <div class="table-wrapper">
          <div class="table-wrapper-inner">
            <table>
              <thead>
                <tr>
                  <th>Сделка</th>
                  <th>Статус</th>
                  <th>Сумма</th>
                  <th>Профит</th>
                  <th>Создано</th>
                </tr>
              </thead>
              <tbody>${invRows}</tbody>
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
      </div>
    `;

    const exportBtn = document.getElementById("ledger-export-btn");
    if (exportBtn) {
      exportBtn.onclick = () => {
        window.location.href = `${API_BASE}/ledger/${userId}/export`;
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

async function loadWithdrawals() {
  const section = document.getElementById("withdrawals-section");
  section.innerHTML = "<h1>Выводы</h1><p>Загрузка...</p>";
  try {
    const statusParam = document.getElementById("withdrawals-status-filter")?.value || "PENDING";
    const data = await apiRequest(`/withdrawals?status=${statusParam}`);
    const rows = data.items
      .map(
        (w) => `
      <tr>
        <td>${w.id}</td>
        <td>${w.telegram_id}</td>
        <td>${w.username || ""}</td>
        <td class="amount-negative">−${w.amount} ${w.currency}</td>
        <td class="cell-address">${w.address}</td>
        <td><span class="${withdrawalStatusBadge(w.status)}">${w.status}</span></td>
        <td>
          ${w.status === "PENDING" ? `<button data-id="${w.id}" data-action="approve" class="btn-approve">Подтвердить</button> <button data-id="${w.id}" data-action="reject" class="btn-reject">Отклонить</button>` : "—"}
        </td>
      </tr>`
      )
      .join("");
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
          <button type="button" id="withdrawals-apply-filters">Применить</button>
        </div>
        <div class="table-wrapper">
          <div class="table-wrapper-inner">
            <table>
              <thead>
                <tr>
                  <th>ID</th>
                  <th>Telegram ID</th>
                  <th>Username</th>
                  <th>Сумма</th>
                  <th>Кошелек</th>
                  <th>Статус</th>
                  <th>Действия</th>
                </tr>
              </thead>
              <tbody>${rows}</tbody>
            </table>
          </div>
        </div>
      </div>
    `;

    document.getElementById("withdrawals-apply-filters")?.addEventListener("click", () => loadWithdrawals());
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
  section.innerHTML = "<h1>Настройки</h1><p>Загрузка...</p>";
  try {
    const s = await apiRequest("/system-settings");
    section.innerHTML = `
      <h1>Финансовые настройки</h1>
      <p class="section-desc">Глобальные лимиты депозитов, выводов и инвестиций. Мин. и макс. могут быть <b>одинаковыми</b> (например 50 и 50 — фиксированная сумма).</p>
      <div class="settings-card">
        <div class="settings-header">
          <h2>Лимиты операций</h2>
          <p>Изменения применяются глобально для всех пользователей и бота.</p>
        </div>
        <form id="settings-form" class="settings-form">
          <div class="settings-grid">
            <div class="settings-field">
              <div>
                <div class="settings-label">Мин. депозит (USDT)</div>
                <div class="settings-hint">Минимальная сумма пополнения</div>
              </div>
              <input type="number" step="0.01" min="0" id="min_deposit_usdt" class="settings-input" value="${s.min_deposit_usdt}" />
            </div>
            <div class="settings-field">
              <div>
                <div class="settings-label">Макс. депозит (USDT)</div>
                <div class="settings-hint">Максимальная сумма пополнения</div>
              </div>
              <input type="number" step="0.01" min="0" id="max_deposit_usdt" class="settings-input" value="${s.max_deposit_usdt}" />
            </div>
            <div class="settings-field">
              <div>
                <div class="settings-label">Мин. вывод (USDT)</div>
                <div class="settings-hint">Минимальная сумма вывода</div>
              </div>
              <input type="number" step="0.01" min="0" id="min_withdraw_usdt" class="settings-input" value="${s.min_withdraw_usdt}" />
            </div>
            <div class="settings-field">
              <div>
                <div class="settings-label">Макс. вывод (USDT)</div>
                <div class="settings-hint">Максимальная сумма вывода</div>
              </div>
              <input type="number" step="0.01" min="0" id="max_withdraw_usdt" class="settings-input" value="${s.max_withdraw_usdt}" />
            </div>
            <div class="settings-field">
              <div>
                <div class="settings-label">Мин. инвестиция (USDT)</div>
                <div class="settings-hint">Минимальная сумма участия</div>
              </div>
              <input type="number" step="0.01" min="0" id="min_invest_usdt" class="settings-input" value="${s.min_invest_usdt}" />
            </div>
            <div class="settings-field">
              <div>
                <div class="settings-label">Макс. инвестиция (USDT)</div>
                <div class="settings-hint">Максимальная сумма участия</div>
              </div>
              <input type="number" step="0.01" min="0" id="max_invest_usdt" class="settings-input" value="${s.max_invest_usdt}" />
            </div>
            <div class="settings-field">
              <div>
                <div class="settings-label">Пополнения</div>
                <div class="settings-hint">Разрешить создание новых инвойсов пополнения</div>
              </div>
              <label class="switch">
                <input type="checkbox" id="allow_deposits" ${s.allow_deposits ? "checked" : ""} />
                <span class="switch-slider"></span>
              </label>
            </div>
            <div class="settings-field">
              <div>
                <div class="settings-label">Участие в сделках</div>
                <div class="settings-hint">Технический запрет/разрешение новых инвестиций</div>
              </div>
              <label class="switch">
                <input type="checkbox" id="allow_investments" ${s.allow_investments !== false ? "checked" : ""} />
                <span class="switch-slider"></span>
              </label>
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
            <p class="section-desc">Необратимые действия с тестовой БД перед запуском в прод.</p>
          </div>
        </div>
        <div class="danger-zone-note">
          Будут удалены: пользователи, сделки, платежи, выводы, леджер, логи.
          <br />Структура БД и финансовые настройки сохраняются.
        </div>
        <div class="toolbar danger-zone-toolbar">
          <button type="button" id="db-reset-btn" class="btn-danger-wide">
            <span class="btn-label">Очистить базу данных</span>
          </button>
        </div>
      </div>
    `;

    const form = document.getElementById("settings-form");
    if (form) {
      form.onsubmit = async (e) => {
        e.preventDefault();
        const fields = [
          "min_deposit_usdt",
          "max_deposit_usdt",
          "min_withdraw_usdt",
          "max_withdraw_usdt",
          "min_invest_usdt",
          "max_invest_usdt",
        ];
        const saveBtn = document.getElementById("settings-save-btn");
        const originalText = saveBtn ? saveBtn.innerHTML : "";
        try {
          // Frontend-валидация: числа, > 0, min <= max (равенство разрешено).
          const values = {};
          for (const field of fields) {
            const input = document.getElementById(field);
            if (!input) continue;
            const raw = input.value.trim().replace(",", ".");
            const num = parseFloat(raw);
            if (Number.isNaN(num) || num <= 0) {
              showToast(`Поле "${field}" должно быть числом больше 0`, "error");
              return;
            }
            values[field] = num;
          }

          if (values.min_deposit_usdt > values.max_deposit_usdt) {
            showToast("Мин. депозит не может быть больше макс. депозита", "error");
            return;
          }
          if (values.min_withdraw_usdt > values.max_withdraw_usdt) {
            showToast("Мин. вывод не может быть больше макс. вывода", "error");
            return;
          }
          if (values.min_invest_usdt > values.max_invest_usdt) {
            showToast("Мин. инвестиция не может быть больше макс. инвестиции", "error");
            return;
          }

          if (saveBtn) {
            saveBtn.disabled = true;
            saveBtn.innerHTML = '<span class="btn-spinner"></span><span>Сохранение…</span>';
          }

          for (const field of fields) {
            await apiRequest("/system-settings", {
              method: "PATCH",
              body: JSON.stringify({ field, value: String(values[field]) }),
            });
          }
          const allowDepositsInput = document.getElementById("allow_deposits");
          await apiRequest("/system-settings", {
            method: "PATCH",
            body: JSON.stringify({
              field: "allow_deposits",
              value: Boolean(allowDepositsInput?.checked),
            }),
          });
          const allowInvestmentsInput = document.getElementById("allow_investments");
          await apiRequest("/system-settings", {
            method: "PATCH",
            body: JSON.stringify({
              field: "allow_investments",
              value: Boolean(allowInvestmentsInput?.checked),
            }),
          });
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
    if (resetBtn) {
      resetBtn.onclick = async () => {
        const firstConfirm = await openUxDialog({
          title: "Очистка базы",
          message: "Это удалит ВСЕ тестовые данные (пользователи, сделки, платежи, леджер, выводы). Продолжить?",
          confirmText: "Очистить",
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
          resetBtn.disabled = false;
          resetBtn.innerHTML = '<span class="btn-label">Очистить базу данных</span>';
        }
      };
    }
  } catch (e) {
    section.innerHTML = `<h1>Настройки</h1><div class="error">${e.message}</div>`;
  }
}

function showToast(message, type = "success") {
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
  `;
  document.body.appendChild(el);
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
    const data = await apiRequest("/logs?page=1&page_size=100");
    const rows = data.items
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
    section.innerHTML = `
      <h1>Логи</h1>
      <p class="section-desc">Действия админов в системе.</p>
      <div class="panel-card">
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
              <tbody>${rows}</tbody>
            </table>
          </div>
        </div>
      </div>
    `;
  } catch (e) {
    section.innerHTML = `<h1>Логи</h1><div class="error">${e.message}</div>`;
  }
}

window.addEventListener("hashchange", () => {
  switchSection(location.hash);
});

document.addEventListener("DOMContentLoaded", () => {
  document
    .getElementById("login-form")
    .addEventListener("submit", handleLogin);

  // Пытаемся сразу загрузить дашборд (если уже есть cookie).
  showMainView();
  loadDashboard().catch(() => {
    showLoginView();
  });

  switchSection(location.hash || "#dashboard");
});

