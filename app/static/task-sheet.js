/* The task sheet (partials/task_sheet.html): one way of writing a task, for
   adding it (compose, the last row of a list card) and for editing it in
   place of its row (edit).

   The title is a line of a document: a plaintext contenteditable that wraps,
   with the do-date, due, repeat, estimate and priority icons trailing its
   last word.
   Typing "tomorrow", "friday", "due friday", "every week", "30m" or "p2"
   followed by a space turns the words into the matching field;
   Backspace straight after puts them back. Each field is a hidden input the
   form posts; the icons and the small menus they open only read and write
   those inputs. A sheet that files its task (edit, and the New task
   window) also takes "#" and a few letters: the projects and workstreams
   they match drop down under it, and Enter or Tab files the task there.

   A sheet of controls only (data-sheet="props", a task row's in Today's
   notepad) is the icons and their menus alone: each change it makes is
   announced (sheet:field) for the page to keep. A habit's has one field,
   its days (the weekdays it is due), with the repeat icon.

   Compose adds with Ctrl+Enter or Add task. Edit has no Save: the sheet
   saves when focus leaves it (a click elsewhere, Tab away, Esc or
   Ctrl+Enter), and goes back to its row untouched when nothing changed.
   A task's own page (data-sheet="page", task.html) saves as it is
   written: a moment after the writing pauses, as a field is chosen, and
   as the page is left; Ctrl+S, Ctrl+Enter or Esc save at once.
   The description is notes-editor.js. Listeners sit on document, so they
   survive htmx swaps. */

