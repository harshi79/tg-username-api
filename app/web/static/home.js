/* TG Username API — homepage quick checker widget.
   Calls the production API and renders a compact result preview. */
(function () {
  "use strict";

  function apiBase() { return window.location.origin + "/api/v1"; }

  var input = document.getElementById("home-qc-input");
  var btn = document.getElementById("home-qc-btn");
  var chip = document.getElementById("home-qc-chip");
  var resultDiv = document.getElementById("home-qc-result");
  var grid = document.getElementById("home-qc-grid");
  var reportLink = document.getElementById("home-qc-report-link");

  function statusBadge(status) {
    var known = ["taken", "fragment_collectible", "available", "invalid", "unknown"];
    var cls = known.indexOf(status) >= 0 ? "badge badge-" + status : "badge";
    var span = document.createElement("span");
    span.className = cls;
    span.textContent = status || "unknown";
    return span;
  }

  function setChip(text, cls) {
    chip.textContent = text;
    chip.className = "req-chip " + (cls || "");
  }

  function clearGrid() {
    while (grid.firstChild) grid.removeChild(grid.firstChild);
  }

  function addItem(key, value, mono) {
    var item = document.createElement("div");
    item.className = "quick-check-item";
    var k = document.createElement("div");
    k.className = "k";
    k.textContent = key;
    item.appendChild(k);
    var v = document.createElement("div");
    v.className = "v" + (mono ? " mono" : "");
    if (value && value.nodeType) v.appendChild(value);
    else v.textContent = value === null || value === undefined ? "\u2014" : String(value);
    item.appendChild(v);
    grid.appendChild(item);
  }

  function doCheck() {
    var value = input.value.trim();
    if (!value) { input.focus(); return; }

    setChip("Checking\u2026", "loading");
    resultDiv.classList.add("hidden");
    reportLink.classList.add("hidden");
    clearGrid();

    fetch(apiBase() + "/check?username=" + encodeURIComponent(value), {
      headers: { "Accept": "application/json" }
    })
      .then(function (res) {
        return res.json().then(function (body) { return { status: res.status, body: body }; });
      })
      .then(function (outcome) {
        if (outcome.status === 429) {
          setChip("Rate limited", "limited");
          addItem("Error", "Rate limit exceeded (25 req/min)");
          resultDiv.classList.remove("hidden");
          return;
        }
        if (outcome.status >= 400 || !outcome.body) {
          setChip("Error", "error");
          addItem("Error", "Request failed (HTTP " + outcome.status + ")");
          resultDiv.classList.remove("hidden");
          return;
        }
        var body = outcome.body;
        setChip("Done", "success");
        addItem("Username", body.username ? "@" + body.username : "\u2014", true);
        addItem("Final status", statusBadge(body.result ? body.result.status : "unknown"));
        var tg = body.telegram || {};
        if (tg.checked) {
          var tgVal = tg.exists === true ? "Resolves" : tg.exists === false ? "No page" : "Inconclusive";
          addItem("Telegram", tgVal + (tg.entity_type ? " (" + tg.entity_type + ")" : ""));
        } else {
          addItem("Telegram", "Skipped");
        }
        var fr = body.fragment || {};
        if (fr.checked) {
          var frVal = fr.status ? fr.status.replace(/_/g, " ") : fr.found === false ? "No listing" : "Inconclusive";
          addItem("Fragment", frVal);
          addItem("Collectible", fr.collectible === true ? "Yes" : fr.collectible === false ? "No" : "\u2014");
        } else {
          addItem("Fragment", "Skipped");
        }
        resultDiv.classList.remove("hidden");
        reportLink.classList.remove("hidden");
        reportLink.href = "/tester?report=" + encodeURIComponent(value);
      })
      .catch(function () {
        setChip("Error", "error");
        addItem("Error", "Network error");
        resultDiv.classList.remove("hidden");
      });
  }

  btn.addEventListener("click", doCheck);
  input.addEventListener("keydown", function (e) {
    if (e.key === "Enter") { e.preventDefault(); doCheck(); }
  });
})();
