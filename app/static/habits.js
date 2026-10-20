/* The habits' pane, beside a day's notes (today.html): each habit due that
   day, and each ticked on it, a row: its box, its name (which opens the
   day's comment), its last seven days (the page's day last), its streak
   and its days' icon. Habits are not written in the notes.

   The box ticks the habit done for the day, or unticks it. A day of the
   seven picked (a click on its square, or Left and Right on a box), the
   boxes and comments are that day's: the pane's head names it, and the
   page's day, picked again (or Esc), brings it back.

   A comment is the day's entry in the habit's log, its file's words
   (habits/<name>.md): written in the drawer its name opens under the row
   (with a way to the habit's page, where its whole log is), saved a
   moment after the writing pauses and as it is left, Enter saving and
   closing it (Shift+Enter, a new line). A comment on a day not ticked
   says why it was skipped. A name whose day has a comment has a bubble
   after it.

   A habit begins at the pane's foot (New habit), due any day until its
   days say otherwise; All habits is the Habits page. A habit shown stays
   until the page is left, whatever its days become meanwhile. */

(() => {
  const pane = document.getElementById("pad-habits");
  if (!pane) return;

  const NOTE_AFTER_MS = 600;
  const DAYS_AFTER_MS = 300;
  const STATES = { done: "Done", skipped: "Skipped", missed: "Missed" };

  const day = pane.dataset.day; // the page's
  const list = pane.querySelector(".habit-list");
  let habits = [];
  try { habits = JSON.parse(pane.querySelector(".habit-data").textContent || "[]"); } catch { /* none */ }
  let on = day; // the day the boxes and comments are for
  const shown = new Set(); // ids listed since the page was drawn
  const rows = new Map(); // id -> its row

  const post = (url, fields, keepalive = false) => fetch(url, {
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
  const weekdayOf = (iso) => String((dateOf(iso).getDay() + 6) % 7);
  const dayName = (iso) => dateOf(iso).toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short" });
  // "today", "yesterday" or the day: what a comment or a box is for.
  const dayWords = (iso, today) => {
    if (iso === today) return "today";
    const before = new Date(dateOf(today));
    before.setDate(before.getDate() - 1);
    const yesterday = `${before.getFullYear()}-${String(before.getMonth() + 1).padStart(2, "0")}-${String(before.getDate()).padStart(2, "0")}`;
    return iso === yesterday ? "yesterday" : dayName(iso);
  };

  const byId = (id) => habits.find((h) => h.id === id);
  const cellOf = (h, iso) => h.week.find((c) => c.day === iso) || { day: iso, state: null, note: "" };
  const isDue = (h) => !h.days || h.days.includes(weekdayOf(day));
  const ticked = (h) => ["done", "skipped"].includes(cellOf(h, day).state);
  const listed = () => habits
    .filter((h) => isDue(h) || ticked(h) || shown.has(h.id))
    .sort((a, b) => a.slug.localeCompare(b.slug));

  /* ---- a row ---- */

  const BUBBLE = '<svg viewBox="0 0 20 20" aria-hidden="true"><path d="M4.5 4.5h11a1.5 1.5 0 0 1 1.5 1.5v6.5a1.5 1.5 0 0 1-1.5 1.5H9l-3.5 3v-3h-1A1.5 1.5 0 0 1 3 12.5V6a1.5 1.5 0 0 1 1.5-1.5z"/></svg>';

  const make = (h) => {
    const li = document.createElement("li");
    li.className = "habit-row";
    li.dataset.habit = h.id;
    li.innerHTML = `
      <div class="habit-line">
        <button type="button" class="habit-box" role="checkbox"></button>
        <button type="button" class="habit-name" aria-expanded="false"><span class="habit-name-text"></span>${BUBBLE}</button>
        <span class="habit-week" role="group"></span>
        <span class="habit-streak"></span>
      </div>
      <div class="habit-drawer" hidden>
        <textarea class="habit-note" rows="1" spellcheck="true"></textarea>
        <a class="habit-open">Its page and log</a>
      </div>`;
    const week = li.querySelector(".habit-week");
    week.setAttribute("aria-label", `${h.slug}'s last seven days`);
    for (let i = 0; i < 7; i++) {
      const cell = document.createElement("button");
      cell.type = "button";
      cell.className = "habit-day";
      cell.tabIndex = -1;
      week.append(cell);
    }
    const days = pane.querySelector(".habit-days-template").content.firstElementChild.cloneNode(true);
    days.elements.days.value = h.days;
    days.addEventListener("sheet:field", (e) => setDays(h.id, e.detail.value));
    li.querySelector(".habit-line").append(days);
    document.dispatchEvent(new CustomEvent("htmx:load", { detail: { elt: days } }));
    return li;
  };

  const update = (li, h) => {
    const cell = cellOf(h, on);
    const state = cell.state === "done" || cell.state === "skipped" ? cell.state : "open";
    const when = dayWords(on, h.today);
    li.classList.remove("done", "skipped", "open");
    li.classList.add(state);
    li.classList.toggle("has-note", !!cell.note);
    const box = li.querySelector(".habit-box");
    box.setAttribute("aria-checked", String(state === "done"));
    box.setAttribute("aria-label", `${h.slug}, done ${when}`);
    box.title = state === "done" ? `Done ${when}: a click unticks it` : `Not done ${when}: a click ticks it`;
    const name = li.querySelector(".habit-name");
    name.querySelector(".habit-name-text").textContent = h.slug;
    name.setAttribute("aria-label", `${h.slug}: comment on ${when}${cell.note ? `: ${cell.note}` : ""}`);
    name.title = cell.note ? `${dayName(on)}: ${cell.note}` : `Comment on ${when}`;
    li.querySelector(".habit-open").href = h.href;
    li.querySelectorAll(".habit-day").forEach((el, i) => {
      const c = h.week[i];
      if (!c) return;
      const open = c.day === day && !["done", "skipped"].includes(c.state);
      el.dataset.day = c.day;
      el.className = `habit-day ${open ? "today" : c.state || "none"}${c.day === on && on !== day ? " picked" : ""}`;
      el.classList.toggle("noted", !!c.note);
      const said = open ? "not yet" : (STATES[c.state] || "nothing").toLowerCase();
      el.title = `${dayName(c.day)}: ${said}${c.note ? `. ${c.note}` : ""}`;
      el.setAttribute("aria-label", el.title);
      el.setAttribute("aria-pressed", String(c.day === on));
    });
    const streak = li.querySelector(".habit-streak");
    streak.textContent = h.streak ? `${h.streak}d` : "";
    streak.title = h.streak ? `${h.streak} ${h.streak === 1 ? "day" : "days"} in a row` : "";
    const days = li.querySelector(".habit-days");
    if (days.elements.days.value !== h.days) {
      days.elements.days.value = h.days;
      window.TaskSheet?.refresh(days);
    }
  };

  /* ---- the pane ---- */

  function draw() {
    const now = listed();
    for (const h of now) shown.add(h.id);
    const head = pane.querySelector(".today-fold-summary");
    const done = now.filter((h) => cellOf(h, on).state === "done").length;
    head.querySelector(".count").textContent = now.length ? `${done}/${now.length}` : "";
    const picked = head.querySelector(".habit-on");
    picked.hidden = on === day;
    picked.textContent = on === day ? "" : dayName(on);
    head.querySelectorAll(".habit-week-head i").forEach((i) => i.classList.toggle("is-on", on !== day && i.dataset.day === on));
    if (!now.length) {
      const none = document.createElement("li");
      none.className = "habit-none";
      none.textContent = habits.length ? "None due this day." : "No habits yet. Start one below: it is ticked here, day by day.";
      list.replaceChildren(none);
      return;
    }
    const items = now.map((h) => {
      let li = rows.get(h.id);
      if (!li) {
        li = make(h);
        rows.set(h.id, li);
      }
      update(li, h);
      return li;
    });
    // Moved only when the order changed, so a comment being written keeps its caret.
    const same = items.length === list.children.length && items.every((li, i) => list.children[i] === li);
    if (!same) list.replaceChildren(...items);
  }

  const replace = (habit) => {
    const at = habits.findIndex((h) => h.id === habit.id);
    if (at === -1) habits.push(habit);
    else habits[at] = habit;
  };

  // The day the boxes and comments are for: a comment open is saved first,
  // and goes on with the new day's.
  const pick = (iso) => {
    if (iso === on) iso = day;
    if (iso === on) return;
    const open = list.querySelector(".habit-drawer:not([hidden])")?.closest(".habit-row");
    if (open) saveNote(open);
    on = iso;
    draw();
    if (open) openDrawer(open, { focus: false });
  };

  /* ---- ticking ---- */

  async function tick(li) {
    const h = byId(Number(li.dataset.habit));
    const was = cellOf(h, on);
    const done = was.state !== "done";
    const at = h.week.indexOf(was);
    // Drawn at once, put right by the answer.
    if (at !== -1) h.week[at] = { ...was, state: done ? "done" : (was.note ? "skipped" : null) };
    update(li, h);
    const res = await post(`/ui/habits/${h.id}/done`, { day: on, done: String(done), on: day }).catch(() => null);
    if (res?.ok) {
      replace((await res.json()).habit);
    } else {
      if (at !== -1) h.week[at] = was;
      await failed(res, "Could not tick that habit.");
    }
    draw();
  }

  /* ---- comments ---- */

  const noteTimers = new WeakMap();

  function openDrawer(li, { focus = true } = {}) {
    for (const other of list.querySelectorAll(".habit-row")) {
      if (other !== li && !other.querySelector(".habit-drawer").hidden) closeDrawer(other);
    }
    const h = byId(Number(li.dataset.habit));
    const drawer = li.querySelector(".habit-drawer");
    const note = drawer.querySelector(".habit-note");
    drawer.hidden = false;
    drawer.dataset.day = on;
    note.value = cellOf(h, on).note;
    const when = dayWords(on, h.today);
    note.placeholder = `A comment on ${when}: how it went, or why not`;
    note.setAttribute("aria-label", `${h.slug}: comment on ${when}`);
    li.classList.add("writing");
    li.querySelector(".habit-name").setAttribute("aria-expanded", "true");
    grow(note);
    if (focus) {
      note.focus();
      note.setSelectionRange(note.value.length, note.value.length);
    }
  }

  function closeDrawer(li, { leaving = false } = {}) {
    saveNote(li, { leaving });
    li.querySelector(".habit-drawer").hidden = true;
    li.classList.remove("writing");
    li.querySelector(".habit-name").setAttribute("aria-expanded", "false");
  }

  const grow = (note) => {
    note.style.height = "auto";
    note.style.height = `${note.scrollHeight}px`;
  };

  // The drawer's comment saved, when it is not what the day has already.
  function saveNote(li, { leaving = false } = {}) {
    clearTimeout(noteTimers.get(li));
    const drawer = li.querySelector(".habit-drawer");
    if (drawer.hidden) return;
    const h = byId(Number(li.dataset.habit));
    const forDay = drawer.dataset.day;
    const note = drawer.querySelector(".habit-note").value.trim();
    const cell = cellOf(h, forDay);
    if (note === cell.note) return;
    const at = h.week.indexOf(cell);
    if (at !== -1) {
      const state = cell.state === "done" ? "done" : note ? "skipped" : cell.state === "skipped" ? null : cell.state;
      h.week[at] = { ...cell, note, state };
    }
    update(li, h);
    post(`/ui/habits/${h.id}/note`, { day: forDay, note, on: day }, leaving).then(async (res) => {
      if (leaving) return;
      if (!res.ok) {
        await failed(res, "Could not save that comment.");
        return;
      }
      replace((await res.json()).habit);
      draw();
    }).catch(() => { if (!leaving) window.toast("Could not save that comment."); });
  }

  /* ---- days ---- */

  const daysTimers = new Map();
  function setDays(id, days) {
    const h = byId(id);
    h.days = days;
    clearTimeout(daysTimers.get(id));
    daysTimers.set(id, setTimeout(async () => {
      const res = await post(`/ui/habits/${id}/days`, { days: h.days }).catch(() => null);
      if (!res?.ok) await failed(res, "Could not set that habit's days.");
    }, DAYS_AFTER_MS));
    draw();
  }

  /* ---- a new one ---- */

  const foot = pane.querySelector(".habit-foot");
  const opener = foot.querySelector(".habit-new-open");
  const form = foot.querySelector(".habit-new");
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
    const res = await post("/ui/habits", { name, on: day }).catch(() => null);
    if (!res?.ok) {
      await failed(res, "Could not start that habit.");
      input.focus();
      return;
    }
    const { habit } = await res.json();
    replace(habit);
    shown.add(habit.id);
    closeNew();
    draw();
    rows.get(habit.id)?.querySelector(".habit-box").focus();
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

  /* ---- hands on it ---- */

  list.addEventListener("click", (e) => {
    const li = e.target.closest(".habit-row");
    if (!li) return;
    if (e.target.closest(".habit-box")) {
      tick(li);
    } else if (e.target.closest(".habit-name")) {
      if (li.querySelector(".habit-drawer").hidden) openDrawer(li);
      else {
        closeDrawer(li);
        li.querySelector(".habit-name").focus();
      }
    } else if (e.target.closest(".habit-day")) {
      pick(e.target.closest(".habit-day").dataset.day);
    }
  });
  list.addEventListener("keydown", (e) => {
    const li = e.target.closest(".habit-row");
    if (!li) return;
    if (e.target.matches(".habit-box") && (e.key === "ArrowLeft" || e.key === "ArrowRight")) {
      const week = byId(Number(li.dataset.habit)).week.map((c) => c.day);
      const at = week.indexOf(on) + (e.key === "ArrowLeft" ? -1 : 1);
      if (at < 0 || at >= week.length) return;
      e.preventDefault();
      pick(week[at]);
      li.querySelector(".habit-box").focus();
    } else if (e.target.matches(".habit-note")) {
      if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
        e.preventDefault();
        closeDrawer(li);
        li.querySelector(".habit-name").focus();
      } else if (e.key === "Escape") {
        e.preventDefault();
        e.stopPropagation();
        closeDrawer(li);
        li.querySelector(".habit-name").focus();
      }
    } else if (e.key === "Escape" && on !== day) {
      e.preventDefault();
      pick(day);
    }
  });
  list.addEventListener("input", (e) => {
    if (!e.target.matches(".habit-note")) return;
    const li = e.target.closest(".habit-row");
    grow(e.target);
    clearTimeout(noteTimers.get(li));
    noteTimers.set(li, setTimeout(() => saveNote(li), NOTE_AFTER_MS));
  });
  list.addEventListener("focusout", (e) => {
    if (!e.target.matches(".habit-note")) return;
    saveNote(e.target.closest(".habit-row"));
  });
  // Left, what is written goes with it.
  const leave = () => {
    for (const li of list.querySelectorAll(".habit-row")) saveNote(li, { leaving: true });
  };
  window.addEventListener("pagehide", leave);
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") leave();
  });

  draw();
  // For the page's tests.
  window.HabitsPane = { get on() { return on; }, habits: () => habits };
})();
