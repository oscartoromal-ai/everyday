/* Shell chrome shared by every page: the light/dark toggle, the collapsible
   sidebar, and the Brasa confirm dialog behind hx-confirm. The saved theme
   and sidebar state are first applied by the inline script in base.html's
   <head>, before paint; this file keeps them in step with the controls. */

(() => {
  const root = document.documentElement;
  const store = (key, value) => {
    try { localStorage.setItem(key, value); } catch { /* private mode: session-only */ }
  };
  const saved = (key) => {
    try { return localStorage.getItem(key); } catch { return null; }
  };

  /* ---- theme: a two-way toggle; with no saved choice, follow the system ---- */

  const isDark = () => root.dataset.theme === "dark";
  const applyTheme = (dark) => {
    if (dark) root.dataset.theme = "dark";
    else delete root.dataset.theme;
    const button = document.querySelector(".theme-toggle");
    if (!button) return;
    button.setAttribute("aria-pressed", String(dark));
    button.setAttribute("aria-label", dark ? "Switch to light mode" : "Switch to dark mode");
  };

  document.addEventListener("click", (e) => {
    if (!e.target.closest(".theme-toggle")) return;
    const dark = !isDark();
    store("pc-theme", dark ? "dark" : "light");
    applyTheme(dark);
  });
  matchMedia("(prefers-color-scheme: dark)").addEventListener("change", (e) => {
    const choice = saved("pc-theme");
    if (choice !== "light" && choice !== "dark") applyTheme(e.matches);
  });
  applyTheme(isDark());

  /* ---- sidebar: collapses to an icon rail, remembered per browser ---- */

  const applyRail = (collapsed) => {
    if (collapsed) root.dataset.rail = "collapsed";
    else delete root.dataset.rail;
    const button = document.querySelector(".rail-collapse");
    if (!button) return;
    button.setAttribute("aria-expanded", String(!collapsed));
    const label = collapsed ? "Expand sidebar" : "Collapse sidebar";
    button.setAttribute("aria-label", label);
    button.title = label;
  };

  document.addEventListener("click", (e) => {
    if (!e.target.closest(".rail-collapse")) return;
    const collapsed = root.dataset.rail !== "collapsed";
    store("pc-rail", collapsed ? "collapsed" : "expanded");
    applyRail(collapsed);
  });
  applyRail(root.dataset.rail === "collapsed");

  /* ---- confirm: hx-confirm on an element with data-confirm-* opens the
     Brasa dialog (#confirm-dialog) instead of the browser's native box ---- */

  document.addEventListener("htmx:confirm", (e) => {
    const source = e.detail.elt;
    if (!source.dataset.confirmTitle) return;
    e.preventDefault();
    const dialog = document.getElementById("confirm-dialog");
    dialog.querySelector(".confirm-title").textContent = source.dataset.confirmTitle;
    dialog.querySelector(".confirm-name").textContent = source.dataset.confirmName || "";
    dialog.querySelector(".confirm-detail").textContent = source.dataset.confirmDetail || "";
    dialog.querySelector("[value=go]").textContent = source.dataset.confirmAction || "Confirm";
    dialog.returnValue = "";
    dialog.addEventListener("close", () => {
      if (dialog.returnValue === "go") e.detail.issueRequest(true);
    }, { once: true });
    dialog.showModal();
  });
})();
