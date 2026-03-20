const API_BASE = "/database/api";

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
  section.innerHTML = `
    <h1>Пользователи</h1>
    <p class="section-desc">Список пользователей, кеш баланса и текущие инвестиции.</p>
    <div class="panel-card">
      <div class="toolbar">
        <div class="search-field">
          <span class="search-field-icon">🔍</span>
          <input id="users-search" type="text" placeholder="Поиск по username / Telegram ID" />
        </div>
        <button id="users-search-btn">Искать</button>
      </div>
      <p>Загрузка...</p>
    </div>
  `;
  try {
    const searchInput = document.getElementById("users-search");
    const q = searchInput && searchInput.value ? `&search=${encodeURIComponent(searchInput.value)}` : "";
    const data = await apiRequest(`/users?page=1&page_size=50${q}`);
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
    section.innerHTML = `
      <h1>Пользователи</h1>
      <p class="section-desc">Список пользователей, кеш баланса и текущие инвестиции.</p>
      <div class="panel-card">
        <div class="toolbar">
          <div class="search-field">
            <span class="search-field-icon">🔍</span>
            <input id="users-search" type="text" placeholder="Поиск по username / Telegram ID" />
          </div>
          <button id="users-search-btn">Искать</button>
        </div>
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
      </div>
    `;

    const btn = document.getElementById("users-search-btn");
    if (btn) {
      btn.onclick = () => loadUsers();
    }

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
          alert(e.message);
        }
      };
    }

    const sendNotifBtn = document.getElementById("deal-send-notifications-btn");
    if (sendNotifBtn) {
      sendNotifBtn.onclick = async () => {
        try {
          const res = await apiRequest("/deals/send-notifications", { method: "POST" });
          alert(`Уведомления отправлены: ${res.sent_count} получателей.`);
          loadDeals();
        } catch (e) {
          alert(e.message || "Ошибка отправки уведомлений");
        }
      };
    }

    const forceCloseBtn = document.getElementById("deal-force-close-btn");
    if (forceCloseBtn) {
      forceCloseBtn.onclick = async () => {
        if (!confirm("Вы уверены, что хотите досрочно закрыть текущую активную сделку?")) {
          return;
        }
        try {
          await apiRequest("/deals/force-close", { method: "POST" });
          alert("Сделка досрочно закрыта. Участникам отправлены уведомления.");
          loadDeals();
        } catch (e) {
          alert(e.message || "Ошибка досрочного закрытия сделки");
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
          alert("Введите корректное значение процента");
          return;
        }
        try {
          await apiRequest(`/deals/${dealId}`, {
            method: "PATCH",
            body: JSON.stringify({ profit_percent: value }),
          });
          alert("Доходность сделки обновлена");
          loadDeals();
        } catch (e) {
          alert(e.message);
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
          alert("Введите ненулевую сумму корректировки (можно со знаком - для списания).");
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
          alert("Запрос на корректировку отправлен администраторам в бота. Итоговый баланс изменится после подтверждения.");
          loadUserDetail(userId);
        } catch (e) {
          alert(e.message || "Ошибка корректировки баланса");
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
          alert(e.message);
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
      <p class="section-desc">Глобальные лимиты депозитов, выводов и инвестиций.</p>
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
          // Frontend-валидация: числа, > 0, min < max.
          const values = {};
          for (const field of fields) {
            const input = document.getElementById(field);
            if (!input) continue;
            const raw = input.value.trim().replace(",", ".");
            const num = parseFloat(raw);
            if (Number.isNaN(num) || num <= 0) {
              alert(`Поле "${field}" должно быть числом больше 0`);
              return;
            }
            values[field] = num;
          }

          if (values.min_deposit_usdt >= values.max_deposit_usdt) {
            alert("Мин. депозит должен быть меньше макс. депозита");
            return;
          }
          if (values.min_withdraw_usdt >= values.max_withdraw_usdt) {
            alert("Мин. вывод должен быть меньше макс. вывода");
            return;
          }
          if (values.min_invest_usdt >= values.max_invest_usdt) {
            alert("Мин. инвестиция должна быть меньше макс. инвестиции");
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
          showToast("Настройки успешно обновлены");
          loadSettings();
        } catch (e) {
          alert(e.message);
        } finally {
          if (saveBtn) {
            saveBtn.disabled = false;
            saveBtn.innerHTML = originalText;
          }
        }
      };
    }

    const resetBtn = document.getElementById("db-reset-btn");
    if (resetBtn) {
      resetBtn.onclick = async () => {
        const firstConfirm = confirm(
          "Это удалит ВСЕ тестовые данные (пользователи, сделки, платежи, леджер, выводы). Продолжить?"
        );
        if (!firstConfirm) return;

        const phrase = prompt('Для подтверждения введите слово RESET');
        if ((phrase || "").trim().toUpperCase() !== "RESET") {
          alert("Очистка отменена: подтверждение не пройдено.");
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
          alert(e.message || "Ошибка очистки базы");
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

function showToast(message) {
  const existing = document.querySelector(".toast");
  if (existing) {
    existing.remove();
  }
  const el = document.createElement("div");
  el.className = "toast";
  el.innerHTML = `
    <span class="toast-icon">✅</span>
    <span class="toast-message">${message}</span>
  `;
  document.body.appendChild(el);
  setTimeout(() => {
    el.classList.add("toast-hide");
    el.style.opacity = "0";
    setTimeout(() => el.remove(), 300);
  }, 2500);
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

