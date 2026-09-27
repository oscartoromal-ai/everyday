/* A day's notepad (today.html): plain text, saved as it is written.

   The page saves a moment after each change, when the tab is hidden, and
   when it is left, as a whole (POST /ui/notebook/<day>). A save names the
   version it was made from; one refused because another window saved
   since stops the saving and asks which to keep. Coming back to the tab
   shows a newer version, when nothing here is still to be saved.
   Left and Right, outside the text, go a day back or on. */

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

  const el = pad();
  if (el) {
    version = Number(el.dataset.version) || 0;
    saved = el.value;
  }
})();
