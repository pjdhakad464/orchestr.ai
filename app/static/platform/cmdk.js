/* Command palette (⌘K / Ctrl+K). Data injected server-side (#cmdk-data).
   Keyboard-first: arrows to move, Enter to open, Esc to close. */
(function () {
  var root = document.getElementById("cmdk");
  var dataEl = document.getElementById("cmdk-data");
  if (!root || !dataEl) return;

  var COMMANDS = [];
  try { COMMANDS = JSON.parse(dataEl.textContent) || []; } catch (e) { COMMANDS = []; }

  var input = document.getElementById("cmdk-input");
  var results = document.getElementById("cmdk-results");
  var active = 0;
  var visible = [];

  function open() {
    root.hidden = false; root.setAttribute("aria-hidden", "false");
    input.value = ""; render(""); input.focus();
    document.body.style.overflow = "hidden";
  }
  function close() {
    root.hidden = true; root.setAttribute("aria-hidden", "true");
    document.body.style.overflow = "";
  }
  function isOpen() { return !root.hidden; }

  function match(cmd, q) {
    if (!q) return true;
    var hay = (cmd.label + " " + (cmd.keywords || "") + " " + cmd.group).toLowerCase();
    return q.toLowerCase().split(/\s+/).every(function (tok) { return hay.indexOf(tok) !== -1; });
  }

  function render(q) {
    visible = COMMANDS.filter(function (c) { return match(c, q); });
    active = 0;
    if (!visible.length) {
      results.innerHTML = '<div class="cmdk-empty">No matching commands. Try “validator”, “activity”, or “tools”.</div>';
      return;
    }
    var html = "", lastGroup = null;
    visible.forEach(function (c, i) {
      if (c.group !== lastGroup) { html += '<div class="cmdk-group">' + c.group + "</div>"; lastGroup = c.group; }
      var ext = c.external ? '<span class="material-symbols-outlined cmdk-ext">open_in_new</span>' : "";
      html += '<a class="cmdk-item' + (c.ai ? " ai" : "") + (i === 0 ? " active" : "") +
        '" role="option" data-i="' + i + '" href="' + c.href + '"' +
        (c.external ? ' target="_blank" rel="noopener"' : "") + '>' +
        '<span class="material-symbols-outlined">' + c.icon + '</span>' +
        '<span class="cmdk-label">' + c.label + "</span>" + ext + "</a>";
    });
    results.innerHTML = html;
  }

  function setActive(n) {
    var items = results.querySelectorAll(".cmdk-item");
    if (!items.length) return;
    active = (n + items.length) % items.length;
    items.forEach(function (el, i) {
      el.classList.toggle("active", i === active);
      if (i === active) el.scrollIntoView({ block: "nearest" });
    });
  }
  function activate() {
    var items = results.querySelectorAll(".cmdk-item");
    if (items[active]) items[active].click();
  }

  document.addEventListener("keydown", function (e) {
    if ((e.metaKey || e.ctrlKey) && (e.key === "k" || e.key === "K")) {
      e.preventDefault(); isOpen() ? close() : open(); return;
    }
    if (!isOpen()) return;
    if (e.key === "Escape") { e.preventDefault(); close(); }
    else if (e.key === "ArrowDown") { e.preventDefault(); setActive(active + 1); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setActive(active - 1); }
    else if (e.key === "Enter") { e.preventDefault(); activate(); }
  });
  input.addEventListener("input", function () { render(input.value.trim()); });
  root.addEventListener("click", function (e) {
    if (e.target.closest("[data-cmdk-close]")) close();
  });
  document.addEventListener("click", function (e) {
    if (e.target.closest("[data-cmdk-open]")) { e.preventDefault(); open(); }
  });
})();
