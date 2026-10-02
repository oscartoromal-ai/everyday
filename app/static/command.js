/* The command menu (#command-dialog, Ctrl+K or Cmd+K anywhere): one line to
   go to a page or a day, search tasks, projects, events and the days' notes
   (/ui/search), or do something (a new task or event, the theme, compact
   rows). Up and Down move, Enter opens, Esc closes. */

(() => {
  const dialog = document.getElementById("command-dialog");
  if (!dialog) return;
  const input = dialog.querySelector(".command-input");
  const list = dialog.querySelector(".command-results");

  /* ---- days: words a day is called by ---- */

  const pad = (n) => String(n).padStart(2, "0");
  const iso = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
  const today = () => { const d = new Date(); d.setHours(0, 0, 0, 0); return d; };
  const plus = (d, n) => { const out = new Date(d); out.setDate(out.getDate() + n); return out; };
  const DAYS = ["sunday", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday"];
  const MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"];
  const cap = (word) => word[0].toUpperCase() + word.slice(1);
  // "Fri 9 Oct", or "Tomorrow, Sat 3 Oct".
  const label = (d) => {
    const named = `${cap(DAYS[d.getDay()].slice(0, 3))} ${d.getDate()} ${cap(MONTHS[d.getMonth()])}`;
    const word = { 0: "Today", 1: "Tomorrow", [-1]: "Yesterday" }[Math.round((d - today()) / 86400000)];
    return word ? `${word}, ${named}` : named;
  };
  // "today", "tomorrow", "yesterday", a weekday (the next one), "next week",
  // "12 oct", "oct 12", "12/10" (day first), "2026-10-12".
  const dayOf = (text) => {
    const q = text.trim().toLowerCase();
    if (!q) return null;
    if (q === "today") return today();
    if (q === "tomorrow") return plus(today(), 1);
    if (q === "yesterday") return plus(today(), -1);
    if (q === "next week") return plus(today(), ((1 - today().getDay() + 6) % 7) + 1);
    const weekday = DAYS.findIndex((d) => d.startsWith(q) && q.length >= 3);
    if (weekday >= 0) return plus(today(), ((weekday - today().getDay() + 6) % 7) + 1);
    let m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(q);
    if (m) return new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
    const month = (word) => MONTHS.findIndex((mo) => word.startsWith(mo));
    const build = (dayNum, monthIdx) => {
      if (monthIdx < 0 || dayNum < 1 || dayNum > 31) return null;
      const d = new Date(today().getFullYear(), monthIdx, dayNum);
      if (d.getMonth() !== monthIdx) return null;
      // A day well past this year means next year's.
      if (d < plus(today(), -180)) d.setFullYear(d.getFullYear() + 1);
      return d;
    };
    m = /^(\d{1,2})\s+([a-z]{3,})$/.exec(q);
    if (m) return build(Number(m[1]), month(m[2]));
    m = /^([a-z]{3,})\s+(\d{1,2})$/.exec(q);
    if (m) return build(Number(m[2]), month(m[1]));
    m = /^(\d{1,2})\/(\d{1,2})$/.exec(q);
    if (m) return build(Number(m[1]), Number(m[2]) - 1);
    return null;
  };

  /* ---- what the menu offers ---- */

  const go = (href) => () => { window.location.href = href; };
  const press = (selector) => () => document.querySelector(selector)?.click();

  // Every page in the nav, and the things to do from anywhere.
  const commands = () => [
    ...[...document.querySelectorAll(".nav a[href]")].map((a) => ({
      kind: "Page",
      label: a.querySelector(".nav-label")?.textContent.trim() || a.textContent.trim(),
      words: "go to",
      hint: a.getAttribute("aria-keyshortcuts") || "",
      run: go(a.getAttribute("href")),
    })),
    {
      kind: "Do", label: "New task", words: "add write capture", hint: "N",
      // As N would: the page's own list, or the capture window.
      run: () => document.body.dispatchEvent(new KeyboardEvent("keydown", { key: "n", bubbles: true })),
    },
    {
      kind: "Do", label: "New event", words: "add calendar meeting", hint: document.querySelector("[data-new-event]") ? "E" : "",
      run: () => (document.querySelector("[data-new-event]") ? press("[data-new-event]")() : go("/calendar?new=1")()),
    },
    { kind: "Do", label: "Switch to the other theme", words: "dark light day night mode", run: press(".theme-toggle") },
    { kind: "Do", label: "Compact or roomy rows", words: "density", hint: "C", run: press(".density-toggle") },
    { kind: "Do", label: "Every key", words: "keyboard shortcuts help", hint: "?",
      run: () => { const keys = document.getElementById("keys-dialog"); keys.showModal(); keys.focus(); } },
  ];

  const matches = (item, q) => {
    if (!q) return true;
    const hay = `${item.label} ${item.words || ""}`.toLowerCase();
    return q.toLowerCase().split(/\s+/).every((w) => hay.includes(w));
  };

  const dayItems = (q) => {
    const d = dayOf(q);
    if (!d) return [];
    const day = iso(d);
    const isToday = day === iso(today());
    return [
      { kind: "Day", label: `${label(d)} on the calendar`, run: go(`/calendar?start=${day}`) },
      { kind: "Day", label: `${label(d)}, its notes`, run: go(isToday ? "/today" : `/day/${day}`) },
    ];
  };

  const foundItems = (found) => [
    ...found.tasks.map((t) => ({
      kind: "Task", label: t.title, meta: t.meta, done: t.done,
      // Tasks opens with the cursor on it (tasks.js carries it across loads).
      run: () => {
        try { sessionStorage.setItem("pc-task-cursor", `task-${t.id}`); } catch { /* blocked */ }
        go("/")();
      },
    })),
    ...found.projects.map((p) => ({ kind: "Project", label: p.name, color: p.color, run: go(`/projects/${p.id}`) })),
    ...found.events.map((e) => ({
      kind: "Event", label: e.title, meta: e.when, done: e.cancelled,
      run: go(`/calendar?view=day&start=${e.day}&event=${e.id}`),
    })),
    ...found.notes.map((n) => ({ kind: "Notes", label: n.label, meta: n.snippet, run: go(`/day/${n.day}`) })),
  ];

  /* ---- drawing it ---- */

  let items = [];
  let active = 0;
  const GROUPS = { Day: "Days", Page: "Pages", Do: "Do", Task: "Tasks", Project: "Projects", Event: "Events", Notes: "Notes" };

  const draw = () => {
    list.replaceChildren();
    let group = "";
    items.forEach((item, i) => {
      if (item.kind !== group) {
        group = item.kind;
        const head = document.createElement("li");
        head.className = "command-group";
        head.setAttribute("role", "presentation");
        head.textContent = GROUPS[group];
        list.append(head);
      }
      const li = document.createElement("li");
      li.className = "command-item";
      li.id = `command-item-${i}`;
      li.setAttribute("role", "option");
      li.setAttribute("aria-selected", String(i === active));
      li.dataset.index = i;
      li.dataset.kind = item.kind;
      li.innerHTML = '<span class="command-label"></span><span class="command-meta"></span>';
      const name = li.querySelector(".command-label");
      name.textContent = item.label;
      if (item.done) name.classList.add("done");
      if (item.color) {
        li.style.setProperty("--project", `var(--hue-${item.color})`);
        li.classList.add("in-project");
      }
      li.querySelector(".command-meta").textContent = item.meta || item.hint || "";
      if (item.hint && !item.meta) li.querySelector(".command-meta").classList.add("hint");
      list.append(li);
    });
    if (!items.length) {
      const none = document.createElement("li");
      none.className = "command-empty";
      none.setAttribute("role", "presentation");
      none.textContent = input.value.trim().length < 2 ? "Type to search." : "Nothing matches.";
      list.append(none);
    }
    input.setAttribute("aria-activedescendant", items.length ? `command-item-${active}` : "");
    list.querySelector(`[aria-selected="true"]`)?.scrollIntoView({ block: "nearest" });
  };

  let asked = 0; // the latest search, so an older answer never overwrites a newer
  let timer = 0;
  const update = () => {
    const q = input.value.trim();
    const local = [...dayItems(q), ...commands().filter((c) => matches(c, q))];
    items = local;
    active = 0;
    draw();
    clearTimeout(timer);
    if (q.length < 2) return;
    const ask = ++asked;
    timer = setTimeout(async () => {
      const res = await fetch(`/ui/search?q=${encodeURIComponent(q)}`).catch(() => null);
      if (!res?.ok || ask !== asked) return;
      const found = foundItems(await res.json());
      // What was found comes first once a word is searched; a day stays on top.
      const days = local.filter((i) => i.kind === "Day");
      items = [...days, ...found, ...local.filter((i) => i.kind !== "Day")];
      active = 0;
      draw();
    }, 120);
  };

  const run = (i) => {
    const item = items[i];
    if (!item) return;
    dialog.close();
    item.run();
  };

  const open = () => {
    if (dialog.open) return;
    input.value = "";
    update();
    dialog.showModal();
    input.focus();
  };

  /* ---- keys ---- */

  document.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && !e.altKey && !e.shiftKey && e.key.toLowerCase() === "k") {
      e.preventDefault();
      if (dialog.open) dialog.close();
      else if (!document.querySelector("dialog[open]")) open();
    }
  }, true);

  input.addEventListener("input", update);
  input.addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      if (!items.length) return;
      active = (active + (e.key === "ArrowDown" ? 1 : -1) + items.length) % items.length;
      draw();
    } else if (e.key === "Enter") {
      e.preventDefault();
      run(active);
    }
  });
  list.addEventListener("pointermove", (e) => {
    const li = e.target.closest(".command-item");
    if (li && Number(li.dataset.index) !== active) {
      active = Number(li.dataset.index);
      draw();
    }
  });
  list.addEventListener("click", (e) => {
    const li = e.target.closest(".command-item");
    if (li) run(Number(li.dataset.index));
  });
  // A click on the backdrop closes it.
  dialog.addEventListener("click", (e) => { if (e.target === dialog) dialog.close(); });
  document.querySelector("[data-command-open]")?.addEventListener("click", open);

  window.CommandMenu = { open, dayOf };
})();
