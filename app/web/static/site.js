/* TG Username API — shared site behaviour.
   Dynamic base URL, copy buttons, live health indicator, mobile nav toggle. */
(function () {
  "use strict";

  function apiBase() {
    return window.location.origin + "/api/v1";
  }

  /* Fill [data-base-url] elements with the real API base URL. */
  function paintBaseUrls() {
    var base = apiBase();
    document.querySelectorAll("[data-base-url]").forEach(function (el) {
      el.textContent = base;
    });
    document.querySelectorAll("[data-base-url-suffix]").forEach(function (el) {
      el.textContent = base + el.getAttribute("data-base-url-suffix");
    });
  }

  /* Copy buttons: <button class="copy-btn" data-copy="#target-id"> */
  function bindCopyButtons() {
    document.querySelectorAll("[data-copy]").forEach(function (btn) {
      if (btn.dataset.bound === "1") return;
      btn.dataset.bound = "1";
      btn.addEventListener("click", function () {
        var target = document.querySelector(btn.getAttribute("data-copy"));
        if (!target) return;
        var text = target.textContent || "";
        copyText(text).then(function (ok) {
          var original = btn.textContent;
          btn.textContent = ok ? "Copied" : "Failed";
          btn.classList.add("copied");
          window.setTimeout(function () {
            btn.textContent = original;
            btn.classList.remove("copied");
          }, 1600);
        });
      });
    });
  }

  function copyText(text) {
    if (navigator.clipboard && window.isSecureContext) {
      return navigator.clipboard.writeText(text).then(
        function () { return true; },
        function () { return fallbackCopy(text); }
      );
    }
    return Promise.resolve(fallbackCopy(text));
  }

  function fallbackCopy(text) {
    try {
      var area = document.createElement("textarea");
      area.value = text;
      area.setAttribute("readonly", "");
      area.style.position = "absolute";
      area.style.left = "-9999px";
      document.body.appendChild(area);
      area.select();
      var ok = document.execCommand("copy");
      document.body.removeChild(area);
      return ok;
    } catch (err) {
      return false;
    }
  }

  /* Live health indicator in the navigation bar. */
  function paintHealth() {
    var dot = document.querySelector("[data-health-dot]");
    var label = document.querySelector("[data-health-label]");
    if (!dot) return;
    fetch("/api/health", { headers: { "Accept": "application/json" } })
      .then(function (res) {
        if (res.ok) {
          dot.classList.add("ok");
          if (label) label.textContent = "Operational";
        } else {
          dot.classList.add("down");
          if (label) label.textContent = "Degraded";
        }
      })
      .catch(function () {
        dot.classList.add("down");
        if (label) label.textContent = "Unavailable";
      });
  }

  /* Mobile navigation toggle */
  function bindNavToggle() {
    var toggle = document.getElementById("nav-toggle");
    var nav = document.getElementById("main-nav");
    if (!toggle || !nav) return;
    toggle.addEventListener("click", function () {
      var expanded = nav.classList.toggle("open");
      toggle.setAttribute("aria-expanded", expanded);
    });
    /* Close nav when clicking a link (mobile) */
    nav.querySelectorAll("a").forEach(function (link) {
      link.addEventListener("click", function () {
        nav.classList.remove("open");
        toggle.setAttribute("aria-expanded", "false");
      });
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    paintBaseUrls();
    bindCopyButtons();
    paintHealth();
    bindNavToggle();
  });
})();
