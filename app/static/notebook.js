/* The notebook: a day page (today.html) written like a document.

   The page is a column of blocks (partials/notebook_block.html): prose,
   tasks and reflections, with a prose block around every box, so there is
   always a line to write on before, between and after them. Prose and
   reflections are notes-editor.js in prose mode; a task is its row, and
   while it is being written, the task sheet in a box (task-sheet.js).

   Writing:
   - "- " at the start of a line opens a task box there, the rest of the
     line its title; Ctrl+Enter or Esc closes it (the task is added and
     takes the box's place), as does moving on to write elsewhere. An empty
     box closes to nothing; Backspace in its empty title puts the line back.
   - "/" at the start of a line offers the commands (Reflection, Task);
     Enter or Tab takes the highlighted one. A reflection is free text in a
     box of its own, closed by Ctrl+Enter or Esc.
   - Up and Down at a block's edge move to the next block, a task row
     included (its keys then work as in any list: X, E, D, Delete…); N adds
     a task box at the end; Left and Right, outside the text, go a day back
     or on.

   The page saves itself as it is written, as a whole, a moment after each
   change and when the tab is left; a save from a copy older than the
   server's (another window) is refused, and the page asks which to keep.
   Tasks are saved on their own, by the sheet, and only referenced here.
   Listeners sit on document, so they survive htmx swaps. */

