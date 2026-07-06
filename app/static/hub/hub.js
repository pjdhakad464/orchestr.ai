/* Media Tools Hub — client behavior: search, category filter, favorites, and
   recently-used. Favorites + history are localStorage only (no server state). */
(function () {
  var root = document.querySelector("[data-hub]");
  if (!root) return;

  var FAV_KEY = "orchestrai-hub-favorites";
  var RECENT_KEY = "orchestrai-hub-recent";
  var search = document.getElementById("hub-search");
  var chips = Array.prototype.slice.call(root.querySelectorAll(".hub-chip"));
  var cards = Array.prototype.slice.call(root.querySelectorAll("#hub-all .hub-card"));
  var emptyMsg = document.getElementById("hub-empty");
  var activeCat = "all";

  function read(key) {
    try { return JSON.parse(localStorage.getItem(key)) || []; } catch (e) { return []; }
  }
  function write(key, val) {
    try { localStorage.setItem(key, JSON.stringify(val)); } catch (e) {}
  }

  /* ---- Search + category filter ---------------------------------------- */
  function applyFilter() {
    var q = (search.value || "").trim().toLowerCase();
    var shown = 0;
    cards.forEach(function (card) {
      var matchCat = activeCat === "all" || card.dataset.cat === activeCat;
      var hay = (card.dataset.name + " " + card.dataset.keywords + " " + card.dataset.cat).toLowerCase();
      var matchQ = !q || hay.indexOf(q) !== -1;
      var show = matchCat && matchQ;
      card.hidden = !show;
      if (show) shown++;
    });
    if (emptyMsg) emptyMsg.hidden = shown !== 0;
  }
  search.addEventListener("input", applyFilter);
  chips.forEach(function (chip) {
    chip.addEventListener("click", function () {
      chips.forEach(function (c) { c.classList.remove("is-active"); });
      chip.classList.add("is-active");
      activeCat = chip.dataset.cat;
      applyFilter();
    });
  });

  /* ---- Favorites -------------------------------------------------------- */
  function favSet() { return read(FAV_KEY); }
  function isFav(id) { return favSet().indexOf(id) !== -1; }
  function toggleFav(id) {
    var favs = favSet();
    var i = favs.indexOf(id);
    if (i === -1) favs.push(id); else favs.splice(i, 1);
    write(FAV_KEY, favs);
    syncFavButtons();
    renderShelves();
  }
  function syncFavButtons() {
    root.querySelectorAll(".hub-fav").forEach(function (btn) {
      var on = isFav(btn.dataset.fav);
      btn.setAttribute("aria-pressed", on ? "true" : "false");
    });
  }
  root.querySelectorAll("#hub-all .hub-fav").forEach(function (btn) {
    btn.addEventListener("click", function (e) {
      e.preventDefault();
      toggleFav(btn.dataset.fav);
    });
  });

  /* ---- Recently used ---------------------------------------------------- */
  function pushRecent(id) {
    var recent = read(RECENT_KEY).filter(function (x) { return x !== id; });
    recent.unshift(id);
    write(RECENT_KEY, recent.slice(0, 4));
  }
  root.querySelectorAll("[data-tool-link]").forEach(function (link) {
    link.addEventListener("click", function () { pushRecent(link.dataset.id); });
  });

  /* ---- Build a compact card for the shelves ---------------------------- */
  function meta(id) {
    var link = root.querySelector('#hub-all [data-tool-link][data-id="' + id + '"]');
    if (!link) return null;
    return {
      id: id, name: link.dataset.name, icon: link.dataset.icon,
      url: link.dataset.url, external: link.dataset.external === "1",
      desc: link.dataset.desc,
    };
  }
  function cardHTML(m) {
    var ext = m.external ? ' target="_blank" rel="noopener"' : "";
    var extIcon = m.external ? '<span class="material-symbols-outlined hub-ext" aria-hidden="true">open_in_new</span>' : "";
    return '' +
      '<article class="hub-card">' +
      '<a class="hub-card-link" href="' + m.url + '"' + ext + ' data-recent-link data-id="' + m.id + '">' +
      '<span class="hub-card-icon"><span class="material-symbols-outlined" aria-hidden="true">' + m.icon + '</span></span>' +
      '<span class="hub-card-body">' +
      '<span class="hub-card-name">' + m.name + extIcon + '</span>' +
      '<span class="hub-card-desc">' + m.desc + '</span>' +
      '</span></a></article>';
  }
  function fill(containerId, shelfId, ids) {
    var container = document.getElementById(containerId);
    var shelf = document.getElementById(shelfId);
    if (!container || !shelf) return;
    var items = ids.map(meta).filter(Boolean);
    if (!items.length) { shelf.hidden = true; container.innerHTML = ""; return; }
    container.innerHTML = items.map(cardHTML).join("");
    shelf.hidden = false;
    container.querySelectorAll("[data-recent-link]").forEach(function (link) {
      link.addEventListener("click", function () { pushRecent(link.dataset.id); });
    });
  }
  function renderShelves() {
    fill("hub-recent", "hub-recent-shelf", read(RECENT_KEY));
    fill("hub-favorites", "hub-fav-shelf", favSet());
  }

  syncFavButtons();
  renderShelves();
  applyFilter();
})();
