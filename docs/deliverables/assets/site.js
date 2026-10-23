/* my-planner 산출물 — site.js
 * 하는 일: 문서 목록 현재 위치 표시, 폰에서 목록 열고 닫기, "이 문서에서" 목차 만들기,
 * 접는 상세 열기(해시 이동 포함), 화면설계 콜아웃 번호 ↔ 설명 행 함께 강조.
 * 테마는 건드리지 않는다(뷰어가 data-theme을 정한다). 저장소가 없어도 모두 동작한다.
 */
(function () {
  "use strict";
  var doc = document;
  doc.documentElement.classList.add("js");

  /* 저장소: 쓸 수 없으면 조용히 무시 */
  var store = {
    get: function (k) { try { return window.localStorage.getItem(k); } catch (e) { return null; } },
    set: function (k, v) { try { window.localStorage.setItem(k, v); } catch (e) { /* 없음 */ } }
  };

  function ready(fn) {
    if (doc.readyState === "loading") doc.addEventListener("DOMContentLoaded", fn);
    else fn();
  }

  ready(function () {
    var pageEl = doc.querySelector("[data-doc]");
    var page = pageEl ? pageEl.getAttribute("data-doc") : "";

    /* 1. 문서 목록: 현재 문서 표시 (data-doc가 우선, 없으면 파일 이름) */
    if (!page) {
      var file = (location.pathname.split("/").pop() || "index.html").replace(/\.html?$/, "");
      page = file || "index";
    }
    var links = doc.querySelectorAll(".docnav a[data-doc]");
    for (var i = 0; i < links.length; i++) {
      if (links[i].getAttribute("data-doc") === page) links[i].setAttribute("aria-current", "page");
    }

    /* 2. 폰: 목록 열고 닫기 */
    var toggle = doc.querySelector(".navtoggle");
    var nav = doc.getElementById(toggle ? toggle.getAttribute("aria-controls") : "docnav");
    function setNav(open) {
      if (!toggle || !nav) return;
      nav.classList.toggle("is-open", open);
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
    }
    if (toggle && nav) {
      toggle.addEventListener("click", function () { setNav(!nav.classList.contains("is-open")); });
      nav.addEventListener("click", function (e) { if (e.target.closest && e.target.closest("a")) setNav(false); });
      doc.addEventListener("keydown", function (e) {
        if (e.key === "Escape" && nav.classList.contains("is-open")) { setNav(false); toggle.focus(); }
      });
      if (window.matchMedia) {
        var mq = window.matchMedia("(min-width: 960px)");
        var onMq = function () { if (mq.matches) setNav(false); };
        if (mq.addEventListener) mq.addEventListener("change", onMq); else if (mq.addListener) mq.addListener(onMq);
      }
    }

    /* 3. "이 문서에서" 목차(.toc[data-auto])와 바로 가기 막대(.jumpbar[data-auto]): main 안의 h2[id] */
    var toc = doc.querySelector(".toc[data-auto]");
    var jump = doc.querySelector(".jumpbar[data-auto]");
    var main = doc.querySelector("main");
    var heads = main ? main.querySelectorAll("h2[id]") : [];
    var groups = [];   /* groups[i] = 그 h2를 가리키는 링크들 */
    if (main && heads.length >= 2) {
      var ol = null;
      if (toc) {
        var title = doc.createElement("div");
        title.className = "toc__title"; title.textContent = "이 문서에서";
        ol = doc.createElement("ol");
        toc.appendChild(title); toc.appendChild(ol);
      }
      var autoJump = jump && !jump.querySelector("a");
      for (var h = 0; h < heads.length; h++) {
        var no = heads[h].querySelector(".section__no");
        var noText = no ? no.textContent.trim() : "";
        var label = heads[h].getAttribute("data-toc") || textWithout(heads[h], ".section__no");
        groups[h] = [];
        if (ol) {
          var li = doc.createElement("li");
          var a = doc.createElement("a");
          a.href = "#" + heads[h].id;
          a.textContent = (noText ? noText + " " : "") + label;
          li.appendChild(a); ol.appendChild(li); groups[h].push(a);
        }
        if (autoJump) {
          var j = doc.createElement("a");
          j.href = "#" + heads[h].id;
          if (noText) { var n = doc.createElement("span"); n.className = "jumpbar__no"; n.textContent = noText; j.appendChild(n); }
          j.appendChild(doc.createTextNode(heads[h].getAttribute("data-jump") || label));
          jump.appendChild(j); groups[h].push(j);
        }
      }
      if (jump && !autoJump) {   /* 손으로 쓴 막대도 현재 위치 표시 */
        var manual = jump.querySelectorAll('a[href^="#"]');
        for (var mj = 0; mj < manual.length; mj++) {
          for (var hh = 0; hh < heads.length; hh++) if (manual[mj].getAttribute("href") === "#" + heads[hh].id) groups[hh].push(manual[mj]);
        }
      }
      if ("IntersectionObserver" in window) {
        var currentIdx = -1;
        var io = new IntersectionObserver(function (entries) {
          entries.forEach(function (en) {
            if (!en.isIntersecting) return;
            var idx = Array.prototype.indexOf.call(heads, en.target);
            if (idx === currentIdx) return;
            if (currentIdx >= 0) groups[currentIdx].forEach(function (x) { x.removeAttribute("aria-current"); });
            currentIdx = idx;
            groups[idx].forEach(function (x) {
              x.setAttribute("aria-current", "true");
              if (x.parentNode === jump && jump.scrollWidth > jump.clientWidth) {
                jump.scrollLeft = x.offsetLeft - jump.clientWidth / 2 + x.offsetWidth / 2;
              }
            });
          });
        }, { rootMargin: "-15% 0px -70% 0px" });
        for (var k = 0; k < heads.length; k++) io.observe(heads[k]);
      }
    } else {
      if (toc) toc.setAttribute("data-empty", "");
      if (jump && !jump.querySelector("a")) jump.setAttribute("data-empty", "");
    }

    /* 4. 접는 상세: 해시 대상이 접힌 상세 안에 있으면 연다 + 열림 상태 기억(선택) */
    function openFor(hash) {
      if (!hash || hash.length < 2) return;
      var id = decodeURIComponent(hash.slice(1));
      var t = doc.getElementById(id);
      if (!t) return;
      var d = t.closest ? t.closest("details") : null;
      while (d) { d.open = true; d = d.parentElement ? d.parentElement.closest("details") : null; }
      if (t.tagName === "DETAILS") t.open = true;
    }
    openFor(location.hash);
    window.addEventListener("hashchange", function () { openFor(location.hash); });
    doc.addEventListener("click", function (e) {
      var a = e.target.closest ? e.target.closest('a[href^="#"]') : null;
      if (a) openFor(a.getAttribute("href"));
    });
    var keyBase = "mp-details:" + page + ":";
    var dets = doc.querySelectorAll("details.more[id]");
    for (var j = 0; j < dets.length; j++) {
      (function (d) {
        var saved = store.get(keyBase + d.id);
        if (saved === "1") d.open = true;
        d.addEventListener("toggle", function () { store.set(keyBase + d.id, d.open ? "1" : "0"); });
      })(dets[j]);
    }
    var togg = doc.querySelectorAll("[data-toggle-all]");
    for (var t2 = 0; t2 < togg.length; t2++) {
      togg[t2].addEventListener("click", function (e) {
        var scope = doc.querySelector(e.currentTarget.getAttribute("data-toggle-all") || "main") || doc;
        var all = scope.querySelectorAll("details.more");
        var anyClosed = false;
        for (var q = 0; q < all.length; q++) if (!all[q].open) anyClosed = true;
        for (var r = 0; r < all.length; r++) all[r].open = anyClosed;
        e.currentTarget.textContent = anyClosed ? "모두 접기" : "모두 펼치기";
      });
    }

    /* 5. 화면설계: 같은 data-mk를 가진 요소(표식, 화면 요소, 설명 행)를 함께 강조 */
    function hot(key, on) {
      var els = doc.querySelectorAll('[data-mk="' + key.replace(/"/g, "") + '"]');
      for (var m = 0; m < els.length; m++) els[m].classList.toggle("is-hot", on);
    }
    ["mouseover", "focusin"].forEach(function (ev) {
      doc.addEventListener(ev, function (e) {
        var el = e.target.closest ? e.target.closest("[data-mk]") : null;
        if (el) hot(el.getAttribute("data-mk"), true);
      });
    });
    ["mouseout", "focusout"].forEach(function (ev) {
      doc.addEventListener(ev, function (e) {
        var el = e.target.closest ? e.target.closest("[data-mk]") : null;
        if (el) hot(el.getAttribute("data-mk"), false);
      });
    });

    /* 5b. mermaid 그림은 줄이지 않는다: 렌더된 SVG의 원래 폭(max-width)을 최소 폭으로 고정해 판 안에서 가로 스크롤 */
    function keepNatural(svg) {
      if (svg.getAttribute("data-mp-natural")) return;
      var w = parseFloat(svg.style.maxWidth) || (svg.viewBox && svg.viewBox.baseVal ? svg.viewBox.baseVal.width : 0);
      if (!w) return;
      svg.setAttribute("data-mp-natural", "1");
      svg.style.minWidth = Math.round(Math.min(w, 1400)) + "px";   /* 아주 큰 그림만 1400px까지 줄인다 */
      var body = svg.closest(".fig__body");
      if (body && body.scrollWidth > body.clientWidth + 2 && !body.hasAttribute("tabindex")) {
        body.setAttribute("tabindex", "0");
        body.setAttribute("aria-label", "가로로 스크롤되는 그림");
      }
    }
    function scanMermaid() {
      var svgs = doc.querySelectorAll(".fig__body .mermaid svg, .fig__body svg[id^='mermaid']");
      for (var s = 0; s < svgs.length; s++) keepNatural(svgs[s]);
    }
    scanMermaid();
    if ("MutationObserver" in window) {
      var figs = doc.querySelectorAll(".fig__body");
      var mo = new MutationObserver(scanMermaid);
      for (var fb = 0; fb < figs.length; fb++) mo.observe(figs[fb], { childList: true, subtree: true });
    }

    /* 6. 넓은 표·그림 래퍼: 키보드로 가로 스크롤할 수 있게 */
    var wraps = doc.querySelectorAll(".table-wrap, .fig__body, .dayrail__scroll");
    for (var w = 0; w < wraps.length; w++) {
      var el = wraps[w];
      if (el.scrollWidth > el.clientWidth + 2 && !el.hasAttribute("tabindex")) {
        el.setAttribute("tabindex", "0");
        if (!el.hasAttribute("aria-label")) el.setAttribute("aria-label", "가로로 스크롤되는 영역");
      }
    }
  });

  function textWithout(el, sel) {
    var c = el.cloneNode(true);
    var rm = c.querySelectorAll(sel + ", svg");
    for (var i = 0; i < rm.length; i++) rm[i].parentNode.removeChild(rm[i]);
    return c.textContent.replace(/\s+/g, " ").trim();
  }
})();
