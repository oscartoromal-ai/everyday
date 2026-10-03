/* The installed app's service worker (served at /sw.js, pwa.py). It caches
   nothing: pages come from the server as they do in a tab. It steps in only
   when opening a page finds the server not answering (the window opened
   before the app started at sign-in, or the app is restarting), with a page
   that says so and reconnects by itself. */

self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (e) => e.waitUntil(self.clients.claim()));

self.addEventListener("fetch", (e) => {
  if (e.request.mode !== "navigate" || e.request.method !== "GET") return;
  e.respondWith(
    fetch(e.request).catch(
      () => new Response(OFFLINE, { status: 503, headers: { "Content-Type": "text/html; charset=utf-8" } }),
    ),
  );
});

// Self-contained, since the server it would load from is the one not
// answering: the design's paper, ink and spark, light or dark as the app
// last was, and its mark.
const OFFLINE = `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Personal Calendar</title>
<meta name="theme-color" content="#ffffff">
<style>
  :root { --paper: #ffffff; --ink: #1a1530; --pewter: #68627a; --hairline: #ebe7f0; --fog: #f5f3f8; --spark: #e5006e; color-scheme: light; }
  :root[data-theme="dark"] { --paper: #14111e; --ink: #f4f0ff; --pewter: #9992b8; --hairline: #241f33; --fog: #1a1626; --spark: #ff2e88; color-scheme: dark; }
  html, body { height: 100%; margin: 0; }
  body {
    display: grid; place-items: center; padding: 16px; box-sizing: border-box;
    background: var(--paper); color: var(--ink);
    font: 15px/1.5 "Segoe UI Variable Text", "Segoe UI", system-ui, sans-serif;
  }
  main { max-width: 26rem; text-align: center; }
  svg { width: 48px; height: 48px; }
  h1 { margin: 20px 0 8px; font-size: 20px; font-weight: 600; letter-spacing: -0.01em; }
  p { margin: 0; color: var(--pewter); }
  .status { margin-top: 20px; font-size: 13px; }
  .status::before {
    content: ""; display: inline-block; width: 6px; height: 6px; margin-right: 8px; vertical-align: 2px;
    border-radius: 50%; background: var(--spark); animation: pulse 1.6s ease-in-out infinite;
  }
  @keyframes pulse { 50% { opacity: 0.25; } }
  @media (prefers-reduced-motion: reduce) { .status::before { animation: none; } }
  button {
    margin-top: 20px; padding: 8px 16px; border: 1px solid var(--hairline); border-radius: 12px;
    background: var(--paper); color: var(--ink); font: inherit; font-size: 14px; cursor: pointer;
  }
  button:hover { background: var(--fog); }
</style>
<script>
  // As the app last was (base.html keeps it), else the system's.
  let theme = null;
  try { theme = localStorage.getItem("pc-theme"); } catch {}
  if (theme !== "light" && theme !== "dark") theme = matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  if (theme === "dark") {
    document.documentElement.dataset.theme = "dark";
    document.querySelector('meta[name="theme-color"]').content = "#14111e";
  }
</script>
</head>
<body>
<main>
  <svg viewBox="0 0 32 32" aria-hidden="true">
    <g fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round">
      <rect x="6" y="7.5" width="20" height="18" rx="3.5"/><path d="M6 13h20"/><path d="M11.5 5v4"/><path d="M20.5 5v4"/>
    </g>
    <circle cx="16" cy="19.25" r="2.4" fill="var(--spark)"/>
  </svg>
  <h1>Personal Calendar isn’t running</h1>
  <p>It starts when you sign in to Windows. This window opens the app as soon as it answers.</p>
  <p class="status" role="status">Waiting for the app</p>
  <button type="button" onclick="location.reload()">Try now</button>
</main>
<script>
  // Every two seconds: once the server answers, the page it was opening.
  setInterval(async () => {
    try {
      const res = await fetch("/manifest.webmanifest", { cache: "no-store" });
      if (res.ok) location.reload();
    } catch {}
  }, 2000);
</script>
</body>
</html>`;