(() => {
  const SAVE_AFTER_MS = 600;
  const RETRY_AFTER_MS = 4000;

  const notebook = () => document.getElementById("notebook");
  const Editor = () => window.NotesEditor;
  const blocks = () => [...(notebook()?.children || [])].filter((el) => el.dataset.block);
  const blockOf = (el) => {
    const root = notebook();
    let node = el;
    while (node && node.parentElement !== root) node = node.parentElement;
    return node && root ? node : null;
  };
  const kind = (block) => block?.dataset.block;
  const editorOf = (block) => block?.querySelector("[data-notes-editor]");
  const prose = (el) => el?.closest?.("#notebook [data-notes-editor='prose']");
  const texts = (block) => Editor().texts(editorOf(block));
  const isBlank = (lines) => lines.length === 1 && lines[0] === "";

  /* ---- the page, as it saves ---- */

  const serialize = () =>
    blocks().flatMap((block) => {
      const k = kind(block);
      if (k === "text" || k === "reflection") {
        return [{ kind: k, text: block.querySelector("textarea").value }];
      }
      if (k === "task") return [{ kind: "task", id: Number(block.dataset.taskId) }];
      return []; // a box still being written joins once it is added
    });

  let version = 0;
  let saved = ""; // what the server has, as serialized
  let timer = 0;
  let inflight = null;
  let again = false;
  let stale = false;

  const pending = () => notebook() && JSON.stringify(serialize()) !== saved;

  const schedule = () => {
    clearTimeout(timer);
    timer = setTimeout(flush, SAVE_AFTER_MS);
  };

  async function flush({ leaving = false } = {}) {
    clearTimeout(timer);
    const root = notebook();
    if (!root || stale) return;
    if (inflight && !leaving) {
      again = true;
      return;
    }
    const page = serialize();
    const body = JSON.stringify(page);
    if (body === saved) return;
    const request = fetch(`/ui/notebook/${root.dataset.day}`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRF": window.csrfToken() },
      body: JSON.stringify({ version, blocks: page }),
      keepalive: leaving,
    });
    if (leaving) return;
    inflight = request;
    try {
      const res = await request;
      const answer = await res.json().catch(() => ({}));
      if (res.ok) {
        version = answer.version;
        root.dataset.version = String(version);
        saved = body;
        recount();
      } else if (res.status === 409) {
        showStale(answer.version);
      } else {
        window.toast(answer.detail || "Could not save the page.");
      }
    } catch {
      // Offline for a moment: what is written stays here and goes later.
      setTimeout(schedule, RETRY_AFTER_MS);
    } finally {
      inflight = null;
    }
    if (again) {
      again = false;
      flush();
    }
  }

  // The sheet's title block counts what was saved. Read on its own, not
  // through htmx, whose queue drops a read that meets one in flight; one
  // more read follows when saves land during one.
  let counting = false;
  let recountAgain = false;
  async function recount() {
    if (counting) {
      recountAgain = true;
      return;
    }
    counting = true;
    try {
      const res = await fetch(location.pathname, { headers: { "X-Row-Context": "day" } });
      const fresh = new DOMParser().parseFromString(await res.text(), "text/html").getElementById("day-rest");
      if (fresh) document.getElementById("day-rest")?.replaceWith(fresh);
    } catch { /* the next save counts again */ }
    counting = false;
    if (recountAgain) {
      recountAgain = false;
      recount();
    }
  }

  /* ---- another window saved the page ---- */

  let theirs = 0;
  const showStale = (serverVersion) => {
    stale = true;
    theirs = serverVersion;
    document.getElementById("nb-stale").hidden = false;
  };
  document.addEventListener("click", (e) => {
    if (e.target.closest?.("[data-nb-reload]")) {
      stale = true; // what is here is being let go
      location.reload();
    } else if (e.target.closest?.("[data-nb-keep]")) {
      stale = false;
      version = theirs;
      document.getElementById("nb-stale").hidden = true;
      flush();
    }
  });

  // Back to a page written elsewhere since (the phone, another window): the
  // latest shows, unless something here is still to be saved.
  const refresh = async () => {
    const root = notebook();
    if (!root || stale || pending() || document.querySelector("#notebook .nb-draft")) return;
    if (root.contains(document.activeElement) && document.activeElement !== document.body) return;
    const res = await fetch(`/ui/notebook/${root.dataset.day}/version`).catch(() => null);
    const answer = res?.ok ? await res.json() : null;
    if (!answer || answer.version <= version || pending()) return;
    htmx.ajax("GET", location.pathname, { target: "#notebook", select: "#notebook", swap: "outerHTML" });
  };

  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") flush();
    else refresh();
  });
  window.addEventListener("pagehide", () => {
    writeOpenBoxes();
    if (pending()) flush({ leaving: true });
  });

  /* ---- building blocks ---- */

  const fromTemplate = (id) => document.getElementById(id).content.firstElementChild.cloneNode(true);

  // New content is taken up as htmx takes up what it swaps in.
  const activate = (el) => {
    htmx.process(el);
    el.dispatchEvent(new CustomEvent("htmx:load", { bubbles: true, detail: { elt: el } }));
  };

  const textBlock = (lines) => {
    const block = fromTemplate("nb-text-template");
    block.querySelector("textarea").value = lines.join("\n");
    return block;
  };

  const focusTitle = (box) => {
    const form = box.querySelector(".task-sheet");
    window.TaskSheet.compose(form);
  };

  // Open a box in a prose block at line `at`: the lines before stay, the
  // line itself goes (its `seed` becomes the box's first words), and the
  // lines after follow the box as prose of their own.
  const openBox = (block, at, boxKind, seed = "") => {
    const lines = texts(block);
    const before = lines.slice(0, at);
    const after = lines.slice(at + 1);
    // Blank lines left over above the box only space it; the sheet's rule does that.
    while (before.length && !before[before.length - 1].trim()) before.pop();
    Editor().set(editorOf(block), before.length ? before : [""]);
    const box = fromTemplate(boxKind === "task" ? "nb-draft-template" : "nb-reflection-template");
    if (boxKind === "task") {
      const title = box.querySelector(".sheet-title");
      title.textContent = seed;
    } else {
      box.querySelector("textarea").value = seed;
    }
    const rest = textBlock(after.length ? after : [""]);
    block.after(box, rest);
    activate(box);
    activate(rest);
    if (boxKind === "task") focusTitle(box);
    else Editor().focusEnd(editorOf(box));
    schedule();
    return box;
  };

  // Take a box away and join the prose around it, with `line` put back
  // where the box was (null: nothing). The caret goes there, if `focus`.
  const closeBox = (box, { line = null, focus = true } = {}) => {
    const above = box.previousElementSibling;
    const below = box.nextElementSibling;
    if (kind(above) !== "text" || kind(below) !== "text") {
      box.remove();
      schedule();
      return;
    }
    const top = isBlank(texts(above)) ? [] : texts(above);
    const bottom = isBlank(texts(below)) ? [] : texts(below);
    const middle = line === null ? [] : [line];
    const joined = [...top, ...middle, ...bottom];
    const caretLine = line === null ? Math.max(0, top.length - 1) : top.length;
    const caretAt = line === null ? (top.length ? top[top.length - 1].length : 0) : line.length;
    box.remove();
    below.remove();
    Editor().set(editorOf(above), joined.length ? joined : [""], focus ? caretLine : null, caretAt);
    schedule();
  };

  // On from a closed box: the start of the prose after it.
  const after = (box) => {
    const next = box.nextElementSibling;
    if (kind(next) === "text") Editor().place(editorOf(next), 0, 0);
  };

  // A box still being written when the page is left is written down anyway.
  const writeOpenBoxes = () => {
    document.querySelectorAll("#notebook .nb-draft .task-sheet").forEach((form) => {
      if (!form.elements.title.value.trim() || form.dataset.sending != null) return;
      const data = new URLSearchParams(new FormData(form));
      fetch("/ui/tasks/quick-add", {
        method: "POST",
        headers: { "X-CSRF": window.csrfToken() },
        body: data,
        keepalive: true,
      });
    });
  };

  /* ---- moving between blocks ---- */

  const caretRect = () => {
    const sel = getSelection();
    if (!sel.rangeCount) return null;
    const range = sel.getRangeAt(0).cloneRange();
    range.collapse(true);
    const rects = range.getClientRects();
    if (rects.length) return rects[0];
    // An empty line has no rects of its own: its line does.
    const node = range.startContainer.nodeType === 1 ? range.startContainer : range.startContainer.parentElement;
    return node.closest(".ln")?.getBoundingClientRect() || null;
  };
  // Is the caret on the editor's first (or last) row as drawn, wrapped lines included?
  const onEdgeRow = (editor, last) => {
    const caret = caretRect();
    const line = last ? editor.lastElementChild : editor.firstElementChild;
    if (!caret || !line) return true;
    const box = line.getBoundingClientRect();
    const rowHeight = parseFloat(getComputedStyle(editor).lineHeight) || 20;
    return last ? box.bottom - caret.bottom < rowHeight / 2 : caret.top - box.top < rowHeight / 2;
  };

  // Enter a block from above (start) or below (end).
  const enter = (block, fromBelow) => {
    if (!block) return false;
    const k = kind(block);
    if (k === "text" || k === "reflection") {
      const editor = editorOf(block);
      if (fromBelow) Editor().focusEnd(editor);
      else Editor().place(editor, 0, 0);
      return true;
    }
    if (k === "task" && block.matches("ul")) {
      const row = block.querySelector(".task-row[tabindex]");
      if (row) {
        row.focus({ focusVisible: true });
        row.scrollIntoView({ block: "nearest" });
        return true;
      }
    }
    if (k === "draft") {
      focusTitle(block);
      return true;
    }
    // A deleted task's line: past it.
    return enter(fromBelow ? block.previousElementSibling : block.nextElementSibling, fromBelow);
  };

  /* ---- "- " opens a task box ---- */

  document.addEventListener("beforeinput", (e) => {
    const editor = prose(e.target);
    if (!editor || e.inputType !== "insertText" || e.data !== " ") return;
    const block = blockOf(editor);
    if (kind(block) !== "text") return; // a reflection is free text
    const caret = Editor().caret(editor);
    const sel = getSelection();
    if (!caret || !sel.isCollapsed) return;
    const line = texts(block)[caret.i];
    if (caret.o !== 1 || line[0] !== "-") return;
    e.preventDefault();
    e.stopImmediatePropagation();
    openBox(block, caret.i, "task", line.slice(1).trimStart());
  }, true);

  /* ---- "/" offers the commands ---- */

  const COMMANDS = [
    { name: "reflection", label: "Reflection", hint: "free text about the day" },
    { name: "task", label: "Task", hint: "as a line starting with -" },
  ];
  let slash = null; // {el, editor, block, line, items, at}

  const closeSlash = () => {
    slash?.el.remove();
    slash = null;
  };

  const drawSlash = () => {
    slash.items.forEach((item, n) => item.el.setAttribute("aria-selected", String(n === slash.at)));
  };

  const openSlash = (editor, block, lineIndex, query) => {
    const matches = COMMANDS.filter((c) => c.name.startsWith(query.toLowerCase()));
    if (!matches.length) return closeSlash();
    if (!slash) {
      const el = document.createElement("div");
      el.className = "sheet-menu nb-slash";
      el.setAttribute("role", "listbox");
      el.setAttribute("aria-label", "Commands");
      document.body.append(el);
      slash = { el };
    }
    const previous = slash.items?.[slash.at]?.command.name;
    slash.editor = editor;
    slash.block = block;
    slash.line = lineIndex;
    slash.items = matches.map((command) => {
      const el = document.createElement("div");
      el.setAttribute("role", "option");
      el.className = "nb-slash-item";
      el.innerHTML = '<span class="label"></span><span class="aside"></span>';
      el.querySelector(".label").textContent = command.label;
      el.querySelector(".aside").textContent = command.hint;
      el.addEventListener("pointerdown", (e) => {
        e.preventDefault();
        run(command);
      });
      return { el, command };
    });
    slash.at = Math.max(0, slash.items.findIndex((i) => i.command.name === previous));
    slash.el.replaceChildren(...slash.items.map((i) => i.el));
    drawSlash();
    const at = caretRect();
    if (at) {
      slash.el.style.left = `${Math.max(8, Math.min(at.left, innerWidth - slash.el.offsetWidth - 8))}px`;
      const below = at.bottom + 6 + slash.el.offsetHeight < innerHeight;
      slash.el.style.top = `${below ? at.bottom + 6 : at.top - slash.el.offsetHeight - 6}px`;
    }
  };

  const run = (command) => {
    const { block, line } = slash;
    closeSlash();
    const words = texts(block)[line];
    const rest = words.replace(/^\/\S*\s?/, "");
    openBox(block, line, command.name, rest);
  };

  document.addEventListener("input", (e) => {
    const editor = prose(e.target);
    if (!editor) return;
    const block = blockOf(editor);
    const caret = Editor().caret(editor);
    const typed = caret && kind(block) === "text" ? texts(block)[caret.i].slice(0, caret.o) : "";
    const m = /^\/([a-z]*)$/i.exec(typed);
    if (m) openSlash(editor, block, caret.i, m[1]);
    else closeSlash();
  });
  document.addEventListener("focusout", (e) => {
    if (slash && e.target === slash.editor) closeSlash();
  });
  window.addEventListener("resize", closeSlash);

  /* ---- keys ---- */

  const TYPING = "input, textarea, select, [contenteditable]";

  document.addEventListener("keydown", (e) => {
    if (!notebook() || e.isComposing) return;
    const mod = e.ctrlKey || e.metaKey || e.altKey;

    // The command menu, while it is open, has the keys it names.
    if (slash) {
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault();
        e.stopImmediatePropagation();
        const step = e.key === "ArrowDown" ? 1 : -1;
        slash.at = (slash.at + step + slash.items.length) % slash.items.length;
        drawSlash();
        return;
      }
      if ((e.key === "Enter" || e.key === "Tab") && !mod && !e.shiftKey) {
        e.preventDefault();
        e.stopImmediatePropagation();
        run(slash.items[slash.at].command);
        return;
      }
      if (e.key === "Escape") {
        e.preventDefault();
        e.stopImmediatePropagation();
        closeSlash();
        return;
      }
    }

    const editor = prose(e.target);
    if (editor) {
      const block = blockOf(editor);
      const caret = Editor().caret(editor);
      const collapsed = getSelection().isCollapsed;

      if (kind(block) === "reflection" && (e.key === "Escape" || (e.key === "Enter" && (e.ctrlKey || e.metaKey)))) {
        e.preventDefault();
        if (isBlank(texts(block))) closeBox(block);
        else after(block);
        return;
      }
      if (kind(block) === "text" && e.key === "Escape") {
        e.preventDefault();
        editor.blur();
        return;
      }
      if (mod || e.shiftKey || !caret || !collapsed) return;

      if (e.key === "ArrowUp" && caret.i === 0 && onEdgeRow(editor, false)) {
        if (enter(block.previousElementSibling, true)) e.preventDefault();
        return;
      }
      if (e.key === "ArrowDown" && caret.i === texts(block).length - 1 && onEdgeRow(editor, true)) {
        if (enter(block.nextElementSibling, false)) e.preventDefault();
        return;
      }
      if (e.key === "Backspace" && caret.i === 0 && caret.o === 0) {
        if (kind(block) === "reflection") {
          // An empty reflection goes; otherwise the start of its text stays put.
          e.preventDefault();
          if (isBlank(texts(block))) closeBox(block, { line: "" });
          return;
        }
        const above = block.previousElementSibling;
        if (!above) return;
        e.preventDefault();
        if (above.matches(".nb-gone")) closeBox(above, { line: null });
        else enter(above, true);
      }
      return;
    }

    // A box's empty title: Backspace puts the line back as it was, a dash gone.
    const title = e.target.closest?.("#notebook .nb-draft .sheet-title");
    if (title && e.key === "Backspace" && !mod && title.textContent === "") {
      const form = title.closest(".task-sheet");
      if (!form.elements.notes.value.trim()) {
        e.preventDefault();
        e.stopImmediatePropagation();
        form.dataset.closing = "";
        closeBox(blockOf(title), { line: "" });
      }
      return;
    }

    if (mod || e.target.closest?.(TYPING) || document.querySelector("dialog[open]")) return;

    // A task row in the page: Up and Down go on through the page's blocks.
    const row = e.target.closest?.("#notebook .task-row");
    if (row && !e.shiftKey && ["ArrowUp", "ArrowDown", "k", "j"].includes(e.key)) {
      const block = blockOf(row);
      const up = e.key === "ArrowUp" || e.key === "k";
      e.preventDefault();
      enter(up ? block.previousElementSibling : block.nextElementSibling, up);
      return;
    }

    if (e.key === "n" || e.key === "N") {
      // A new task, at the end of the page.
      e.preventDefault();
      const last = blocks().filter((b) => kind(b) === "text").pop();
      const lines = texts(last);
      openBox(last, isBlank(lines) ? 0 : lines.length, "task");
      return;
    }

    if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
      const link = document.querySelector(`[data-day-step="${e.key === "ArrowLeft" ? "prev" : "next"}"]`);
      if (!link) return;
      e.preventDefault();
      flush();
      link.click();
    }
  }, true);

  // A click on the page's margin, or on a blank frame under what is written, writes at its end.
  document.addEventListener("pointerdown", (e) => {
    const root = notebook();
    if (e.target !== root && !e.target.closest?.(".sb-blank")) return;
    const last = blocks().filter((b) => kind(b) === "text").pop();
    if (!last) return;
    const lastBox = last.getBoundingClientRect();
    if (e.clientY < lastBox.top) return;
    e.preventDefault();
    Editor().focusEnd(editorOf(last));
  });

  /* ---- boxes closing ---- */

  // An empty task box, closed: gone, and the caret back where it was written.
  document.addEventListener("notebook:discard", (e) => {
    const box = blockOf(e.target);
    if (!box) return;
    const here = box.contains(document.activeElement) || document.activeElement === document.body;
    closeBox(box, { focus: here });
  });

  // An empty reflection left behind is not kept.
  document.addEventListener("focusout", (e) => {
    const editor = prose(e.target);
    const block = editor && blockOf(editor);
    if (kind(block) !== "reflection" || block.contains(e.relatedTarget)) return;
    if (isBlank(texts(block))) closeBox(block, { focus: false });
  });

  // A task added from its box has taken the box's place: on to the next line
  // (unless the writer already moved on elsewhere), and the page saves.
  document.addEventListener("htmx:load", (e) => {
    const el = e.detail.elt;
    if (el?.id === "notebook") {
      start(el);
      return;
    }
    if (!el?.matches?.("#notebook > ul.nb-task")) return;
    if (!document.activeElement || document.activeElement === document.body) after(el);
    schedule();
  });

  // A task deleted from the page (its row's bin, or its sheet's) leaves an
  // empty block behind: it goes, and the prose around it joins up.
  const tidy = () => {
    document.querySelectorAll("#notebook > ul.nb-task").forEach((block) => {
      if (!block.querySelector("li")) closeBox(block, { focus: false });
    });
  };

  document.addEventListener("click", (e) => {
    const remove = e.target.closest?.("[data-nb-remove]");
    if (remove) closeBox(blockOf(remove), { focus: false });
  });

  // Any change to the text, however it came, is saved a moment later.
  document.addEventListener("notes:change", (e) => {
    if (prose(e.target) && !starting) schedule();
  });

  /* ---- start ---- */

  let starting = false;
  let observer = null;
  function start(root) {
    starting = true;
    version = Number(root.dataset.version) || 0;
    saved = JSON.stringify(serialize());
    starting = false;
    observer?.disconnect();
    observer = new MutationObserver(tidy);
    observer.observe(root, { childList: true, subtree: true });
  }
  const initial = notebook();
  if (initial) start(initial);
})();
