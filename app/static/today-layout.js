/* Today's panes (app/services/today_layout.py), in three columns: each
   dragged by its title bar to another place in its column or another
   column (with a column not showing, a zone at its edge makes it), or, its
   grip in focus, moved by the arrow keys; hidden by its eye (Undo on the
   toast) and shown again from Panes, at the day's header, which also sets
   them back as they were. The page changes at once, and the server keeps
   the layout, on every device. The side columns fold away by their buttons
   (Alt+P, Ctrl+\), a fold this browser's, kept with the page's other folds
   in the today_folded cookie (read as the page is drawn). */
(() => {
  const body = document.querySelector(".today-body");

  /* ---- the folds: the plan's groups and the habits (notepad.js), the side
     columns (here); those folded are kept in a cookie, the page drawn so ---- */

  const FOLDED = "today_folded";
  const folds = {
    get: () => new Set((document.cookie.split("; ").find((c) => c.startsWith(`${FOLDED}=`)) || "")
      .slice(FOLDED.length + 1).split(".").filter(Boolean)),
    set(name, folded) {
      const names = folds.get();
      if (folded) names.add(name);
      else names.delete(name);
      document.cookie = `${FOLDED}=${[...names].join(".")}; path=/; max-age=31536000; samesite=strict`;
    },
  };
  window.TodayFolds = folds;
  if (!body) return;

  const COLUMNS = ["left", "center", "right"];
  const columns = () => COLUMNS.map((key) => body.querySelector(`.today-col[data-col="${key}"]`));
  const panesOf = (column) => [...column.querySelectorAll(":scope > .today-pane")];
  const shownIn = (column) => panesOf(column).filter((p) => !p.hidden);
  const allPanes = () => columns().flatMap(panesOf);
  const label = (pane) => pane.querySelector(".pane-head h2, .pane-head .today-fold-label").textContent.trim();

  /* ---- the page drawn as the panes now stand ---- */

  // A side column's panes showing, in words: "Plan and Habits".
  const named = (column) => {
    const names = shownIn(column).map(label);
    return names.length > 1 ? `${names.slice(0, -1).join(", ")} and ${names.at(-1)}` : names[0] || "";
  };
  const showing = (column) => shownIn(column).length && !folds.get().has(column.dataset.col);
  const draw = () => {
    body.dataset.cols = columns().filter(showing).map((c) => c.dataset.col[0]).join("");
    for (const button of document.querySelectorAll("[data-fold-col]")) {
      const side = button.dataset.foldCol;
      const column = body.querySelector(`.today-col[data-col="${side}"]`);
      const folded = folds.get().has(side);
      const words = folded ? `Show ${named(column)}` : `Fold ${named(column)} away`;
      button.hidden = !shownIn(column).length;
      button.setAttribute("aria-pressed", String(folded));
      button.setAttribute("aria-label", words);
      button.title = window.Keys.title(words, side === "left" ? "today.plan" : "today.timeline");
    }
    // The notes measure their rows again, in their new width.
    document.dispatchEvent(new CustomEvent("density:change"));
  };

  // One save after another, so the server keeps the last state, not
  // whichever of two quick moves' saves landed last.
  let saving = Promise.resolve();
  const save = () => (saving = saving.then(() =>
    fetch("/ui/today/layout", {
      method: "PUT",
      headers: { "Content-Type": "application/json", "X-CSRF": window.csrfToken() },
      body: JSON.stringify({
        columns: columns().map((c) => panesOf(c).map((p) => p.dataset.pane)),
        hidden: allPanes().filter((p) => p.hidden).map((p) => p.dataset.pane),
      }),
    })
      .then((res) => { if (!res.ok) throw new Error(res.statusText); })
      .catch(() => window.toast("Could not save Today's panes. Try again?"))));

  // The panes moved slide from where they were (FLIP); with reduced motion,
  // they are just there. What scrolled inside a pane moved to another
  // column keeps its place (a node moved forgets it).
  const still = matchMedia("(prefers-reduced-motion: reduce)");
  const rearrange = (place) => {
    const panes = allPanes().filter((p) => !p.hidden);
    const before = new Map(panes.map((p) => [p, p.getBoundingClientRect()]));
    const scrolled = panes.flatMap((p) => [...p.querySelectorAll("*")].filter((el) => el.scrollTop))
      .map((el) => [el, el.scrollTop]);
    place();
    draw();
    for (const [el, top] of scrolled) el.scrollTop = top;
    if (still.matches) return;
    for (const p of panes) {
      const was = before.get(p), now = p.getBoundingClientRect();
      if (!now.width || (was.left === now.left && was.top === now.top)) continue;
      p.animate([{ translate: `${was.left - now.left}px ${was.top - now.top}px` }, { translate: "0 0" }],
        { duration: 160, easing: "ease-out" });
    }
  };
  // A pane into a column, before another (or at its end): a folded column
  // opens to show it.
  const put = (pane, column, before) => {
    column.insertBefore(pane, before);
    folds.set(column.dataset.col, false);
  };

  /* ---- hidden and shown again ---- */

  const setHidden = (pane, hidden) => {
    rearrange(() => {
      pane.hidden = hidden;
      if (!hidden) folds.set(pane.parentElement.dataset.col, false);
    });
    save();
  };
  document.addEventListener("click", (e) => {
    const eye = e.target.closest("[data-pane-hide]");
    if (!eye) return;
    // In the habits' title bar, the eye is not a click on the fold.
    e.preventDefault();
    const pane = eye.closest(".today-pane");
    setHidden(pane, true);
    if (!e.detail) document.querySelector(".panes-open").focus();
    window.toast(`${label(pane)} hidden. Panes, at the day's header, shows it again.`,
      { action: "Undo", run: () => setHidden(pane, false) });
  });

  /* ---- the column folds ---- */

  document.addEventListener("click", (e) => {
    const button = e.target.closest("[data-fold-col]");
    if (!button) return;
    const side = button.dataset.foldCol;
    folds.set(side, !folds.get().has(side));
    draw();
  });

  /* ---- Panes: each ticked while shown, and the panes as they were ---- */

  const TICK = '<svg class="tick" viewBox="0 0 20 20" aria-hidden="true"><path d="M4.5 10.5l3.5 3.5 7.5-8"/></svg>';
  const opener = document.querySelector(".panes-open");
  let menu = null; // {el}
  const closeMenu = (restore = true) => {
    if (!menu) return;
    menu.el.remove();
    menu = null;
    opener.setAttribute("aria-expanded", "false");
    if (restore) opener.focus();
  };
  const tick = (item, checked) => {
    item.setAttribute("aria-checked", String(checked));
    item.querySelector(".tick")?.remove();
    if (checked) item.insertAdjacentHTML("beforeend", TICK);
  };
  const openMenu = () => {
    const el = document.createElement("div");
    el.className = "sheet-menu panes-menu";
    el.setAttribute("role", "menu");
    el.setAttribute("aria-label", "Panes");
    const item = (role, text) => {
      const button = document.createElement("button");
      button.type = "button";
      button.tabIndex = -1;
      button.setAttribute("role", role);
      button.innerHTML = '<span class="label"></span>';
      button.querySelector(".label").textContent = text;
      el.append(button);
      return button;
    };
    // In the order the code lists them, wherever they are.
    const order = JSON.parse(body.dataset.defaultCols).flat();
    for (const pane of allPanes().sort((x, y) => order.indexOf(x.dataset.pane) - order.indexOf(y.dataset.pane))) {
      const button = item("menuitemcheckbox", label(pane));
      button.dataset.pane = pane.dataset.pane;
      tick(button, !pane.hidden);
    }
    item("menuitem", "Set them back as they were").classList.add("sep", "panes-reset");
    document.body.append(el);
    const at = opener.getBoundingClientRect();
    el.style.top = `${at.bottom + 4}px`;
    el.style.left = `${Math.max(8, Math.min(at.right - el.offsetWidth, window.innerWidth - el.offsetWidth - 8))}px`;
    opener.setAttribute("aria-expanded", "true");
    menu = { el };
    el.firstElementChild.focus();
  };

  // As they were: the code's columns, every pane showing, no column folded.
  // The toast offers the layout before back.
  const reset = () => {
    const was = { columns: columns().map(panesOf), hidden: allPanes().filter((p) => p.hidden), folded: folds.get() };
    const apply = (cols, hidden, folded) => {
      rearrange(() => {
        cols.forEach((panes, i) => panes.forEach((p) => columns()[i].append(p)));
        for (const p of allPanes()) p.hidden = hidden.includes(p);
        for (const side of ["left", "right"]) folds.set(side, folded.has(side));
      });
      save();
    };
    const byKey = Object.fromEntries(allPanes().map((p) => [p.dataset.pane, p]));
    apply(JSON.parse(body.dataset.defaultCols).map((keys) => keys.map((k) => byKey[k])), [], new Set());
    window.toast("Today's panes are back as they were.", {
      action: "Undo", run: () => apply(was.columns, was.hidden, was.folded),
    });
  };
  const choose = (item) => {
    if (item.classList.contains("panes-reset")) {
      closeMenu();
      reset();
      return;
    }
    const pane = allPanes().find((p) => p.dataset.pane === item.dataset.pane);
    setHidden(pane, !pane.hidden);
    tick(item, !pane.hidden);
  };

  opener.addEventListener("click", () => (menu ? closeMenu() : openMenu()));
  document.addEventListener("click", (e) => {
    if (!menu || e.target.closest?.(".panes-open")) return;
    const item = e.target.closest?.(".panes-menu [role^='menuitem']");
    if (item && menu.el.contains(item)) choose(item);
    else if (!menu.el.contains(e.target)) closeMenu(false);
  });
  document.addEventListener("keydown", (e) => {
    if (!menu || !menu.el.contains(e.target)) return;
    const items = [...menu.el.querySelectorAll("[role^='menuitem']")];
    const at = items.indexOf(e.target.closest("[role^='menuitem']"));
    const handled = () => { e.preventDefault(); e.stopPropagation(); };
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      handled();
      items[(at + (e.key === "ArrowDown" ? 1 : -1) + items.length) % items.length].focus();
    } else if (e.key === "Home" || e.key === "End") {
      handled();
      items[e.key === "Home" ? 0 : items.length - 1].focus();
    } else if (e.key === "Enter" || e.key === " ") {
      handled();
      choose(items[at]);
    } else if (e.key === "Escape" || (e.key === "Tab" && !e.ctrlKey)) {
      handled();
      closeMenu();
    } else if (e.key !== "Tab") {
      e.stopPropagation(); // the page's own keys stay out of the menu
    }
  }, true);
  window.addEventListener("resize", () => closeMenu(false));

  /* ---- the keyboard: a grip in focus moves its pane up and down its
     column, and to the column beside it, at the same place in it; Delete
     hides it ---- */

  body.addEventListener("keydown", (e) => {
    const grip = e.target.closest("[data-pane-grip]");
    if (!grip || e.altKey || e.ctrlKey || e.metaKey || e.shiftKey || e.isComposing) return;
    const pane = grip.closest(".today-pane");
    if (e.key === "Delete" || e.key === "Backspace") {
      e.preventDefault();
      pane.querySelector("[data-pane-hide]").click();
      return;
    }
    const column = pane.parentElement;
    const shown = shownIn(column);
    const at = shown.indexOf(pane);
    let place = null;
    if (e.key === "ArrowUp" && at > 0) place = () => column.insertBefore(pane, shown[at - 1]);
    else if (e.key === "ArrowDown" && at < shown.length - 1) place = () => shown[at + 1].after(pane);
    else if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
      const to = columns()[COLUMNS.indexOf(column.dataset.col) + (e.key === "ArrowLeft" ? -1 : 1)];
      if (to) place = () => put(pane, to, shownIn(to)[at] || null);
    } else if (!["ArrowUp", "ArrowDown"].includes(e.key)) return;
    // At an end, the key does nothing else (not the day before or after).
    e.preventDefault();
    if (!place) return;
    rearrange(place);
    grip.focus();
    save();
  });

  /* ---- the pointer: a press on a title bar that moves 5px picks its pane
     up; let go, it lands where the spark line (or the zone lit) says, and
     the click it would have made is not one. Esc puts it back. ---- */

  let drag = null;
  const phone = matchMedia("(max-width: 720px)");
  body.addEventListener("pointerdown", (e) => {
    if (e.button !== 0 || phone.matches) return;
    const head = e.target.closest(".today-pane .pane-head");
    if (!head || head.closest(".today-pane").parentElement.parentElement !== body) return;
    if (e.target.closest("button, a, input, [data-md-modes]") && !e.target.closest("[data-pane-grip]")) return;
    drag = { pane: head.closest(".today-pane"), id: e.pointerId, x: e.clientX, y: e.clientY, started: false };
  });

  // Each column not showing gets a zone at its place: those before the
  // first column showing at the left edge, those after the last at the
  // right, the middle between the two sides.
  const ZONE = 96;
  const zonesFor = () => {
    const box = body.getBoundingClientRect();
    const shown = columns().map((c) => (showing(c) ? c.getBoundingClientRect() : null));
    const zones = [];
    const first = shown.findIndex(Boolean);
    const last = shown.findLastIndex(Boolean);
    columns().forEach((column, i) => {
      if (shown[i]) return;
      let left;
      if (i < first) left = i * (ZONE + 8);
      else if (i > last) left = box.width - (COLUMNS.length - i) * (ZONE + 8) + 8;
      else left = (shown[i - 1].right + shown[i + 1].left) / 2 - box.left - ZONE / 2;
      const el = document.createElement("div");
      el.className = "pane-drop-zone";
      el.textContent = "A column here";
      el.style.left = `${left}px`;
      body.append(el);
      zones.push({ el, column });
    });
    return zones;
  };

  // Where the pointer would land it: a zone it is in, else the column
  // showing nearest it, before the first pane there whose middle is under
  // the pointer.
  const landing = (x, y) => {
    const zone = drag.zones.find((z) => {
      const r = z.el.getBoundingClientRect();
      return x >= r.left && x <= r.right && y >= r.top && y <= r.bottom;
    });
    if (zone) return { column: zone.column, before: null, zone };
    const away = (r) => Math.hypot(Math.max(r.left - x, 0, x - r.right), Math.max(r.top - y, 0, y - r.bottom));
    const column = columns().filter(showing)
      .sort((a, b) => away(a.getBoundingClientRect()) - away(b.getBoundingClientRect()))[0];
    const others = shownIn(column).filter((p) => p !== drag.pane);
    const before = others.find((p) => { const r = p.getBoundingClientRect(); return y < r.top + r.height / 2; }) || null;
    return { column, before, others };
  };
  // Landing where it is already moves nothing.
  const inPlace = (pane, to) => {
    if (to.zone || to.column !== pane.parentElement) return false;
    const shown = shownIn(to.column);
    return (shown[shown.indexOf(pane) + 1] || null) === to.before;
  };
  const mark = (to) => {
    for (const z of drag.zones) z.el.classList.toggle("is-over", z === to.zone);
    const line = drag.line;
    line.hidden = !!to.zone || inPlace(drag.pane, to);
    if (line.hidden) return;
    const box = body.getBoundingClientRect();
    const col = to.column.getBoundingClientRect();
    const gap = parseFloat(getComputedStyle(to.column).rowGap) || 0;
    let y;
    if (to.before) y = to.before.getBoundingClientRect().top - gap / 2;
    else if (to.others.length) y = to.others.at(-1).getBoundingClientRect().bottom + gap / 2;
    else y = col.top;
    line.style.top = `${y - box.top}px`;
    line.style.left = `${col.left - box.left}px`;
    line.style.width = `${col.width}px`;
  };

  const start = () => {
    drag.started = true;
    getSelection()?.removeAllRanges();
    drag.pane.classList.add("is-dragging");
    body.dataset.dragging = "";
    drag.lift = document.createElement("div");
    drag.lift.className = "pane-lift";
    drag.lift.textContent = label(drag.pane);
    document.body.append(drag.lift);
    drag.line = document.createElement("div");
    drag.line.className = "pane-drop-line";
    drag.line.hidden = true;
    body.append(drag.line);
    drag.zones = zonesFor();
  };
  const finish = (cancelled) => {
    const d = drag;
    drag = null;
    if (!d?.started) return;
    d.lift.remove();
    d.line.remove();
    for (const z of d.zones) z.el.remove();
    d.pane.classList.remove("is-dragging");
    delete body.dataset.dragging;
    // The click the title bar would get from this press is the drop (the
    // habits' would fold them).
    const swallow = (ev) => { ev.preventDefault(); ev.stopPropagation(); };
    window.addEventListener("click", swallow, { capture: true, once: true });
    setTimeout(() => window.removeEventListener("click", swallow, { capture: true }));
    if (cancelled || !d.to || inPlace(d.pane, d.to)) return;
    rearrange(() => put(d.pane, d.to.column, d.to.before));
    save();
  };

  document.addEventListener("pointermove", (e) => {
    if (!drag || e.pointerId !== drag.id) return;
    if (!drag.started) {
      if (Math.hypot(e.clientX - drag.x, e.clientY - drag.y) < 5) return;
      start();
    }
    e.preventDefault();
    // Its name beside the pointer, on the side the window has room on.
    const { offsetWidth: w, offsetHeight: h } = drag.lift;
    drag.lift.style.left = `${e.clientX + 14 + w + 8 <= innerWidth ? e.clientX + 14 : e.clientX - 14 - w}px`;
    drag.lift.style.top = `${Math.min(e.clientY + 10, innerHeight - h - 8)}px`;
    drag.to = landing(e.clientX, e.clientY);
    mark(drag.to);
  });
  document.addEventListener("pointerup", (e) => { if (drag && e.pointerId === drag.id) finish(false); });
  document.addEventListener("pointercancel", (e) => { if (drag && e.pointerId === drag.id) finish(true); });
  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape" || !drag?.started) return;
    e.preventDefault();
    e.stopPropagation();
    finish(true);
  }, true);
})();
