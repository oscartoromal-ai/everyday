/* Shell chrome shared by every page: the light/dark toggle, the collapsible
   sidebar and its folding projects, the agent window expanded and collapsed, Back to the page before, the keys that work everywhere, the confirm dialog behind
   hx-confirm, and the desktop app's title bar and taskbar count. The saved theme and sidebar state are first applied by the
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
  let paintTitleBar = () => {}; // the desktop app's, set below
  const applyTheme = (dark) => {
    if (dark) root.dataset.theme = "dark";
    else delete root.dataset.theme;
    // The browser's bar, and the desktop app's title bar, in the theme's paper.
    const bar = document.querySelector('meta[name="theme-color"]');
    if (bar) bar.content = getComputedStyle(root).getPropertyValue("--paper").trim() || bar.content;
    paintTitleBar();
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
    button.title = window.Keys.title(label, "app.sidebar");
  };

  document.addEventListener("click", (e) => {
    if (!e.target.closest(".rail-collapse")) return;
    const collapsed = root.dataset.rail !== "collapsed";
    store("pc-rail", collapsed ? "collapsed" : "expanded");
    applyRail(collapsed);
  });
  applyRail(root.dataset.rail === "collapsed");

  /* ---- the agent window: expanded at the page's side or collapsed away,
     remembered per browser; the sidebar's Agent, its own Collapse and A
     (below) switch it. Collapsed, it is inert, so neither Tab nor a screen
     reader reaches into it. ---- */

  const agentPanel = document.getElementById("agent-panel");
  const applyAgent = (open) => {
    if (open) root.dataset.agent = "open";
    else delete root.dataset.agent;
    if (!agentPanel) return;
    agentPanel.inert = !open;
    document.querySelectorAll("[data-agent-toggle]").forEach((button) => {
      button.setAttribute("aria-expanded", String(open));
    });
  };
  const toggleAgent = (open = root.dataset.agent !== "open") => {
    if (!agentPanel) return;
    const had = agentPanel.contains(document.activeElement);
    store("pc-agent", open ? "open" : "closed");
    applyAgent(open);
    if (open) {
      const log = document.getElementById("agent-log");
      if (log) log.scrollTop = log.scrollHeight;
      agentPanel.querySelector("textarea:not(:disabled)")?.focus();
    } else if (had) {
      // The focus was in the window going away: to the button that brings it back.
      document.querySelector(".rail-button[data-agent-toggle]")?.focus();
    }
  };
  document.addEventListener("click", (e) => {
    if (e.target.closest?.("[data-agent-toggle]")) toggleAgent();
  });
  // Esc in the message steps out of it, so the page's keys (A among them) work again.
  agentPanel?.addEventListener("keydown", (e) => {
    if (e.key !== "Escape" || e.isComposing || !e.target.matches("textarea")) return;
    e.preventDefault();
    e.target.blur();
  });
  // A new chat, or another agent, draws the window again: back at its message.
  document.addEventListener("htmx:afterSwap", (e) => {
    if (e.detail.target === agentPanel && root.dataset.agent === "open") {
      agentPanel.querySelector("textarea:not(:disabled)")?.focus();
    }
  });
  applyAgent(root.dataset.agent === "open");

  /* ---- the sidebar's projects, under Projects: folded away by its chevron, remembered ---- */

  const applyRailProjects = (folded) => {
    if (folded) root.dataset.railProjects = "folded";
    else delete root.dataset.railProjects;
    const button = document.querySelector(".nav-fold");
    if (!button) return;
    button.setAttribute("aria-expanded", String(!folded));
    const label = folded ? "Show the projects" : "Hide the projects";
    button.setAttribute("aria-label", label);
    button.title = label;
  };

  document.addEventListener("click", (e) => {
    if (!e.target.closest(".nav-fold")) return;
    const folded = root.dataset.railProjects !== "folded";
    store("pc-rail-projects", folded ? "folded" : "shown");
    applyRailProjects(folded);
  });
  applyRailProjects(root.dataset.railProjects === "folded");

  /* ---- the sidebar's layout (app/services/rail.py): a module hidden by its
     eye and brought back from Settings; a module dragged within its section,
     a section by its name (or its one module), a project among the projects;
     Alt+Up/Down moves the focused one (with Shift, its section). The page
     changes at once, and the server keeps it. ---- */

  const railNav = document.querySelector(".nav");
  if (railNav) {
    // One save after another, so the server keeps the last state, not
    // whichever of two quick moves' saves landed last.
    let saving = Promise.resolve();
    const send = (url, body) => (saving = saving.then(() =>
      fetch(url, {
        method: "PUT",
        headers: { "Content-Type": "application/json", "X-CSRF": window.csrfToken() },
        body: JSON.stringify(body),
      })
        .then((res) => { if (!res.ok) throw new Error(res.statusText); })
        .catch(() => window.toast("Could not save the sidebar. Try again?"))));

    const groups = () => [...railNav.querySelectorAll(":scope > .nav-group[data-section]")];
    const modulesOf = (group) => [...group.querySelectorAll(":scope > .nav-item")];
    // The modules showing, top to bottom, are the sidebar's pages 1 to 9
    // (Alt+1 to Alt+9, unless the keys were changed): numbered again as one
    // is hidden, shown or moved (as app/services/rail.py numbers them), each
    // with its key's last part on its icon.
    const renumber = () => {
      const shown = [...railNav.querySelectorAll(".nav-item")].filter((i) => !i.hidden);
      for (const item of railNav.querySelectorAll(".nav-item")) {
        const link = item.querySelector("a");
        const n = item.hidden ? 0 : shown.indexOf(item) + 1;
        const slot = n && n <= 9 ? String(n) : "";
        const keys = slot ? window.Keys.keys(`nav.slot${slot}`) : [];
        item.querySelector(".nav-key").textContent = keys.length ? window.Keys.parts(keys[0]).at(-1) : "";
        link.dataset.slot = slot;
        if (keys.length) link.setAttribute("aria-keyshortcuts", window.Keys.aria(`nav.slot${slot}`));
        else link.removeAttribute("aria-keyshortcuts");
      }
    };
    const saveLayout = () => {
      renumber();
      return send("/ui/rail", {
        sections: groups().map((g) => g.dataset.section),
        modules: Object.fromEntries(groups().map((g) => [g.dataset.section, modulesOf(g).map((i) => i.dataset.module)])),
        hidden: [...railNav.querySelectorAll(".nav-item[hidden]")].map((i) => i.dataset.module),
      });
    };
    // The projects' order is Projects' too: its timeline, Plan, and this list
    // are drawn again in it (the link that had focus keeps it).
    const saveProjects = (focusHref = null) => {
      const ids = [...document.querySelectorAll("#rail-projects > li")].map((li) => Number(li.dataset.projectId));
      send("/ui/projects/order", { ids }).then(() => {
        if (focusHref) {
          document.body.addEventListener("htmx:afterSettle", function refocus(e) {
            if (e.detail.elt.id !== "rail-projects") return;
            document.body.removeEventListener("htmx:afterSettle", refocus);
            document.querySelector(`#rail-projects a[href="${focusHref}"]`)?.focus();
          });
        }
        htmx.trigger(document.body, "projects:changed");
      });
    };

    const label = (item) => item.querySelector(".nav-label").textContent.trim();
    const setHidden = (item, hidden) => {
      item.hidden = hidden;
      saveLayout();
    };

    // The module below slides up under the pointer: its eye waits for the
    // pointer to move on, so a second click does not hide that one too.
    let settling = null;
    document.addEventListener("pointermove", (e) => {
      if (settling && Math.hypot(e.clientX - settling.x, e.clientY - settling.y) > 6) {
        settling = null;
        delete railNav.dataset.settling;
      }
    });
    document.addEventListener("click", (e) => {
      const hide = e.target.closest("[data-nav-hide]");
      if (!hide) return;
      const item = hide.closest(".nav-item");
      if (e.detail) {
        settling = { x: e.clientX, y: e.clientY };
        railNav.dataset.settling = "";
      }
      // From the keyboard, focus goes on to the next module showing.
      const next = e.detail ? null : [...railNav.querySelectorAll(".nav-item:not([hidden])")]
        .filter((i) => i !== item && item.compareDocumentPosition(i) & Node.DOCUMENT_POSITION_FOLLOWING)[0];
      setHidden(item, true);
      if (!e.detail) (next?.querySelector("a") || document.querySelector("[data-settings-open]")).focus();
      window.toast(`${label(item)} hidden. Settings brings it back.`, { action: "Undo", run: () => setHidden(item, false) });
    });

    /* Settings: the hidden modules, each with its section and Show. */
    const settings = document.getElementById("settings-dialog");
    const listHidden = () => {
      const list = settings.querySelector("[data-hidden-modules]");
      list.replaceChildren(...[...railNav.querySelectorAll(".nav-item[hidden]")].map((item) => {
        const row = document.createElement("li");
        row.className = "settings-module";
        const name = document.createElement("span");
        name.className = "settings-module__name";
        name.textContent = label(item);
        const section = document.createElement("span");
        section.className = "settings-module__section";
        section.textContent = item.closest(".nav-group").querySelector(".nav-group-label")?.textContent.trim() || "";
        const show = document.createElement("button");
        show.type = "button";
        show.className = "btn quiet";
        show.textContent = "Show";
        show.setAttribute("aria-label", `Show ${label(item)} in the sidebar`);
        show.addEventListener("click", () => {
          setHidden(item, false);
          const next = row.nextElementSibling?.querySelector("button") || row.previousElementSibling?.querySelector("button");
          row.remove();
          settings.toggleAttribute("data-empty", !list.children.length);
          (next || settings.querySelector("header .btn")).focus();
        });
        row.append(item.querySelector("a svg").cloneNode(true), name, section, show);
        return row;
      }));
      settings.toggleAttribute("data-empty", !list.children.length);
    };
    document.addEventListener("click", (e) => {
      if (!e.target.closest("[data-settings-open]")) return;
      listHidden();
      settings.showModal();
      settings.focus(); // the dialog itself, so no control starts out ringed
    });

    /* What a grab at the target moves: its element, the elements it moves
       among (the visible ones, in its container) and how the order is kept. */
    const sectionUnit = (group) => ({
      el: group, container: railNav, save: saveLayout,
      peers: () => groups().filter((g) => getComputedStyle(g).display !== "none"),
    });
    const unitAt = (target) => {
      const project = target.closest("#rail-projects > li");
      if (project) {
        return {
          el: project, container: project.parentElement, save: saveProjects,
          peers: () => [...project.parentElement.children],
        };
      }
      const labelEl = target.closest(".nav-group-label");
      if (labelEl) return sectionUnit(labelEl.parentElement);
      const item = target.closest(".nav-item");
      if (!item) return null;
      const group = item.parentElement;
      const visible = () => modulesOf(group).filter((i) => !i.hidden);
      // A section's one module heads it: grabbing it moves the section.
      if (visible().length < 2) return sectionUnit(group);
      return { el: item, container: group, save: saveLayout, peers: visible };
    };

    // An element's top on the screen as laid out, before any transform: its
    // container is positioned (app.css), so offsetTop measures from it.
    const layoutTop = (el, container) =>
      container.getBoundingClientRect().top + container.clientTop + el.offsetTop - container.scrollTop;

    // The peers slide to their new places (FLIP), the one in hand stays put;
    // with reduced motion, they are just there.
    const still = matchMedia("(prefers-reduced-motion: reduce)");
    const slide = (el, keyframes) => {
      if (!still.matches) el.animate(keyframes, { duration: 160, easing: "ease-out" });
    };
    const reorder = (unit, place) => {
      const peers = unit.peers();
      const before = new Map(peers.map((p) => [p, p.getBoundingClientRect().top]));
      place();
      for (const p of peers) {
        if (p === unit.el) continue;
        const dy = before.get(p) - p.getBoundingClientRect().top;
        if (dy) slide(p, [{ transform: `translateY(${dy}px)` }, { transform: "none" }]);
      }
    };

    // Up or down one place among its peers, as Alt+Up/Down asks.
    const step = (unit, by) => {
      const peers = unit.peers();
      const target = peers[peers.indexOf(unit.el) + by];
      if (!target) return false;
      reorder(unit, () => (by < 0 ? target.before(unit.el) : target.after(unit.el)));
      return true;
    };

    railNav.addEventListener("keydown", (e) => {
      const link = e.target.closest("a");
      if (!link || e.isComposing) return;
      const keys = window.Keys;
      // A page hidden from the keyboard, as its eye does (focus going on).
      if (keys.is(e, "rail.hide")) {
        const eye = link.closest(".nav-item")?.querySelector("[data-nav-hide]");
        if (!eye) return;
        e.preventDefault();
        eye.click();
        return;
      }
      const section = keys.is(e, "rail.sectionUp") ? -1 : keys.is(e, "rail.sectionDown") ? 1 : 0;
      const by = section || (keys.is(e, "rail.up") ? -1 : keys.is(e, "rail.down") ? 1 : 0);
      if (!by) return;
      e.preventDefault();
      let unit = unitAt(link);
      if (section && unit.container !== railNav) unit = sectionUnit(link.closest(".nav-group"));
      if (!step(unit, by)) return;
      link.focus();
      if (unit.save === saveProjects) saveProjects(link.getAttribute("href"));
      else unit.save();
    });

    /* The pointer: a press that moves 5px picks the thing up; it follows the
       pointer, the others making room as it passes their middles; let go, it
       lands (and the click it would have made is not one). Esc puts it back. */
    let drag = null;
    const phone = matchMedia("(max-width: 720px)");
    railNav.addEventListener("pointerdown", (e) => {
      if (e.button !== 0 || phone.matches || e.target.closest("button")) return;
      const unit = unitAt(e.target);
      if (!unit) return;
      drag = { ...unit, id: e.pointerId, x: e.clientX, y: e.clientY, started: false };
    });

    const follow = (y) => {
      drag.el.style.translate = "";
      drag.el.style.translate = `0 ${y - drag.grab - drag.el.getBoundingClientRect().top}px`;
    };
    const finish = (cancelled) => {
      const d = drag;
      drag = null;
      if (!d?.started) return;
      // It lands from where it is in hand into its place (home, if put back).
      const held = d.el.getBoundingClientRect().top;
      d.el.style.translate = "";
      if (cancelled) reorder(d, () => d.home.parent.insertBefore(d.el, d.home.next));
      slide(d.el, [{ translate: `0 ${held - d.el.getBoundingClientRect().top}px` }, { translate: "0 0" }]);
      d.el.classList.remove("is-dragging");
      delete railNav.dataset.dragging;
      // The click a link would get from this press is the drop, not a visit.
      const swallow = (ev) => { ev.preventDefault(); ev.stopPropagation(); };
      window.addEventListener("click", swallow, { capture: true, once: true });
      setTimeout(() => window.removeEventListener("click", swallow, { capture: true }));
      if (!cancelled && d.el.nextElementSibling !== d.home.next) d.save();
    };

    document.addEventListener("pointermove", (e) => {
      if (!drag || e.pointerId !== drag.id) return;
      if (!drag.started) {
        if (Math.hypot(e.clientX - drag.x, e.clientY - drag.y) < 5) return;
        drag.started = true;
        drag.grab = drag.y - drag.el.getBoundingClientRect().top;
        drag.home = { parent: drag.el.parentElement, next: drag.el.nextElementSibling };
        drag.el.classList.add("is-dragging");
        railNav.dataset.dragging = "";
      }
      e.preventDefault();
      // Near the rail's edges, a rail that scrolls scrolls along.
      const edge = railNav.getBoundingClientRect();
      if (e.clientY < edge.top + 24) railNav.scrollTop -= 8;
      else if (e.clientY > edge.bottom - 24) railNav.scrollTop += 8;
      // It passes another once the pointer passes that one's middle (sections
      // differ in height; a tall one landing never puts it back over).
      const y = e.clientY;
      const middle = (p) => layoutTop(p, drag.container) + p.offsetHeight / 2;
      const peers = drag.peers();
      const at = peers.indexOf(drag.el);
      let to = at;
      while (to > 0 && y < middle(peers[to - 1])) to--;
      if (to === at) while (to < peers.length - 1 && y > middle(peers[to + 1])) to++;
      if (to < at) reorder(drag, () => peers[to].before(drag.el));
      else if (to > at) reorder(drag, () => peers[to].after(drag.el));
      follow(e.clientY);
    });
    document.addEventListener("pointerup", (e) => { if (drag && e.pointerId === drag.id) finish(false); });
    document.addEventListener("pointercancel", (e) => { if (drag && e.pointerId === drag.id) finish(true); });
    document.addEventListener("keydown", (e) => {
      if (e.key !== "Escape" || !drag?.started) return;
      e.preventDefault();
      e.stopPropagation();
      finish(true);
    }, true);
  }

  /* ---- compact rows: a two-way toggle (its key presses it), remembered ---- */

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

  /* ---- Today's timeline: folded away (its key, or its button), remembered ---- */

  const applyTimeline = (folded) => {
    if (folded) root.dataset.timeline = "folded";
    else delete root.dataset.timeline;
    const button = document.querySelector(".timeline-toggle");
    if (!button) return;
    button.setAttribute("aria-pressed", String(folded));
    button.title = window.Keys.title(folded ? "Show the timeline" : "Fold the timeline away", "today.timeline");
    button.setAttribute("aria-label", folded ? "Show the timeline" : "Fold the timeline away");
    document.dispatchEvent(new CustomEvent("density:change"));
  };
  const toggleTimeline = () => {
    const folded = root.dataset.timeline !== "folded";
    store("pc-timeline", folded ? "folded" : "shown");
    applyTimeline(folded);
  };
  // Its key presses it (keys.js), anywhere on Today, writing in the notes too.
  document.addEventListener("click", (e) => {
    if (e.target.closest(".timeline-toggle")) toggleTimeline();
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
  // A window closing hands its toast back to the page, to finish its moment
  // ("close" does not bubble; caught on the way down).
  document.addEventListener("close", (e) => {
    const el = e.target.querySelector?.(":scope > .cal-toast");
    if (el) document.body.appendChild(el);
  }, true);
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
    }
    // Over an open window (the New task window), in it: the page under a
    // window is out of reach, and its action with it.
    const host = document.querySelector("dialog[open]:modal") || document.body;
    if (el.parentElement !== host) host.appendChild(el);
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

  /* ---- keys that work on every page and need a script (keys.js does the
     rest, such as compact rows, or stepping a page of days by its
     [data-day-step] links): the sidebar's pages 1 to 9 as it shows them,
     each its number beside its name (from a field too, which saves as the
     page goes); every key (#keys-dialog); and a new task (on a task list,
     a project's Tasks or Plan, tasks.js puts it in the page's own list; elsewhere it opens
     #capture-dialog, as the sidebar's New task does on every page). ---- */

  const openCapture = () => {
    const capture = document.getElementById("capture-dialog");
    if (!capture) return false;
    if (!capture.open) capture.showModal();
    window.TaskSheet.capture(capture.querySelector(".task-sheet"));
    return true;
  };
  document.addEventListener("click", (e) => {
    if (e.target.closest?.("[data-capture-open]")) openCapture();
  });
  window.Keys.handle("task.new", () => !!window.TaskCursor?.compose() || openCapture());

  for (let n = 1; n <= 9; n++) {
    window.Keys.handle(`nav.slot${n}`, () => {
      const link = document.querySelector(`.nav a[data-slot="${n}"]`);
      if (!link) return false;
      if (link.getAttribute("aria-current") !== "page") link.click();
      return true;
    });
  }
  // The agent window (A, or the sidebar's Agent), where the page has one.
  window.Keys.handle("app.agent", () => toggleAgent(), () => !!agentPanel);

  window.Keys.handle("app.keys", () => {
    const dialog = document.getElementById("keys-dialog");
    dialog.showModal();
    dialog.focus(); // the dialog itself, so no control starts out ringed
  });

  /* ---- Back: to the page before, named, and as it was left. The window's
     own history (the Navigation API) says which page that is. Each page
     leaves its name under its history entry, and as it goes, where it was
     as its own script keeps it (window.keepPlace: a sheet's cursor, a
     grid's scroll; the window's scroll is the browser's to keep). The
     server never lets a page be cached (app/fresh.py), so the page comes
     back as it is now, and is put back where it was. The sidebar's Back
     goes back, as Alt+Left and the mouse's back button do; a page's own
     "‹" link (a task's, a project's)
     goes back too when the page before is the one it names, else it opens
     that page. ---- */

  const sessionHistory = window.navigation;
  const PLACE = "pc-place:";
  const pageName = () => document.title.replace(/\s*·\s*Personal Calendar$/, "");
  const keptAt = (entry) => {
    try { return JSON.parse(sessionStorage.getItem(PLACE + entry.key)) || {}; } catch { return {}; }
  };
  const keepAt = (entry, kept) => {
    try { sessionStorage.setItem(PLACE + entry.key, JSON.stringify(kept)); } catch { /* full or off: no place kept */ }
  };
  // The page before this one in the window, if it is one of the app's.
  const before = () => {
    const at = sessionHistory?.currentEntry;
    if (!at || at.index < 1) return null;
    const entry = sessionHistory.entries()[at.index - 1];
    return entry ? { url: new URL(entry.url), name: keptAt(entry).name } : null;
  };

  // Arriving back (or reloaded), the place each script kept, once.
  const arrivedBy = sessionHistory?.activation?.navigationType;
  const returning = arrivedBy === "traverse" || arrivedBy === "reload";
  const kept = returning && sessionHistory.currentEntry ? keptAt(sessionHistory.currentEntry) : {};
  const keepers = new Map();
  window.keepPlace = (name, save, restore) => {
    keepers.set(name, save);
    if (kept.places?.[name] !== undefined) restore(kept.places[name]);
  };
  if (sessionHistory?.currentEntry) keepAt(sessionHistory.currentEntry, { ...kept, name: pageName() });
  window.addEventListener("pagehide", () => {
    if (!sessionHistory?.currentEntry) return;
    const places = {};
    for (const [name, save] of keepers) {
      try { places[name] = save(); } catch { /* that one is not kept */ }
    }
    keepAt(sessionHistory.currentEntry, { name: pageName(), places });
  });
  // A page restored as it was left (the back-forward cache) would show what
  // has changed since as it was: drawn again instead.
  window.addEventListener("pageshow", (e) => { if (e.persisted) location.reload(); });

  const goBack = () => {
    if (before()) sessionHistory.back();
  };
  // Its key (Alt+Left), where the page has no use of its own for it (a
  // sheet moves its bars with it: keys.js lets the page go first), and the
  // mouse's back button. Forward has a key of its own.
  window.Keys.handle("app.back", goBack, () => !!before());
  window.Keys.handle("app.forward", () => sessionHistory.forward(), () => !!sessionHistory?.canGoForward);
  window.addEventListener("mouseup", (e) => {
    if (e.button !== 3 || !before()) return;
    e.preventDefault();
    goBack();
  });

  const back = document.querySelector("[data-back]");
  if (back) {
    const to = before();
    const label = to?.name ? `Back to ${to.name}` : "Back";
    back.disabled = !to;
    back.querySelector("[data-back-label]").textContent = label;
    back.title = to ? window.Keys.title(label, "app.back") : "Nothing to go back to";
    back.addEventListener("click", goBack);
  }

  // A page's own "‹" link names where it goes; when that is the page
  // before, it goes back there, as it was left.
  const isBefore = (href) => {
    const to = before();
    if (!to) return false;
    const url = new URL(href, location.href);
    return url.origin === to.url.origin && url.pathname === to.url.pathname && (!url.search || url.search === to.url.search);
  };
  document.addEventListener("click", (e) => {
    const link = e.target.closest?.("a.page-back");
    if (!link || e.button !== 0 || e.ctrlKey || e.metaKey || e.shiftKey || e.altKey) return;
    if (!isBefore(link.href)) return;
    e.preventDefault();
    goBack();
  });
  // So does the server's way out of a page whose thing is gone (a task
  // deleted on its own page goes back to where it was opened from).
  document.addEventListener("htmx:beforeOnLoad", (e) => {
    const to = e.detail.xhr?.getResponseHeader("HX-Redirect");
    if (!to || !isBefore(to)) return;
    e.preventDefault();
    goBack();
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

  /* ---- a ruled sheet's row numbers (app.css, "ruled sheets") ---- */

  // Chrome can leave the numbers after a part of a sheet that was swapped
  // in as they were, counting the rows it replaced, when the same answer
  // also swaps something out of band; counting the sheet afresh puts them right.
  document.addEventListener("htmx:afterSettle", (e) => {
    const sheet = e.detail.elt.closest?.(".ruled-sheet");
    if (!sheet) return;
    sheet.style.counterReset = "none";
    void sheet.offsetHeight;
    sheet.style.counterReset = "";
  });

  /* ---- the phone's tab bar scrolls sideways once it holds more tabs than
     fit, and the desktop's rail down once it holds more pages and projects
     than fit: it opens on the current page's tab, and marks the edges that
     have more past them (data-more), which fade ---- */
  const nav = document.querySelector(".nav");
  if (nav) {
    const markMore = () => {
      const more = [];
      if (nav.scrollLeft > 1) more.push("start");
      if (nav.scrollLeft + nav.clientWidth < nav.scrollWidth - 1) more.push("end");
      if (nav.scrollTop > 1) more.push("top");
      if (nav.scrollTop + nav.clientHeight < nav.scrollHeight - 1) more.push("bottom");
      if (more.length) nav.dataset.more = more.join(" ");
      else delete nav.dataset.more;
    };
    // On a project's Gantt, Projects' tab (its projects are not in the bar).
    const current = nav.querySelector('a[aria-current="page"], a[aria-current="true"]');
    if (current && nav.scrollWidth > nav.clientWidth) {
      const middle = current.offsetLeft - nav.offsetLeft + current.offsetWidth / 2;
      nav.scrollLeft = middle - nav.clientWidth / 2;
    }
    markMore();
    nav.addEventListener("scroll", markMore, { passive: true });
    window.addEventListener("resize", markMore);
    // Folding the projects away, or the list drawn again, changes its height.
    const projects = nav.querySelector(".nav-sub")?.parentElement;
    if (projects) new ResizeObserver(markMore).observe(projects);
  }

  /* ---- the desktop app (app/desktop): its title bar in the page's paper
     and ink, titled as the page is, and the nudges counted again on its
     taskbar button as one is dismissed. Its tray's New task opens the
     capture window over the page (openCapture), else here as
     /today?capture=1. ---- */

  window.openCapture = openCapture;
  const arrival = new URL(location.href);
  if (arrival.searchParams.has("capture")) {
    arrival.searchParams.delete("capture");
    history.replaceState(history.state, "", arrival);
    document.addEventListener("DOMContentLoaded", openCapture);
  }

  const desktop = () => window.pywebview?.api;
  paintTitleBar = () => {
    const style = getComputedStyle(root);
    desktop()?.title_bar(
      style.getPropertyValue("--paper").trim(), style.getPropertyValue("--ink").trim(), isDark(), document.title,
    );
  };
  // pywebview's bridge usually comes in after this script has run.
  if (desktop()?.title_bar) paintTitleBar();
  else window.addEventListener("pywebviewready", paintTitleBar);
  document.addEventListener("htmx:afterRequest", (e) => {
    if (/\/ui\/nudges\/\d+\/dismiss$/.test(e.detail.pathInfo?.requestPath ?? "")) desktop()?.nudges_changed();
  });
})();
