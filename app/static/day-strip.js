/* A day page's strip (partials/day_strip.html): the day's time as a
   horizontal scale. A task row dropped on it gets an hour's block where it
   lands, snapped to the quarter hour (calendar.js makes the rows
   draggable and fills the drag's data); pointing at a task's block marks
   its row on the page, and pointing at a row marks its block. Moving and
   resizing blocks stays the Calendar's. Listeners sit on document, so they
   survive the strip's refreshes. */

(() => {
  const SNAP_MIN = 15;
  const LENGTH_MIN = 60;

  const strip = () => document.getElementById("day-strip");
  const scaleOf = (el) => el?.closest?.("[data-strip-scale]");

  // Minutes after midnight under the pointer, snapped, kept inside the scale.
  const minutesAt = (scale, clientX) => {
    const s = strip();
    const start = Number(s.dataset.startHour) * 60;
    const end = Number(s.dataset.endHour) * 60;
    const rect = scale.getBoundingClientRect();
    const raw = start + ((clientX - rect.left) / rect.width) * (end - start);
    const snapped = Math.round(raw / SNAP_MIN) * SNAP_MIN;
    return Math.max(start, Math.min(end - LENGTH_MIN, snapped));
  };
  const pctOf = (minutes) => {
    const s = strip();
    const start = Number(s.dataset.startHour) * 60;
    const end = Number(s.dataset.endHour) * 60;
    return ((minutes - start) / (end - start)) * 100;
  };
  const hhmm = (minutes) => `${String(Math.floor(minutes / 60)).padStart(2, "0")}:${String(minutes % 60).padStart(2, "0")}`;

  /* ---- a task dropped on the scale: an hour there ---- */

  let preview = null;
  const clearPreview = () => { preview?.remove(); preview = null; };
  const showPreview = (scale, minutes) => {
    if (!preview || preview.parentElement !== scale) {
      clearPreview();
      preview = document.createElement("div");
      preview.className = "strip-preview";
      scale.append(preview);
    }
    preview.style.left = `${pctOf(minutes)}%`;
    preview.style.width = `${pctOf(minutes + LENGTH_MIN) - pctOf(minutes)}%`;
    preview.textContent = `${hhmm(minutes)}–${hhmm(minutes + LENGTH_MIN)}`;
  };

  document.addEventListener("dragover", (e) => {
    if (!e.dataTransfer.types.includes("text/task-id")) return;
    const scale = scaleOf(e.target);
    if (!scale) {
      if (preview) clearPreview();
      return;
    }
    e.preventDefault();
    e.dataTransfer.dropEffect = "copy";
    showPreview(scale, minutesAt(scale, e.clientX));
  });

  document.addEventListener("drop", async (e) => {
    const scale = scaleOf(e.target);
    const taskId = e.dataTransfer.getData("text/task-id");
    clearPreview();
    if (!scale || !taskId) return;
    e.preventDefault();
    const start = minutesAt(scale, e.clientX);
    const day = strip().dataset.day;
    const res = await fetch("/api/blocks", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRF": window.csrfToken() },
      body: JSON.stringify({
        task_id: Number(taskId),
        start: `${day}T${hhmm(start)}:00`,
        end: `${day}T${hhmm(start + LENGTH_MIN)}:00`,
      }),
    });
    if (!res.ok) {
      let detail = "Could not give that task time.";
      try { detail = (await res.json()).detail || detail; } catch { /* keep default */ }
      window.toast(detail);
      return;
    }
    window.toast(`${hhmm(start)}–${hhmm(start + LENGTH_MIN)}: ${e.dataTransfer.getData("text/task-title")}`);
    htmx.trigger(document.body, "calendar:refresh");
  });

  document.addEventListener("dragend", clearPreview);

  /* ---- a block and its row point at each other ---- */

  const mark = (taskId, on) => {
    document.querySelectorAll(`[data-task-id="${CSS.escape(taskId)}"]`).forEach((el) => {
      if (el.matches(".strip-item, .task-row")) el.classList.toggle("is-linked", on);
    });
  };
  document.addEventListener("pointerover", (e) => {
    const el = e.target.closest?.(".strip-item[data-task-id], .day-sheet .task-row[data-task-id]");
    const from = e.relatedTarget?.closest?.(".strip-item[data-task-id], .day-sheet .task-row[data-task-id]");
    if (el === from) return;
    if (from) mark(from.dataset.taskId, false);
    if (el) mark(el.dataset.taskId, true);
  });
  document.addEventListener("pointerleave", (e) => {
    if (e.target === document.documentElement) document.querySelectorAll(".is-linked").forEach((el) => el.classList.remove("is-linked"));
  }, true);

  // A task's block, clicked: to its row on the page, if the page has it.
  document.addEventListener("click", (e) => {
    const item = e.target.closest?.(".strip-item[data-task-id]");
    if (!item) return;
    const row = document.querySelector(`.day-sheet .task-row[data-task-id="${CSS.escape(item.dataset.taskId)}"]`);
    if (!row) return;
    row.focus({ focusVisible: true });
    row.scrollIntoView({ block: "center", behavior: "smooth" });
  });
})();
