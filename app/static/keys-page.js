/* Keyboard (keys.html): an action's + takes the next key pressed (Esc lets
   it go), × takes a key away, Default puts an action's back, and the foot
   puts every key back. Each change is kept by the server in keys.toml
   (PUT or DELETE /ui/keys/<action>), the list drawn again from it, and the
   new keys loaded into keys.js, so they work at once. The field above
   finds an action by its name, its id or its keys. */

(() => {
  const list = document.getElementById("keys-list");
  if (!list) return;
  const find = document.querySelector("[data-keys-find]");

  /* ---- a key pressed, written as keys.py writes it ---- */

  const NAMED = new Set([
    "ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight", "Enter", "Escape", "Tab", "Backspace",
    "Delete", "Insert", "Home", "End", "PageUp", "PageDown",
    ...Array.from({ length: 12 }, (_, i) => `F${i + 1}`),
  ]);
  const combo = (e) => {
    let key;
    if (e.key === " ") key = "Space";
    else if (NAMED.has(e.key)) key = e.key;
    // Where a modifier makes the key another character (Alt on a Mac), its place.
    else if (/^Key[A-Z]$/.test(e.code) && !/^[a-z]$/i.test(e.key)) key = e.code.slice(3);
    else if (/^Digit[0-9]$/.test(e.code) && (e.altKey || e.ctrlKey || e.metaKey)) key = e.code.slice(5);
    else if (e.key.length === 1) key = e.key.toUpperCase();
    else return null;
    const character = key.length === 1 && !/[A-Z0-9]/.test(key);
    return [
      (e.ctrlKey || e.metaKey) && "Ctrl", e.altKey && "Alt", e.shiftKey && !character && "Shift", key,
    ].filter(Boolean).join("+");
  };

  /* ---- the server keeps them; the list is drawn again ---- */

  const failure = async (res) => {
    try { return (await res.json()).detail; } catch { return "Could not keep that key. Try again?"; }
  };
  const redraw = async (focusOn) => {
    const res = await fetch("/ui/keys/list");
    if (!res.ok) return;
    list.innerHTML = await res.text();
    const map = list.querySelector("[data-keymap]");
    if (map) window.Keys.load(JSON.parse(map.textContent));
    filter();
    if (focusOn) list.querySelector(`[data-action="${CSS.escape(focusOn)}"] [data-record]`)?.focus();
  };
  const send = async (method, url, body, focusOn) => {
    const res = await fetch(url, {
      method,
      headers: { "Content-Type": "application/json", "X-CSRF": window.csrfToken() },
      body: body ? JSON.stringify(body) : undefined,
    }).catch(() => null);
    if (!res) { window.toast("Could not reach the app. Try again?"); return; }
    if (!res.ok) { window.toast(await failure(res)); return; }
    await redraw(focusOn);
  };
  const keysOf = (row) => JSON.parse(row.dataset.keys || "[]");
  const setKeys = (row, keys) => send("PUT", `/ui/keys/${encodeURIComponent(row.dataset.action)}`, { keys }, row.dataset.action);

  /* ---- recording: the next key pressed, and nothing else hears it ---- */

  let recording = null; // {row, button}
  const stopRecording = () => {
    if (!recording) return;
    const { row, button } = recording;
    recording = null;
    window.Keys.pause(false);
    row.classList.remove("is-recording");
    button.textContent = "+";
    button.setAttribute("aria-label", `Add a key to ${row.querySelector(".keys-label").firstChild.textContent.trim()}`);
  };
  const record = (row) => {
    stopRecording();
    const button = row.querySelector("[data-record]");
    recording = { row, button };
    window.Keys.pause(true);
    row.classList.add("is-recording");
    button.textContent = "Press a key…";
    button.setAttribute("aria-label", "Press the new key, or Esc to let it go");
    button.focus();
  };
  window.addEventListener("keydown", (e) => {
    if (!recording || e.isComposing) return;
    e.preventDefault();
    e.stopImmediatePropagation();
    if (/^(Control|Alt|Shift|Meta|AltGraph|CapsLock|Dead|Unidentified)$/.test(e.key)) return;
    const { row } = recording;
    if (e.key === "Escape" && !e.ctrlKey && !e.altKey && !e.shiftKey && !e.metaKey) {
      stopRecording();
      row.querySelector("[data-record]").focus();
      return;
    }
    const pressed = combo(e);
    stopRecording();
    if (!pressed) { window.toast("That key can't be used. Try another?"); return; }
    const keys = keysOf(row);
    if (keys.includes(pressed)) { row.querySelector("[data-record]").focus(); return; }
    setKeys(row, [...keys, pressed]);
  }, true);
  document.addEventListener("pointerdown", (e) => {
    if (recording && !recording.button.contains(e.target)) stopRecording();
  }, true);
  window.addEventListener("blur", stopRecording);

  /* ---- the buttons ---- */

  list.addEventListener("click", (e) => {
    const action = e.target.closest("[data-action]");
    const add = e.target.closest("[data-record]");
    if (add && action) {
      if (recording?.row === action) stopRecording();
      else record(action);
      return;
    }
    const remove = e.target.closest("[data-remove]");
    if (remove && action) {
      setKeys(action, keysOf(action).filter((k) => k !== remove.dataset.remove));
      return;
    }
    if (e.target.closest("[data-reset]") && action) {
      send("DELETE", `/ui/keys/${encodeURIComponent(action.dataset.action)}`, null, action.dataset.action);
      return;
    }
    if (e.target.closest("[data-reset-all]")) {
      window.confirmAction({
        title: "Every key back to its default?",
        detail: "The keys you chose are taken out of keys.toml.",
        action: "Put them back",
      }).then((yes) => { if (yes) send("DELETE", "/ui/keys", null, null); });
    }
  });

  /* ---- finding an action ---- */

  const filter = () => {
    const words = (find?.value || "").trim().toLowerCase().split(/\s+/).filter(Boolean);
    for (const item of list.querySelectorAll(".keys-action")) {
      const hay = item.dataset.find.toLowerCase();
      item.hidden = !words.every((w) => hay.includes(w));
    }
    for (const scope of list.querySelectorAll(".keys-scope")) {
      const title = scope.querySelector("h2").textContent.toLowerCase();
      const titled = words.length && words.every((w) => title.includes(w));
      if (titled) scope.querySelectorAll(".keys-action").forEach((item) => { item.hidden = false; });
      scope.hidden = !scope.querySelector(".keys-action:not([hidden])");
    }
  };
  find?.addEventListener("input", filter);
  find?.addEventListener("keydown", (e) => {
    if (e.key !== "Escape" || !find.value) return;
    e.preventDefault();
    find.value = "";
    filter();
  });
})();
