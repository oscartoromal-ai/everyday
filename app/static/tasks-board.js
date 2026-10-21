/* Board, a view of a project's Tasks tab (partials/project_tasks/board.html):
   what the board does beyond every view's keys, filing and folds (tasks.js,
   tasks-views.js):
   - Left and Right (keys.py's list.left and list.right) move the cursor to
     the card level with it in the next column that has one;
   - the board drawn again (after every change) keeps where it was scrolled,
     sideways and in each column. */
(() => {
  const board = () => document.querySelector(".tasks-in-board .board");

  /* ---- the keys: across the columns ---- */

  document.addEventListener("keydown", (e) => {
    const step = window.Keys?.is(e, "list.right") ? 1 : window.Keys?.is(e, "list.left") ? -1 : 0;
    if (!step || e.defaultPrevented || e.isComposing) return;
    // The cursor itself, not a control inside its card.
    const card = e.target.closest?.(".tasks-in-board .board-card[tabindex]");
    if (!card || card !== e.target) return;
    e.preventDefault();
    const columns = [...document.querySelectorAll(".tasks-in-board .board-column")];
    const level = card.getBoundingClientRect().top;
    for (let at = columns.indexOf(card.closest(".board-column")) + step; at >= 0 && at < columns.length; at += step) {
      const cards = [...columns[at].querySelectorAll(".board-card[tabindex]")].filter(window.TaskCursor.shown);
      if (!cards.length) continue;
      const off = (c) => Math.abs(c.getBoundingClientRect().top - level);
      const next = cards.reduce((best, c) => (off(c) < off(best) ? c : best));
      next.focus();
      next.scrollIntoView({ block: "nearest", inline: "nearest" });
      return;
    }
  });

  /* ---- drawn again: where it was scrolled ---- */

  // The new workstream's line keeps itself (hx-preserve); the scrolling,
  // sideways and down each column, is kept here.
  let kept = null;
  document.addEventListener("htmx:beforeSwap", (e) => {
    if (e.detail.target?.id !== "project-tasks") return;
    const was = board();
    if (!was) return;
    kept = {
      left: was.scrollLeft,
      tops: [...was.querySelectorAll(".board-column[id]")]
        .map((column) => [column.id, column.querySelector(".board-body")?.scrollTop ?? 0]),
    };
  });
  document.addEventListener("htmx:afterSwap", (e) => {
    if (e.target.id !== "project-tasks" || !kept) return;
    for (const [id, top] of kept.tops) {
      const body = document.getElementById(id)?.querySelector(".board-body");
      if (body) body.scrollTop = top;
    }
    const now = board();
    if (now) now.scrollLeft = kept.left;
  });
  // Settled, and drawn as the view keeps it (tasks-views.js), which can make
  // room for where it was: there again; and the cursor stays in sight.
  document.addEventListener("htmx:afterSettle", (e) => {
    if (e.target.id !== "project-tasks" || !kept) return;
    const now = board();
    if (now) now.scrollLeft = kept.left;
    kept = null;
    const active = document.activeElement;
    if (active?.matches?.(".board-card")) active.scrollIntoView({ block: "nearest", inline: "nearest" });
  });

  /* ---- a description's placeholder, in a column's width ---- */

  // Its "- [ ]" is one piece (a word joiner after the hyphen, which a line
  // may otherwise break after): a narrow column must not break it over two
  // lines. Before notes-editor.js reads it (its htmx:load, heard later).
  document.addEventListener("htmx:load", (e) => {
    const root = e.detail.elt;
    const editors = root.matches?.("[data-notes-editor]") ? [root] : [...(root.querySelectorAll?.("[data-notes-editor]") ?? [])];
    for (const editor of editors) {
      if (editor.closest(".tasks-in-board") && editor.dataset.placeholder) {
        editor.dataset.placeholder = editor.dataset.placeholder.replace("- [ ]", "-\u2060\u00a0[\u00a0]");
      }
    }
  }, true);
})();
