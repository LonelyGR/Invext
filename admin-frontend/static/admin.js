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
  return resp.json();
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
          <div class="stat-value">
            ${
              data.active_deal_number
                ? `#${data.active_deal_number} · ${data.active_deal_percent}% · инвестировано ${data.active_deal_invested_usdt} USDT`
                : "Нет активной сделки"
            }
          </div>
        </div>
      </div>
    `;
  } catch (e) {
    section.innerHTML = `<h1>Дашборд</h1><div class="error">${e.message}</div>`;
  }
}

async function loadUsers() {
  const section = document.getElementById("users-section");
  section.innerHTML = `
    <h1>Пользователи</h1>
    <div class="toolbar">
      <div class="search-field">
        <span class="search-field-icon">🔍</span>
        <input id="users-search" type="text" placeholder="Поиск по username / Telegram ID" />
      </div>
      <button id="users-search-btn">Искать</button>
    </div>
    <p>Загрузка...</p>
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
  const sections = ["dashboard", "users", "deals", "withdrawals", "logs", "user"];
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
  } else if (hash.startsWith("#user-")) {
    const id = hash.replace("#user-", "");
    loadUserDetail(id);
  } else if (hash === "#withdrawals") {
    loadWithdrawals();
  } else if (hash === "#logs") {
    loadLogs();
  }
}

async function loadDeals() {
  const section = document.getElementById("deals-section");
  section.innerHTML = "<h1>Сделки</h1><p>Загрузка...</p>";
  try {
    const deals = await apiRequest("/deals");
    const rows = deals
      .map(
        (d) => `
      <tr data-deal-id="${d.id}">
        <td>${d.number}</td>
        <td>${d.status}</td>
        <td>
          <input type="number" step="0.01" min="0" value="${d.percent}" class="deal-percent-input" />
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
      <div class="toolbar">
        <button id="deal-open-now-btn">Открыть новую сделку</button>
      </div>
      <p>Здесь можно скорректировать процент доходности по каждой сделке (open/closed).</p>
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
            body: JSON.stringify({ percent: value }),
          });
          alert("Процент обновлён");
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
        return `
        <tr>
          <td>${new Date(tx.created_at).toLocaleString()}</td>
          <td>${tx.type}</td>
          <td class="${cls}">${sign}${tx.amount_usdt}</td>
        </tr>`;
      })
      .join("");

    const mismatch =
      Number(u.balance_usdt) !== Number(u.ledger_balance_usdt)
        ? `<div class="warning">Кэш баланса != ledger</div>`
        : "";

    section.innerHTML = `
      <h1>Пользователь #${u.id}</h1>
      <div>Telegram ID: <strong>${u.telegram_id}</strong></div>
      <div>Username: <strong>${u.username || ""}</strong></div>
      <div>balance_usdt: <strong>${u.balance_usdt}</strong></div>
      <div>ledger_balance: <strong>${u.ledger_balance_usdt}</strong> ${mismatch}</div>
      <h2>Ledger</h2>
      <div class="toolbar">
        <button id="ledger-export-btn">Экспорт CSV</button>
      </div>
      <div class="table-wrapper">
        <div class="table-wrapper-inner">
          <table>
            <thead>
              <tr>
                <th>Дата</th>
                <th>Тип</th>
                <th>Сумма</th>
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
    `;

    const exportBtn = document.getElementById("ledger-export-btn");
    if (exportBtn) {
      exportBtn.onclick = () => {
        window.location.href = `${API_BASE}/ledger/${userId}/export`;
      };
    }
  } catch (e) {
    section.innerHTML = `<h1>Пользователь</h1><div class="error">${e.message}</div>`;
  }
}

async function loadWithdrawals() {
  const section = document.getElementById("withdrawals-section");
  section.innerHTML = "<h1>Выводы</h1><p>Загрузка...</p>";
  try {
    const data = await apiRequest("/withdrawals?status=PENDING");
    const rows = data.items
      .map(
        (w) => `
      <tr>
        <td>${w.id}</td>
        <td>${w.telegram_id}</td>
        <td>${w.username || ""}</td>
        <td>${w.amount} ${w.currency}</td>
        <td>${w.address}</td>
        <td>${w.status}</td>
        <td>
          <button data-id="${w.id}" data-action="approve">Approve</button>
          <button data-id="${w.id}" data-action="reject">Reject</button>
        </td>
      </tr>`
      )
      .join("");
    section.innerHTML = `
      <h1>Выводы (PENDING)</h1>
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
    `;

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

