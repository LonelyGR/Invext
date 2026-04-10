/**
 * Minimal React layer for Invext Admin.
 * Phase 1: React-powered Dashboard mounted into existing #dashboard-section.
 *
 * Uses React/ReactDOM UMD globals and reuses existing API_BASE/apiRequest from admin.js when available.
 */
(function (global) {
  "use strict";

  if (!global.React || !global.ReactDOM) {
    // React not available – keep legacy dashboard only.
    global.ReactAdmin = {
      renderDashboard: function () {
        /* no-op */
      },
    };
    return;
  }

  const React = global.React;
  const ReactDOM = global.ReactDOM;
  const { useState, useEffect } = React;

  function useDashboardData() {
    const [state, setState] = useState({
      loading: true,
      error: null,
      data: null,
    });

    useEffect(() => {
      let cancelled = false;

      async function load() {
        setState({ loading: true, error: null, data: null });
        try {
          // Reuse existing apiRequest if present, otherwise fallback to fetch.
          const api = typeof global.apiRequest === "function"
            ? global.apiRequest
            : async function (path) {
                const resp = await fetch((global.API_BASE || "/database/api") + path, {
                  credentials: "include",
                });
                if (!resp.ok) throw new Error("HTTP " + resp.status);
                return resp.json();
              };
          const data = await api("/dashboard");
          if (cancelled) return;
          setState({ loading: false, error: null, data });
        } catch (e) {
          if (cancelled) return;
          setState({ loading: false, error: e instanceof Error ? e : new Error(String(e)), data: null });
        }
      }

      load();

      return () => {
        cancelled = true;
      };
    }, []);

    return state;
  }

  function computeQueueLevel(count) {
    const n = Number(count || 0);
    if (n >= 30) return "action";
    if (n >= 10) return "watch";
    return "ok";
  }

  function SignalBadge(props) {
    const level = props.level || "ok";
    let text = "OK";
    if (level === "watch") text = "Watch";
    if (level === "action") text = "Action";
    const cls =
      level === "action"
        ? "status-badge status-expired"
        : level === "watch"
        ? "status-badge status-pending"
        : "status-badge status-paid";
    return React.createElement("span", { className: cls }, text);
  }

  function ReactDashboard() {
    const { loading, error, data } = useDashboardData();

    if (loading) {
      return React.createElement(
        "div",
        null,
        React.createElement("h1", null, "Дашборд (React)"),
        React.createElement("p", { className: "section-desc" }, "Загрузка…")
      );
    }

    if (error) {
      return React.createElement(
        "div",
        null,
        React.createElement("h1", null, "Дашборд (React)"),
        React.createElement("div", { className: "error" }, error.message || "Ошибка загрузки дашборда")
      );
    }

    const pending = Number(data.pending_withdrawals_count || 0);
    const usersCount = Number(data.users_count || 0);
    const totalLedger =
      typeof globalThis.formatUsdt2 === "function"
        ? globalThis.formatUsdt2(Number(data.total_ledger_balance_usdt || 0))
        : Number(data.total_ledger_balance_usdt || 0).toLocaleString("ru-RU", {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2,
          });
    const queueLevel = computeQueueLevel(pending);

    return React.createElement(
      React.Fragment,
      null,
      React.createElement("h1", null, "Дашборд (React — эксперимент)"),
      React.createElement(
        "div",
        { className: "dashboard-attention panel-card" },
        React.createElement(
          "div",
          { className: "dashboard-attention__head" },
          React.createElement("h2", { className: "dashboard-attention__title" }, "Operational Health"),
          React.createElement(
            "div",
            { className: "dashboard-attention__meta" },
            React.createElement("span", { className: "dashboard-attention__updated" }, "Экспериментальный React-слой"),
            React.createElement(SignalBadge, { level: queueLevel })
          )
        ),
        React.createElement(
          "div",
          { className: "dashboard-attention__body" },
          React.createElement(
            "p",
            { className: "dashboard-attention__summary" },
            "Pending выводов: ",
            pending
          ),
          React.createElement(
            "div",
            { className: "dashboard-attention__actions" },
            React.createElement(
              "a",
              { href: "#withdrawals", className: "ds-btn ds-btn--secondary ds-btn--sm" },
              "Выводы"
            ),
            React.createElement(
              "a",
              { href: "#deals", className: "ds-btn ds-btn--secondary ds-btn--sm" },
              "Сделки"
            )
          )
        )
      ),
      React.createElement(
        "div",
        { className: "cards-grid" },
        React.createElement(
          "div",
          { className: "stat-card" },
          React.createElement("div", { className: "stat-label" }, "Пользователей"),
          React.createElement("div", { className: "stat-value" }, usersCount)
        ),
        React.createElement(
          "div",
          { className: "stat-card" },
          React.createElement("div", { className: "stat-label" }, "Общий баланс (ledger)"),
          React.createElement(
            "div",
            { className: "stat-value" },
            totalLedger,
            " ",
            React.createElement("span", { className: "stat-unit" }, "USDT")
          )
        ),
        React.createElement(
          "div",
          { className: "stat-card" },
          React.createElement("div", { className: "stat-label" }, "Pending выводов"),
          React.createElement("div", { className: "stat-value" }, pending)
        )
      )
    );
  }

  function mountReactDashboard() {
    const section = document.getElementById("dashboard-section");
    if (!section || !ReactDOM.createRoot) return;
    if (section.__reactRoot) {
      // Already mounted; nothing else to do.
      return;
    }
    const root = ReactDOM.createRoot(section);
    section.__reactRoot = root;
    root.render(React.createElement(ReactDashboard));
    if (global.AdminUI && typeof global.AdminUI.refreshIcons === "function") {
      global.AdminUI.refreshIcons();
    }
  }

  global.ReactAdmin = {
    renderDashboard: mountReactDashboard,
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", mountReactDashboard);
  } else {
    mountReactDashboard();
  }
})(typeof window !== "undefined" ? window : this);

