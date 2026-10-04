/* The app's keys (app/services/keys.py): every action's keys as this page
   was drawn with them (#keymap), the keys Oscar chose over the defaults
   among them. A page's own script asks Keys.is(e, "task.done") of a key
   it has the context for (a list's cursor, a sheet's cell); the actions
   that need none (click the page's button, focus its field, go to a page,
   or a handler a script hands over with Keys.handle) are done here, by the
   one listener on the window, after every page's own: a key a page took
   is the page's. Single keys never fire while typing, nor anything over a
   dialog. */

(() => {
  let actions = {};
  const load = (map) => {
    actions = map || {};
    parsed.clear();
  };

  /* ---- a key, as keys.py writes it: "Ctrl+Alt+Shift+K" ---- */

  const parsed = new Map();
  const parse = (combo) => {
    if (!parsed.has(combo)) {
      const parts = combo === "+" ? ["+"] : combo.split(/\+(?!$)/);
      const key = parts.pop();
      parsed.set(combo, {
        ctrl: parts.includes("Ctrl"), alt: parts.includes("Alt"), shift: parts.includes("Shift"), key,
      });
    }
    return parsed.get(combo);
  };

  const LETTER = /^[A-Z]$/;
  const DIGIT = /^[0-9]$/;
  // A character typed with Shift ("?", "!") has its Shift in it: not checked.
  const matches = (e, combo) => {
    const k = parse(combo);
    if ((e.ctrlKey || e.metaKey) !== k.ctrl || e.altKey !== k.alt) return false;
    const character = k.key.length === 1 && !LETTER.test(k.key) && !DIGIT.test(k.key);
    if (character) return e.key === k.key;
    if (e.shiftKey !== k.shift) return false;
    if (k.key === "Space") return e.key === " ";
    // The key, not its character where a modifier changes it: on a Mac,
    // Alt+1 types "¡", and Alt+W "∑"; a digit by its place on any layout.
    if (DIGIT.test(k.key)) return e.key === k.key || e.code === `Digit${k.key}`;
    if (LETTER.test(k.key)) {
      const ch = (e.key || "").toUpperCase();
      if (ch === k.key) return true;
      return !/^[A-Z]$/.test(ch) && (e.altKey || e.ctrlKey || e.metaKey) && e.code === `Key${k.key}`;
    }
    return e.key === k.key;
  };

  const keysOf = (id) => actions[id]?.keys || [];
  const is = (e, id) => keysOf(id).some((combo) => matches(e, combo));

  const SHOWN = {
    ArrowUp: "↑", ArrowDown: "↓", ArrowLeft: "←", ArrowRight: "→",
    Escape: "Esc", PageUp: "PgUp", PageDown: "PgDn",
  };
  const parts = (combo) => (combo === "+" ? ["+"] : combo.split(/\+(?!$)/)).map((p) => SHOWN[p] || p);
  // Its first key in words, "Ctrl+K", or "" with none.
  const text = (id) => (keysOf(id)[0] ? parts(keysOf(id)[0]).join("+") : "");
  const title = (words, id) => (text(id) ? `${words} (${text(id)})` : words);
  // For aria-keyshortcuts: each key, space-separated.
  const aria = (id) => keysOf(id).map((combo) => combo.replace(/^Ctrl\+/, "Control+")).join(" ");
  // As CodeMirror writes them: "Mod-Shift-x".
  const cm = (id) => keysOf(id).map((combo) => {
    const k = parse(combo);
    const key = LETTER.test(k.key) ? k.key.toLowerCase() : k.key;
    return [k.ctrl && "Mod", k.alt && "Alt", k.shift && "Shift", key].filter(Boolean).join("-");
  });

  /* ---- doing an action ---- */

  const handlers = new Map(); // id -> {run, when}
  const handle = (id, run, when = null) => handlers.set(id, { run, when });

  // The page's element for it: the first one showing, else the first.
  const element = (selector) => {
    if (!selector) return null;
    const all = [...document.querySelectorAll(selector)];
    return all.find((el) => el.checkVisibility?.() ?? true) || all[0] || null;
  };
  const available = (id) => {
    const a = actions[id];
    if (!a) return false;
    const h = handlers.get(id);
    if (h) return !h.when || h.when();
    const el = element(a.click || a.focus);
    if (el) return !el.disabled;
    return !!a.go;
  };

  // Done (true), or nothing here to do it on (false).
  const run = (id, e = null) => {
    const a = actions[id];
    if (!a) return false;
    const h = handlers.get(id);
    if (h) return (!h.when || h.when()) && h.run(e) !== false;
    const clicked = element(a.click);
    if (clicked) {
      if (clicked.disabled) return false;
      // The page it goes to is the one showing: nothing to do, but the key's.
      if (!clicked.matches("[aria-current]")) clicked.click();
      return true;
    }
    const focused = element(a.focus);
    if (focused) {
      focused.focus();
      focused.scrollIntoView({ block: "nearest" });
      return true;
    }
    if (a.go) {
      window.location.href = a.go;
      return true;
    }
    return false;
  };

  /* ---- the one listener ---- */

  const TYPING = "input, textarea, select, [contenteditable]";
  // An action of the page's own (a scope of its own) before one that works anywhere.
  const LAST = new Set(["anywhere", "go"]);
  const ordered = () => Object.keys(actions).sort((a, b) =>
    Number(LAST.has(actions[a].scope)) - Number(LAST.has(actions[b].scope)));
  let paused = false;

  window.addEventListener("keydown", (e) => {
    if (paused || e.defaultPrevented || e.isComposing || /^(Control|Alt|Shift|Meta)$/.test(e.key)) return;
    if (document.querySelector("dialog[open]")) return;
    const single = !e.ctrlKey && !e.metaKey && !e.altKey;
    if (single && e.target.closest?.(TYPING)) return;
    for (const id of ordered()) {
      if (!is(e, id) || !run(id, e)) continue;
      e.preventDefault();
      return;
    }
  });

  load(JSON.parse(document.getElementById("keymap")?.textContent || "{}"));

  window.Keys = {
    is, text, title, aria, cm, parts, handle, run, available, load,
    keys: keysOf,
    get actions() { return actions; },
    // While Keyboard records a key, no key does anything else.
    pause(on) { paused = on; },
  };
})();
