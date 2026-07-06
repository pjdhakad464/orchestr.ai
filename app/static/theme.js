/* OrchestrAI theme controller — dark default, light optional, persisted.
   The no-flash apply runs inline in <head>; this file wires the toggle
   buttons and keeps every open tab in sync. */
(function () {
  var KEY = "orchestrai-theme";
  function current() {
    return document.documentElement.getAttribute("data-theme") || "dark";
  }
  function apply(theme) {
    document.documentElement.setAttribute("data-theme", theme);
    try { localStorage.setItem(KEY, theme); } catch (e) {}
  }
  window.toggleTheme = function () {
    apply(current() === "dark" ? "light" : "dark");
  };
  document.addEventListener("click", function (e) {
    var btn = e.target.closest("[data-theme-toggle]");
    if (btn) { e.preventDefault(); window.toggleTheme(); }
  });
  // Cross-tab sync
  window.addEventListener("storage", function (e) {
    if (e.key === KEY && e.newValue) {
      document.documentElement.setAttribute("data-theme", e.newValue);
    }
  });
})();
