/* The stay's pane, beside a day's notes (today.html): where Oscar stays
   that day, an item a row (place and accommodation to begin with): its
   name and its value, written in place, and accommodation's box, ticked
   once sorted (as Calendar's sheet has it). Stays are not written in the
   notes.

   A value saves a moment after the writing pauses, as it is left, and with
   Enter (which goes on to the next item); Esc puts it back as it was. The
   values an item had before are offered under it as it is written, the
   last first, so a place is written as it was. A day with no stay is
   written with the items the last stay had; "Same as yesterday" (or as the
   last day with one) takes that stay again, item for item. Carry on gives
   the day's stay to the days after it, up to the one picked; Undo puts
   them back. An item begins at the pane's foot, and its × takes it away.

   Under the date, among the day's facts, the stay reads item by item,
   accommodation in amber until sorted; a click goes to its value here. */

(() => {
  const pane = document.getElementById("pad-stay");
  if (!pane) return;

  const SAVE_AFTER_MS = 600;
  const day = pane.dataset.day; // the page's
  const list = pane.querySelector(".stay-list");
  const sum = pane.querySelector(".stay-sum");
  const same = pane.querySelector(".stay-same");
  const carry = pane.querySelector(".stay-carry");
  const through = pane.querySelector(".stay-through");
  let stay = { day, items: [], names: [], checks: [], before: null, through: null, values: {} };
  try { stay = JSON.parse(pane.querySelector(".stay-data").textContent) || stay; } catch { /* none */ }
  const rows = new Map(); // name, lower case -> its row

  const post = (path, fields = {}, keepalive = false) => fetch(`/ui/stays/${day}/${path}`, {
    method: "POST", headers: { "X-CSRF": window.csrfToken() }, body: new URLSearchParams(fields), keepalive,
  });
  const failed = async (res, fallback) => {
    const answer = res ? await res.json().catch(() => ({})) : {};
    window.toast(typeof answer.detail === "string" ? answer.detail : fallback);
  };

  const dateOf = (iso) => {
    const [y, m, d] = iso.split("-").map(Number);
    return new Date(y, m - 1, d);
  };
  const isoOf = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  const plusDays = (iso, n) => {
    const d = dateOf(iso);
    d.setDate(d.getDate() + n);
    return isoOf(d);
  };
  const dayName = (iso) => dateOf(iso).toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short" });
  // The day before the page's is "yesterday" to it, whatever today is.
  const beforeWords = (iso) => (iso === plusDays(day, -1) ? "yesterday" : dayName(iso));
  const upper = (s) => s.charAt(0).toUpperCase() + s.slice(1);
  const key = (name) => name.toLowerCase();
  // A checkbox, sorted or not (accommodation); the rest are their words.
  const isCheck = (name) => stay.checks.some((c) => key(c) === key(name));
  const isOpen = (item) => isCheck(item.name) && !item.done;

  // What each row shows: the day's items, or with none, the items a stay
  // written here starts with, empty.
  const shown = () => (stay.items.length
    ? stay.items
    : stay.names.map((name) => ({ name, value: "", done: false })));
  const isEmpty = (items) => !items.some((i) => i.value || i.done);
  const PLACEHOLDERS = { place: "Town or area", accommodation: "Hotel, flat, a friend's" };

  /* ---- a row ---- */

  const REMOVE = '<svg viewBox="0 0 20 20" aria-hidden="true"><path d="M6 6l8 8"/><path d="M14 6l-8 8"/></svg>';

  const make = (item) => {
    const li = document.createElement("li");
    li.className = "stay-row";
    const box = isCheck(item.name)
      ? '<button type="button" class="stay-box" role="checkbox"></button>'
      : '<span class="stay-box" aria-hidden="true"></span>';
    li.innerHTML = `
      ${box}
      <label class="stay-name"></label>
      <input class="stay-value" type="text" autocomplete="off" spellcheck="false" maxlength="200"
             role="combobox" aria-autocomplete="list" aria-expanded="false">
      <button type="button" class="stay-remove">${REMOVE}</button>`;
    const id = `stay-value-${key(item.name).replace(/[^a-z0-9]+/g, "-")}`;
    li.querySelector(".stay-value").id = id;
    li.querySelector(".stay-name").htmlFor = id;
    return li;
  };

  const update = (li, item) => {
    li.dataset.name = item.name;
    li.classList.toggle("open", isOpen(item));
    li.classList.toggle("done", isCheck(item.name) && item.done);
    const name = upper(item.name);
    const box = li.querySelector("button.stay-box");
    if (box) {
      box.setAttribute("aria-checked", String(item.done));
      box.setAttribute("aria-label", `${name} sorted`);
      box.title = item.done ? `${name} sorted: a click unticks it` : `${name} not sorted yet: a click ticks it`;
    }
    li.querySelector(".stay-name").textContent = name;
    const input = li.querySelector(".stay-value");
    // A value being written stays as written until it is saved.
    if (document.activeElement !== input) input.value = item.value;
    input.dataset.saved = item.value;
    input.placeholder = PLACEHOLDERS[key(item.name)] || "Not written";
    const remove = li.querySelector(".stay-remove");
    remove.setAttribute("aria-label", `Take ${name} away`);
    remove.title = `Take ${name} away from this day's stay`;
  };

  /* ---- the pane, and the facts under the date ---- */

  function draw() {
    const items = shown();
    const drawn = items.map((item) => {
      let li = rows.get(key(item.name));
      if (!li) {
        li = make(item);
        rows.set(key(item.name), li);
      }
      update(li, item);
      return li;
    });
    for (const [name, li] of rows) {
      if (!items.some((i) => key(i.name) === name)) rows.delete(name);
    }
    // Moved only when the order changed, so a value being written keeps its caret.
    const kept = drawn.length === list.children.length && drawn.every((li, i) => list.children[i] === li);
    if (!kept) list.replaceChildren(...drawn);

    // After its name: whether what is to be sorted is.
    const checks = stay.items.filter((i) => isCheck(i.name));
    const open = checks.some((i) => !i.done);
    sum.textContent = !checks.length ? "" : open ? "not sorted" : "sorted";
    sum.classList.toggle("open", open);

    const before = stay.before;
    same.hidden = !(before && before.items.length && isEmpty(stay.items));
    if (!same.hidden) {
      const words = beforeWords(before.day);
      const first = before.items.find((i) => i.value)?.value || "";
      same.replaceChildren(`Same as ${words}`);
      if (first) {
        const value = document.createElement("span");
        value.className = "stay-same-value";
        value.textContent = first;
        same.append(value);
      }
      same.title = `Take ${dayName(before.day)}'s stay again: ${before.items.map((i) => `${upper(i.name)} ${i.value || "not written"}${i.done ? ", sorted" : ""}`).join("; ")}`;
    }
    carry.hidden = !stay.items.length || isEmpty(stay.items);
    through.hidden = !stay.through;
    through.textContent = stay.through ? `Same to ${dayName(stay.through)}` : "";
    through.title = stay.through ? `The days after this one have this same stay, to ${dayName(stay.through)}` : "";
    drawFacts();
  }

  // Under the date: each item of the day's stay, its name and its value,
  // accommodation's box before it (in amber until sorted); a click goes to
  // it here.
  let factsShow = null;
  function drawFacts() {
    const facts = document.getElementById("day-stay");
    if (!facts) return;
    const shows = JSON.stringify([stay.items, stay.checks]);
    if (shows === factsShow) return;
    factsShow = shows;
    facts.hidden = !stay.items.length;
    facts.replaceChildren(...stay.items.map((item) => {
      const { name, value, done } = item;
      const check = isCheck(name);
      const li = document.createElement("li");
      const go = document.createElement("button");
      go.type = "button";
      go.className = `day-stay-item${check ? (done ? " done" : " open") : ""}`;
      go.dataset.name = name;
      go.innerHTML = `${check ? '<span class="day-stay-box" aria-hidden="true"></span>' : ""}<span class="day-stay-name"></span><span class="day-stay-value"></span>`;
      go.querySelector(".day-stay-name").textContent = upper(name);
      go.querySelector(".day-stay-value").textContent = value || (isOpen(item) ? "not sorted" : "");
      const state = check ? `, ${done ? "sorted" : "not sorted"}` : "";
      go.setAttribute("aria-label", `${upper(name)}: ${value || "not written"}${state}`);
      li.append(go);
      return li;
    }));
  }

  // The pane in sight: its column shown, the pane open. False when it is
  // hidden (Panes, at the day's header, shows it).
  const reveal = () => {
    if (pane.hidden) {
      window.toast("Stay is hidden. Panes, at the day's header, shows it again.");
      return false;
    }
    const side = pane.closest(".today-col")?.dataset.col;
    const fold = side && document.querySelector(`[data-fold-col="${side}"][aria-pressed="true"]`);
    if (fold) fold.click();
    pane.open = true;
    return true;
  };
  document.addEventListener("click", (e) => {
    const go = e.target.closest?.(".day-stay-item");
    if (!go || !reveal()) return;
    const input = rows.get(key(go.dataset.name))?.querySelector(".stay-value");
    input?.focus();
    input?.setSelectionRange(input.value.length, input.value.length);
  });

  // The answer drawn: the day's stay as the server has it now.
  const take = async (res, fallback) => {
    if (!res?.ok) {
      await failed(res, fallback);
      draw();
      return null;
    }
    const answer = await res.json();
    stay = answer.stay;
    draw();
    return answer;
  };

  /* ---- ticking ---- */

  async function tick(li) {
    const item = shown().find((i) => key(i.name) === key(li.dataset.name));
    const done = !item.done;
    li.classList.toggle("done", done); // at once, put right by the answer
    li.querySelector(".stay-box").setAttribute("aria-checked", String(done));
    await take(await post("item", { name: item.name, done: String(done) }).catch(() => null), "Could not tick that.");
  }

  /* ---- values ---- */

  const timers = new WeakMap();
  function save(input, { leaving = false } = {}) {
    clearTimeout(timers.get(input));
    const value = input.value.replace(/\s+/g, " ").trim();
    if (value === input.dataset.saved) return null;
    input.dataset.saved = value;
    const name = input.closest(".stay-row").dataset.name;
    const sent = post("item", { name, value }, leaving);
    if (leaving) return null;
    return sent.catch(() => null).then((res) => take(res, "Could not save that."));
  }

  /* ---- what was written before, offered under a value ---- */

  let offer = null; // {input, el, active}
  const closeOffer = () => {
    if (!offer) return;
    offer.el.remove();
    offer.input.setAttribute("aria-expanded", "false");
    offer.input.removeAttribute("aria-activedescendant");
    offer = null;
  };
  const activate = (n) => {
    const options = [...offer.el.querySelectorAll("[role=option]")];
    options.forEach((o, i) => {
      o.toggleAttribute("data-active", i === n);
      o.setAttribute("aria-selected", String(i === n));
    });
    offer.active = n;
    if (n >= 0) {
      offer.input.setAttribute("aria-activedescendant", options[n].id);
      options[n].scrollIntoView({ block: "nearest" });
    } else {
      offer.input.removeAttribute("aria-activedescendant");
    }
  };
  function openOffer(input) {
    const name = input.closest(".stay-row").dataset.name;
    const typed = input.value.trim().toLowerCase();
    const values = (stay.values[name] || []).filter((v) => v.toLowerCase() !== typed && (!typed || v.toLowerCase().includes(typed)));
    if (!values.length) {
      closeOffer();
      return;
    }
    if (!offer || offer.input !== input) {
      closeOffer();
      const el = document.createElement("div");
      el.className = "sheet-menu stay-offer";
      el.setAttribute("role", "listbox");
      el.id = `${input.id}-offer`;
      el.setAttribute("aria-label", `${upper(name)}s written before`);
      document.body.append(el);
      offer = { input, el, active: -1 };
      input.setAttribute("aria-controls", el.id);
    }
    offer.el.replaceChildren(...values.map((value, i) => {
      const option = document.createElement("div");
      option.setAttribute("role", "option");
      option.id = `${input.id}-offer-${i}`;
      option.className = "stay-option";
      option.dataset.value = value;
      option.innerHTML = '<span class="label"></span>';
      option.querySelector(".label").textContent = value;
      return option;
    }));
    offer.active = -1;
    input.setAttribute("aria-expanded", "true");
    const at = input.getBoundingClientRect();
    const el = offer.el;
    el.style.minWidth = `${Math.max(200, at.width)}px`;
    const below = window.innerHeight - at.bottom >= el.offsetHeight + 8;
    el.style.top = `${Math.max(8, below ? at.bottom + 4 : at.top - el.offsetHeight - 4)}px`;
    el.style.left = `${Math.max(8, Math.min(at.left, window.innerWidth - el.offsetWidth - 8))}px`;
  }
  const choose = (value) => {
    const { input } = offer;
    closeOffer();
    input.value = value;
    save(input);
  };
  // A click on one: the input keeps the focus.
  document.addEventListener("pointerdown", (e) => {
    if (!offer) return;
    const option = e.target.closest?.(".stay-offer [role=option]");
    if (option) {
      e.preventDefault();
      choose(option.dataset.value);
    } else if (!offer.el.contains(e.target) && e.target !== offer.input) {
      closeOffer();
    }
  });
  window.addEventListener("resize", closeOffer);
  document.addEventListener("scroll", (e) => {
    if (offer && !offer.el.contains(e.target)) closeOffer();
  }, true);

  /* ---- carrying it on to the days after ---- */

  let menu = null;
  const closeMenu = (restore = true) => {
    if (!menu) return;
    menu.remove();
    menu = null;
    carry.setAttribute("aria-expanded", "false");
    if (restore) carry.focus();
  };
  function openMenu() {
    closeMenu(false);
    const el = document.createElement("div");
    el.className = "sheet-menu stay-carry-menu";
    el.setAttribute("role", "menu");
    el.setAttribute("aria-label", "Carry this stay on to");
    // The days after this one: the next, to its week's Sunday, a week on, or one picked.
    const toSunday = plusDays(day, ((7 - dateOf(day).getDay()) % 7) || 7);
    const choices = [["The next day", plusDays(day, 1)]];
    if (toSunday !== plusDays(day, 1)) choices.push(["To Sunday", toSunday]);
    choices.push(["A week on", plusDays(day, 7)], ["Pick a date…", "pick"]);
    for (const [label, value] of choices) {
      const item = document.createElement("button");
      item.type = "button";
      item.tabIndex = -1;
      item.setAttribute("role", "menuitem");
      item.dataset.value = value;
      item.innerHTML = '<span class="label"></span>';
      item.querySelector(".label").textContent = label;
      if (value === "pick") {
        // The native picker anchors to its input, unseen under the item.
        item.classList.add("pick");
        const input = document.createElement("input");
        input.type = "date";
        input.tabIndex = -1;
        input.min = plusDays(day, 1);
        input.setAttribute("aria-hidden", "true");
        input.addEventListener("change", () => {
          if (!input.value) return;
          closeMenu();
          fill(input.value);
        });
        item.append(input);
      } else {
        const aside = document.createElement("span");
        aside.className = "aside";
        aside.textContent = window.TaskSheet?.shortDate(value) || dayName(value);
        item.append(aside);
      }
      el.append(item);
    }
    document.body.append(el);
    const at = carry.getBoundingClientRect();
    const below = window.innerHeight - at.bottom >= el.offsetHeight + 8;
    el.style.top = `${Math.max(8, below ? at.bottom + 4 : at.top - el.offsetHeight - 4)}px`;
    el.style.left = `${Math.max(8, Math.min(at.left, window.innerWidth - el.offsetWidth - 8))}px`;
    carry.setAttribute("aria-expanded", "true");
    menu = el;
    el.firstElementChild.focus();
  }
  const pick = (item) => {
    if (item.dataset.value === "pick") {
      const input = item.querySelector("input");
      try { input.showPicker(); } catch { input.click(); }
      return;
    }
    closeMenu();
    fill(item.dataset.value);
  };
  async function fill(until) {
    const answer = await take(await post("fill", { until }).catch(() => null), "Could not carry the stay on.");
    if (!answer) return;
    const n = answer.days;
    window.toast(`Stay carried on to ${dayName(until)}, ${n} ${n === 1 ? "day" : "days"}.`, {
      action: "Undo",
      run: async () => {
        const res = await post("put", { stays: JSON.stringify(answer.was) }).catch(() => null);
        if (await take(res, "Could not put those days back.")) window.toast("Those days are back as they were.");
      },
    });
  }
  carry.addEventListener("click", () => (menu ? closeMenu() : openMenu()));
  document.addEventListener("click", (e) => {
    if (!menu || e.target.closest?.(".stay-carry")) return;
    const item = e.target.closest?.(".stay-carry-menu [data-value]");
    if (item && menu.contains(item)) {
      if (!e.target.closest?.("input")) pick(item);
    } else if (!menu.contains(e.target)) closeMenu(false);
  });
  document.addEventListener("keydown", (e) => {
    if (!menu || !menu.contains(e.target)) return;
    const items = [...menu.querySelectorAll("[data-value]")];
    const at = items.indexOf(e.target.closest("[data-value]"));
    const handled = () => { e.preventDefault(); e.stopPropagation(); };
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      handled();
      items[(at + (e.key === "ArrowDown" ? 1 : -1) + items.length) % items.length].focus();
    } else if (e.key === "Home" || e.key === "End") {
      handled();
      items[e.key === "Home" ? 0 : items.length - 1].focus();
    } else if (e.key === "Enter" || e.key === " ") {
      handled();
      pick(items[at]);
    } else if (e.key === "Escape" || (e.key === "Tab" && !e.ctrlKey)) {
      handled();
      closeMenu();
    } else if (e.key !== "Tab") {
      e.stopPropagation(); // the page's own keys stay out of the menu
    }
  }, true);
  window.addEventListener("resize", () => closeMenu(false));
  document.addEventListener("scroll", (e) => {
    if (menu && !menu.contains(e.target)) closeMenu(false);
  }, true);

  /* ---- the last stay again ---- */

  same.addEventListener("click", async () => {
    if (await take(await post("same").catch(() => null), "Could not take that stay again.")) {
      rows.get(key(shown()[0]?.name || ""))?.querySelector(".stay-value").focus();
    }
  });

  /* ---- an item begun, or taken away ---- */

  const opener = pane.querySelector(".stay-new-open");
  const form = pane.querySelector(".stay-new");
  const input = form.elements.name;
  const closeNew = () => {
    form.hidden = true;
    opener.hidden = false;
    input.value = "";
  };
  opener.addEventListener("click", () => {
    opener.hidden = true;
    form.hidden = false;
    input.focus();
  });
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const name = input.value.trim();
    if (!name) return;
    if (!(await take(await post("add", { name }).catch(() => null), "Could not add that item."))) {
      input.focus();
      return;
    }
    closeNew();
    rows.get(key(name.replace(/\s+/g, " ")))?.querySelector(".stay-value").focus();
  });
  input.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      e.preventDefault();
      e.stopPropagation();
      closeNew();
      opener.focus();
    }
  });
  input.addEventListener("blur", () => {
    if (!input.value.trim()) closeNew();
  });

  async function remove(li) {
    const name = li.dataset.name;
    const was = { [day]: stay.items };
    const answer = await take(await post("remove", { name }).catch(() => null), "Could not take that away.");
    if (!answer) return;
    window.toast(`${upper(name)} taken away from this day's stay.`, {
      action: "Undo",
      run: async () => take(await post("put", { stays: JSON.stringify(was) }).catch(() => null), "Could not put it back."),
    });
  }

  /* ---- hands on it ---- */

  list.addEventListener("click", (e) => {
    const li = e.target.closest(".stay-row");
    if (!li) return;
    if (e.target.closest("button.stay-box")) tick(li);
    else if (e.target.closest(".stay-remove")) remove(li);
  });
  list.addEventListener("input", (e) => {
    if (!e.target.matches(".stay-value")) return;
    const field = e.target;
    openOffer(field);
    clearTimeout(timers.get(field));
    timers.set(field, setTimeout(() => save(field), SAVE_AFTER_MS));
  });
  list.addEventListener("focusin", (e) => {
    if (e.target.matches(".stay-value")) openOffer(e.target);
  });
  list.addEventListener("focusout", (e) => {
    if (!e.target.matches(".stay-value")) return;
    if (offer?.input === e.target) closeOffer();
    save(e.target);
  });
  list.addEventListener("keydown", (e) => {
    const field = e.target.closest(".stay-value");
    if (!field || e.isComposing) return;
    const options = offer?.input === field ? offer.el.querySelectorAll("[role=option]").length : 0;
    if ((e.key === "ArrowDown" || e.key === "ArrowUp") && options) {
      e.preventDefault();
      const step = e.key === "ArrowDown" ? 1 : -1;
      // Past either end, back to what is written.
      let next = offer.active + step;
      if (next >= options) next = -1;
      else if (next < -1) next = options - 1;
      activate(next);
    } else if (e.key === "Enter") {
      e.preventDefault();
      if (offer?.input === field && offer.active >= 0) {
        choose(offer.el.querySelectorAll("[role=option]")[offer.active].dataset.value);
        return;
      }
      closeOffer();
      save(field);
      // On to the next item's value, as a sheet goes down its column.
      const next = field.closest(".stay-row").nextElementSibling?.querySelector(".stay-value");
      if (next) next.focus();
      else field.blur();
    } else if (e.key === "Escape") {
      e.preventDefault();
      e.stopPropagation();
      if (offer?.input === field) {
        closeOffer();
        return;
      }
      clearTimeout(timers.get(field));
      field.value = field.dataset.saved;
      field.blur();
    }
  });
  // Left, what is written goes with it.
  const leave = () => {
    for (const field of list.querySelectorAll(".stay-value")) save(field, { leaving: true });
  };
  window.addEventListener("pagehide", leave);
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") leave();
  });

  draw();
  // For the page's tests.
  window.StayPane = { stay: () => stay };
})();
