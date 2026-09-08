(function () {
  "use strict";

  var root = document.documentElement;
  var deck = document.getElementById("deck");
  if (!deck) return;
  root.classList.add("js");
  var qaMode = /[?&]qa=1\b/.test(window.location.search);
  var captureMode = /[?&]capture=1\b/.test(window.location.search);
  if (qaMode || captureMode) root.classList.add("qa-mode");

  var slides = Array.prototype.slice.call(deck.querySelectorAll(".slide"));
  var indicator = deck.querySelector(".page-indicator");
  var qaPanel = deck.querySelector(".qa-panel");
  var reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var defaultTransition = deck.getAttribute("data-transition") || "push";
  var current = 0;
  var wheelTotal = 0;
  var wheelTimer = 0;
  var wheelLockedUntil = 0;
  var touchStart = null;
  var countFrames = [];
  var qaTimer = 0;
  var demoTimer = 0;
  var deckMap = null;
  var mapOpen = false;
  var mapReturnFocus = null;

  function pad(value) { return String(value).padStart(2, "0"); }
  function clamp(value, min, max) { return Math.max(min, Math.min(max, value)); }
  function isInteractive(target) { return !!(target && typeof target.closest === "function" && target.closest("a, input, textarea, select, button, [contenteditable='true']")); }

  function resetAnimations(slide) {
    slide.classList.remove("is-entered");
    slide.querySelectorAll("[data-delay]").forEach(function (node) {
      var delay = clamp(Number(node.getAttribute("data-delay")) || 0, 0, 1200);
      node.style.setProperty("--delay", delay + "ms");
    });
    slide.querySelectorAll("[data-duration]").forEach(function (node) {
      var duration = clamp(Number(node.getAttribute("data-duration")) || 420, 160, 1600);
      node.style.setProperty("--object-duration", duration + "ms");
    });
    slide.querySelectorAll("[data-value]").forEach(function (node) {
      var value = clamp(Number(node.getAttribute("data-value")) || 0, 0, 100);
      node.style.setProperty("--bar-value", value / 100);
    });
    slide.querySelectorAll("[data-draw]").forEach(function (node) {
      if (typeof node.getTotalLength === "function") node.style.setProperty("--path-length", String(Math.ceil(node.getTotalLength())));
    });
    slide.querySelectorAll("[data-ring]").forEach(function (node) {
      var value = clamp(Number(node.getAttribute("data-ring")) || 0, 0, 100);
      node.style.setProperty("--ring-value", value);
    });
    countFrames.forEach(cancelAnimationFrame);
    countFrames = [];
  }

  function animateCounts(slide) {
    slide.querySelectorAll("[data-count]").forEach(function (node) {
      var target = Number(node.getAttribute("data-count"));
      if (!Number.isFinite(target)) return;
      var prefix = node.getAttribute("data-prefix") || "";
      var suffix = node.getAttribute("data-suffix") || "";
      var decimals = Math.max(0, Number(node.getAttribute("data-decimals")) || 0);
      var start = performance.now();
      var duration = reduced ? 0 : clamp(Number(node.getAttribute("data-duration")) || 700, 160, 1600);
      function frame(now) {
        var progress = duration ? Math.min(1, (now - start) / duration) : 1;
        var eased = 1 - Math.pow(1 - progress, 3);
        var value = target * eased;
        node.textContent = prefix + value.toLocaleString(undefined, { minimumFractionDigits: decimals, maximumFractionDigits: decimals }) + suffix;
        if (progress < 1) countFrames.push(requestAnimationFrame(frame));
      }
      countFrames.push(requestAnimationFrame(frame));
    });
  }

  function stopDemoLoop() {
    clearTimeout(demoTimer);
    demoTimer = 0;
  }

  function demoRunTime(slide) {
    var longest = 0;
    slide.querySelectorAll("[data-animate], [data-draw], [data-count], [data-value], [data-ring]").forEach(function (node) {
      var delay = clamp(Number(node.getAttribute("data-delay")) || 0, 0, 4000);
      var fallback = node.hasAttribute("data-count") ? 700 : node.hasAttribute("data-draw") ? 760 : node.hasAttribute("data-ring") ? 700 : node.hasAttribute("data-value") ? 650 : 620;
      var duration = clamp(Number(node.getAttribute("data-duration")) || fallback, 160, 1600);
      longest = Math.max(longest, delay + duration);
    });
    return longest || 620;
  }

  function scheduleDemoReplay(slide, dwell) {
    demoTimer = window.setTimeout(function () { replayDemo(slide, dwell); }, demoRunTime(slide) + dwell);
  }

  function replayDemo(slide, dwell) {
    if (!slide.classList.contains("is-active")) return;
    resetAnimations(slide);
    slide.classList.remove("is-entered");
    requestAnimationFrame(function () {
      requestAnimationFrame(function () {
        if (!slide.classList.contains("is-active")) return;
        slide.classList.add("is-entered");
        animateCounts(slide);
        scheduleDemoReplay(slide, dwell);
      });
    });
  }

  function enterSlide(slide) {
    stopDemoLoop();
    resetAnimations(slide);
    requestAnimationFrame(function () {
      requestAnimationFrame(function () {
        slide.classList.add("is-entered");
        animateCounts(slide);
        var demoDwell = clamp(Number(slide.getAttribute("data-demo-loop")) || 0, 0, 4000);
        if (demoDwell >= 250 && !reduced && !qaMode && !captureMode) {
          scheduleDemoReplay(slide, demoDwell);
        }
      });
    });
  }

  function slideTitle(slide) {
    var declared = slide.getAttribute("data-nav-title");
    if (declared) return declared;
    var heading = slide.querySelector("h1, h2, h3");
    return heading ? heading.textContent.trim().replace(/\s+/g, " ") : "Untitled";
  }

  function updateMapCurrent() {
    if (!deckMap) return;
    deckMap.querySelectorAll("[data-nav-index]").forEach(function (button) {
      var active = Number(button.getAttribute("data-nav-index")) === current;
      if (active) button.setAttribute("aria-current", "page");
      else button.removeAttribute("aria-current");
    });
  }

  function closeMap(restoreFocus) {
    if (!deckMap || !mapOpen) return;
    mapOpen = false;
    deckMap.hidden = true;
    root.classList.remove("map-open");
    if (indicator) indicator.setAttribute("aria-expanded", "false");
    if (restoreFocus && mapReturnFocus && typeof mapReturnFocus.focus === "function") mapReturnFocus.focus({ preventScroll: true });
  }

  function openMap() {
    if (!deckMap || mapOpen) return;
    mapReturnFocus = document.activeElement;
    mapOpen = true;
    deckMap.hidden = false;
    root.classList.add("map-open");
    if (indicator) indicator.setAttribute("aria-expanded", "true");
    updateMapCurrent();
    var active = deckMap.querySelector('[aria-current="page"]');
    var close = deckMap.querySelector(".deck-map-close");
    (active || close).focus({ preventScroll: true });
  }

  function jumpTo(target, focus) {
    var slide = typeof target === "string" ? deck.querySelector(target) : target;
    var index = slides.indexOf(slide);
    if (index >= 0) update(index, { focus: !!focus });
  }

  function buildChapterMap() {
    if (slides.length <= 20) return;
    var groups = [];
    slides.forEach(function (slide, index) {
      var section = slide.getAttribute("data-section") || "Other";
      var group = groups.find(function (item) { return item.name === section; });
      if (!group) { group = { name: section, slides: [] }; groups.push(group); }
      group.slides.push({ slide: slide, index: index, title: slideTitle(slide) });
    });

    deckMap = document.createElement("div");
    deckMap.className = "deck-map";
    deckMap.hidden = true;
    deckMap.setAttribute("role", "dialog");
    deckMap.setAttribute("aria-modal", "true");
    deckMap.setAttribute("aria-labelledby", "deck-map-title");
    var panel = document.createElement("div");
    panel.className = "deck-map-panel";
    var head = document.createElement("div");
    head.className = "deck-map-head";
    var title = document.createElement("h2");
    title.id = "deck-map-title";
    title.textContent = "Jump to a chapter or slide";
    var close = document.createElement("button");
    close.type = "button";
    close.className = "deck-map-close";
    close.textContent = "Close";
    close.addEventListener("click", function () { closeMap(true); });
    head.appendChild(title);
    head.appendChild(close);
    var sections = document.createElement("div");
    sections.className = "deck-map-sections";
    groups.forEach(function (group) {
      var wrapper = document.createElement("section");
      wrapper.className = "deck-map-group";
      var heading = document.createElement("h3");
      heading.textContent = group.name;
      var list = document.createElement("ol");
      list.className = "deck-map-list";
      group.slides.forEach(function (item) {
        var row = document.createElement("li");
        var button = document.createElement("button");
        button.type = "button";
        button.className = "deck-map-jump";
        button.setAttribute("data-nav-index", String(item.index));
        var number = document.createElement("span");
        number.textContent = pad(item.index + 1);
        button.appendChild(number);
        button.appendChild(document.createTextNode(item.title));
        button.addEventListener("click", function () {
          closeMap(false);
          update(item.index, { focus: true });
        });
        row.appendChild(button);
        list.appendChild(row);
      });
      wrapper.appendChild(heading);
      wrapper.appendChild(list);
      sections.appendChild(wrapper);
    });
    panel.appendChild(head);
    panel.appendChild(sections);
    deckMap.appendChild(panel);
    deck.appendChild(deckMap);
    deck.classList.add("has-map");
    if (indicator) {
      indicator.removeAttribute("disabled");
      indicator.setAttribute("aria-haspopup", "dialog");
      indicator.setAttribute("aria-expanded", "false");
      indicator.setAttribute("aria-label", "Open slide navigation");
      indicator.addEventListener("click", openMap);
    }
  }

  function update(next, options) {
    if (!slides.length) return;
    var target = clamp(next, 0, slides.length - 1);
    var changed = target !== current || (options && options.force);
    current = target;
    deck.setAttribute("data-transition", slides[current].getAttribute("data-transition") || defaultTransition);
    slides.forEach(function (slide, index) {
      slide.classList.toggle("is-active", index === current);
      slide.classList.toggle("is-before", index < current);
      slide.classList.toggle("is-after", index > current);
      slide.setAttribute("aria-hidden", index === current ? "false" : "true");
      if (index !== current) slide.classList.remove("is-entered");
    });
    if (indicator) indicator.textContent = pad(current + 1);
    if (indicator && deckMap) indicator.setAttribute("aria-label", "Open slide navigation, current page " + pad(current + 1));
    deck.style.setProperty("--ambient-x", ((current % 3) - 1) * 2 + "%");
    deck.style.setProperty("--ambient-y", (((current + 1) % 3) - 1) * 1.5 + "%");
    var hash = "#" + slides[current].id;
    if (window.location.hash !== hash) history.replaceState(null, "", hash);
    updateMapCurrent();
    if (changed) enterSlide(slides[current]);
    if (options && options.focus) slides[current].focus({ preventScroll: true });
    if (qaMode) scheduleQA();
  }

  function goBy(delta, focus) { update(current + delta, { focus: !!focus }); }

  function onKey(event) {
    if (event.altKey || event.ctrlKey || event.metaKey) return;
    if (mapOpen) {
      if (event.key === "Escape" || event.key.toLowerCase() === "m") {
        closeMap(true);
        event.preventDefault();
      } else if (event.key === "Tab") {
        var focusable = Array.prototype.slice.call(deckMap.querySelectorAll("button:not([disabled])"));
        if (focusable.length) {
          var first = focusable[0];
          var last = focusable[focusable.length - 1];
          if (event.shiftKey && document.activeElement === first) { last.focus(); event.preventDefault(); }
          else if (!event.shiftKey && document.activeElement === last) { first.focus(); event.preventDefault(); }
        }
      }
      return;
    }
    if (event.key.toLowerCase() === "m" && deckMap && !isInteractive(event.target)) {
      openMap();
      event.preventDefault();
      return;
    }
    if (isInteractive(event.target)) return;
    var handled = true;
    switch (event.key) {
      case "ArrowRight": case "ArrowDown": case "PageDown": case " ": goBy(1, true); break;
      case "ArrowLeft": case "ArrowUp": case "PageUp": goBy(-1, true); break;
      case "Home": update(0, { focus: true }); break;
      case "End": update(slides.length - 1, { focus: true }); break;
      default: handled = false;
    }
    if (handled) event.preventDefault();
  }

  function onWheel(event) {
    if (mapOpen) { event.preventDefault(); return; }
    if (event.ctrlKey || isInteractive(event.target)) return;
    event.preventDefault();
    var now = performance.now();
    if (now < wheelLockedUntil) return;
    wheelTotal += Math.abs(event.deltaY) >= Math.abs(event.deltaX) ? event.deltaY : event.deltaX;
    clearTimeout(wheelTimer);
    wheelTimer = setTimeout(function () { wheelTotal = 0; }, 180);
    if (Math.abs(wheelTotal) < 42) return;
    goBy(wheelTotal > 0 ? 1 : -1, false);
    wheelTotal = 0;
    wheelLockedUntil = now + (reduced ? 120 : 560);
  }

  function onTouchStart(event) {
    var touch = event.changedTouches && event.changedTouches[0];
    if (touch) touchStart = { x: touch.clientX, y: touch.clientY };
  }

  function onTouchEnd(event) {
    if (!touchStart) return;
    var touch = event.changedTouches && event.changedTouches[0];
    if (!touch) return;
    var dx = touchStart.x - touch.clientX;
    var dy = touchStart.y - touch.clientY;
    var primary = Math.abs(dy) >= Math.abs(dx) ? dy : dx;
    if (Math.abs(primary) >= 54) goBy(primary > 0 ? 1 : -1, false);
    touchStart = null;
  }

  function webDeckQA() {
    var deckRect = deck.getBoundingClientRect();
    var ratio = deckRect.width / deckRect.height;
    var ids = slides.map(function (slide) { return slide.id; });
    var duplicateIds = ids.filter(function (id, index) { return id && ids.indexOf(id) !== index; });
    var overflows = [];
    var missingLayouts = [];
    var badValues = [];
    var badRings = [];
    var fillFailures = [];
    slides.forEach(function (slide, index) {
      var slideRect = slide.getBoundingClientRect();
      var overflowX = 0;
      var overflowY = 0;
      var overflowXNode = "";
      var overflowYNode = "";
      slide.querySelectorAll("*").forEach(function (node) {
        if (node.hasAttribute("data-qa-ignore")) return;
        if (node.getAttribute("aria-hidden") === "true") return;
        var rect = node.getBoundingClientRect();
        if (!rect.width && !rect.height) return;
        var nodeName = node.tagName.toLowerCase() + (node.className && typeof node.className === "string" ? "." + node.className.trim().replace(/\s+/g, ".") : "");
        var rectX = Math.max(slideRect.left - rect.left, rect.right - slideRect.right);
        var rectY = Math.max(slideRect.top - rect.top, rect.bottom - slideRect.bottom);
        if (rectX > overflowX) { overflowX = rectX; overflowXNode = nodeName; }
        if (rectY > overflowY) { overflowY = rectY; overflowYNode = nodeName; }
        if (!node.childElementCount) {
          var style = window.getComputedStyle(node);
          if (/(hidden|clip|auto|scroll)/.test(style.overflowX)) {
            var scrollX = node.scrollWidth - node.clientWidth;
            if (scrollX > overflowX) { overflowX = scrollX; overflowXNode = nodeName; }
          }
          if (/(hidden|clip|auto|scroll)/.test(style.overflowY)) {
            var scrollY = node.scrollHeight - node.clientHeight;
            if (scrollY > overflowY) { overflowY = scrollY; overflowYNode = nodeName; }
          }
        }
      });
      overflowX = Math.max(0, Math.ceil(overflowX));
      overflowY = Math.max(0, Math.ceil(overflowY));
      slide.classList.toggle("qa-overflow", overflowX > 2 || overflowY > 2);
      if (overflowX > 2 || overflowY > 2) overflows.push({ slide: index + 1, x: overflowX, y: overflowY, xNode: overflowXNode, yNode: overflowYNode });
      if (!slide.getAttribute("data-layout")) missingLayouts.push(index + 1);
      slide.querySelectorAll("[data-value]").forEach(function (node) {
        var value = Number(node.getAttribute("data-value"));
        if (!Number.isFinite(value) || value < 0 || value > 100) badValues.push({ slide: index + 1, value: node.getAttribute("data-value") });
      });
      slide.querySelectorAll("[data-ring]").forEach(function (node) {
        var value = Number(node.getAttribute("data-ring"));
        if (!Number.isFinite(value) || value < 0 || value > 100) badRings.push({ slide: index + 1, value: node.getAttribute("data-ring") });
      });
      var fillNodes = Array.prototype.slice.call(slide.querySelectorAll("[data-fill-target]"));
      var primaryContent = slide.querySelector(".slide-content");
      if (primaryContent && parseFloat(window.getComputedStyle(primaryContent).getPropertyValue("--fill-target")) > 0 && fillNodes.indexOf(primaryContent) === -1) fillNodes.push(primaryContent);
      fillNodes.forEach(function (node) {
        var nodeStyle = window.getComputedStyle(node);
        var target = Number(node.getAttribute("data-fill-target") || nodeStyle.getPropertyValue("--fill-target"));
        var nodeRect = node.getBoundingClientRect();
        var children = Array.prototype.filter.call(node.children, function (child) {
          var childRect = child.getBoundingClientRect();
          return childRect.width > 0 && childRect.height > 0;
        });
        if (!Number.isFinite(target) || target <= 0 || target > 1 || !children.length || !nodeRect.height) {
          fillFailures.push({ slide: index + 1, target: target, actual: 0 });
          return;
        }
        var top = Math.min.apply(null, children.map(function (child) { return child.getBoundingClientRect().top; }));
        var bottom = Math.max.apply(null, children.map(function (child) { return child.getBoundingClientRect().bottom; }));
        var contentHeight = nodeRect.height - (parseFloat(nodeStyle.paddingTop) || 0) - (parseFloat(nodeStyle.paddingBottom) || 0);
        var actual = contentHeight > 0 ? (bottom - top) / contentHeight : 0;
        if (actual + .005 < target) fillFailures.push({ slide: index + 1, target: target, actual: Number(actual.toFixed(3)) });
      });
    });
    var viewportFit = deckRect.left >= -1 && deckRect.top >= -1 && deckRect.right <= window.innerWidth + 1 && deckRect.bottom <= window.innerHeight + 1;
    var currentOnly = !!indicator && /^\d+$/.test(indicator.textContent.trim());
    var longDeckReady = slides.length <= 20 || (!!deckMap && slides[1] && slides[1].getAttribute("data-layout") === "toc" && slides.every(function (slide) { return !!slide.getAttribute("data-section"); }));
    var report = {
      pass: Math.abs(ratio - 16 / 9) <= .002 && viewportFit && !overflows.length && !duplicateIds.length && !missingLayouts.length && !badValues.length && !badRings.length && !fillFailures.length && currentOnly && longDeckReady,
      ratio: Number(ratio.toFixed(4)),
      expectedRatio: Number((16 / 9).toFixed(4)),
      viewportFit: viewportFit,
      slideCount: slides.length,
      overflows: overflows,
      duplicateIds: duplicateIds,
      missingLayouts: missingLayouts,
      invalidBarValues: badValues,
      invalidRingValues: badRings,
      fillFailures: fillFailures,
      pageIndicator: indicator ? indicator.textContent : null,
      currentOnlyIndicator: currentOnly,
      longDeckNavigation: longDeckReady
    };
    console.log("[web-deck-qa]", report);
    return report;
  }

  function renderQA() {
    if (!qaPanel) return;
    var report = webDeckQA();
    qaPanel.hidden = false;
    qaPanel.dataset.pass = String(report.pass);
    var overflowSlides = report.overflows.length ? " [" + report.overflows.map(function (item) { return item.slide + ":" + item.x + "/" + item.y + " " + (item.xNode || item.yNode); }).join(",") + "]" : "";
    var selfTest = window.webDeckSelfTestResult;
    var failedChecks = selfTest ? selfTest.checks.filter(function (check) { return !check.pass; }).map(function (check) { return check.name; }) : [];
    var selfTestLabel = selfTest ? " | input " + (selfTest.pass ? "PASS" : "FAIL[" + failedChecks.join(",") + "]") : "";
    qaPanel.textContent = (report.pass ? "PASS" : "FAIL") + " | ratio " + report.ratio + " | overflow " + report.overflows.length + overflowSlides + " | layouts " + report.missingLayouts.length + " | fill " + report.fillFailures.length + " | indicator " + report.pageIndicator + selfTestLabel;
  }

  function scheduleQA() {
    clearTimeout(qaTimer);
    qaTimer = setTimeout(renderQA, reduced ? 20 : 620);
  }

  function runSelfTest() {
    var checks = [];
    function record(name, pass) { checks.push({ name: name, pass: !!pass }); }
    update(0, { force: true });
    record("numeric-indicator", !!indicator && indicator.textContent === "01");
    if (deckMap && indicator) {
      indicator.click();
      record("map-open", mapOpen && !deckMap.hidden);
      document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true }));
      record("map-close", !mapOpen && deckMap.hidden);
    }
    var firstChapter = deck.querySelector("[data-jump]");
    if (firstChapter) {
      var chapterTarget = deck.querySelector(firstChapter.getAttribute("data-jump"));
      firstChapter.click();
      record("chapter-jump", current === slides.indexOf(chapterTarget));
      update(0, { force: true });
    }
    document.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowRight", bubbles: true, cancelable: true }));
    record("keyboard-next", current === Math.min(1, slides.length - 1));
    document.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowLeft", bubbles: true, cancelable: true }));
    record("keyboard-previous", current === 0);
    deck.dispatchEvent(new WheelEvent("wheel", { deltaY: 100, bubbles: true, cancelable: true }));
    record("wheel-next", current === Math.min(1, slides.length - 1));
    var afterFirstWheel = current;
    deck.dispatchEvent(new WheelEvent("wheel", { deltaY: 100, bubbles: true, cancelable: true }));
    record("wheel-lock", current === afterFirstWheel);
    document.dispatchEvent(new KeyboardEvent("keydown", { key: "End", bubbles: true, cancelable: true }));
    record("keyboard-end", current === slides.length - 1);
    document.dispatchEvent(new KeyboardEvent("keydown", { key: "Home", bubbles: true, cancelable: true }));
    record("keyboard-home", current === 0);
    var explorer = deck.querySelector("[data-explorer]");
    if (explorer) {
      var explorerButtons = explorer.querySelectorAll("[data-explorer-values]");
      if (explorerButtons.length > 1) explorerButtons[1].click();
      var explorerValue = explorer.querySelector("[data-explorer-bar] output");
      record("interactive-explorer", !!explorerValue && explorerValue.textContent === "68%");
      if (explorerButtons.length) explorerButtons[0].click();
    }
    var allocation = deck.querySelector("[data-allocation]");
    if (allocation) {
      var allocationInput = allocation.querySelector("#alloc-evidence");
      var allocationRemaining = allocation.querySelector("[data-allocation-remaining]");
      if (allocationInput) { allocationInput.value = "10"; allocationInput.dispatchEvent(new Event("input", { bubbles: true })); }
      record("interactive-allocation", !!allocationRemaining && allocationRemaining.textContent === "23");
      var allocationReset = allocation.querySelector("[data-allocation-reset]");
      if (allocationReset) allocationReset.click();
    }
    var simulator = deck.querySelector("[data-simulator]");
    if (simulator) {
      var simulatorInput = simulator.querySelector("#sim-demand");
      var simulatorScore = simulator.querySelector("[data-simulator-score]");
      var beforeScore = simulatorScore ? simulatorScore.textContent : "";
      if (simulatorInput) { simulatorInput.value = "10"; simulatorInput.dispatchEvent(new Event("input", { bubbles: true })); }
      record("interactive-simulator", !!simulatorScore && simulatorScore.textContent !== beforeScore);
      var simulatorReset = simulator.querySelector("[data-simulator-reset]");
      if (simulatorReset) simulatorReset.click();
    }
    var report = { pass: checks.every(function (check) { return check.pass; }), checks: checks };
    var output = document.createElement("output");
    output.id = "web-deck-selftest";
    output.hidden = true;
    output.dataset.pass = String(report.pass);
    output.textContent = JSON.stringify(report);
    document.body.appendChild(output);
    window.webDeckSelfTestResult = report;
    console.log("[web-deck-selftest]", report);
  }

  window.webDeckQA = webDeckQA;
  document.addEventListener("keydown", onKey);
  deck.addEventListener("wheel", onWheel, { passive: false });
  deck.addEventListener("touchstart", onTouchStart, { passive: true });
  deck.addEventListener("touchend", onTouchEnd, { passive: true });
  window.addEventListener("resize", function () { if (qaMode) scheduleQA(); });
  window.addEventListener("hashchange", function () {
    var id = decodeURIComponent(window.location.hash.slice(1));
    var index = slides.findIndex(function (slide) { return slide.id === id; });
    if (index >= 0) update(index, { force: true });
  });

  slides.forEach(function (slide, index) {
    slide.tabIndex = -1;
    slide.setAttribute("role", "group");
    slide.setAttribute("aria-roledescription", "slide");
    if (!slide.getAttribute("aria-label")) {
      var heading = slide.querySelector("h1, h2, h3");
      var name = heading ? heading.textContent.trim().replace(/\s+/g, " ") : "Untitled";
      slide.setAttribute("aria-label", name + ", " + (index + 1) + " of " + slides.length);
    }
  });
  buildChapterMap();
  deck.querySelectorAll("[data-jump]").forEach(function (button) {
    button.addEventListener("click", function () { jumpTo(button.getAttribute("data-jump"), true); });
  });

  deck.querySelectorAll("[data-explorer]").forEach(function (explorer) {
    var buttons = Array.prototype.slice.call(explorer.querySelectorAll("[data-explorer-values]"));
    var bars = Array.prototype.slice.call(explorer.querySelectorAll("[data-explorer-bar]"));
    var summary = explorer.querySelector("[data-explorer-summary]");
    function select(button) {
      var values = (button.getAttribute("data-explorer-values") || "").split(",").map(Number);
      buttons.forEach(function (item) { item.setAttribute("aria-pressed", String(item === button)); });
      bars.forEach(function (bar, index) {
        var value = clamp(values[index] || 0, 0, 100);
        bar.style.setProperty("--explorer-value", value + "%");
        var output = bar.querySelector("output");
        if (output) output.textContent = value + "%";
      });
      if (summary) summary.textContent = button.getAttribute("data-explorer-summary") || button.textContent.trim();
    }
    buttons.forEach(function (button) { button.addEventListener("click", function () { select(button); }); });
    if (buttons.length) select(buttons.find(function (button) { return button.getAttribute("aria-pressed") === "true"; }) || buttons[0]);
  });

  deck.querySelectorAll("[data-allocation]").forEach(function (game) {
    var inputs = Array.prototype.slice.call(game.querySelectorAll("input[type='range'][data-allocation-input]"));
    var remaining = game.querySelector("[data-allocation-remaining]");
    var score = game.querySelector("[data-allocation-score]");
    var result = game.querySelector("[data-allocation-result]");
    function render(changed) {
      var otherTotal = inputs.reduce(function (sum, input) { return sum + (input === changed ? 0 : Number(input.value)); }, 0);
      if (changed && otherTotal + Number(changed.value) > 100) changed.value = String(Math.max(0, 100 - otherTotal));
      var values = inputs.map(function (input) {
        var output = game.querySelector("[data-output-for='" + input.id + "']");
        if (output) output.textContent = input.value;
        return Number(input.value);
      });
      var total = values.reduce(function (sum, value) { return sum + value; }, 0);
      var pointsLeft = Math.max(0, 100 - total);
      var spread = Math.max.apply(null, values) - Math.min.apply(null, values);
      var outcome = Math.round(clamp(88 - spread * .8 + (values[2] || 0) * .25, 0, 100));
      if (remaining) remaining.textContent = String(pointsLeft);
      if (score) score.textContent = String(outcome);
      if (result) result.textContent = pointsLeft ? pointsLeft + " points remain. Use the full budget to lock the scenario." : spread <= 18 ? "Balanced enough to run the next test." : "The allocation is concentrated; expect a fragile result.";
    }
    inputs.forEach(function (input) { input.addEventListener("input", function () { render(input); }); });
    var reset = game.querySelector("[data-allocation-reset]");
    if (reset) reset.addEventListener("click", function () { inputs.forEach(function (input) { input.value = input.getAttribute("data-initial") || input.defaultValue; }); render(null); });
    render(null);
  });

  deck.querySelectorAll("[data-simulator]").forEach(function (simulator) {
    var inputs = Array.prototype.slice.call(simulator.querySelectorAll("input[type='range'][data-simulator-input]"));
    var score = simulator.querySelector("[data-simulator-score]");
    var result = simulator.querySelector("[data-simulator-result]");
    function render() {
      var values = inputs.map(function (input) {
        var output = simulator.querySelector("[data-output-for='" + input.id + "']");
        if (output) output.textContent = input.value;
        return Number(input.value);
      });
      var value = Math.round((values[0] || 0) * .45 + (values[1] || 0) * .4 + (100 - (values[2] || 0)) * .15);
      if (score) score.textContent = String(value);
      if (result) result.textContent = value >= 72 ? "Run the pilot" : value >= 52 ? "Strengthen the evidence" : "Hold and reframe";
    }
    inputs.forEach(function (input) { input.addEventListener("input", render); });
    var reset = simulator.querySelector("[data-simulator-reset]");
    if (reset) reset.addEventListener("click", function () { inputs.forEach(function (input) { input.value = input.getAttribute("data-initial") || input.defaultValue; }); render(); });
    render();
  });

  var initialId = decodeURIComponent(window.location.hash.slice(1));
  var initialIndex = slides.findIndex(function (slide) { return slide.id === initialId; });
  update(initialIndex >= 0 ? initialIndex : 0, { force: true });
  if (/[?&]map=1\b/.test(window.location.search) && deckMap) setTimeout(openMap, 60);
  if (/[?&]autotest=1\b/.test(window.location.search)) setTimeout(runSelfTest, 40);
})();
