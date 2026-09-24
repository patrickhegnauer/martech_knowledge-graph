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
    const header = document.querySelector("header.site-header");
    if (!header) return;

    let switcher = document.getElementById("mode-switcher");
    if (!switcher) {
      switcher = document.createElement("div");
      switcher.id = "mode-switcher";
      switcher.className = "mode-switcher";
      header.appendChild(switcher);
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

  renderVersion(null);

  fetch("/api/state")
    .then(r => { if (!r.ok) throw new Error("bad response"); return r.json(); })
    .then(data => {
      renderVersion(data.version);
      renderBanner(data.mode);
      renderSwitcher(data.mode);
    })
    .catch(() => { /* server not reachable -- nothing to show */ });
})();
