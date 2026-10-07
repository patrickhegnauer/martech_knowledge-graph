/*
 * Shared demo/org mode banner + switcher, included on every page.
 * Deliberate exception to the "most pages are JS-free" pattern -- the user
 * wants this reachable everywhere, not just on pages that already have their
 * own script. Self-contained: does not depend on any page's own inline code.
 *
 * If the local API isn't reachable, this does nothing -- each page already
 * shows its own static/fallback note elsewhere, and without a server there's
 * no real mode to report.
 */
(function () {
  // Light/dark/system theme toggle. Independent of the local API -- works even on a page opened
  // standalone via file://. The choice is a per-browser convenience, so it lives in localStorage, never
  // sent anywhere; index.html's inline snippet applies it before first paint to avoid a flash.
  const THEME_KEY = "mkg-theme";
  const THEME_ORDER = ["auto", "light", "dark"];
  const THEME_LABEL = { auto: "Theme: Auto", light: "Theme: Light", dark: "Theme: Dark" };

  function getTheme() {
    try {
      const t = localStorage.getItem(THEME_KEY);
      return THEME_ORDER.includes(t) ? t : "auto";
    } catch (e) {
      return "auto";
    }
  }

  function applyTheme(theme) {
    if (theme === "light" || theme === "dark") {
      document.documentElement.setAttribute("data-theme", theme);
    } else {
      document.documentElement.removeAttribute("data-theme");
    }
  }

  function ensureHeaderActions() {
    // Lives in the sidebar's footer card (where the mockup puts its workspace/user card), not the
    // header itself -- these are session controls, not part of the page title.
    const footer = document.getElementById("sidebar-footer");
    if (!footer) return null;
    let actions = document.getElementById("header-actions");
    if (!actions) {
      actions = document.createElement("div");
      actions.id = "header-actions";
      actions.className = "header-actions";
      footer.appendChild(actions);
    }
    return actions;
  }

  // Mobile sidebar drawer: hidden off-canvas by default (see the @media rule in style.css), opened by
  // the hamburger button, closed by the backdrop or by picking a nav link.
  function wireSidebarToggle() {
    const toggle = document.getElementById("sidebar-toggle");
    const sidebar = document.getElementById("sidebar");
    const backdrop = document.getElementById("sidebar-backdrop");
    if (!toggle || !sidebar || !backdrop) return;
    const open = () => { sidebar.classList.add("open"); backdrop.classList.add("open"); toggle.style.visibility = "hidden"; };
    const close = () => { sidebar.classList.remove("open"); backdrop.classList.remove("open"); toggle.style.visibility = ""; };
    toggle.addEventListener("click", () => {
      sidebar.classList.contains("open") ? close() : open();
    });
    backdrop.addEventListener("click", close);
    sidebar.querySelectorAll("nav.site-nav a").forEach(a => a.addEventListener("click", close));
  }
  wireSidebarToggle();

  function renderThemeToggle() {
    const actions = ensureHeaderActions();
    if (!actions) return;
    let btn = document.getElementById("theme-toggle");
    if (!btn) {
      btn = document.createElement("button");
      btn.type = "button";
      btn.id = "theme-toggle";
      btn.className = "secondary theme-toggle";
      btn.title = "Switch between light, dark and your system's theme";
      btn.addEventListener("click", () => {
        const next = THEME_ORDER[(THEME_ORDER.indexOf(getTheme()) + 1) % THEME_ORDER.length];
        try { localStorage.setItem(THEME_KEY, next); } catch (e) { /* ignore */ }
        applyTheme(next);
        renderThemeToggle();
      });
      actions.insertBefore(btn, actions.firstChild);
    }
    btn.textContent = THEME_LABEL[getTheme()];
  }

  applyTheme(getTheme());
  renderThemeToggle();

  function switchMode(newMode) {
    if (newMode === "org") {
      const ok = confirm(
        "Switch to your own data workspace?\n\nDemo content will no longer be shown, but nothing is deleted " +
        "-- you can switch back to the demo at any time."
      );
      if (!ok) return;
    }
    fetch("/api/mode", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mode: newMode }),
    })
      .then(r => r.json())
      .then(() => { location.reload(); })
      .catch(() => { alert("Could not reach the local API to switch modes."); });
  }

  function renderSwitcher(mode) {
    const actions = ensureHeaderActions();
    if (!actions) return;

    let switcher = document.getElementById("mode-switcher");
    if (!switcher) {
      switcher = document.createElement("div");
      switcher.id = "mode-switcher";
      switcher.className = "mode-switcher";
      actions.appendChild(switcher);
    }
    switcher.innerHTML = "";

    const label = document.createElement("span");
    label.className = "mode-switcher-label";
    label.textContent = mode === "demo" ? "Demo data" : "Your data";
    switcher.appendChild(label);

    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "secondary";
    btn.textContent = mode === "demo" ? "Switch to your data" : "Switch to demo";
    btn.addEventListener("click", () => switchMode(mode === "demo" ? "org" : "demo"));
    switcher.appendChild(btn);
  }

  function renderBanner(mode) {
    const existing = document.getElementById("mode-banner");
    if (mode !== "demo") {
      if (existing) existing.remove();
      return;
    }
    if (existing) return;

    const banner = document.createElement("div");
    banner.id = "mode-banner";
    banner.className = "mode-banner mode-banner--demo";

    const text = document.createElement("span");
    text.textContent = "Demo environment — showing bundled example data (read-only).";
    banner.appendChild(text);

    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "secondary";
    btn.textContent = "Switch to your data";
    btn.addEventListener("click", () => switchMode("org"));
    banner.appendChild(btn);

    document.body.insertBefore(banner, document.body.firstChild);
  }

  function renderVersion(version) {
    const title = document.querySelector("header.site-header h1");
    if (!title) return;
    let beta = document.getElementById("beta-badge");
    if (!beta) {
      beta = document.createElement("span");
      beta.id = "beta-badge";
      beta.className = "beta-badge";
      beta.textContent = "BETA";
      title.appendChild(beta);
    }
    if (version) {
      let tag = document.getElementById("version-tag");
      if (!tag) {
        tag = document.createElement("span");
        tag.id = "version-tag";
        tag.className = "version-tag";
        title.appendChild(tag);
      }
      tag.textContent = "v" + version;
      tag.title = "Version of the server that is currently running";
    }
  }

  // Small counts next to the matching sidebar nav links -- only real counts we show elsewhere too,
  // never invented for this.
  function setNavCount(href, count) {
    const a = document.querySelector('nav.site-nav a[href="' + href + '"]');
    if (!a) return;
    let el = a.querySelector(".nav-count");
    if (!el) {
      el = document.createElement("span");
      el.className = "nav-count";
      a.appendChild(el);
    }
    el.textContent = String(count);
  }

  function renderNavCounts(data) {
    // From the /api/state this already fetches -- no extra request for these two.
    setNavCount("components.html", data.components.length);
    setNavCount("journeys.html", data.journeys.length);
    // Sources isn't in /api/state, so this is one small extra request; failing silently just leaves
    // the Sources link without a count rather than breaking anything else on the page.
    fetch("/api/sources")
      .then(r => { if (!r.ok) throw new Error("bad response"); return r.json(); })
      .then(sources => setNavCount("sources.html", sources.cja.data_views.length))
      .catch(() => { /* no count shown -- not worth surfacing an error for this */ });
  }

  renderVersion(null);

  fetch("/api/state")
    .then(r => { if (!r.ok) throw new Error("bad response"); return r.json(); })
    .then(data => {
      renderVersion(data.version);
      renderBanner(data.mode);
      renderSwitcher(data.mode);
      renderNavCounts(data);
    })
    .catch(() => { /* server not reachable -- nothing to show */ });
})();
