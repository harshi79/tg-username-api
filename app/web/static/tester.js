/* TG Username API — interactive tester.
   Talks only to this origin's /api/v1 endpoints, accepts usernames only,
   and renders dynamic values exclusively through textContent. */
(function () {
  "use strict";

  var BULK_MAX = 15;
  var STATUS_BADGES = ["taken", "fragment_collectible", "available", "invalid", "unknown"];

  function apiBase() { return window.location.origin + "/api/v1"; }

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }

  function clear(node) { while (node.firstChild) node.removeChild(node.firstChild); }

  /* -------------------------------------------------- generic request flow */
  function runRequest(stateEls, requestFn, onData) {
    setChip(stateEls.chip, "loading", "Loading…");
    stateEls.raw.classList.add("hidden");
    clear(stateEls.result);
    stateEls.region.classList.remove("hidden");

    requestFn()
      .then(function (res) {
        return res.json().catch(function () { return null; }).then(function (body) {
          return { status: res.status, body: body };
        });
      })
      .then(function (outcome) {
        showRaw(stateEls, outcome.body);
        var code = outcome.body && outcome.body.error ? outcome.body.error.code : null;
        if (outcome.status === 429 || code === "rate_limit_exceeded") {
          setChip(stateEls.chip, "limited", "Rate limited");
          addNotice(stateEls.result, "bad", "Rate limit exceeded (25 requests per IP per minute). Try again shortly.");
          return;
        }
        if (outcome.status >= 500 || outcome.body === null) {
          setChip(stateEls.chip, "error", "Upstream unavailable");
          addNotice(stateEls.result, "bad", "The service is temporarily unavailable. No data was returned.");
          return;
        }
        if (outcome.status === 400 || outcome.status === 401 || outcome.status === 422) {
          setChip(stateEls.chip, "invalid", "Request rejected");
          var msg = outcome.body && outcome.body.error ? outcome.body.error.message : "The request was rejected.";
          addNotice(stateEls.result, "warn", msg);
          return;
        }
        onData(outcome.body);
      })
      .catch(function () {
        setChip(stateEls.chip, "error", "Upstream unavailable");
        addNotice(stateEls.result, "bad", "Network error while reaching the API. Try again.");
      });
  }

  function setChip(chip, cls, text) {
    chip.className = "req-chip " + cls;
    chip.textContent = text;
  }

  function addNotice(region, kind, text) {
    var notice = el("div", "notice " + kind);
    notice.textContent = text;
    region.appendChild(notice);
  }

  function showRaw(stateEls, body) {
    stateEls.raw.classList.remove("hidden");
    stateEls.rawBody.textContent = body === null ? "(no JSON body)" : JSON.stringify(body, null, 2);
  }

  /* ------------------------------------------------------------ renderers */
  function statusBadge(status) {
    var cls = STATUS_BADGES.indexOf(status) >= 0 ? "badge badge-" + status : "badge";
    return el("span", cls, status || "unknown");
  }

  function kvCard(key, valueNode) {
    var card = el("div", "kv");
    card.appendChild(el("div", "k", key));
    var value = el("div", "v");
    if (typeof valueNode === "string") value.classList.add("mono");
    if (valueNode && valueNode.nodeType) value.appendChild(valueNode);
    else value.textContent = valueNode === null || valueNode === undefined ? "—" : String(valueNode);
    card.appendChild(value);
    return card;
  }

  function tri(value, yes, no, none_) {
    if (value === true) return yes || "yes";
    if (value === false) return no || "no";
    return none_ || "inconclusive";
  }

  function fmtPrice(price) {
    if (!price || price.amount === null || price.amount === undefined) return null;
    var text = price.amount + " " + (price.currency || "TON");
    if (price.approx_usd) text += "  (~ " + price.approx_usd + ")";
    return text;
  }

  function renderCheckBody(stateEls, body, includeReport) {
    var region = stateEls.result;
    var status = body && body.result ? body.result.status : "unknown";
    setChip(stateEls.chip, status === "invalid" ? "invalid" : "success", status === "invalid" ? "Invalid username" : "Done");

    var grid = el("div", "result-grid");
    var tg = body.telegram || {};
    var fr = body.fragment || {};
    var val = body.validation || {};

    grid.appendChild(kvCard("Normalized username", body.username ? "@" + body.username : "—"));
    grid.appendChild(kvCard("Final status", statusBadge(status)));
    grid.appendChild(kvCard("Validation", tri(val.valid, "valid", "invalid", "—")));
    if (val && val.valid === false) grid.appendChild(kvCard("Validation reason", val.reason));

    if (tg.checked) {
      grid.appendChild(kvCard("Telegram resolves", tri(tg.exists, "yes", "no", "inconclusive (ambiguous page)")));
      grid.appendChild(kvCard("Telegram entity type", tg.entity_type || "—"));
    } else {
      grid.appendChild(kvCard("Telegram", "not checked"));
    }

    if (fr.checked) {
      grid.appendChild(kvCard("Fragment page found", tri(fr.found, "yes", "no", "inconclusive")));
      grid.appendChild(kvCard("Collectible state", tri(fr.collectible, "collectible", "not a collectible", "unknown")));
      if (fr.status) grid.appendChild(kvCard("Marketplace state", fr.status.replace(/_/g, " ")));
      var priceText = fmtPrice(fr.price);
      if (priceText) grid.appendChild(kvCard("Public TON price / min bid", priceText));
      if (fr.auction && fr.auction.highest_bid) {
        var hb = fr.auction.highest_bid;
        grid.appendChild(kvCard("Highest bid (public)", hb.amount + " " + (hb.currency || "TON") + (hb.approx_usd ? "  (~ " + hb.approx_usd + ")" : "")));
      }
      if (fr.auction && fr.auction.ends_in) grid.appendChild(kvCard("Auction ends in", fr.auction.ends_in));
      if (fr.url) grid.appendChild(kvCard("Fragment URL", fr.url));
    } else {
      grid.appendChild(kvCard("Fragment", "not checked"));
    }

    grid.appendChild(kvCard("Checked at", body.checked_at || body.generated_at || "—"));
    region.appendChild(grid);

    if (body.result && body.result.explanation) {
      addNotice(region, status === "available" ? "ok" : status === "invalid" ? "warn" : status === "unknown" ? "warn" : "", body.result.explanation);
    }

    var srcError = tg.error || fr.error;
    if (srcError) {
      addNotice(region, "bad", "Source error (" + (srcError.source || "upstream") + "): " + (srcError.message || "unknown") + " — the verdict stays conservative.");
    }

    if (includeReport && body.characteristics) {
      region.appendChild(el("h3", null, "Username characteristics"));
      var cg = el("div", "result-grid");
      var c = body.characteristics;
      [["Length", c.length], ["Digits", c.digit_count], ["Underscores", c.underscore_count],
       ["Letters only", tri(c.only_letters)], ["Longest repeated run", c.max_repeated_char_run],
       ["Unique characters", c.unique_characters]
      ].forEach(function (pair) { cg.appendChild(kvCard(pair[0], pair[1])); });
      region.appendChild(cg);

      if (body.heuristic_score) {
        var h = body.heuristic_score;
        var hg = el("div", "result-grid");
        hg.appendChild(kvCard("Heuristic score (not a valuation)", h.score + " / 100"));
        hg.appendChild(kvCard("Label", h.label));
        region.appendChild(hg);
        if (h.factor_notes && h.factor_notes.length) {
          region.appendChild(el("h3", null, "Heuristic factors"));
          var ul = el("ul");
          h.factor_notes.forEach(function (note) { ul.appendChild(el("li", null, note)); });
          region.appendChild(ul);
        }
      }

      if (body.signals && body.signals.length) {
        region.appendChild(el("h3", null, "Public signals"));
        var sl = el("ul");
        body.signals.forEach(function (s) { sl.appendChild(el("li", null, s)); });
        region.appendChild(sl);
      }
    }
  }

  function renderBulkBody(stateEls, body) {
    var region = stateEls.result;
    setChip(stateEls.chip, "success", "Done");
    var results = body.results || [];
    var counts = {};
    results.forEach(function (r) {
      var s = r.result ? r.result.status : "unknown";
      counts[s] = (counts[s] || 0) + 1;
    });
    addNotice(region, "", body.total + " username(s) checked: " +
      Object.keys(counts).map(function (s) { return counts[s] + " × " + s; }).join(", ") + ".");

    var wrap = el("div", "table-wrap");
    var table = el("table", "data");
    var thead = el("thead");
    var hrow = el("tr");
    ["Username", "Status", "Telegram", "Fragment", "Notes"].forEach(function (h) { hrow.appendChild(el("th", null, h)); });
    thead.appendChild(hrow);
    table.appendChild(thead);
    var tbody = el("tbody");

    results.forEach(function (r) {
      var row = el("tr");
      var tg = r.telegram || {};
      var fr = r.fragment || {};
      row.appendChild(el("td", null, r.username ? "@" + r.username : (r.validation ? r.validation.input : "—"))).className = "mono";
      var st = el("td");
      st.appendChild(statusBadge(r.result ? r.result.status : "unknown"));
      row.appendChild(st);
      row.appendChild(el("td", null, tg.checked ? tri(tg.exists, "resolves" + (tg.entity_type ? " (" + tg.entity_type + ")" : ""), "no page", "inconclusive") : "not checked"));
      var frSummary = "not checked";
      if (fr.checked) {
        if (fr.status) frSummary = fr.status.replace(/_/g, " ");
        else if (fr.found === false) frSummary = "no listing";
        else frSummary = "inconclusive";
        var p = fmtPrice(fr.price);
        if (p) frSummary += " · " + p;
      }
      row.appendChild(el("td", null, frSummary));
      var note = "";
      var srcError = tg.error || fr.error;
      if (srcError) note = srcError.code || "";
      row.appendChild(el("td", null, note || "—"));
      tbody.appendChild(row);
    });

    table.appendChild(tbody);
    wrap.appendChild(table);
    region.appendChild(wrap);
  }

  /* ------------------------------------------------------------ bulk input */
  function parseBulk(raw) {
    return raw.split(/[\s,;]+/).map(function (t) { return t.trim(); }).filter(function (t) { return t.length > 0; });
  }

  function bindBulkCounter(textarea, counter, limitNote, submitBtn) {
    function update() {
      var items = parseBulk(textarea.value);
      counter.textContent = items.length + " / " + BULK_MAX + " usernames";
      var over = items.length > BULK_MAX;
      counter.classList.toggle("over", over);
      limitNote.classList.toggle("hidden", !over);
      submitBtn.disabled = over || items.length === 0;
    }
    textarea.addEventListener("input", update);
    update();
  }

  /* ------------------------------------------------------------------ tabs */
  function bindTabs() {
    var buttons = document.querySelectorAll(".tabs button[data-tab]");
    var panels = document.querySelectorAll(".tab-panel");
    buttons.forEach(function (btn) {
      btn.addEventListener("click", function () {
        buttons.forEach(function (b) { b.classList.remove("active"); b.setAttribute("aria-selected", "false"); });
        panels.forEach(function (p) { p.classList.remove("active"); });
        btn.classList.add("active");
        btn.setAttribute("aria-selected", "true");
        var panel = document.getElementById("panel-" + btn.getAttribute("data-tab"));
        if (panel) panel.classList.add("active");
      });
    });
  }

  /* ------------------------------------------------------------------ init */
  document.addEventListener("DOMContentLoaded", function () {
    bindTabs();

    var singleInput = document.getElementById("single-username");
    var singleChip = document.getElementById("single-chip");
    var singleEls = {
      chip: singleChip,
      result: document.getElementById("single-result"),
      region: document.getElementById("single-region"),
      raw: document.getElementById("single-raw"),
      rawBody: document.getElementById("single-raw-body")
    };

    function submitSingle() {
      var value = singleInput.value.trim();
      if (!value) { singleInput.focus(); return; }
      runRequest(singleEls, function () {
        return fetch(apiBase() + "/check?username=" + encodeURIComponent(value), { headers: { "Accept": "application/json" } });
      }, function (body) { renderCheckBody(singleEls, body, false); });
    }
    document.getElementById("single-submit").addEventListener("click", submitSingle);
    singleInput.addEventListener("keydown", function (e) { if (e.key === "Enter") { e.preventDefault(); submitSingle(); } });

    var reportInput = document.getElementById("report-username");
    var reportEls = {
      chip: document.getElementById("report-chip"),
      result: document.getElementById("report-result"),
      region: document.getElementById("report-region"),
      raw: document.getElementById("report-raw"),
      rawBody: document.getElementById("report-raw-body")
    };
    function submitReport() {
      var value = reportInput.value.trim();
      if (!value) { reportInput.focus(); return; }
      runRequest(reportEls, function () {
        return fetch(apiBase() + "/report?username=" + encodeURIComponent(value), { headers: { "Accept": "application/json" } });
      }, function (body) { renderCheckBody(reportEls, body, true); });
    }
    document.getElementById("report-submit").addEventListener("click", submitReport);
    reportInput.addEventListener("keydown", function (e) { if (e.key === "Enter") { e.preventDefault(); submitReport(); } });

    var bulkInput = document.getElementById("bulk-usernames");
    var bulkSubmit = document.getElementById("bulk-submit");
    var bulkEls = {
      chip: document.getElementById("bulk-chip"),
      result: document.getElementById("bulk-result"),
      region: document.getElementById("bulk-region"),
      raw: document.getElementById("bulk-raw"),
      rawBody: document.getElementById("bulk-raw-body")
    };
    bindBulkCounter(bulkInput, document.getElementById("bulk-counter"), document.getElementById("bulk-over"), bulkSubmit);
    function submitBulk() {
      var items = parseBulk(bulkInput.value);
      if (items.length === 0 || items.length > BULK_MAX) return;
      runRequest(bulkEls, function () {
        return fetch(apiBase() + "/check/bulk", {
          method: "POST",
          headers: { "Content-Type": "application/json", "Accept": "application/json" },
          body: JSON.stringify({ usernames: items })
        });
      }, function (body) { renderBulkBody(bulkEls, body); });
    }
    bulkSubmit.addEventListener("click", submitBulk);
    bulkInput.addEventListener("keydown", function (e) {
      if ((e.ctrlKey || e.metaKey) && e.key === "Enter") { e.preventDefault(); submitBulk(); }
    });
  });
})();
