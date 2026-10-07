/* Same destinations, with a readable compact-screen section picker. */
(() => {
  const workspace = window.HaloWorkspace;
  if (!workspace) return;
  const nav = document.querySelector(".tabs");
  const compact = document.createElement("nav");
  compact.className = "mobile-section-nav";
  compact.setAttribute("aria-label", "Sections");
  const select = document.createElement("select");
  select.setAttribute("aria-label", "Open section");
  for (const button of nav.querySelectorAll("button[data-view]")) {
    const option = document.createElement("option");
    option.value = button.dataset.view;
    option.textContent = button.querySelector("span").textContent;
    select.append(option);
  }
  compact.append(select);
  nav.after(compact);
  select.addEventListener("change", () => {
    workspace.view(select.value);
    window.scrollTo(0, 0);
  });
  document.addEventListener("click", (event) => {
    if (event.target.closest("[data-view]")) window.scrollTo(0, 0);
  });
  function sync(name) {
    const button =
      [...nav.querySelectorAll("button[data-view]")].find(
        (b) => b.dataset.view === name,
      ) || nav.querySelector('[data-view="twin"]');
    select.value = button.dataset.view;
    document.body.dataset.currentView = select.value;
    document.querySelector(".workspace-breadcrumb").textContent =
      button.querySelector("span").textContent;
    for (const item of nav.querySelectorAll("button[data-view]")) {
      if (item === button) item.setAttribute("aria-current", "page");
      else item.removeAttribute("aria-current");
    }
    requestAnimationFrame(() => window.HaloActiveTwin?.draw());
  }
  window.addEventListener("halo:view", (e) => sync(e.detail));
  sync(location.hash.slice(1) || "twin");
})();
