/**
 * Admin UI runtime: shell helpers + Lucide auto-hydration for dynamically rendered HTML.
 * Загружать после lucide.min.js, до admin.js.
 */
(function (global) {
  "use strict";

  const LUCIDE_ATTRS = {
    "stroke-width": "1.75",
    width: "18",
    height: "18",
  };

  /**
   * Заменяет все [data-lucide] внутри root на SVG (Lucide UMD).
   * Безопасно вызывать многократно: обрабатываются только плейсхолдеры <i>.
   */
  function refreshIcons() {
    if (typeof global.lucide === "undefined" || typeof global.lucide.createIcons !== "function") {
      return;
    }
    try {
      global.lucide.createIcons({
        attrs: LUCIDE_ATTRS,
        nameAttr: "data-lucide",
      });
    } catch (e) {
      console.warn("Lucide createIcons failed:", e);
    }
  }

  function installLucideObserver(rootEl) {
    if (!rootEl || rootEl.dataset.lucideObserver === "1") return;
    rootEl.dataset.lucideObserver = "1";
    let t = null;
    const run = () => {
      refreshIcons();
    };
    const mo = new MutationObserver(() => {
      if (t) clearTimeout(t);
      t = setTimeout(run, 32);
    });
    mo.observe(rootEl, { childList: true, subtree: true });
    refreshIcons();
  }

  function initShell() {
    const main = document.getElementById("main-view");
    if (main) installLucideObserver(main);
    else refreshIcons();
  }

  global.AdminUI = {
    refreshIcons,
    installLucideObserver,
    initShell,
  };
})(typeof window !== "undefined" ? window : this);
