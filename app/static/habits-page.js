/* A habit's own page (habit.html), around its words (doc-editor.js): its
   days, from the repeat icon under its name, written as they are chosen;
   its half year drawn again as they change and as its log is saved (a
   comment written or taken out makes a day skipped, or not); and, renamed,
   its file's path and its bin's question following the name. */

(() => {
  const page = document.querySelector(".habit-page[data-habit]");
  if (!page) return;
  const id = page.dataset.habit;

  const redrawYear = () => {
    const year = document.getElementById("habit-year");
    if (year) window.htmx.ajax("GET", `/ui/habits/${id}/year`, { target: year, swap: "outerHTML" });
  };

  let daysTimer = null;
  page.querySelector(".habit-days")?.addEventListener("sheet:field", (e) => {
    clearTimeout(daysTimer);
    const days = e.detail.value;
    daysTimer = setTimeout(async () => {
      const res = await fetch(`/ui/habits/${id}/days`, {
        method: "POST",
        headers: { "X-CSRF": window.csrfToken() },
        body: new URLSearchParams({ days }),
      }).catch(() => null);
      if (!res?.ok) {
        window.toast("Could not set the habit's days.");
        return;
      }
      redrawYear();
    }, 300);
  });

  page.addEventListener("doc:saved", redrawYear);
  page.addEventListener("doc:moved", (e) => {
    const file = page.querySelector("[data-habit-file]");
    if (file && e.detail.file) file.textContent = e.detail.file;
  });
})();
