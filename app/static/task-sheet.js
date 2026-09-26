/* The task sheet (partials/task_sheet.html): one way of writing a task, for
   adding it (compose, the last row of a list card) and for editing it in
   place of its row (edit).

   The title is a line of a document: a plaintext contenteditable that wraps,
   with the do-date, time, due and repeat icons trailing its last word.
   Typing "tomorrow", "friday", "at 3pm", "15:00-16:30", "due friday" or
   "every week" followed by a space turns the words into the matching field;
   Backspace straight after puts them back. Each field is a hidden input the
   form posts; the icons and the small menus they open only read and write
   those inputs.

   Compose adds with Ctrl+Enter or Add task. Edit has no Save: the sheet
   saves when focus leaves it (a click elsewhere, Tab away, Esc or
   Ctrl+Enter), and goes back to its row untouched when nothing changed.
   A notebook's box (compose, data-notebook) is written down the same way,
   when it is closed (Ctrl+Enter, Esc) or focus leaves it; an empty one is
   handed back to the page (notebook:discard), which takes the box away.
   The description is notes-editor.js. Listeners sit on document, so they
   survive htmx swaps. */

(() => {
  const SUBMIT = (e) => e.key === "Enter" && (e.ctrlKey || e.metaKey);

  const sheetOf = (el) => el?.closest?.(".task-sheet");
  const isNotebook = (form) => form.dataset.notebook != null;
  const titleOf = (form) => form.querySelector(".sheet-title");
  const notesEditorOf = (form) => form.querySelector("[data-notes-editor]");
  const isEdit = (form) => form.dataset.sheet === "edit";
  const field = (form, name) => form.elements[name];
  const valueOf = (form, name) => field(form, name)?.value ?? "";
  const titleText = (form) => titleOf(form).textContent.replace(/\s+/g, " ").trim();
  const hasNotes = (form) => field(form, "notes").value.trim() !== "";

  /* ---- dates, as the server writes them (app/dates.py short_date) ---- */

  const DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
  const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const pad = (n) => String(n).padStart(2, "0");
  const iso = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
  const fromIso = (s) => {
    const [y, m, d] = s.split("-").map(Number);
    return new Date(y, m - 1, d);
  };
  const today = () => {
    const d = new Date();
    d.setHours(0, 0, 0, 0);
    return d;
  };
  const plusDays = (d, n) => {
    const out = new Date(d);
    out.setDate(out.getDate() + n);
    return out;
  };
  const shortDate = (value) => {
    const d = fromIso(value);
    const diff = Math.round((d - today()) / 86400000);
    if (diff === 0) return "today";
    if (diff === 1) return "tomorrow";
    if (diff === -1) return "yesterday";
    return `${DAYS[d.getDay()]} ${d.getDate()} ${MONTHS[d.getMonth()]}`;
  };
  // A weekday named on its own day means the next one: that day's own is "today".
  const nextWeekday = (day) => plusDays(today(), ((day - today().getDay() + 6) % 7) + 1);

  /* ---- typed words become fields ---- */

  const WEEKDAYS = ["sunday", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday"];
  const DATE_WORDS = `today|tomorrow|next week|${WEEKDAYS.join("|")}`;
  const dateOfWord = (word) => {
    word = word.toLowerCase();
    if (word === "today") return iso(today());
    if (word === "tomorrow") return iso(plusDays(today(), 1));
    if (word === "next week") return iso(nextWeekday(1));
    return iso(nextWeekday(WEEKDAYS.indexOf(word)));
  };
  const REPEATS = { day: "daily", weekday: "weekdays", week: "weekly", month: "monthly" };

  // "at 3", "3pm", "15:30", "9-10:30am", "15:00-16:30": a time needs "at",
  // a colon or am/pm, so a bare number ("buy 2 ") stays a word. Without an
  // end it lasts an hour, as a drop on the timeline does.
  const TIME = /(?:^|\s)((at )?(\d{1,2})(?::([0-5]\d))?(am|pm)?(?:-(\d{1,2})(?::([0-5]\d))?(am|pm)?)?) $/i;
  const hhmm = (minutes) => `${pad(Math.floor(minutes / 60) % 24)}:${pad(minutes % 60)}`;
  const minutesOf = (value) => {
    const [h, m] = value.split(":").map(Number);
    return h * 60 + m;
  };
  const DEFAULT_MINUTES = 60;
  const timeOfWords = (m) => {
    const [, , at, h1, m1, ap1, h2, m2, ap2] = m;
    if (!at && m1 === undefined && !ap1 && !ap2) return null;
    const clock = (h, min, ap) => {
      let hour = Number(h);
      if (ap) {
        if (hour < 1 || hour > 12) return null;
        hour = (hour % 12) + (ap.toLowerCase() === "pm" ? 12 : 0);
      } else if (hour > 23) {
        return null;
      }
      return hour * 60 + Number(min || 0);
    };
    // "9-10:30am": the start takes the end's half of the day, if that keeps it first.
    let start = clock(h1, m1, ap1 || (h2 !== undefined && ap2 && Number(h1) <= Number(h2) ? ap2 : undefined));
    if (start === null) return null;
    if (h2 === undefined) return `${hhmm(start)}-${hhmm(Math.min(start + DEFAULT_MINUTES, 24 * 60 - 1))}`;
    const end = clock(h2, m2, ap2);
    if (end === null || end <= start) return null;
    return `${hhmm(start)}-${hhmm(end)}`;
  };

  // Tried in order against the text before the caret; each ends at the typed space.
  const RULES = [
    { name: "due", re: new RegExp(`(?:^|\\s)(due (${DATE_WORDS})) $`, "i"), value: (m) => dateOfWord(m[2]) },
    { name: "planned_for", re: new RegExp(`(?:^|\\s)((${DATE_WORDS})) $`, "i"), value: (m) => dateOfWord(m[2]) },
    { name: "time", re: TIME, value: timeOfWords },
    { name: "repeat", re: /(?:^|\s)(every (day|weekday|week|month)) $/i, value: (m) => REPEATS[m[2].toLowerCase()] },
  ];

  // The last conversion, so Backspace right after it can take it back.
  let converted = null; // {form, before, caretBefore, after, caretAfter, name, previous, start}
  // Words taken back stay words: {form, start} of each, until the title changes around them.
  const kept = new WeakMap(); // form -> Set of start offsets

  const caretIn = (el) => {
    const sel = document.getSelection();
    if (!sel.rangeCount || !el.contains(sel.anchorNode)) return null;
    const range = sel.getRangeAt(0).cloneRange();
    range.selectNodeContents(el);
    range.setEnd(sel.anchorNode, sel.anchorOffset);
    return range.toString().length;
  };
  const placeCaret = (el, offset) => {
    el.focus();
    const node = el.firstChild;
    const range = document.createRange();
    if (node) range.setStart(node, Math.min(offset, node.length));
    else range.setStart(el, 0);
    range.collapse(true);
    const sel = document.getSelection();
    sel.removeAllRanges();
    sel.addRange(range);
  };
  const setTitle = (form, text, caret) => {
    const title = titleOf(form);
    title.textContent = text;
    if (caret != null) placeCaret(title, caret);
    syncTitle(form);
  };

  // `text` is the title up to the caret, ending in the space just typed.
  const convert = (form, text, caret, { moveCaret = true } = {}) => {
    for (const rule of RULES) {
      const m = rule.re.exec(text);
      if (!m) continue;
      const value = rule.value(m);
      if (value == null) continue;
      const start = text.length - m[1].length - 1;
      if (kept.get(form)?.has(start)) return false;
      const full = titleOf(form).textContent;
      const after = full.slice(0, start) + full.slice(caret);
      converted = {
        form, before: full, caretBefore: caret, after, caretAfter: start,
        name: rule.name, previous: valueOf(form, rule.name), start,
      };
      setField(form, rule.name, value);
      setTitle(form, after, moveCaret ? start : null);
      return true;
    }
    return false;
  };

  // A word still at the end of the title when it is written (no space after).
  const convertTrailing = (form) => {
    const text = titleOf(form).textContent.replace(/\s+$/, "");
    if (!text) return;
    titleOf(form).textContent = `${text} `;
    convert(form, `${text} `, text.length + 1, { moveCaret: false });
    converted = null;
    setTitle(form, titleOf(form).textContent.replace(/\s+$/, ""));
  };

  const undoConversion = (form) => {
    const c = converted;
    converted = null;
    setField(form, c.name, c.previous);
    // Backspace would have eaten the space: the words come back without it.
    setTitle(form, c.before.slice(0, c.caretBefore - 1) + c.before.slice(c.caretBefore), c.caretBefore - 1);
    if (!kept.has(form)) kept.set(form, new Set());
    kept.get(form).add(c.start);
  };

  /* ---- fields: hidden inputs, drawn as the icons and their labels ---- */

  const REPEAT_LABELS = { none: "Does not repeat", daily: "Daily", weekdays: "Weekdays", weekly: "Weekly", monthly: "Monthly" };
  const STATUS_LABELS = {
    todo: "To do", in_progress: "In progress", blocked: "Blocked",
    needs_review: "Needs review", done: "Done", cancelled: "Cancelled",
  };
  const OWNER_LABELS = { oscar: "Oscar", claude: "Claude" };

  const projectsOf = (form) => {
    const data = form.querySelector("[data-sheet-projects]");
    return data ? JSON.parse(data.textContent) : [];
  };
  const projectLabel = (form) => {
    const project = projectsOf(form).find((p) => String(p.id) === valueOf(form, "project_id"));
    if (!project) return "";
    const milestone = project.milestones.find((m) => String(m.id) === valueOf(form, "milestone_id"));
    return milestone ? `${project.name} › ${milestone.name}` : project.name;
  };

  const draw = (form) => {
    for (const button of form.querySelectorAll(".prop[data-prop]")) {
      const name = button.dataset.prop;
      const label = button.querySelector(".prop-value");
      let text = "";
      let set = false;
      let spoken = button.title;
      if (name === "planned_for" || name === "due") {
        const value = valueOf(form, name);
        set = value !== "";
        text = set ? shortDate(value) : "";
        if (set) spoken = `${button.title}: ${text}`;
      } else if (name === "time") {
        const value = valueOf(form, "time");
        set = value !== "";
        text = set ? value.replace("-", "–") : "";
        if (set) spoken = `Time: ${text}`;
      } else if (name === "repeat") {
        const value = valueOf(form, "repeat") || "none";
        set = value !== "none";
        spoken = set ? `Repeats: ${REPEAT_LABELS[value].toLowerCase()}` : "Repeat";
        button.title = set ? `Repeats ${REPEAT_LABELS[value].toLowerCase()}` : "Repeat";
      } else if (name === "project") {
        text = projectLabel(form);
        set = text !== "";
        spoken = set ? `Project: ${text}` : "Project: none";
        if (!set) text = label.dataset.empty;
      } else if (name === "owner") {
        const value = valueOf(form, "owner");
        set = value === "claude";
        // Oscar's own tasks are the rule; only Claude's name is worth the space.
        text = set ? OWNER_LABELS[value] : "";
        spoken = `Owner: ${OWNER_LABELS[value]}`;
        button.title = set ? "Claude's task" : "Your task. Hand it to Claude?";
      } else if (name === "status") {
        const value = valueOf(form, "status");
        // Only Claude's work, or a status beyond the checkbox, needs saying.
        button.hidden = valueOf(form, "owner") !== "claude" && (value === "todo" || value === "done");
        set = true;
        text = STATUS_LABELS[value];
        spoken = `Status: ${text}`;
      }
      if (label) label.textContent = text;
      button.classList.toggle("is-set", set);
      button.setAttribute("aria-label", spoken);
    }
    const check = form.querySelector("[data-sheet-check]");
    if (check) check.checked = valueOf(form, "status") === "done";
  };

  const setField = (form, name, value) => {
    field(form, name).value = value;
    if (name === "project_id") field(form, "milestone_id").value = "";
    draw(form);
  };

  /* ---- the title line ---- */

  const syncTitle = (form) => {
    const title = titleOf(form);
    // An emptied contenteditable can keep a stray <br>; the placeholder needs it truly empty.
    if (title.textContent === "" && title.firstChild) title.replaceChildren();
    title.classList.toggle("is-empty", title.textContent === "");
    field(form, "title").value = titleText(form);
    if (!isEdit(form) && (titleText(form) || hasNotes(form))) form.classList.add("composing");
  };

  document.addEventListener("beforeinput", (e) => {
    if (!e.target.matches?.(".sheet-title")) return;
    // One line: Enter is the keydown handler's, and pasted lines join with spaces.
    if (e.inputType === "insertParagraph" || e.inputType === "insertLineBreak") e.preventDefault();
  });

  document.addEventListener("paste", (e) => {
    if (!e.target.closest?.(".sheet-title")) return;
    e.preventDefault();
    const text = (e.clipboardData?.getData("text/plain") || "").replace(/\s+/g, " ");
    document.execCommand("insertText", false, text);
  });

  document.addEventListener("input", (e) => {
    const title = e.target.closest?.(".sheet-title");
    if (!title) return;
    const form = sheetOf(title);
    syncTitle(form);
    if (e.inputType === "insertText" && e.data === " ") {
      const caret = caretIn(title);
      if (caret != null) convert(form, title.textContent.slice(0, caret), caret);
    }
  });

  // A click beside the words (the rest of the line) writes at the title's end.
  document.addEventListener("pointerdown", (e) => {
    const line = e.target.closest?.(".sheet-line");
    if (!line || e.target.closest(".sheet-title, .prop")) return;
    e.preventDefault();
    const title = line.querySelector(".sheet-title");
    placeCaret(title, title.textContent.length);
  });

  /* ---- the menus the icons open ---- */

  let menu = null; // {form, button, el, returnTo, range}

  const CHECK = '<svg class="tick" viewBox="0 0 20 20" aria-hidden="true"><path d="M4.5 10.5l3.5 3.5 7.5-8"/></svg>';

  // Items are buttons, except one that holds the date picker's input (a
  // button may not contain an input); the menu's keys press either.
  const item = (label, { checked = false, aside = "", indent = false, pick, tag = "button" } = {}) => {
    const el = document.createElement(tag);
    if (tag === "button") el.type = "button";
    el.setAttribute("role", "menuitemradio");
    el.setAttribute("aria-checked", String(checked));
    el.tabIndex = -1;
    if (indent) el.classList.add("indent");
    el.innerHTML = `<span class="label"></span>${aside ? '<span class="aside"></span>' : ""}${checked ? CHECK : ""}`;
    el.querySelector(".label").textContent = label;
    if (aside) el.querySelector(".aside").textContent = aside;
    el._pick = pick;
    return el;
  };

  const dateItems = (form, name) => {
    const current = valueOf(form, name);
    const choose = (value) => () => setField(form, name, value);
    const options = [
      ["Today", iso(today())],
      ["Tomorrow", iso(plusDays(today(), 1))],
      ["Next week", iso(nextWeekday(1))],
    ];
    const items = options.map(([label, value]) =>
      item(label, { checked: current === value, aside: shortDate(value) === label.toLowerCase() ? "" : shortDate(value), pick: choose(value) }));
    // The native picker anchors to its input, which sits unseen under the item.
    const pickItem = item("Pick a date…", {
      tag: "div",
      checked: current !== "" && !options.some(([, v]) => v === current),
      aside: current !== "" && !options.some(([, v]) => v === current) ? shortDate(current) : "",
    });
    const input = document.createElement("input");
    input.type = "date";
    input.tabIndex = -1;
    input.value = current;
    input.addEventListener("change", () => {
      if (input.value) setField(form, name, input.value);
      closeMenu();
    });
    pickItem.classList.add("pick");
    pickItem.append(input);
    pickItem._pick = () => {
      try {
        input.showPicker();
      } catch {
        input.focus(); // no showPicker: the input itself takes the date
      }
      return "keep";
    };
    items.push(pickItem);
    if (current) items.push(item("No date", { pick: choose("") }));
    return items;
  };

  // A native time picker under a menu item, as the date picker's is.
  const timePickItem = (label, current, aside, apply) => {
    const pickItem = item(label, { tag: "div", aside });
    const input = document.createElement("input");
    input.type = "time";
    input.step = 900;
    input.tabIndex = -1;
    input.value = current;
    input.addEventListener("change", () => {
      if (input.value) apply(input.value);
      closeMenu();
    });
    pickItem.classList.add("pick");
    pickItem.append(input);
    pickItem._pick = () => {
      try {
        input.showPicker();
      } catch {
        input.focus();
      }
      return "keep";
    };
    return pickItem;
  };

  const timeItems = (form) => {
    const current = valueOf(form, "time");
    const [start, end] = current ? current.split("-") : ["", ""];
    const length = current ? minutesOf(end) - minutesOf(start) : DEFAULT_MINUTES;
    const items = [
      // A new start keeps the length the time had.
      timePickItem(current ? "Change the start…" : "Pick a time…", start, start, (value) => {
        const from = minutesOf(value);
        setField(form, "time", `${value}-${hhmm(Math.min(from + length, 24 * 60 - 1))}`);
      }),
    ];
    if (current) {
      items.push(timePickItem("Change the end…", end, end, (value) => {
        if (minutesOf(value) > minutesOf(start)) setField(form, "time", `${start}-${value}`);
        else window.toast?.("The end has to come after the start.");
      }));
      items.push(item("No time", { pick: () => setField(form, "time", "") }));
    }
    return items;
  };

  const menuItems = (form, name) => {
    if (name === "planned_for" || name === "due") return dateItems(form, name);
    if (name === "time") return timeItems(form);
    if (name === "repeat") {
      const current = valueOf(form, "repeat") || "none";
      return Object.entries(REPEAT_LABELS).map(([value, label]) =>
        item(label, { checked: current === value, pick: () => setField(form, "repeat", value) }));
    }
    if (name === "owner") {
      const current = valueOf(form, "owner");
      return Object.entries(OWNER_LABELS).map(([value, label]) =>
        item(label, { checked: current === value, pick: () => setField(form, "owner", value) }));
    }
    if (name === "status") {
      const current = valueOf(form, "status");
      return Object.entries(STATUS_LABELS).map(([value, label]) =>
        item(label, { checked: current === value, pick: () => setField(form, "status", value) }));
    }
    if (name === "project") {
      const project = valueOf(form, "project_id");
      const milestone = valueOf(form, "milestone_id");
      const items = [item("No project", { checked: project === "", pick: () => setField(form, "project_id", "") })];
      for (const p of projectsOf(form)) {
        items.push(item(p.name, {
          checked: String(p.id) === project && milestone === "",
          pick: () => setField(form, "project_id", String(p.id)),
        }));
        for (const m of p.milestones) {
          items.push(item(m.name, {
            indent: true,
            checked: String(m.id) === milestone,
            pick: () => {
              setField(form, "project_id", String(p.id));
              setField(form, "milestone_id", String(m.id));
            },
          }));
        }
      }
      return items;
    }
    return [];
  };

  const place = (el, button) => {
    const at = button.getBoundingClientRect();
    const width = el.offsetWidth;
    const height = el.offsetHeight;
    const below = window.innerHeight - at.bottom;
    const top = below >= height + 8 || below >= at.top ? at.bottom + 4 : at.top - height - 4;
    el.style.top = `${Math.max(8, top)}px`;
    el.style.left = `${Math.max(8, Math.min(at.left, window.innerWidth - width - 8))}px`;
  };

  const openMenu = (form, button) => {
    closeMenu(false);
    const sel = document.getSelection();
    const range = sel.rangeCount && form.contains(sel.anchorNode) ? sel.getRangeAt(0).cloneRange() : null;
    const returnTo = form.contains(document.activeElement) ? document.activeElement : titleOf(form);
    const el = document.createElement("div");
    el.className = "sheet-menu";
    el.setAttribute("role", "menu");
    el.setAttribute("aria-label", button.title);
    const items = menuItems(form, button.dataset.prop);
    el.append(...items);
    // In the body, not the sheet: list cards clip what overflows them.
    document.body.append(el);
    place(el, button);
    button.setAttribute("aria-expanded", "true");
    menu = { form, button, el, returnTo, range };
    (items.find((i) => i.getAttribute("aria-checked") === "true") || items[0])?.focus();
  };

  const closeMenu = (restore = true) => {
    if (!menu) return;
    const { form, el, button, returnTo, range } = menu;
    menu = null;
    el.remove();
    button.setAttribute("aria-expanded", "false");
    // A sheet opened for one field (D or P on Tasks) is done once its menu is.
    if (form._quick) {
      save(form, { keyboard: true });
      return;
    }
    if (!restore || !returnTo.isConnected) return;
    returnTo.focus();
    if (range) {
      const sel = document.getSelection();
      sel.removeAllRanges();
      sel.addRange(range);
    }
  };

  // Pressing an icon keeps focus (and the caret) where it was writing.
  document.addEventListener("pointerdown", (e) => {
    if (e.target.closest?.(".task-sheet .prop, .sheet-actions button")) e.preventDefault();
  });

  document.addEventListener("click", (e) => {
    const button = e.target.closest?.(".task-sheet .prop[data-prop]");
    if (button) {
      const open = menu?.button === button;
      closeMenu(open);
      if (!open) openMenu(sheetOf(button), button);
      return;
    }
    const chosen = e.target.closest?.(".sheet-menu [role='menuitemradio']");
    if (chosen && menu) {
      if (chosen._pick?.() !== "keep") closeMenu();
      return;
    }
    if (menu && !e.target.closest?.(".sheet-menu")) closeMenu(false);
  });

  document.addEventListener("keydown", (e) => {
    if (!menu || !menu.el.contains(e.target)) return;
    const items = [...menu.el.querySelectorAll("[role='menuitemradio']")];
    const at = items.indexOf(e.target.closest("[role='menuitemradio']"));
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      const step = e.key === "ArrowDown" ? 1 : -1;
      items[(at + step + items.length) % items.length].focus();
    } else if ((e.key === "Enter" || e.key === " ") && e.target.tagName !== "BUTTON") {
      e.preventDefault();
      e.target.click();
    } else if (e.key === "Home" || e.key === "End") {
      e.preventDefault();
      items[e.key === "Home" ? 0 : items.length - 1].focus();
    } else if (e.key === "Escape") {
      e.preventDefault();
      e.stopPropagation();
      closeMenu();
    } else if (e.key === "Tab") {
      e.preventDefault();
      closeMenu();
    }
  }, true);

  window.addEventListener("resize", () => closeMenu(false));
  document.addEventListener("scroll", (e) => {
    if (menu && !menu.el.contains(e.target)) closeMenu(false);
  }, true);

  /* ---- writing: keys shared by both modes ---- */

  document.addEventListener("keydown", (e) => {
    const form = sheetOf(e.target);
    if (!form || e.isComposing) return;
    const inTitle = e.target.matches(".sheet-title");

    if (inTitle && e.key === "Backspace" && converted?.form === form) {
      const title = titleOf(form);
      if (title.textContent === converted.after && caretIn(title) === converted.caretAfter
          && document.getSelection().isCollapsed) {
        e.preventDefault();
        undoConversion(form);
        return;
      }
    }
    if (inTitle && e.key !== "Shift") converted = e.key === "Backspace" ? converted : null;

    if ((SUBMIT(e) || e.key === "Escape") && isNotebook(form)) {
      e.preventDefault();
      writeDown(form);
      return;
    }

    if (SUBMIT(e)) {
      e.preventDefault();
      if (isEdit(form)) save(form, { keyboard: true });
      else if (!titleText(form)) placeCaret(titleOf(form), 0);
      else form.requestSubmit();
      return;
    }

    if (e.key === "Escape") {
      e.preventDefault();
      if (isEdit(form)) {
        save(form, { keyboard: true });
        return;
      }
      // Esc steps away, back to the list's cursor where there is one (or out
      // of the capture window); a draft stays put until Cancel or Add.
      if (!hasNotes(form) && !titleText(form)) form.classList.remove("composing");
      const dialog = form.closest("dialog");
      if (dialog) {
        dialog.close();
        return;
      }
      if (!window.TaskCursor?.restore()) e.target.blur();
      return;
    }

    if (inTitle && e.key === "Enter") {
      // Enter moves on to the description, like a heading's next line.
      e.preventDefault();
      if (titleText(form) || isEdit(form)) {
        form.classList.add("composing");
        window.NotesEditor.focusEnd(notesEditorOf(form));
      }
    }
  });

  // A title's trailing words are fields too, and a sheet posts its title's text.
  document.addEventListener("submit", (e) => {
    const form = sheetOf(e.target);
    if (!form || e.target !== form) return;
    // A sheet only ever posts through htmx: one that htmx has not taken over
    // yet would be submitted by the browser itself, leaving the page. The
    // submit waits, and goes to the sheet that is live by then (a composer's
    // draft moves to its re-rendered twin).
    if (form.dataset.ready == null) {
      e.preventDefault();
      e.stopPropagation();
      const key = form.dataset.composerKey;
      setTimeout(() => {
        const live = form.isConnected ? form
          : key && document.querySelector(`.task-sheet[data-composer-key="${CSS.escape(key)}"]`);
        if (live?.dataset.ready != null) live.requestSubmit();
      }, 60);
      return;
    }
    closeMenu(false);
    convertTrailing(form);
    if (!titleText(form)) {
      if (isEdit(form)) {
        setTitle(form, titleOf(form).dataset.original);
      } else {
        e.preventDefault();
        e.stopPropagation(); // before htmx, which listens on the form
        placeCaret(titleOf(form), 0);
      }
    }
  }, true);

  /* ---- compose: the description opens once a title is being written ---- */

  // Not on mere focus: after an add, focus returns to the empty title, and a
  // composer that folded away on the next click elsewhere would shift the
  // page under the pointer between mousedown and mouseup, losing that click.
  document.addEventListener("focusin", (e) => {
    const form = sheetOf(e.target);
    if (form && !isEdit(form) && (titleText(form) || hasNotes(form))) form.classList.add("composing");
  });

  document.addEventListener("focusout", (e) => {
    const form = sheetOf(e.target);
    if (!form || isEdit(form) || form.contains(e.relatedTarget) || menu?.form === form) return;
    // A started task stays open; only an untouched composer folds away.
    if (!titleText(form) && !hasNotes(form)) form.classList.remove("composing");
  });

  const resetComposer = (form) => {
    form.reset(); // the description (notes-editor.js follows the reset)
    // Hidden inputs keep what was set on them; their defaults are the card's context.
    form.querySelectorAll("input[type='hidden'][data-default]").forEach((input) => {
      input.value = input.dataset.default;
    });
    kept.delete(form);
    setTitle(form, "");
    form.classList.remove("composing");
    draw(form);
  };

  document.addEventListener("click", (e) => {
    const cancel = e.target.closest?.("[data-composer-cancel]");
    if (!cancel) return;
    resetComposer(sheetOf(cancel));
    document.activeElement?.blur();
  });

  // An add, done. Heard on the form itself (init), since a list that
  // re-rendered while the add was in flight took this composer with it, and a
  // detached form's events never reach the document.
  const added = (form, e) => {
    const row = /id="(task-\d+)"/.exec(e.detail.xhr.responseText);
    if (row) window.TaskCursor?.remember(row[1]);
    if (isNotebook(form)) return; // it took the box's place; notebook.js moves on
    if (form.closest("dialog")) {
      // Written away from any list: say where it went, and let the page's
      // own views of tasks catch up (Weeks' Unplanned tray, say).
      const day = valueOf(form, "planned_for");
      window.toast(`Added “${titleText(form)}” ${day ? `for ${shortDate(day)}` : "to No date"}`);
      document.getElementById("capture-sink")?.replaceChildren();
      htmx.trigger(document.body, "weeks:refresh");
      htmx.trigger(document.body, "calendar:refresh");
    }
    // The list re-rendered while the add was in flight, from a moment before
    // it: the new row went to the old list. Render the lists again.
    if (!e.detail.target?.isConnected) htmx.trigger(document.body, "tasks:changed");
    if (!form.isConnected) return; // its twin took the focus, and no draft
    resetComposer(form);
    placeCaret(titleOf(form), 0); // ready for the next one
  };

  /* ---- a notebook's box: written down when it closes ---- */

  // The task is added (and takes the box's place), or, with no title, the
  // page takes the empty box away. Once only: a box being added is done.
  const writeDown = (form) => {
    if (!form.isConnected || form.dataset.sending != null || form.dataset.closing != null) return;
    closeMenu(false);
    if (titleText(form)) {
      form.requestSubmit();
      return;
    }
    form.dataset.closing = "";
    form.dispatchEvent(new CustomEvent("notebook:discard", { bubbles: true }));
  };

  /* ---- edit: saves when focus leaves the sheet ---- */

  const snapshot = (form) => new URLSearchParams(new FormData(form)).toString();

  // `keyboard`: closed by a key (Esc, Ctrl+Enter, a quick menu), so the
  // list's cursor comes back: to this task, or after a quick change, to the
  // row the list said follows it.
  const save = (form, { keyboard = false } = {}) => {
    if (!form.isConnected || form.dataset.saving) return;
    form.dataset.saving = "";
    closeMenu(false);
    convertTrailing(form);
    if (!titleText(form)) setTitle(form, titleOf(form).dataset.original);
    const id = form.closest("[id^='task-']").id;
    const changed = snapshot(form) !== form._initial;
    if (keyboard) window.TaskCursor?.land((changed && form._quick?.landOnChange) || id);
    if (!changed) {
      // Nothing changed: back to the row, without a save that re-renders the lists.
      htmx.ajax("GET", `/ui/tasks/${id.slice(5)}/row`, { target: `#${id}`, swap: "outerHTML" });
    } else {
      form.requestSubmit();
    }
  };

  const outside = (form, el) => el && !form.contains(el) && !menu?.el.contains(el) && !el.closest("dialog");

  document.addEventListener("pointerdown", (e) => {
    document.querySelectorAll(".task-sheet[data-sheet='edit']").forEach((form) => {
      if (outside(form, e.target)) save(form);
    });
    document.querySelectorAll(".task-sheet[data-notebook]").forEach((form) => {
      if (outside(form, e.target)) writeDown(form);
    });
  }, true);

  // Focus lost to nothing (the window, the browser's own controls) is not
  // leaving the sheet; see Tab below for the page's last control.
  document.addEventListener("focusout", (e) => {
    const form = sheetOf(e.target);
    if (!form || !outside(form, e.relatedTarget)) return;
    if (isEdit(form)) save(form);
    else if (isNotebook(form)) writeDown(form);
  });

  // Tab past a sheet's last control leaves it, even where nothing on the
  // page comes after it to take the focus (it would go to the browser).
  const TABBABLE = "button:not([hidden]), input:not([type='hidden']), [contenteditable], [tabindex='0']";
  document.addEventListener("keydown", (e) => {
    if (e.key !== "Tab" || e.shiftKey || e.defaultPrevented) return;
    const form = sheetOf(e.target);
    if (!form || (!isEdit(form) && !isNotebook(form))) return;
    const stops = [...form.querySelectorAll(TABBABLE)].filter((el) => el.tabIndex >= 0 && el.checkVisibility());
    if (e.target !== stops[stops.length - 1]) return;
    e.preventDefault();
    if (isEdit(form)) save(form, { keyboard: true });
    else writeDown(form);
  });

  // A task's history, under its sheet: loaded once (hx-trigger), then shown and hidden.
  document.addEventListener("click", (e) => {
    const button = e.target.closest?.(".task-sheet [data-history]");
    if (!button) return;
    const panel = document.getElementById(button.getAttribute("aria-controls"));
    const open = button.getAttribute("aria-expanded") !== "true";
    button.setAttribute("aria-expanded", String(open));
    panel.hidden = !open;
  });

  document.addEventListener("change", (e) => {
    if (!e.target.matches?.("[data-sheet-check]")) return;
    const form = sheetOf(e.target);
    setField(form, "status", e.target.checked ? "done" : "todo");
  });

  /* ---- ready: labels drawn, an opened editor takes the caret ---- */

  const init = (form) => {
    if (form.dataset.ready != null) return;
    form.dataset.ready = "";
    syncTitle(form);
    draw(form);
    if (!isEdit(form)) {
      // While its add is in flight, what it holds is being saved, not a draft.
      form.addEventListener("htmx:beforeRequest", () => { form.dataset.sending = ""; });
      form.addEventListener("htmx:afterRequest", (e) => {
        delete form.dataset.sending;
        if (e.detail.successful) added(form, e);
      });
    }
    if (isEdit(form)) {
      // notes-editor.js loads first, so its htmx:load has already rendered the
      // description from the field: this is the task exactly as it stands.
      form._initial = snapshot(form);
      const title = titleOf(form);
      placeCaret(title, title.textContent.length);
      if (pending && form.closest("li").id === pending.id) {
        form._quick = { landOnChange: pending.landOnChange };
        openMenu(form, form.querySelector(`.prop[data-prop="${pending.field}"]`));
      }
      pending = null;
    }
  };

  /* ---- for tasks.js: the keyboard's ways in ---- */

  let pending = null; // {id, field, landOnChange}: an edit to open on one field's menu
  window.TaskSheet = {
    // Edit a row's task with one field's menu open; choosing (or Esc) saves.
    edit(row, field, landOnChange) {
      pending = { id: row.id, field, landOnChange };
      row.querySelector(".task-title-btn").click();
    },
    // Take up a sheet made by the page (a notebook's box, from its template).
    init,
    // Start writing in a composer (N).
    compose(form) {
      if (!form) return;
      form.scrollIntoView({ block: "nearest" });
      const title = titleOf(form);
      placeCaret(title, title.textContent.length);
    },
  };
  document.addEventListener("htmx:load", (e) => {
    const elt = e.detail.elt;
    if (elt.matches?.(".task-sheet")) init(elt);
    elt.querySelectorAll?.(".task-sheet").forEach(init);
  });

  /* ---- open edits survive live refreshes ---- */

  // A list re-rendering around an open edit (a refresh from elsewhere, or a
  // regroup still in flight when E was pressed) keeps the sheet as it is,
  // words, fields and caret, where the task's new row lands. Not a sheet
  // being saved, and not when the swap is the sheet's own (its save).
  const held = new WeakMap(); // request -> [{li, active, range}]
  document.addEventListener("htmx:beforeSwap", (e) => {
    const target = e.detail.target;
    const sheets = [...target.querySelectorAll(".task-sheet[data-sheet='edit']")]
      .filter((form) => form.dataset.saving == null && form.closest("li") !== target)
      .map((form) => {
        const sel = document.getSelection();
        const inside = form.contains(document.activeElement);
        return {
          li: form.closest("li"),
          active: inside ? document.activeElement : null,
          range: inside && sel.rangeCount ? sel.getRangeAt(0).cloneRange() : null,
        };
      });
    if (sheets.length) held.set(e.detail.xhr, sheets);
  });
  document.addEventListener("htmx:afterSwap", (e) => {
    const sheets = held.get(e.detail.xhr);
    if (!sheets) return;
    held.delete(e.detail.xhr);
    for (const { li, active, range } of sheets) {
      const row = document.getElementById(li.id);
      if (!row || row === li) continue; // gone from this list, or untouched
      row.replaceWith(li);
      if (!active) continue;
      active.focus();
      if (range) {
        const sel = document.getSelection();
        sel.removeAllRanges();
        sel.addRange(range);
      }
    }
  });

  /* ---- drafts survive live refreshes ---- */

  // Today's list and the Tasks page re-render from the server whenever the
  // plan changes, composers included. Carry a half-written task, its fields
  // and focus over to the fresh composer with the same key.
  const FIELDS = ["planned_for", "time", "due", "repeat", "project_id"];
  const carried = new WeakMap(); // request -> drafts
  document.addEventListener("htmx:beforeSwap", (e) => {
    const drafts = [...e.detail.target.querySelectorAll(".task-sheet[data-composer]")]
      .map((form) => {
        const focus = !form.contains(document.activeElement) ? null
          : document.activeElement === titleOf(form) ? "title" : "notes";
        const key = form.dataset.composerKey;
        // An add in flight is being saved: only the focus moves over, so the
        // same task is never offered to be added twice.
        if (form.dataset.sending != null) return { key, title: "", notes: "", fields: null, focus };
        return {
          key,
          title: titleOf(form).textContent,
          notes: field(form, "notes").value,
          fields: Object.fromEntries(FIELDS.map((name) => [name, valueOf(form, name)])),
          focus,
        };
      })
      .filter((d) => d.title || d.notes || d.focus);
    if (drafts.length) carried.set(e.detail.xhr, drafts);
  });
  document.addEventListener("htmx:afterSettle", (e) => {
    const drafts = carried.get(e.detail.xhr);
    if (!drafts) return;
    carried.delete(e.detail.xhr);
    for (const d of drafts) {
      const form = document.querySelector(`.task-sheet[data-composer-key="${CSS.escape(d.key)}"]`);
      if (!form) continue;
      for (const [name, value] of Object.entries(d.fields || {})) field(form, name).value = value;
      field(form, "notes").value = d.notes;
      window.NotesEditor.reload(notesEditorOf(form));
      setTitle(form, d.title);
      draw(form);
      if (d.focus === "title") placeCaret(titleOf(form), d.title.length);
      else if (d.focus === "notes") window.NotesEditor.focusEnd(notesEditorOf(form));
    }
  });
})();
