/* Moving between panes (Ctrl+Alt+arrows, keys.py's pane.*): each region
   marked data-nav-pane is a pane (Today's, a task's map and page, the
   sidebar at the left, the agent window and a task's panes at the right,
   else the page between them), unless it holds panes of its own. The key
   goes to the pane showing nearest in its direction, of those as near the
   one the focus was in last, and the focus to where it was in it; else to
   what the attribute names (the notes' editor, the agent's message), else
   to its first control, else to the pane itself. Its edge, lit a moment,
   says where the focus went. */
(() => {
  const PANES = "[data-nav-pane]";
  const CONTROLS = [
    "a[href]", "button:not(:disabled)", "input:not(:disabled):not([type=hidden])",
    "select:not(:disabled)", "textarea:not(:disabled)", "summary", "[contenteditable=true]",
    "[tabindex]:not([tabindex='-1'])",
  ].join(", ");
  // A pane's grip moves it and its eye hides it: never where the focus lands.
  const HANDLES = "[data-pane-grip], [data-pane-hide]";
  const HEADS = ".pane-head, .side-head";

  const showing = (el) => el.isConnected && !el.closest("[inert]")
    && el.checkVisibility({ visibilityProperty: true }) && el.getClientRects().length > 0;
  const isPane = (el) => !el.querySelector(PANES);
  const panes = () => [...document.querySelectorAll(PANES)].filter((p) => isPane(p) && showing(p));
  const paneOf = (el) => {
    const pane = el?.closest?.(PANES);
    return pane && isPane(pane) ? pane : null;
  };

  /* ---- where the focus was in each pane, and the panes it was in last ---- */

  const was = new WeakMap(); // pane -> the element focused in it last
  let visited = []; // the panes, the one the focus was in last first
  const visit = (pane) => { visited = [pane, ...visited.filter((p) => p !== pane && p.isConnected)]; };
  document.addEventListener("focusin", (e) => {
    const pane = paneOf(e.target);
    if (!pane) return;
    if (e.target !== pane) was.set(pane, e.target);
    visit(pane);
  });
  // A click in a pane, on nothing that takes the focus, is in it too.
  document.addEventListener("pointerdown", (e) => {
    const pane = paneOf(e.target);
    if (pane) visit(pane);
  }, true);

  /* ---- the pane nearest in a direction ---- */

  // How far a box is past another, in the direction, and how far off to
  // the side (0 while they overlap across it). One over another (the
  // sidebar floating over a narrow window) is that way if it reaches
  // further.
  const AXES = {
    left: { past: (f, c) => f.left - c.right, beyond: (f, c) => c.left < f.left - 2, across: "y" },
    right: { past: (f, c) => c.left - f.right, beyond: (f, c) => c.right > f.right + 2, across: "y" },
    up: { past: (f, c) => f.top - c.bottom, beyond: (f, c) => c.top < f.top - 2, across: "x" },
    down: { past: (f, c) => c.top - f.bottom, beyond: (f, c) => c.bottom > f.bottom + 2, across: "x" },
  };
  const aside = (f, c, across) => {
    const [lo, hi] = across === "y" ? ["top", "bottom"] : ["left", "right"];
    const overlap = Math.min(f[hi], c[hi]) - Math.max(f[lo], c[lo]);
    return overlap > 0 ? 0 : -overlap;
  };
  // Panes this much nearer than another are as near: a column's panes,
  // from the pane beside them.
  const AS_NEAR = 24;

  // Where the key starts from: the focus's pane, else the pane clicked or
  // focused last, else what has the focus, else the window's far edge.
  const origin = (dir) => {
    const active = document.activeElement;
    const pane = paneOf(active) || (active === document.body || !active ? visited.find(showing) : null);
    if (pane) return { pane, box: pane.getBoundingClientRect() };
    if (active && active !== document.body) return { pane: null, box: active.getBoundingClientRect() };
    const w = innerWidth, h = innerHeight;
    const edge = { left: [w, w, 0, h], right: [0, 0, 0, h], up: [0, w, h, h], down: [0, w, 0, 0] }[dir];
    const [left, right, top, bottom] = edge;
    return { pane: null, box: { left, right, top, bottom } };
  };

  const nearest = (dir) => {
    const { pane: from, box: f } = origin(dir);
    const axis = AXES[dir];
    const scored = panes().filter((p) => p !== from).map((pane) => {
      const c = pane.getBoundingClientRect();
      const past = axis.past(f, c);
      const off = aside(f, c, axis.across);
      if (past < -2 && (off > 0 || !axis.beyond(f, c))) return null;
      return { pane, c, off, score: Math.max(past, 0) + 2 * off };
    }).filter(Boolean);
    if (!scored.length) return null;
    const best = scored.reduce((a, b) => (b.score < a.score ? b : a));
    const rank = (pane) => { const i = visited.indexOf(pane); return i < 0 ? Infinity : i; };
    return scored.filter((s) => s.score <= best.score + AS_NEAR && (s.off === 0 || best.off > 0))
      .sort((a, b) => rank(a.pane) - rank(b.pane) || a.c.top - b.c.top || a.c.left - b.c.left)[0].pane;
  };

  /* ---- the focus into it ---- */

  const first = (pane, selector, keep = () => true) =>
    [...pane.querySelectorAll(selector)].find((el) => keep(el) && showing(el)) || null;
  const target = (pane) => {
    const before = was.get(pane);
    if (before && pane.contains(before) && showing(before) && !before.disabled) return before;
    const named = pane.dataset.navPane;
    return (named && first(pane, named))
      || first(pane, CONTROLS, (el) => !el.closest(HEADS))
      || first(pane, CONTROLS, (el) => !el.matches(HANDLES))
      || pane;
  };

  // The pane itself in focus is ringed while it is: not lit as well.
  const light = (pane, lit) => {
    for (const was of document.querySelectorAll(".is-lit[data-nav-pane]")) was.classList.remove("is-lit");
    if (!lit) return;
    void pane.offsetWidth; // the animation again, from its start
    pane.classList.add("is-lit");
  };
  document.addEventListener("animationend", (e) => {
    if (e.animationName === "pane-lit") e.target.classList.remove("is-lit");
  });

  const go = (dir) => {
    const pane = nearest(dir);
    if (!pane) return; // none that way: the key does nothing else
    const el = target(pane);
    if (el === pane && !pane.hasAttribute("tabindex")) pane.tabIndex = -1;
    el.focus({ preventScroll: true, focusVisible: true });
    // An editor keeps its own scroll, its caret where it was left.
    if (!el.isContentEditable) el.scrollIntoView({ block: "nearest", inline: "nearest" });
    visit(pane);
    light(pane, el !== pane);
  };

  for (const dir of Object.keys(AXES)) {
    window.Keys.handle(`pane.${dir}`, () => go(dir), () => panes().length > 1);
  }
})();