(() => {
  const SUBMIT = (e) => e.key === "Enter" && (e.ctrlKey || e.metaKey);

  const sheetOf = (el) => el?.closest?.(".task-sheet");
  const titleOf = (form) => form.querySelector(".sheet-title");
  const notesEditorOf = (form) => form.querySelector("[data-notes-editor]");
  const isEdit = (form) => form.dataset.sheet === "edit";
  const isProps = (form) => form.dataset.sheet === "props";
  const isPage = (form) => form.dataset.sheet === "page";
  const isCompose = (form) => form.dataset.sheet === "compose";
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

  // "at 3", "3pm", "15:30", "9-10:30am", "15:00-16:30": a time, for an
  // event's title (calendar.js). It needs "at", a colon or am/pm, so a bare
  // number ("buy 2 ") stays a word. Without an end it lasts an hour.
  const TIME = /(?:^|\s)((at )?(\d{1,2})(?::([0-5]\d))?(am|pm)?(?:-(\d{1,2})(?::([0-5]\d))?(am|pm)?)?) $/i;
  const hhmm = (minutes) => `${pad(Math.floor(minutes / 60) % 24)}:${pad(minutes % 60)}`;
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

  // "30m", "45 min", "1h", "1.5h", "1h30", "2 hours": how long it takes.
  // A bare number stays a word, as it does for a time.
  const ESTIMATE = /(?:^|\s)((?:(\d{1,2}(?:[.,]\d)?)\s?(?:h|hrs?|hours?)(?:\s?(\d{1,2})\s?(?:m|mins?|minutes?)?)?|(\d{1,3})\s?(?:m|mins?|minutes?))) $/i;
  const estimateOfWords = (m) => {
    const [, , hours, extra, minutes] = m;
    const total = hours !== undefined
      ? Math.round(Number(hours.replace(",", ".")) * 60) + Number(extra || 0)
      : Number(minutes);
    return total > 0 && total <= 24 * 60 ? String(total) : null;
  };
  const durationLabel = (value) => {
    const minutes = Number(value);
    const h = Math.floor(minutes / 60);
    const m = minutes % 60;
    if (!h) return `${m}m`;
    return m ? `${h}h ${m}m` : `${h}h`;
  };
  const ESTIMATES = [15, 30, 45, 60, 90, 120, 180, 240];

  // "p1" to "p4", as Todoist writes them: urgent, high, medium, low.
  const PRIORITIES = ["urgent", "high", "medium", "low"];
  const PRIORITY_LABELS = { urgent: "Urgent", high: "High", medium: "Medium", low: "Low" };

  // Tried in order against the text before the caret; each ends at the typed space.
  const RULES = [
    { name: "due", re: new RegExp(`(?:^|\\s)(due (${DATE_WORDS})) $`, "i"), value: (m) => dateOfWord(m[2]) },
    { name: "planned_for", re: new RegExp(`(?:^|\\s)((${DATE_WORDS})) $`, "i"), value: (m) => dateOfWord(m[2]) },
    { name: "time", re: TIME, value: timeOfWords },
    { name: "repeat", re: /(?:^|\s)(every (day|weekday|week|month)) $/i, value: (m) => REPEATS[m[2].toLowerCase()] },
    { name: "estimate", re: ESTIMATE, value: estimateOfWords },
    { name: "priority", re: /(?:^|\s)(p([1-4])) $/i, value: (m) => PRIORITIES[Number(m[2]) - 1] },
  ];

  // The last conversion, so Backspace right after it can take it back: the
  // fields' values before it, and the title as Backspace would have left it.
  let converted = null; // {form, after, caretAfter, previous: {name: value}, undoText, undoCaret, start}
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

  // The field the words ending `text` (ending in the space just typed) make:
  // {name, value, start}, start where the words begin; or null. Only fields
  // `takes` (a name) are made: a task's sheet has no time.
  const fieldOfWords = (text, takes = () => true) => {
    for (const rule of RULES) {
      if (!takes(rule.name)) continue;
      const m = rule.re.exec(text);
      if (!m) continue;
      const value = rule.value(m);
      if (value == null) continue;
      return { name: rule.name, value, start: text.length - m[1].length - 1 };
    }
    return null;
  };

  // `text` is the title up to the caret, ending in the space just typed.
  const convert = (form, text, caret, { moveCaret = true } = {}) => {
    const field = fieldOfWords(text, (name) => !!form.elements[name]);
    if (!field) return false;
    const { name, value, start } = field;
    if (kept.get(form)?.has(start)) return false;
    const full = titleOf(form).textContent;
    const after = full.slice(0, start) + full.slice(caret);
    converted = {
      form, after, caretAfter: start, previous: { [name]: valueOf(form, name) }, start,
      // Backspace would have eaten the space: the words come back without it.
      undoText: full.slice(0, caret - 1) + full.slice(caret), undoCaret: caret - 1,
    };
    setField(form, name, value);
    setTitle(form, after, moveCaret ? start : null);
    return true;
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
    // In order: a project put back clears the workstream, put back after it.
    for (const [name, value] of Object.entries(c.previous)) setField(form, name, value);
    setTitle(form, c.undoText, c.undoCaret);
    if (!kept.has(form)) kept.set(form, new Set());
    kept.get(form).add(c.start);
  };

  /* ---- fields: hidden inputs, drawn as the icons and their labels ---- */

  const REPEAT_LABELS = { none: "Does not repeat", daily: "Daily", weekdays: "Weekdays", weekly: "Weekly", monthly: "Monthly" };
  const STATUS_LABELS = {
    todo: "To do", in_progress: "In progress", blocked: "Blocked",
    needs_review: "Needs review", done: "Done", cancelled: "Cancelled",
  };
  // The box steps a task on, as Gantt's does: to do, in progress, review,
  // done, and round to to do again; a blocked task starts.
  const NEXT_STATUS = { todo: "in_progress", blocked: "in_progress", in_progress: "needs_review", needs_review: "done", done: "todo" };
  const CHECK_TITLES = {
    todo: "To do: a click starts it", in_progress: "In progress: a click puts it to review",
    needs_review: "Needs review: a click makes it done", done: "Done: a click opens it again",
    blocked: "Blocked: a click starts it", cancelled: "Cancelled: a click opens it again",
  };
  const OWNER_LABELS = { oscar: "Oscar", claude: "Claude" };
  // A habit's days: Monday 0 to Sunday 6, "" for any day.
  const WEEKDAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
  const DAY_PRESETS = [["Any day", ""], ["Every day", "0123456"], ["Weekdays", "01234"]];
  const daysLabel = (days) => {
    if (days === "0123456") return "Every day";
    if (days === "01234") return "Weekdays";
    if (days === "56") return "Weekends";
    return [...days].map((d) => WEEKDAY_NAMES[d].slice(0, 3)).join(", ");
  };

  const projectsOf = (form) => {
    const data = form.querySelector("[data-sheet-projects]");
    return data ? JSON.parse(data.textContent) : [];
  };
  const projectOf = (form) => projectsOf(form).find((p) => String(p.id) === valueOf(form, "project_id"));
  const projectLabel = (form) => {
    const project = projectOf(form);
    if (!project) return "";
    const workstream = project.workstreams.find((m) => String(m.id) === valueOf(form, "workstream_id"));
    return workstream ? `${project.name} › ${workstream.name}` : project.name;
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
      } else if (name === "estimate") {
        const value = valueOf(form, "estimate");
        set = value !== "";
        text = set ? durationLabel(value) : "";
        spoken = set ? `Estimate: ${text}` : "Estimate";
      } else if (name === "priority") {
        // Its bars, as many filled as it matters (app.css, .priority-icon).
        const value = valueOf(form, "priority");
        set = value !== "";
        text = set ? PRIORITY_LABELS[value] : "";
        spoken = set ? `Priority: ${text}` : "Priority";
        button.querySelector(".priority-icon")?.setAttribute("data-priority", value);
      } else if (name === "repeat") {
        const value = valueOf(form, "repeat") || "none";
        set = value !== "none";
        spoken = set ? `Repeats: ${REPEAT_LABELS[value].toLowerCase()}` : "Repeat";
        button.title = set ? `Repeats ${REPEAT_LABELS[value].toLowerCase()}` : "Repeat";
      } else if (name === "project") {
        // In a project: its flag in the project's colour, the name on hover;
        // the New task window's names it in full (data-label="full").
        const project = projectOf(form);
        const full = button.dataset.label === "full";
        set = !!project;
        spoken = set ? `Project: ${projectLabel(form)}` : "Project: none";
        button.title = set ? spoken : "Project and workstream";
        if (full) button.title += " (#)";
        button.classList.toggle("in-project", set);
        if (set) button.style.setProperty("--project", `var(--hue-${project.color})`);
        else button.style.removeProperty("--project");
        text = set ? (full ? projectLabel(form) : "") : label.dataset.empty || "";
      } else if (name === "owner") {
        const value = valueOf(form, "owner");
        set = value === "claude";
        // Oscar's own tasks are the rule; only Claude's name is worth the space.
        text = set ? OWNER_LABELS[value] : "";
        spoken = `Owner: ${OWNER_LABELS[value]}`;
        button.title = set ? "Claude's task" : "Your task. Hand it to Claude?";
      } else if (name === "days") {
        const value = valueOf(form, "days");
        set = value !== "";
        text = daysLabel(value);
        spoken = set ? `Days: ${text}` : "Days: any day";
        button.title = set ? `On ${text}` : "Any day. Set its days?";
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
    if (check) {
      const status = valueOf(form, "status");
      check.checked = status === "done";
      // Started but not done: neither ticked nor empty (app.css draws which).
      check.indeterminate = status === "in_progress" || status === "needs_review";
      check.dataset.status = status;
      check.title = CHECK_TITLES[status];
      check.setAttribute("aria-label", `Status: ${STATUS_LABELS[status]}`);
    }
  };

  const setField = (form, name, value) => {
    field(form, name).value = value;
    if (name === "project_id" && field(form, "workstream_id")) field(form, "workstream_id").value = "";
    draw(form);
    // Heard by a page that keeps the fields itself (Today's notepad).
    form.dispatchEvent(new CustomEvent("sheet:field", { bubbles: true, detail: { name, value } }));
  };

  /* ---- the title line ---- */

  // Its spelling is marked only while it is being written.
  document.addEventListener("focusin", (e) => {
    if (e.target.matches?.(".sheet-title")) e.target.setAttribute("spellcheck", "true");
  });
  document.addEventListener("focusout", (e) => {
    if (e.target.matches?.(".sheet-title")) e.target.setAttribute("spellcheck", "false");
  });

  const syncTitle = (form) => {
    const title = titleOf(form);
    // An emptied contenteditable can keep a stray <br>; the placeholder needs it truly empty.
    if (title.textContent === "" && title.firstChild) title.replaceChildren();
    title.classList.toggle("is-empty", title.textContent === "");
    field(form, "title").value = titleText(form);
    if (isCompose(form) && (titleText(form) || hasNotes(form))) form.classList.add("composing");
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
    // Words after a "#" name a project, not a field.
    if (hashMenu(form)) return;
    if (e.inputType === "insertText" && e.data === " ") {
      const caret = caretIn(title);
      if (caret != null) convert(form, title.textContent.slice(0, caret), caret);
    }
  });

  /* ---- "#": the projects and workstreams the words after it match ---- */

  // A "#" starting a word, then up to 40 characters to the caret (a
  // project's name has spaces in it).
  const HASH = /(?:^|\s)#([^#\n]{0,40})$/;
  const filesTask = (form) => !!field(form, "workstream_id") && projectsOf(form).length > 0;

  // The rect of one character of a title, to drop a menu down from.
  const rectAt = (el, offset) => {
    const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
    for (let node = walker.nextNode(), left = offset; node; node = walker.nextNode()) {
      if (left < node.length) {
        const range = document.createRange();
        range.setStart(node, left);
        range.setEnd(node, left + 1);
        return range.getClientRects()[0] || range.getBoundingClientRect();
      }
      left -= node.length;
    }
    return el.getBoundingClientRect();
  };

  // While the words before the caret are a "#" and some of a name, the
  // menu of projects drops down from the "#", narrowed to them; it goes
  // once they match nothing (a "#2" was just words). True while it is open.
  const hashMenu = (form) => {
    if (!filesTask(form)) return false;
    const title = titleOf(form);
    const caret = caretIn(title);
    const m = caret == null ? null : HASH.exec(title.textContent.slice(0, caret));
    const open = menu?.inline && menu.form === form;
    if (!m) {
      if (open) closeMenu(false);
      return false;
    }
    const start = caret - m[1].length - 1;
    if (open) {
      menu.inline.start = start;
    } else {
      const inline = { query: m[1], start, at: rectAt(title, start) };
      openMenu(form, form.querySelector('.prop[data-prop="project"]'), { inline });
    }
    if (!filterMenu(m[1])) {
      closeMenu(false);
      return false;
    }
    return true;
  };

  // An item taken: the task is filed there, and the "#" and its words go
  // from the title; Backspace right after puts them back, as for a field.
  const fileFromHash = (el) => {
    const { form, inline } = menu;
    const title = titleOf(form);
    const full = title.textContent;
    const caret = caretIn(title) ?? full.length;
    const previous = { project_id: valueOf(form, "project_id"), workstream_id: valueOf(form, "workstream_id") };
    closeMenu(false);
    const tail = full.slice(caret);
    let head = full.slice(0, inline.start);
    if (head.endsWith(" ") && tail.startsWith(" ")) head = head.slice(0, -1);
    const after = head + tail;
    // The words go first: on a task's page, a field chosen is saved at once.
    setTitle(form, after, head.length);
    el._pick();
    converted = {
      form, after, caretAfter: head.length, previous, start: inline.start, undoText: full, undoCaret: caret,
    };
  };

  document.addEventListener("focusout", (e) => {
    if (menu?.inline && e.target === titleOf(menu.form)) closeMenu(false);
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
  // A project's flag, before its name, in its colour (an outline for none).
  const FLAG = '<svg class="flag" viewBox="0 0 20 20" aria-hidden="true"><path d="M5 17.5V3.5"/><path d="M5 4h9.5l-2.2 3.25L14.5 10.5H5"/></svg>';
  const ITEMS = "[role='menuitemradio'], [role='menuitemcheckbox']";

  // Items are buttons, except one that holds the date picker's input (a
  // button may not contain an input); the menu's keys press either.
  // `icon`: an element before the label (a priority's bars).
  const item = (label, { checked = false, aside = "", indent = false, flag = false, color = 0, icon = null, pick, tag = "button", role = "menuitemradio" } = {}) => {
    const el = document.createElement(tag);
    if (tag === "button") el.type = "button";
    el.setAttribute("role", role);
    el.setAttribute("aria-checked", String(checked));
    el.tabIndex = -1;
    if (indent) el.classList.add("indent");
    el.innerHTML = `${flag ? FLAG : ""}<span class="label"></span>${aside ? '<span class="aside"></span>' : ""}${checked ? CHECK : ""}`;
    if (icon) el.prepend(icon);
    if (color) el.style.setProperty("--project", `var(--hue-${color})`);
    el.querySelector(".label").textContent = label;
    if (aside) el.querySelector(".aside").textContent = aside;
    el._pick = pick;
    return el;
  };
  // An item's tick, redrawn in a menu that stays open.
  const tick = (el, checked) => {
    el.setAttribute("aria-checked", String(checked));
    el.querySelector(".tick")?.remove();
    if (checked) el.insertAdjacentHTML("beforeend", CHECK);
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

  const menuItems = (form, name) => {
    if (name === "planned_for" || name === "due") return dateItems(form, name);
    if (name === "repeat") {
      const current = valueOf(form, "repeat") || "none";
      return Object.entries(REPEAT_LABELS).map(([value, label]) =>
        item(label, { checked: current === value, pick: () => setField(form, "repeat", value) }));
    }
    if (name === "estimate") {
      // The usual lengths; any other is written as words ("50m ").
      const current = valueOf(form, "estimate");
      const items = ESTIMATES.map((minutes) => {
        const value = String(minutes);
        return item(durationLabel(value), { checked: current === value, pick: () => setField(form, "estimate", value) });
      });
      if (current && !ESTIMATES.includes(Number(current))) {
        items.unshift(item(durationLabel(current), { checked: true, pick: () => {} }));
      }
      if (current) items.push(item("No estimate", { pick: () => setField(form, "estimate", "") }));
      return items;
    }
    if (name === "priority") {
      // Most first, each after its bars (the field's own icon, redrawn).
      const current = valueOf(form, "priority");
      const bars = form.querySelector('.prop[data-prop="priority"] .priority-icon');
      const iconOf = (value) => {
        const icon = bars.cloneNode(true);
        icon.setAttribute("data-priority", value);
        return icon;
      };
      const items = PRIORITIES.map((value) => item(PRIORITY_LABELS[value], {
        checked: current === value, icon: iconOf(value), aside: `P${PRIORITIES.indexOf(value) + 1}`,
        pick: () => setField(form, "priority", value),
      }));
      items.push(item("No priority", { checked: current === "", icon: iconOf(""), pick: () => setField(form, "priority", "") }));
      return items;
    }
    if (name === "days") {
      // One of the usual sets, or its weekdays one by one (the menu stays
      // open for more).
      const redraw = (el) => {
        const days = valueOf(form, "days");
        for (const other of el.parentElement.children) if (other._checks) tick(other, other._checks(days));
      };
      const items = DAY_PRESETS.map(([label, value]) => {
        const el = item(label, { checked: valueOf(form, "days") === value, pick: () => setField(form, "days", value) });
        el._checks = (days) => days === value;
        return el;
      });
      WEEKDAY_NAMES.forEach((label, d) => {
        const day = String(d);
        const el = item(label, {
          role: "menuitemcheckbox",
          checked: valueOf(form, "days").includes(day),
          pick: () => {
            const days = valueOf(form, "days");
            const next = days.includes(day) ? days.replace(day, "") : [...days, day].sort().join("");
            setField(form, "days", next);
            redraw(el);
            return "keep";
          },
        });
        el._checks = (days) => days.includes(day);
        if (d === 0) el.classList.add("sep");
        items.push(el);
      });
      return items;
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
      // Each item knows the words it is found by (filterMenu): a workstream
      // its project's name and its own, and its project, shown above it.
      const project = valueOf(form, "project_id");
      const workstream = valueOf(form, "workstream_id");
      const none = item("No project", { flag: true, checked: project === "", pick: () => setField(form, "project_id", "") });
      none._words = "no project none";
      const items = [none];
      for (const p of projectsOf(form)) {
        const head = item(p.name, {
          flag: true,
          color: p.color,
          checked: String(p.id) === project && workstream === "",
          pick: () => setField(form, "project_id", String(p.id)),
        });
        head._words = p.name.toLowerCase();
        items.push(head);
        for (const m of p.workstreams) {
          const el = item(m.name, {
            indent: true,
            checked: String(m.id) === workstream,
            pick: () => {
              setField(form, "project_id", String(p.id));
              setField(form, "workstream_id", String(m.id));
            },
          });
          el._words = `${p.name} ${m.name}`.toLowerCase();
          el._head = head;
          items.push(el);
        }
      }
      return items;
    }
    return [];
  };

  // Under its button, or above where there is more room; `at` a rect (the
  // "#" a menu of projects drops down from).
  const place = (el, at) => {
    const width = el.offsetWidth;
    const height = el.offsetHeight;
    const below = window.innerHeight - at.bottom;
    if (below >= height + 8 || below >= at.top) {
      el.style.top = `${at.bottom + 4}px`;
    } else {
      // Above, held by its foot, so a menu that filters stays against it as it shortens.
      el.style.bottom = `${window.innerHeight - at.top + 4}px`;
      el.style.maxHeight = `min(360px, 60vh, ${at.top - 12}px)`;
    }
    el.style.left = `${Math.max(8, Math.min(at.left, window.innerWidth - width - 8))}px`;
  };

  /* A menu of projects filters. Opened from its icon it starts with a line
     to find one on; dropped down from a "#" in the title (inline) the title
     itself is that line, and keeps the focus. Either way the keys move an
     active item rather than the focus, Enter takes it, and what the words
     match shows: a workstream with its project above it. */

  let itemIds = 0;
  const shownItems = () => [...menu.el.querySelectorAll(ITEMS)].filter((el) => !el.hidden);
  const setActive = (el) => {
    const { el: box, find } = menu;
    box.querySelector("[data-active]")?.removeAttribute("data-active");
    (find || titleOf(menu.form)).removeAttribute("aria-activedescendant");
    if (!el) return;
    el.dataset.active = "";
    (find || titleOf(menu.form)).setAttribute("aria-activedescendant", el.id);
    // Into view within the menu (scrolling the page would close it).
    if (el.offsetTop < box.scrollTop) box.scrollTop = el.offsetTop - 4;
    else if (el.offsetTop + el.offsetHeight > box.scrollTop + box.clientHeight) {
      box.scrollTop = el.offsetTop + el.offsetHeight - box.clientHeight + 4;
    }
  };
  const stepActive = (step) => {
    const shown = shownItems();
    if (!shown.length) return;
    const at = shown.indexOf(menu.el.querySelector("[data-active]"));
    setActive(shown[at === -1 ? 0 : (at + step + shown.length) % shown.length]);
  };
  // Every word typed is found in an item's words. The active item is the
  // first found, or with nothing typed yet, the current choice. Returns how
  // many are found.
  const filterMenu = (query) => {
    const words = query.toLowerCase().split(/\s+/).filter(Boolean);
    const items = [...menu.el.querySelectorAll(ITEMS)];
    const found = new Set(items.filter((el) => words.every((w) => el._words.includes(w))));
    for (const el of items) el.hidden = !found.has(el) && ![...found].some((f) => f._head === el);
    const empty = menu.el.querySelector(".sheet-menu-empty");
    if (empty) empty.hidden = found.size > 0;
    const current = !words.length && items.find((el) => el.getAttribute("aria-checked") === "true");
    setActive(current || items.find((el) => found.has(el)));
    return found.size;
  };
  const takeActive = () => {
    const el = menu?.el.querySelector("[data-active]");
    if (!el) return false;
    el.click();
    return true;
  };

  // `inline`: dropped down from the title's "#" (hashMenu), with no line of its own.
  const openMenu = (form, button, { inline = null } = {}) => {
    closeMenu(false);
    const sel = document.getSelection();
    const range = sel.rangeCount && form.contains(sel.anchorNode) ? sel.getRangeAt(0).cloneRange() : null;
    // Back to where the writing was: in the sheet, its title; for a sheet of
    // controls only (Today's notepad), whatever held the focus.
    const returnTo = form.contains(document.activeElement)
      ? document.activeElement : titleOf(form) || document.activeElement;
    const el = document.createElement("div");
    el.className = "sheet-menu";
    el.setAttribute("role", "menu");
    el.setAttribute("aria-label", button.title);
    const items = menuItems(form, button.dataset.prop);
    const filters = button.dataset.prop === "project";
    let find = null;
    if (filters) {
      items.forEach((i) => { i.id = `sheet-item-${++itemIds}`; });
      if (!inline) {
        find = document.createElement("input");
        find.type = "text";
        find.className = "sheet-menu-find";
        find.placeholder = "Find a project or workstream";
        find.setAttribute("aria-label", "Find a project or workstream");
        find.autocomplete = "off";
        find.spellcheck = false;
        el.append(find);
      }
    }
    el.append(...items);
    if (filters) {
      const empty = document.createElement("p");
      empty.className = "sheet-menu-empty";
      empty.textContent = "No project or workstream by that name";
      empty.hidden = true;
      el.append(empty);
    }
    if (inline) el.classList.add("inline");
    // In the body, not the sheet: list cards clip what overflows them. In a
    // window (the New task window), in the window, the top layer the body
    // is under.
    (form.closest("dialog") || document.body).append(el);
    menu = { form, button, el, returnTo, range, find, inline };
    // As wide as its widest name, whatever the words narrow it to.
    if (filters) el.style.width = `${el.offsetWidth}px`;
    if (filters) filterMenu(inline ? inline.query : "");
    place(el, inline ? inline.at : button.getBoundingClientRect());
    button.setAttribute("aria-expanded", "true");
    if (inline) return;
    if (find) {
      find.addEventListener("input", () => filterMenu(find.value));
      find.focus();
      return;
    }
    (items.find((i) => i.getAttribute("aria-checked") === "true") || items[0])?.focus();
  };

  const closeMenu = (restore = true) => {
    if (!menu) return;
    const { form, el, button, returnTo, range, inline } = menu;
    menu = null;
    el.remove();
    button.setAttribute("aria-expanded", "false");
    if (inline) {
      titleOf(form).removeAttribute("aria-activedescendant");
      return; // the title kept the focus all along
    }
    // A sheet opened for one field (D or P on a row) is done once its menu is.
    if (form._quick) {
      save(form, { keyboard: true });
      return;
    }
    if (!restore || !returnTo?.isConnected) return;
    returnTo.focus();
    if (range) {
      const sel = document.getSelection();
      sel.removeAllRanges();
      sel.addRange(range);
    }
  };

  // Pressing an icon keeps focus (and the caret) where it was writing; so
  // does pressing an item of a menu dropped down from the title's "#".
  document.addEventListener("pointerdown", (e) => {
    if (e.target.closest?.(".task-sheet .prop, .sheet-actions button, .sheet-menu.inline")) e.preventDefault();
  });

  document.addEventListener("click", (e) => {
    const button = e.target.closest?.(".task-sheet .prop[data-prop]");
    if (button) {
      const open = menu?.button === button && !menu.inline;
      closeMenu(open);
      if (!open) openMenu(sheetOf(button), button);
      return;
    }
    const chosen = e.target.closest?.(`.sheet-menu :is(${ITEMS})`);
    if (chosen && menu) {
      if (menu.inline) fileFromHash(chosen);
      else if (chosen._pick?.() !== "keep") closeMenu();
      return;
    }
    if (menu && !e.target.closest?.(".sheet-menu")) closeMenu(false);
  });

  document.addEventListener("keydown", (e) => {
    if (!menu || e.isComposing) return;
    // A menu that filters: the keys move its active item, wherever the
    // words are written (its line, or the title after a "#").
    const inline = menu.inline && e.target === titleOf(menu.form);
    if (inline || (menu.find && e.target === menu.find)) {
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault();
        stepActive(e.key === "ArrowDown" ? 1 : -1);
      } else if (e.key === "Enter" || (inline && e.key === "Tab" && !e.shiftKey)) {
        // Ctrl+Enter takes it and adds the task too (the sheet's own keys).
        const adding = SUBMIT(e);
        if (!adding) {
          e.preventDefault();
          e.stopPropagation();
        }
        takeActive();
      } else if (e.key === "Escape") {
        e.preventDefault();
        e.stopPropagation();
        closeMenu();
      } else if (e.key === "Tab") {
        e.preventDefault();
        closeMenu();
      } else if (inline && ["ArrowLeft", "ArrowRight", "Home", "End"].includes(e.key)) {
        closeMenu(false);
      }
      return;
    }
    if (!menu.el.contains(e.target)) return;
    const items = [...menu.el.querySelectorAll(ITEMS)];
    const at = items.indexOf(e.target.closest(ITEMS));
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
    if (!form || e.isComposing || isProps(form)) return;
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

    if (isPage(form) && (SUBMIT(e) || e.key === "Escape" || ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s"))) {
      // Saved now; Esc also steps out of the writing, so the page's keys work again.
      e.preventDefault();
      pageSave(form, { now: true });
      if (e.key === "Escape") e.target.blur();
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
        // Focus can stay on the closed window's title, where the page's keys
        // would read every key as typing: it goes back to the page.
        if (dialog.contains(document.activeElement)) document.activeElement.blur();
        return;
      }
      if (!window.TaskCursor?.restore()) e.target.blur();
      return;
    }

    if (inTitle && e.key === "Enter") {
      // Enter moves on to the description, like a heading's next line.
      e.preventDefault();
      if (titleText(form) || !isCompose(form)) {
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
    if (isPage(form)) {
      // A page saves itself (pageSave), never by the browser's submit.
      e.preventDefault();
      e.stopPropagation();
      pageSave(form, { now: true });
      return;
    }
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
    if (form && isCompose(form) && (titleText(form) || hasNotes(form))) form.classList.add("composing");
  });

  document.addEventListener("focusout", (e) => {
    const form = sheetOf(e.target);
    if (!form || !isCompose(form) || form.contains(e.relatedTarget) || menu?.form === form) return;
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
    const inWindow = !!form.closest("dialog");
    let filed = null; // the project and workstream, kept for the window's next task
    if (inWindow) {
      // Written away from any list: say where it went (its project, else its
      // day), offer its page, and let the page's own views of tasks catch up.
      const day = valueOf(form, "planned_for");
      const where = projectLabel(form);
      const when = day ? `for ${shortDate(day)}` : "to No date";
      const open = row && (() => { window.location.href = `/tasks/${row[1].slice(5)}`; });
      window.toast(`Added “${titleText(form)}” ${where ? `to ${where}${day ? `, ${when}` : ""}` : when}`,
        open ? { action: "Open", run: open } : {});
      document.getElementById("capture-sink")?.replaceChildren();
      htmx.trigger(document.body, "calendar:refresh");
      if (filesTask(form)) filed = { project_id: valueOf(form, "project_id"), workstream_id: valueOf(form, "workstream_id") };
    }
    // The list re-rendered while the add was in flight, from a moment before
    // it: the new row went to the old list. Render the lists again.
    if (!e.detail.target?.isConnected) htmx.trigger(document.body, "tasks:changed");
    if (!form.isConnected) return; // its twin took the focus, and no draft
    resetComposer(form);
    // The window stays for the next task, often one more for the same place.
    if (filed) {
      for (const [name, value] of Object.entries(filed)) field(form, name).value = value;
      draw(form);
    }
    placeCaret(titleOf(form), 0); // ready for the next one
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
  }, true);

  // Focus lost to nothing (the window, the browser's own controls) is not
  // leaving the sheet; see Tab below for the page's last control.
  document.addEventListener("focusout", (e) => {
    const form = sheetOf(e.target);
    if (form && isEdit(form) && outside(form, e.relatedTarget)) save(form);
  });

  // The page left with a sheet open (Alt and a number, Ctrl+K, Back): no
  // focus leaves it, so what is written goes as the page does, the request
  // outliving it.
  window.addEventListener("pagehide", () => {
    document.querySelectorAll(".task-sheet[data-sheet='edit']").forEach((form) => {
      convertTrailing(form);
      if (!titleText(form)) setTitle(form, titleOf(form).dataset.original);
      const body = snapshot(form);
      if (body === form._initial) return;
      fetch(form.getAttribute("hx-post"), {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded", "X-CSRF": window.csrfToken() },
        body,
        keepalive: true,
      });
    });
  });

  // Tab past a sheet's last control leaves it, even where nothing on the
  // page comes after it to take the focus (it would go to the browser).
  const TABBABLE = "button:not([hidden]), input:not([type='hidden']), [contenteditable], [tabindex='0']";
  document.addEventListener("keydown", (e) => {
    if (e.key !== "Tab" || e.shiftKey || e.defaultPrevented) return;
    const form = sheetOf(e.target);
    if (!form || !isEdit(form)) return;
    const stops = [...form.querySelectorAll(TABBABLE)].filter((el) => el.tabIndex >= 0 && el.checkVisibility());
    if (e.target !== stops[stops.length - 1]) return;
    e.preventDefault();
    save(form, { keyboard: true });
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
    setField(form, "status", NEXT_STATUS[valueOf(form, "status")] || "todo");
  });

  /* ---- a task's page: saved as it is written ---- */

  const PAGE_PAUSE_MS = 900;
  const pageState = () => document.querySelector("[data-page-state]");
  const sayState = (text) => {
    const el = pageState();
    if (el) el.textContent = text;
  };

  // A change waits for the writing to pause (`paused`). `now`: saved at
  // once, the title's trailing words taken as fields, as the edit sheet's
  // save takes them; `leaving`: the page is going, so the request must
  // outlive it. Saves go one at a time, and a save asked for while one is
  // in flight follows it with what is newest.
  // The header says "Saved" once one is, nothing while there is writing
  // still to save, and "Not saved" if one fails.
  const pageSave = (form, { now = false, leaving = false, paused = false } = {}) => {
    clearTimeout(form._pause);
    if (form._deleted) return;
    if (!now && !leaving && !paused) {
      form._pause = setTimeout(() => pageSave(form, { paused: true }), PAGE_PAUSE_MS);
      // "Saved" never stands over words that are not.
      if (snapshot(form) !== form._saved) sayState("");
      return;
    }
    if (now) {
      // Its fields, set as the words are taken, are this same save.
      if (form._taking) return;
      form._taking = true;
      try { convertTrailing(form); } finally { form._taking = false; }
    }
    if (!titleText(form)) {
      if (!now) return; // a title being rewritten is not saved empty
      setTitle(form, titleOf(form).dataset.original);
    }
    const body = snapshot(form);
    if (body === form._saved) return;
    if (form._sending && !leaving) {
      form._again = true;
      return;
    }
    form._sending = true;
    fetch(`/ui/tasks/${form.dataset.taskId}/page`, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded", "X-CSRF": window.csrfToken() },
      body,
      keepalive: leaving,
    }).then(async (res) => {
      if (!res.ok) {
        const answer = await res.json().catch(() => ({}));
        throw new Error(typeof answer.detail === "string" ? answer.detail : "");
      }
      form._saved = body;
      titleOf(form).dataset.original = titleText(form);
      document.title = `${titleText(form)} · Personal Calendar`;
      sayState("Saved");
    }).catch((err) => {
      sayState("Not saved");
      window.toast(err.message || "Could not save the task. Try again?");
    }).finally(() => {
      form._sending = false;
      if (form._again) {
        form._again = false;
        pageSave(form, { paused: true });
      }
    });
  };

  const initPage = (form) => {
    form._saved = snapshot(form);
    // Whatever writes in it: words, a sub-task's box; a field chosen, or
    // the box ticked, is saved at once.
    const changed = () => pageSave(form);
    for (const type of ["input", "keyup", "click", "paste", "cut", "drop"]) {
      form.addEventListener(type, changed);
    }
    form.addEventListener("sheet:field", () => pageSave(form, { now: true }));
    // The title's trailing words become fields as it is left.
    form.addEventListener("focusout", (e) => {
      if (e.target === titleOf(form)) pageSave(form, { now: true });
    });
    // Deleted, it goes without saving what it held.
    form.addEventListener("htmx:beforeRequest", (e) => {
      if (e.detail.elt.matches(".task-delete")) form._deleted = true;
    });
    const leave = () => pageSave(form, { leaving: true });
    window.addEventListener("pagehide", leave);
    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState === "hidden") leave();
    });
    // A new task, still to be written out, opens on its description.
    if (!hasNotes(form)) window.NotesEditor.focusEnd(notesEditorOf(form));
  };

  /* ---- ready: labels drawn, an opened editor takes the caret ---- */

  const init = (form) => {
    if (form.dataset.ready != null) return;
    form.dataset.ready = "";
    // A sheet of controls only (a task row's in Today's notepad): its icons
    // and their menus, nothing to write in or post.
    if (form.dataset.sheet === "props") {
      draw(form);
      return;
    }
    syncTitle(form);
    draw(form);
    if (isPage(form)) {
      initPage(form);
      return;
    }
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

  let pending = null; // {id, field, landOnChange, row}: an edit to open on one field's menu
  window.TaskSheet = {
    // Redraw a sheet's icons from its fields, set from outside (a habit's
    // days, changed from its other place on the page).
    refresh(form) {
      draw(form);
    },
    // For Today's notes, whose task titles take the same words: the field
    // the words ending `text` make ({name, value, start}), or null.
    fieldOfWords,
    // Set one field of a sheet of controls, as its menus do (sheet:field).
    setField(form, name, value) {
      setField(form, name, value);
    },
    // Edit a row's task with one field's menu open; choosing (or Esc) saves.
    edit(row, field, landOnChange) {
      pending = { id: row.id, field, landOnChange, row };
      row.querySelector(".task-title-btn").click();
    },
    // Start writing in a composer (N).
    compose(form) {
      if (!form) return;
      form.scrollIntoView({ block: "nearest" });
      const title = titleOf(form);
      placeCaret(title, title.textContent.length);
    },
    // Start writing in the New task window, just opened: a draft left in it
    // stays, else it starts afresh, in the page's project if it has one.
    capture(form) {
      if (!form) return;
      if (!titleText(form) && !hasNotes(form)) resetComposer(form);
      this.compose(form);
    },
  };
  // A list re-rendered while such an edit was on its way (D, then P at
  // once): the row it was opened from is gone, and its sheet would land in
  // that row, unseen. It opens again on the row's live twin.
  document.addEventListener("htmx:afterSettle", () => {
    if (!pending?.row || pending.row.isConnected) return;
    const twin = document.getElementById(pending.id);
    if (!twin || twin.querySelector(".task-sheet")) return;
    pending.row = twin;
    twin.querySelector(".task-title-btn")?.click();
  });
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

  // The task lists (a project's Tasks, Plan) re-render from the server
  // whenever the plan changes, composers included. Carry a half-written task, its fields
  // and focus over to the fresh composer with the same key.
  const FIELDS = ["planned_for", "due", "repeat", "estimate", "priority", "project_id"];
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
