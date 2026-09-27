/* A day's notepad (today.html): plain text, saved as it is written.

   The page saves a moment after each change, when the tab is hidden, and
   when it is left, as a whole (POST /ui/notebook/<day>). A save names the
   version it was made from; one refused because another window saved
   since stops the saving and asks which to keep. Coming back to the tab
   shows a newer version, when nothing here is still to be saved.
   Left and Right, outside the text, go a day back or on. Rows are numbered
   down the left, as in a spreadsheet, the caret's row in ink.

   A task is written in the notes: "- [ ] " at a row's start opens one, and
   the rows it covers are marked until it is closed. Its first row is the
   title; rows added under it with Enter are its description ("- " rows its
   sub-tasks). Ctrl+Enter closes it and goes on to the next row, Esc closes
   it where it is; closing adds the task for the day, and the text stays in
   the notes as written. */

(() => {
  const SAVE_AFTER_MS = 600;
  const RETRY_AFTER_MS = 4000;

  const pad = () => document.getElementById("notepad");
  const staleBar = () => document.getElementById("pad-stale");

  let version = 0;
  let saved = "";
  let timer = 0;
  let inflight = false;
  let again = false;
  let stale = false;
  let theirs = 0;

  const pending = () => !!pad() && pad().value !== saved;
  const schedule = () => {
    clearTimeout(timer);
    timer = setTimeout(flush, SAVE_AFTER_MS);
  };

  async function flush({ leaving = false } = {}) {
    clearTimeout(timer);
    const el = pad();
    if (!el || stale || !pending()) return;
    if (inflight && !leaving) {
      again = true;
      return;
    }
    const text = el.value;
    const request = fetch(`/ui/notebook/${el.dataset.day}`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRF": window.csrfToken() },
      body: JSON.stringify({ version, blocks: text.trim() ? [{ kind: "text", text }] : [] }),
      keepalive: leaving,
    });
    if (leaving) return;
    inflight = true;
    try {
      const res = await request;
      const answer = await res.json().catch(() => ({}));
      if (res.ok) {
        version = answer.version;
        saved = text;
      } else if (res.status === 409) {
        stale = true;
        theirs = answer.version;
        staleBar().hidden = false;
      } else {
        window.toast(answer.detail || "Could not save the notes.");
      }
    } catch {
      // Offline for a moment: what is written stays here and goes later.
      setTimeout(schedule, RETRY_AFTER_MS);
    } finally {
      inflight = false;
    }
    if (again) {
      again = false;
      flush();
    }
  }

  document.addEventListener("input", (e) => {
    if (e.target === pad()) schedule();
  });

  document.addEventListener("click", (e) => {
    if (e.target.closest?.("[data-pad-reload]")) {
      stale = true; // what is here is being let go
      location.reload();
    } else if (e.target.closest?.("[data-pad-keep]")) {
      stale = false;
      version = theirs;
      staleBar().hidden = true;
      flush();
    }
  });

  // Back to notes written elsewhere since (the phone, another window).
  const refresh = async () => {
    const el = pad();
    if (!el || stale || pending() || document.activeElement === el) return;
    const res = await fetch(`/ui/notebook/${el.dataset.day}/version`).catch(() => null);
    const answer = res?.ok ? await res.json() : null;
    if (!answer || answer.version <= version) return;
    const page = await fetch(location.pathname).then((r) => r.text()).catch(() => null);
    const fresh = page && new DOMParser().parseFromString(page, "text/html").getElementById("notepad");
    if (!fresh || pending() || document.activeElement === el) return;
    el.value = fresh.value;
    saved = fresh.value;
    version = Number(fresh.dataset.version) || answer.version;
  };

  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") flush();
    else refresh();
  });
  window.addEventListener("pagehide", () => {
    if (pending()) flush({ leaving: true });
  });

  // Esc steps out of the text; Left and Right, outside it, change the day.
  document.addEventListener("keydown", (e) => {
    if (e.target === pad() && task && (e.key === "Escape" || (e.key === "Enter" && (e.ctrlKey || e.metaKey)))) {
      e.preventDefault();
      closeTask({ nextRow: e.key === "Enter" });
      return;
    }
    if (e.target === pad() && e.key === "Escape") {
      pad().blur();
      return;
    }
    if (e.ctrlKey || e.metaKey || e.altKey || e.isComposing || e.defaultPrevented) return;
    if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
    if (e.target.closest?.("input, textarea, select, [contenteditable]") || document.querySelector("dialog[open]")) return;
    const link = document.querySelector(`[data-day-step="${e.key === "ArrowLeft" ? "prev" : "next"}"]`);
    if (!link) return;
    e.preventDefault();
    flush();
    link.click();
  });

  /* ---- row numbers, down the left like a spreadsheet's ---- */

  const rowsOf = () => document.querySelector(".pad-rows-inner");
  const lineHeight = () => parseFloat(getComputedStyle(pad()).lineHeight) || 36;
  const numberRows = () => {
    const el = pad();
    const rows = rowsOf();
    if (!el || !rows) return;
    const written = el.value.split("\n").length;
    const shown = Math.ceil(el.clientHeight / lineHeight()) + 1;
    const count = Math.max(written, shown) + Math.ceil(el.scrollTop / lineHeight());
    if (rows.childElementCount !== count) {
      rows.replaceChildren(...Array.from({ length: count }, (_, i) => {
        const row = document.createElement("div");
        row.textContent = String(i + 1);
        return row;
      }));
    }
    rows.style.transform = `translateY(${-el.scrollTop}px)`;
    const here = el.value.slice(0, el.selectionStart).split("\n").length - 1;
    [...rows.children].forEach((row, i) => {
      row.classList.toggle("here", i === here && document.activeElement === el);
      row.classList.toggle("task", !!task && i >= task.start && i <= task.end);
    });
    const mark = document.querySelector(".pad-task-mark");
    if (mark) {
      mark.hidden = !task;
      if (task) {
        mark.style.top = `${task.start * lineHeight() - el.scrollTop}px`;
        mark.style.height = `${(task.end - task.start + 1) * lineHeight()}px`;
      }
    }
  };

  /* ---- a task written in the notes ---- */

  const OPENS = /^- \[ \] /;
  let task = null; // {start, end}: the rows the open task covers
  let lineCount = 0;

  const linesOf = () => pad().value.split("\n");
  const caretRow = () => pad().value.slice(0, pad().selectionStart).split("\n").length - 1;

  // Typing follows the task: rows added inside it grow it, and a first row
  // that no longer opens one drops it.
  const followTask = () => {
    const lines = linesOf();
    const delta = lines.length - lineCount;
    lineCount = lines.length;
    const row = caretRow();
    if (task) {
      if (delta && row >= task.start && row - Math.max(delta, 0) <= task.end) task.end = Math.max(task.start, task.end + delta);
      if (!OPENS.test(lines[task.start] || "")) task = null;
      return;
    }
    const line = lines[row];
    const col = pad().selectionStart - lines.slice(0, row).join("\n").length - (row ? 1 : 0);
    if (line.startsWith("- [ ] ") && col === 6) task = { start: row, end: row };
  };

  async function closeTask({ nextRow }) {
    const el = pad();
    const lines = linesOf();
    const { start, end } = task;
    task = null;
    const title = lines[start].replace(OPENS, "").trim();
    const notes = lines.slice(start + 1, end + 1).join("\n");
    if (nextRow) {
      // On to a fresh row under the task.
      const at = lines.slice(0, end + 1).join("\n").length;
      el.setRangeText("\n", at, at, "end");
      el.dispatchEvent(new Event("input", { bubbles: true }));
    }
    numberRows();
    if (!title) return;
    const day = el.dataset.day;
    const res = await fetch("/ui/tasks/quick-add", {
      method: "POST",
      headers: { "X-CSRF": window.csrfToken() },
      body: new URLSearchParams({ title, notes, planned_for: day, list_day: day }),
    }).catch(() => null);
    if (res?.ok) {
      window.toast(`Task added: ${title}`);
      htmx.trigger(document.body, "calendar:refresh");
    } else {
      window.toast("Could not add that task. Its words are still in the notes.");
    }
  }

  document.addEventListener("input", (e) => {
    if (e.target === pad()) followTask();
  }, true);
  // Leaving the page with a task open still adds it.
  window.addEventListener("pagehide", () => {
    if (!task) return;
    const lines = linesOf();
    const title = lines[task.start].replace(OPENS, "").trim();
    if (!title) return;
    const day = pad().dataset.day;
    fetch("/ui/tasks/quick-add", {
      method: "POST",
      headers: { "X-CSRF": window.csrfToken() },
      body: new URLSearchParams({ title, notes: lines.slice(task.start + 1, task.end + 1).join("\n"), planned_for: day, list_day: day }),
      keepalive: true,
    });
  });
  ["input", "scroll", "keyup", "click", "focus", "blur"].forEach((type) => {
    document.addEventListener(type, (e) => {
      if (e.target === pad()) numberRows();
    }, true);
  });
  window.addEventListener("resize", numberRows);

  const el = pad();
  if (el) {
    version = Number(el.dataset.version) || 0;
    saved = el.value;
    lineCount = el.value.split("\n").length;
    numberRows();
  }
})();
