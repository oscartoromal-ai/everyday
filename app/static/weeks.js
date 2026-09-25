/* The multi-week planner: drag a task to another day to replan it, onto a
   day from the Unplanned tray to plan it, or back to the tray to unplan it.
   The board is server-rendered and re-rendered via htmx (weeks:refresh);
   listeners live on document so they survive swaps. */

(() => {
  const refresh = () => htmx.trigger(document.body, "weeks:refresh");

  const toast = (message) => {
    let el = document.querySelector(".cal-toast");
    if (!el) {
      el = document.createElement("div");
      el.className = "cal-toast";
      document.body.appendChild(el);
    }
    el.textContent = message;
    el.classList.add("show");
    setTimeout(() => el.classList.remove("show"), 2600);
  };

  const replan = async (taskId, plannedFor) => {
    const res = await fetch(`/api/tasks/${taskId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json", "X-CSRF": window.csrfToken() },
      body: JSON.stringify({ planned_for: plannedFor }),
    });
    if (!res.ok) {
      let detail = "Could not move that task.";
      try { detail = (await res.json()).detail || detail; } catch { /* keep default */ }
      toast(detail);
    }
    refresh();
  };

  // Past days are history, not a place to plan into.
  const dropTarget = (el) => el.closest?.(".plan-day:not(.past), .plan-tray");

  let dragged = null; // {taskId, from}
  let hovered = null;
  const setHover = (el) => {
    if (hovered === el) return;
    hovered?.classList.remove("drop-over");
    hovered = el;
    hovered?.classList.add("drop-over");
  };

  document.addEventListener("dragstart", (e) => {
    const source = e.target.closest?.("[data-plan-task]");
    if (!source) return;
    const home = source.closest(".plan-day, .plan-tray");
    dragged = { taskId: source.dataset.planTask, from: home?.dataset.date ?? "" };
    e.dataTransfer.setData("text/plain", source.textContent.trim());
    e.dataTransfer.effectAllowed = "move";
    source.classList.add("dragging");
  });

  document.addEventListener("dragover", (e) => {
    if (!dragged) return;
    const target = dropTarget(e.target);
    setHover(target);
    if (!target) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
  });

  document.addEventListener("drop", (e) => {
    if (!dragged) return;
    const target = dropTarget(e.target);
    const { taskId, from } = dragged;
    dragged = null;
    setHover(null);
    if (!target) return;
    e.preventDefault();
    const to = target.dataset.date; // "" on the tray: unplan
    if (to === from) return;
    replan(taskId, to || null);
  });

  document.addEventListener("dragend", () => {
    dragged = null;
    setHover(null);
    document.querySelector(".dragging")?.classList.remove("dragging");
  });

  // One open "add a task" field at a time; Escape closes it.
  document.addEventListener("toggle", (e) => {
    if (!e.target.matches?.(".plan-add") || !e.target.open) return;
    document.querySelectorAll(".plan-add[open]").forEach((d) => { if (d !== e.target) d.open = false; });
    e.target.querySelector("input[name=title]")?.focus();
  }, true);
  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape") return;
    document.querySelectorAll(".plan-add[open]").forEach((d) => { d.open = false; });
  });
})();
