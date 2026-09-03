/* Injected into previewed pages by the forge server: reload when any
 * project file changes (the workspace editor autosaves as you type). */
(() => {
  const m = location.pathname.match(/^\/p\/([a-z0-9-]+)/);
  if (!m) return;
  let seen = null;
  const tick = async () => {
    try {
      const resp = await fetch(`/api/projects/${m[1]}/version`, { cache: "no-store" });
      if (!resp.ok) return;
      const { version } = await resp.json();
      if (seen !== null && version !== seen) location.reload();
      seen = version;
    } catch { /* server briefly away — keep polling */ }
  };
  tick();
  setInterval(tick, 1200);
})();
