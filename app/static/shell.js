/* Shell chrome shared by every page: the light/dark toggle, the collapsible
   sidebar, the keys that work everywhere, and the confirm dialog behind
   hx-confirm. The saved theme and sidebar state are first applied by the
   inline script in base.html's <head>, before paint; this file keeps them
   in step with the controls. */

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
    // The mode names are the design system's own ("Day"/"Night" or "Light mode"/"Dark mode").
    button.setAttribute("aria-label", `Switch to ${dark ? button.dataset.labelLight : button.dataset.labelDark}`);
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

  /* ---- a toast: one line of news at the foot of the page, for a moment ---- */

  let toastTimer = 0;
  window.toast = (message) => {
    let el = document.querySelector(".cal-toast");
    if (!el) {
      el = document.createElement("div");
      el.className = "cal-toast";
      el.setAttribute("role", "status");
      document.body.appendChild(el);
    }
    el.textContent = message;
    el.classList.add("show");
    // A newer toast gets its own full moment.
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => el.classList.remove("show"), 2600);
  };

  /* ---- keys that work on every page: 1-5 go to the nav's pages in order,
     ? shows every key (#keys-dialog), and N or Shift+N writes a new task (on
     the list pages, tasks.js puts it in the page's own list; elsewhere it
     opens #capture-dialog). Never while typing, or over a dialog. ---- */

  const TYPING = "input, textarea, select, [contenteditable]";
  document.addEventListener("keydown", (e) => {
    if (e.ctrlKey || e.metaKey || e.altKey || e.isComposing || e.defaultPrevented) return;
    if (e.target.closest?.(TYPING) || document.querySelector("dialog[open]")) return;
    if ((e.key === "n" || e.key === "N") && !document.querySelector("[data-cursor]")) {
      const capture = document.getElementById("capture-dialog");
      if (!capture) return;
      e.preventDefault();
      capture.showModal();
      window.TaskSheet.compose(capture.querySelector(".task-sheet"));
      return;
    }
    if (e.key === "?") {
      e.preventDefault();
      const dialog = document.getElementById("keys-dialog");
      dialog.showModal();
      dialog.focus(); // the dialog itself, so no control starts out ringed
      return;
    }
    const link = /^[1-9]$/.test(e.key) && document.querySelectorAll(".nav a[aria-keyshortcuts]")[Number(e.key) - 1];
    if (link && link.getAttribute("aria-current") !== "page") {
      e.preventDefault();
      link.click();
    }
  });

  /* ---- confirm: hx-confirm on an element with data-confirm-* opens the
     app's dialog (#confirm-dialog) instead of the browser's native box ---- */

  // A list can re-render while its question is open (a refresh from an
  // earlier change landing late), leaving the asking row detached. The
  // answer goes to the row's live twin: the element with the same id, and
  // within it the control that asks the same thing.
  const live = (el) => {
    if (!el || el.isConnected) return el;
    const holder = el.id ? el : el.closest("[id]");
    const twin = holder && document.getElementById(holder.id);
    if (!twin || holder === el) return twin;
    return [...twin.querySelectorAll("[hx-confirm]")].find(
      (c) => c.getAttribute("hx-post") === el.getAttribute("hx-post") && c.className === el.className,
    ) || null;
  };

  let answer = null; // the open confirm's close handler
  document.addEventListener("htmx:confirm", (e) => {
    const source = e.detail.elt;
    if (!source.dataset.confirmTitle) return;
    e.preventDefault();
    if (source._answered) {
      // Asked already, on the twin this stands in for.
      delete source._answered;
      e.detail.issueRequest(true);
      return;
    }
    const returnTo = document.activeElement;
    const dialog = document.getElementById("confirm-dialog");
    dialog.querySelector(".confirm-title").textContent = source.dataset.confirmTitle;
    dialog.querySelector(".confirm-name").textContent = source.dataset.confirmName || "";
    dialog.querySelector(".confirm-detail").textContent = source.dataset.confirmDetail || "";
    dialog.querySelector("[value=go]").textContent = source.dataset.confirmAction || "Confirm";
    dialog.returnValue = "";
    // One answer per opening. A dialog's "close" arrives a task after it
    // closes, so an Esc followed at once by another open would hand the new
    // opening the old one's close; that one is ignored (the dialog is open
    // again), and a previous opening's handler never hears the new answer.
    if (answer) dialog.removeEventListener("close", answer);
    const heard = () => {
      if (dialog.open) return;
      dialog.removeEventListener("close", heard);
      answer = null;
      // The dialog gives focus back to where it was, unless that was swapped away.
      if (returnTo && !returnTo.isConnected) live(returnTo)?.focus();
      if (dialog.returnValue !== "go") return;
      if (source.isConnected) {
        e.detail.issueRequest(true);
        return;
      }
      const twin = live(source);
      if (!twin) return; // gone for good: nothing left to act on
      twin._answered = true;
      htmx.trigger(twin, "click");
    };
    answer = heard;
    dialog.addEventListener("close", heard);
    dialog.showModal();
  });
})();
