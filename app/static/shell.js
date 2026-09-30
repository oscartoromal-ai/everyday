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

  /* ---- compact rows: a two-way toggle (and C), remembered ---- */

  const applyDensity = (compact) => {
    if (compact) root.dataset.density = "compact";
    else delete root.dataset.density;
    const button = document.querySelector(".density-toggle");
    button?.setAttribute("aria-pressed", String(compact));
    button?.setAttribute("aria-label", compact ? "Compact rows: on" : "Compact rows: off");
    // The notes measure their rows again.
    document.dispatchEvent(new CustomEvent("density:change"));
  };
  const toggleDensity = () => {
    const compact = root.dataset.density !== "compact";
    store("pc-density", compact ? "compact" : "roomy");
    applyDensity(compact);
  };
  document.addEventListener("click", (e) => {
    if (e.target.closest(".density-toggle")) toggleDensity();
  });
  applyDensity(root.dataset.density === "compact");

  /* ---- Today's timeline: folded away (Ctrl+\, or its button), remembered ---- */

  const applyTimeline = (folded) => {
    if (folded) root.dataset.timeline = "folded";
    else delete root.dataset.timeline;
    const button = document.querySelector(".timeline-toggle");
    if (!button) return;
    button.setAttribute("aria-pressed", String(folded));
    button.title = folded ? "Show the timeline (Ctrl+\\)" : "Fold the timeline away (Ctrl+\\)";
    button.setAttribute("aria-label", folded ? "Show the timeline" : "Fold the timeline away");
    document.dispatchEvent(new CustomEvent("density:change"));
  };
  const toggleTimeline = () => {
    const folded = root.dataset.timeline !== "folded";
    store("pc-timeline", folded ? "folded" : "shown");
    applyTimeline(folded);
  };
  document.addEventListener("click", (e) => {
    if (e.target.closest(".timeline-toggle")) toggleTimeline();
  });
  // Anywhere on Today, writing in the notes too.
  document.addEventListener("keydown", (e) => {
    if (e.key !== "\\" || !(e.ctrlKey || e.metaKey) || e.altKey || e.shiftKey) return;
    if (!document.querySelector(".today-page")) return;
    e.preventDefault();
    toggleTimeline();
  });
  applyTimeline(root.dataset.timeline === "folded");

  /* ---- a request refused (a value out of range, a lost connection): said in a toast ---- */

  document.addEventListener("htmx:responseError", (e) => {
    let detail = "";
    try { detail = JSON.parse(e.detail.xhr.responseText).detail; } catch { /* not JSON */ }
    window.toast(typeof detail === "string" && detail ? detail : "Could not save that. Try again?");
  });
  document.addEventListener("htmx:sendError", () => window.toast("Could not reach the app. Try again?"));

  /* ---- a toast: one line of news at the foot of the page, for a moment ---- */

  // One with an action (Undo) stays longer, and while the pointer is on it.
  let toastTimer = 0;
  window.toast = (message, { action = "", run = null } = {}) => {
    let el = document.querySelector(".cal-toast");
    if (!el) {
      el = document.createElement("div");
      el.className = "cal-toast";
      el.setAttribute("role", "status");
      el.addEventListener("pointerenter", () => clearTimeout(toastTimer));
      el.addEventListener("pointerleave", () => {
        toastTimer = setTimeout(() => el.classList.remove("show"), 1500);
      });
      document.body.appendChild(el);
    }
    el.textContent = message;
    if (action && run) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "toast-action";
      button.textContent = action;
      button.addEventListener("click", () => {
        el.classList.remove("show");
        run();
      });
      el.append(button);
    }
    el.classList.toggle("has-action", !!(action && run));
    el.classList.add("show");
    // A newer toast gets its own full moment.
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => el.classList.remove("show"), action && run ? 6000 : 2600);
  };

  /* ---- keys that work on every page: 1-9 go to the nav's pages that have a key, in order,
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
    if (e.key === "c" || e.key === "C") {
      e.preventDefault();
      toggleDensity();
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

  // Left and Right, outside a field, change the day on a page of days
  // (its [data-day-step] links). On the window, so it runs after a page's
  // own handler (Today's saves its notes first) and leaves what that took.
  window.addEventListener("keydown", (e) => {
    if (e.ctrlKey || e.metaKey || e.altKey || e.isComposing || e.defaultPrevented) return;
    if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
    if (e.target.closest?.(TYPING) || document.querySelector("dialog[open]")) return;
    const link = document.querySelector(`[data-day-step="${e.key === "ArrowLeft" ? "prev" : "next"}"]`);
    if (!link) return;
    e.preventDefault();
    link.click();
  });

  /* ---- confirm: hx-confirm on an element with data-confirm-* opens the
     app's dialog (#confirm-dialog) instead of the browser's native box; a
     page's own script asks the same (window.confirmAction) ---- */

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
  // Resolves true when the action is confirmed, false when it is not.
  const confirmAction = ({ title, name = "", detail = "", action = "Confirm" }) => new Promise((resolve) => {
    const returnTo = document.activeElement;
    const dialog = document.getElementById("confirm-dialog");
    dialog.querySelector(".confirm-title").textContent = title;
    dialog.querySelector(".confirm-name").textContent = name;
    dialog.querySelector(".confirm-detail").textContent = detail;
    dialog.querySelector("[value=go]").textContent = action;
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
      resolve(dialog.returnValue === "go");
    };
    answer = heard;
    dialog.addEventListener("close", heard);
    dialog.showModal();
  });
  window.confirmAction = confirmAction;

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
    const { confirmTitle, confirmName, confirmDetail, confirmAction: action } = source.dataset;
    confirmAction({ title: confirmTitle, name: confirmName, detail: confirmDetail, action }).then((yes) => {
      if (!yes) return;
      if (source.isConnected) {
        e.detail.issueRequest(true);
        return;
      }
      const twin = live(source);
      if (!twin) return; // gone for good: nothing left to act on
      twin._answered = true;
      htmx.trigger(twin, "click");
    });
  });

  /* ---- fields written on the line (app.css, "inputs") ---- */

  // A one-line answer wraps as a notes row does, but Enter ends it (a
  // change, which saves) and a pasted line break becomes a space.
  document.addEventListener("keydown", (e) => {
    if (e.key !== "Enter" || e.isComposing || !e.target.matches?.("textarea[data-one-line]")) return;
    e.preventDefault();
    e.target.blur();
  });
  // An empty date reads as a placeholder (data-empty), not as a value.
  const markDate = (input) => input.toggleAttribute("data-empty", !input.value);
  document.addEventListener("input", (e) => {
    const field = e.target;
    if (field.matches?.("textarea[data-one-line]") && /\r|\n/.test(field.value)) {
      field.value = field.value.replace(/\s*[\r\n]+\s*/g, " ");
    }
    if (field.matches?.("input[type=date]")) markDate(field);
  });
  const markDates = (scope) => scope.querySelectorAll("input[type=date]").forEach(markDate);
  markDates(document);
  document.addEventListener("htmx:load", (e) => markDates(e.detail.elt));
  // A form's reset event comes before its fields go back.
  document.addEventListener("reset", (e) => setTimeout(() => markDates(e.target)));

  /* ---- the phone's tab bar scrolls sideways once it holds more tabs than
     fit: it opens on the current page's tab, and marks the edges that have
     more past them (data-more), which fade ---- */
  const nav = document.querySelector(".nav");
  if (nav) {
    const markMore = () => {
      const more = [];
      if (nav.scrollLeft > 1) more.push("start");
      if (nav.scrollLeft + nav.clientWidth < nav.scrollWidth - 1) more.push("end");
      if (more.length) nav.dataset.more = more.join(" ");
      else delete nav.dataset.more;
    };
    const current = nav.querySelector('a[aria-current="page"]');
    if (current && nav.scrollWidth > nav.clientWidth) {
      const middle = current.offsetLeft - nav.offsetLeft + current.offsetWidth / 2;
      nav.scrollLeft = middle - nav.clientWidth / 2;
    }
    markMore();
    nav.addEventListener("scroll", markMore, { passive: true });
    window.addEventListener("resize", markMore);
  }
})();
