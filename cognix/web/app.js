/* Cognix interface. No framework, no build step: this file is the whole client. */
(() => {
  "use strict";

  const TOKEN = document.querySelector('meta[name="cognix-token"]').content;
  const $ = (id) => document.getElementById(id);

  // ---------------------------------------------------------------- icons
  const P = {
    mic: '<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5.5 11a6.5 6.5 0 0 0 13 0M12 17.5V21"/>',
    micOff: '<path d="M9 9.5V6a3 3 0 0 1 5.6-1.5M15 10.5V11a3 3 0 0 1-4.6 2.5M5.5 11a6.5 6.5 0 0 0 10.6 5M18.5 11c0 .9-.2 1.8-.5 2.6M12 17.5V21M4 4l16 16"/>',
    plus: '<path d="M12 5v14M5 12h14"/>',
    sliders: '<path d="M4 7h9M17 7h3M4 17h3M11 17h9"/><circle cx="15" cy="7" r="2"/><circle cx="9" cy="17" r="2"/>',
    close: '<path d="M6 6l12 12M18 6L6 18"/>',
    up: '<path d="M12 19V5M6 11l6-6 6 6"/>',
    stop: '<rect x="7" y="7" width="10" height="10" rx="2" fill="currentColor" stroke="none"/>',
    keyboard: '<rect x="3" y="6" width="18" height="12" rx="2.5"/><path d="M7 10h.01M11 10h.01M15 10h.01M8 14h8"/>',
    arrow: '<path d="M5 12h14M13 6l6 6-6 6"/>',
    app: '<rect x="4" y="4" width="7" height="7" rx="2"/><rect x="13" y="4" width="7" height="7" rx="2"/><rect x="4" y="13" width="7" height="7" rx="2"/><rect x="13" y="13" width="7" height="7" rx="2"/>',
    search: '<circle cx="11" cy="11" r="6.5"/><path d="M20 20l-4.2-4.2"/>',
    file: '<path d="M7 3h7l4 4v14H7z"/><path d="M14 3v4h4"/>',
    pdf: '<path d="M7 3h7l4 4v14H7z"/><path d="M14 3v4h4M10 13h4M10 16.5h4"/>',
    doc: '<path d="M7 3h7l4 4v14H7z"/><path d="M14 3v4h4M10 12h4M10 15h4M10 18h2"/>',
    text: '<path d="M7 3h7l4 4v14H7z"/><path d="M14 3v4h4M10 12h4M10 15h4M10 18h2"/>',
    code: '<path d="M9 8l-4 4 4 4M15 8l4 4-4 4"/>',
    sheet: '<rect x="4" y="5" width="16" height="14" rx="2"/><path d="M4 10h16M4 14.5h16M10 5v14"/>',
    slides: '<rect x="3.5" y="5" width="17" height="11" rx="2"/><path d="M12 16v4M8.5 20h7"/>',
    image: '<rect x="4" y="5" width="16" height="14" rx="2.5"/><circle cx="9" cy="10" r="1.5"/><path d="M5 17l4.5-4 3.5 3 2.5-2 3.5 3"/>',
    audio: '<path d="M9 18V6l10-2v12"/><circle cx="6.5" cy="18" r="2.5"/><circle cx="16.5" cy="16" r="2.5"/>',
    video: '<rect x="3.5" y="6" width="12" height="12" rx="2.5"/><path d="M15.5 10.5l5-3v9l-5-3"/>',
    archive: '<path d="M4 8h16v11H4zM3 5h18v3H3zM10 12h4"/>',
    folder: '<path d="M3.5 7.5a2 2 0 0 1 2-2h4l2 2.5h7a2 2 0 0 1 2 2v7.5a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2z"/>',
    globe: '<circle cx="12" cy="12" r="8.5"/><path d="M3.5 12h17M12 3.5c2.6 2.8 2.6 14.2 0 17M12 3.5c-2.6 2.8-2.6 14.2 0 17"/>',
    link: '<path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.700l-1 1M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.700l1-1"/>',
    volume: '<path d="M4 10v4h3.500l4.500 4V6L7.500 10zM16 9a4 4 0 0 1 0 6M18.500 6.500a8 8 0 0 1 0 11"/>',
    music: '<path d="M9 18V6l10-2v12"/><circle cx="6.5" cy="18" r="2.5"/><circle cx="16.5" cy="16" r="2.5"/>',
    chip: '<rect x="7" y="7" width="10" height="10" rx="2"/><path d="M10 3v4M14 3v4M10 17v4M14 17v4M3 10h4M3 14h4M17 10h4M17 14h4"/>',
    moon: '<path d="M19.500 14.500A8 8 0 0 1 9.500 4.500a8 8 0 1 0 10 10z"/>',
    camera: '<path d="M4 8.500h3.500L9 6h6l1.500 2.500H20V19H4z"/><circle cx="12" cy="13.500" r="3.200"/>',
    clipboard: '<rect x="6" y="5" width="12" height="16" rx="2"/><path d="M9.500 5V3.500h5V5"/>',
    bolt: '<path d="M13 3L5.500 13.500H11l-1 7.500 7.500-10.500H12z"/>',
    spark: '<path d="M12 4v4M12 16v4M4 12h4M16 12h4M7 7l2 2M15 15l2 2M17 7l-2 2M9 15l-2 2"/>',
  };
  function icon(name) {
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("fill", "none");
    svg.setAttribute("stroke", "currentColor");
    svg.setAttribute("stroke-width", "1.6");
    svg.setAttribute("stroke-linecap", "round");
    svg.setAttribute("stroke-linejoin", "round");
    svg.setAttribute("aria-hidden", "true");
    svg.innerHTML = P[name] || P.file; // constant markup defined above, never user data
    return svg;
  }
  function el(tag, cls, text) {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text != null) node.textContent = text;
    return node;
  }

  // ---------------------------------------------------------------- server calls
  async function api(action, body) {
    try {
      const res = await fetch("/api/" + action, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Cognix-Token": TOKEN },
        body: JSON.stringify(body || {}),
      });
      return res.ok ? res.json() : null;
    } catch {
      return null;
    }
  }

  // ---------------------------------------------------------------- the orb
  const orb = (() => {
    const glow = $("orb-glow"), ring = $("orb-ring");
    const g = glow.getContext("2d"), r = ring.getContext("2d");
    const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
    const TICKS = 132;
    // Each phase is a target the ring eases toward: energy (tick length),
    // warmth (bone → ember), spin (rotation), comet (the thinking sweep).
    const LOOKS = {
      starting: { energy: 0.1, warmth: 0.25, spin: 0.25, comet: 1, dim: 0.75 },
      idle: { energy: 0.11, warmth: 0.24, spin: 0.05, comet: 0, dim: 1 },
      listening: { energy: 0.3, warmth: 1, spin: 0.1, comet: 0, dim: 1 },
      thinking: { energy: 0.24, warmth: 0.75, spin: 0.5, comet: 1, dim: 1 },
      speaking: { energy: 0.34, warmth: 0.9, spin: 0.08, comet: 0, dim: 1 },
      muted: { energy: 0.03, warmth: 0, spin: 0.01, comet: 0, dim: 0.42 },
    };
    const now = { ...LOOKS.starting };
    let phase = "starting", level = 0, levelTarget = 0, hearing = 0, hearingTarget = 0;
    let size = 0, dpr = 1, rot = 0, last = performance.now(), frame = 0;

    // Smooth 1-D value noise, looped around the ring so there is no seam.
    const seeds = Array.from({ length: 256 }, () => Math.random());
    function noise(x) {
      const i = Math.floor(x), f = x - i, u = f * f * (3 - 2 * f);
      return seeds[i & 255] * (1 - u) + seeds[(i + 1) & 255] * u;
    }
    function ringNoise(angle, t, scale) {
      return noise(64 + Math.cos(angle) * scale + t) * 0.5 + noise(128 + Math.sin(angle) * scale + t * 1.3) * 0.5;
    }

    function resize() {
      const rect = ring.getBoundingClientRect();
      dpr = Math.min(window.devicePixelRatio || 1, 2);
      size = Math.max(60, rect.width);
      for (const c of [glow, ring]) { c.width = c.height = Math.round(size * dpr); }
    }
    new ResizeObserver(resize).observe(ring);

    const mix = (a, b, t) => a + (b - a) * t;
    function ember(t, alpha) { // bone white → ember → deep ember
      const stops = [[241, 238, 232], [255, 180, 92], [255, 125, 59]];
      const k = Math.min(1.999, Math.max(0, t) * 2), i = Math.floor(k), f = k - i;
      const c = stops[i].map((v, n) => Math.round(mix(v, stops[i + 1][n], f)));
      return `rgba(${c[0]},${c[1]},${c[2]},${alpha})`;
    }

    function draw(ts) {
      frame = requestAnimationFrame(draw);
      const dt = Math.min(0.05, (ts - last) / 1000); last = ts;
      const t = ts / 1000;
      const look = LOOKS[phase] || LOOKS.idle;
      const ease = 1 - Math.pow(0.0025, dt);
      for (const k in now) now[k] = mix(now[k], look[k], ease);
      level = mix(level, levelTarget, levelTarget > level ? 0.5 : 0.12);
      hearing = mix(hearing, hearingTarget, 0.12);
      rot += dt * now.spin * (reduced ? 0.2 : 1);

      // Speech has no audio feed, so its pulse is synthesised to look like one.
      const voice = phase === "speaking"
        ? 0.3 + 0.7 * Math.abs(Math.sin(t * 6.1) * Math.sin(t * 2.3 + 1) * Math.cos(t * 9.7))
        : 0;
      const live = phase === "muted" ? 0 : Math.max(level, voice);
      const warmth = Math.min(1, now.warmth + hearing * 0.35 + live * 0.25);
      const energy = (now.energy + live * 0.7 + hearing * 0.06) * (reduced ? 0.6 : 1);

      const S = size * dpr, c = S / 2, R = S * 0.29;
      r.clearRect(0, 0, S, S);
      g.clearRect(0, 0, S, S);

      // --- soft light behind the ring
      g.globalCompositeOperation = "lighter";
      const blobs = [[0.0, 1.0, 0.62], [2.1, 0.8, 0.5], [4.2, 0.6, 0.42]];
      for (const [offset, tone, scale] of blobs) {
        const a = rot * 1.4 + offset + Math.sin(t * 0.4 + offset) * 0.5;
        const d = R * (0.34 + 0.2 * live);
        const x = c + Math.cos(a) * d, y = c + Math.sin(a) * d;
        const rad = R * (scale + energy * 0.9);
        const grad = g.createRadialGradient(x, y, 0, x, y, rad);
        grad.addColorStop(0, ember(Math.min(1, warmth * tone + 0.05), (0.1 + warmth * 0.42 + live * 0.25) * now.dim));
        grad.addColorStop(1, "rgba(0,0,0,0)");
        g.fillStyle = grad;
        g.beginPath(); g.arc(x, y, rad, 0, Math.PI * 2); g.fill();
      }

      // --- the lens
      const lens = r.createRadialGradient(c - R * 0.3, c - R * 0.36, R * 0.05, c, c, R);
      lens.addColorStop(0, `rgba(255,255,255,${0.085 * now.dim})`);
      lens.addColorStop(0.55, "rgba(255,255,255,0.016)");
      lens.addColorStop(1, "rgba(255,255,255,0.03)");
      r.fillStyle = "#0a0a0c";
      r.beginPath(); r.arc(c, c, R * 0.93, 0, Math.PI * 2); r.fill();
      r.fillStyle = lens; r.fill();
      r.strokeStyle = `rgba(255,255,255,${0.1 * now.dim})`; r.lineWidth = dpr; r.stroke();

      // --- the pupil: grows with the voice it hears or speaks
      const pr = R * (0.1 + 0.34 * Math.min(1, energy * 1.25));
      const pupil = r.createRadialGradient(c, c, 0, c, c, pr * 2.4);
      pupil.addColorStop(0, ember(warmth, (0.5 + warmth * 0.5) * now.dim));
      pupil.addColorStop(0.32, ember(warmth, 0.36 * now.dim * (0.35 + warmth)));
      pupil.addColorStop(1, "rgba(0,0,0,0)");
      r.globalCompositeOperation = "lighter";
      r.fillStyle = pupil;
      r.beginPath(); r.arc(c, c, pr * 2.4, 0, Math.PI * 2); r.fill();
      r.fillStyle = ember(warmth * 0.6, (0.75 + 0.25 * warmth) * now.dim);
      r.beginPath(); r.arc(c, c, Math.max(dpr * 1.6, pr * 0.2), 0, Math.PI * 2); r.fill();

      // --- the dial of ticks
      r.lineCap = "round";
      const inner = R * 1.04, maxLen = R * 0.5, comet = (t * 1.5) % (Math.PI * 2);
      for (let i = 0; i < TICKS; i++) {
        const a = (i / TICKS) * Math.PI * 2;
        const n = ringNoise(a + rot, t * (0.35 + live * 2.2), 2.2);
        const fine = ringNoise(a * 3 - rot, t * 1.7, 5);
        let len = 0.035 + energy * (0.16 + 0.84 * n) * (0.55 + 0.45 * fine);
        let lit = warmth * (0.35 + 0.65 * n);
        if (now.comet > 0.02) {
          let d = (a - comet) % (Math.PI * 2); if (d < 0) d += Math.PI * 2;
          const tail = Math.pow(Math.max(0, 1 - d / 2.6), 2.4) * now.comet;
          len += tail * 0.26; lit = Math.min(1, lit + tail * 0.8);
        }
        len = Math.min(1, len);
        const x0 = c + Math.cos(a - Math.PI / 2) * inner, y0 = c + Math.sin(a - Math.PI / 2) * inner;
        const x1 = c + Math.cos(a - Math.PI / 2) * (inner + len * maxLen), y1 = c + Math.sin(a - Math.PI / 2) * (inner + len * maxLen);
        r.strokeStyle = ember(lit, (0.2 + 0.8 * Math.min(1, len * 2.4 + lit * 0.4)) * now.dim);
        r.lineWidth = dpr * (1.15 + len * 1.5);
        r.beginPath(); r.moveTo(x0, y0); r.lineTo(x1, y1); r.stroke();
      }
      r.globalCompositeOperation = "source-over";
    }

    document.addEventListener("visibilitychange", () => {
      cancelAnimationFrame(frame);
      if (!document.hidden) { last = performance.now(); frame = requestAnimationFrame(draw); }
    });
    resize();
    frame = requestAnimationFrame(draw);

    return {
      setPhase(p) { phase = p; },
      setLevel(v) { levelTarget = v; },
      setHearing(on) { hearingTarget = on ? 1 : 0; },
    };
  })();

  // ---------------------------------------------------------------- state
  let status = null;
  let phase = "starting";
  let busy = false;
  const nodes = new Map(); // entry id → element

  const SUGGESTIONS = [
    ["pdf", "open my most recent PDF"],
    ["search", "find the file called resume"],
    ["folder", "what's on my Desktop?"],
    ["app", "open Safari"],
    ["volume", "turn the volume down"],
    ["globe", "search the web for today's headlines"],
  ];

  // ---------------------------------------------------------------- phase / stage
  function engineName() {
    if (!status) return "";
    return status.settings.engine === "claude" ? "Claude" : "LM Studio";
  }

  function renderPhase(detail) {
    document.body.dataset.phase = phase;
    orb.setPhase(phase);
    busy = phase === "thinking" || phase === "speaking";
    const wake = status ? status.wake_phrase : "Hey Cognix";
    const head = $("headline"), sub = $("subline");
    head.textContent = "";
    const copy = {
      starting: ["Waking up…", detail || "Loading the speech model."],
      idle: [null, "Always listening, privately, on this Mac."],
      listening: ["I’m listening…", "Go ahead. Press Esc to cancel."],
      thinking: [detail === "Transcribing" ? "Got it…" : "Thinking…", `Working with ${engineName()}.`],
      speaking: [status && status.settings.speak ? "Speaking" : "Answering", "Press Esc to stop."],
      muted: ["Microphone off", detail || "Typing still works. Turn the mic back on from the top bar."],
    }[phase] || ["", ""];
    if (copy[0] === null) {
      head.append("Say ", el("em", null, `“${wake}”`));
    } else {
      head.textContent = copy[0];
    }
    sub.textContent = copy[1];
    $("orb").setAttribute("aria-label", busy ? "Stop" : phase === "listening" ? "Cancel listening" : "Wake Cognix");
    updateSend();
  }

  function setChip(id, value, state) {
    const chip = $(id);
    chip.querySelector(".v").textContent = value;
    chip.dataset.state = state || "";
  }

  function renderStatus() {
    if (!status) return;
    const s = status.settings;

    // top bar
    for (const btn of document.querySelectorAll(".engine button")) {
      btn.setAttribute("aria-checked", String(btn.dataset.engine === s.engine));
    }
    document.querySelector('[data-dot="local"]').dataset.state = status.local.ok && status.local.model ? "ok" : "warn";
    document.querySelector('[data-dot="claude"]').dataset.state = status.claude.ready ? "ok" : "warn";
    const micBtn = $("mic-toggle");
    micBtn.replaceChildren(icon(s.mic_enabled ? "mic" : "micOff"));
    micBtn.setAttribute("aria-pressed", String(s.mic_enabled));
    micBtn.title = s.mic_enabled ? "Turn the microphone off" : "Turn the microphone on";

    // telemetry chips
    const mic = status.mic.state;
    if (!s.mic_enabled) setChip("chip-mic", "off", "bad");
    else if (mic === "listening" && status.mic_active) setChip("chip-mic", status.mic_active.replace(/ ?\(.*\)/, ""), "ok");
    else if (mic === "error") setChip("chip-mic", "unavailable", "bad");
    else if (mic === "silent") setChip("chip-mic", "no access", "bad");
    else setChip("chip-mic", "live", "ok");
    if (status.stt.state === "ready") setChip("chip-stt", `${s.stt_model} · on-device`, "ok");
    else if (status.stt.state === "error") setChip("chip-stt", "failed", "bad");
    else setChip("chip-stt", "loading…", "warn");
    if (s.engine === "claude") {
      const label = (status.claude.models.find((m) => m.id === s.claude_model) || {}).label || s.claude_model;
      setChip("chip-engine", status.claude.ready ? label : "Claude · add API key", status.claude.ready ? "ok" : "warn");
    } else if (!status.local.ok) {
      setChip("chip-engine", "LM Studio · not running", "warn");
    } else if (!status.local.model) {
      setChip("chip-engine", "LM Studio · no model loaded", "warn");
    } else {
      setChip("chip-engine", status.local.model, "ok");
    }

    renderSettings();
    renderPhase(status.detail);
  }

  // ---------------------------------------------------------------- conversation
  const thread = $("thread"), entriesEl = $("entries");

  function nearBottom() {
    return thread.scrollHeight - thread.scrollTop - thread.clientHeight < 120;
  }
  function scrollDown(force) {
    if (force || nearBottom()) thread.scrollTop = thread.scrollHeight;
  }

  // Minimal, safe markdown: paragraphs, lists, **bold**, `code`, fenced code. Built as DOM nodes.
  function inline(parent, text) {
    const re = /(\*\*[^*]+\*\*|`[^`]+`|\[[^\]]+\]\([^)]+\))/g;
    let lastIndex = 0, m;
    while ((m = re.exec(text))) {
      if (m.index > lastIndex) parent.append(text.slice(lastIndex, m.index));
      const tok = m[0];
      if (tok.startsWith("**")) parent.append(el("strong", null, tok.slice(2, -2)));
      else if (tok.startsWith("`")) parent.append(el("code", null, tok.slice(1, -1)));
      else parent.append(tok.slice(1, tok.indexOf("]")));
      lastIndex = m.index + tok.length;
    }
    if (lastIndex < text.length) parent.append(text.slice(lastIndex));
  }
  function renderRich(container, text) {
    container.replaceChildren();
    const parts = text.split(/```/);
    parts.forEach((part, i) => {
      if (i % 2) {
        const pre = el("pre");
        pre.append(el("code", null, part.replace(/^[a-z0-9+#-]*\n/i, "").replace(/\n$/, "")));
        container.append(pre);
        return;
      }
      for (const block of part.split(/\n{2,}/)) {
        const lines = block.split("\n").filter((l) => l.trim());
        if (!lines.length) continue;
        const bullet = /^\s*(?:[-*•]|\d+[.)])\s+/;
        if (lines.every((l) => bullet.test(l))) {
          const list = el(/^\s*\d/.test(lines[0]) ? "ol" : "ul");
          for (const l of lines) { const li = el("li"); inline(li, l.replace(bullet, "")); list.append(li); }
          container.append(list);
        } else {
          const p = el("p");
          lines.forEach((l, n) => { if (n) p.append(el("br")); inline(p, l.replace(/^#+\s*/, "")); });
          container.append(p);
        }
      }
    });
  }

  function itemRow(item) {
    const row = el("li", "item");
    const open = el("button", "item-open");
    open.type = "button";
    open.title = item.kind === "link" ? item.path : `Open ${item.name}`;
    const kind = el("span", "item-kind");
    kind.append(icon(P[item.kind] ? item.kind : "file"));
    const text = el("span", "item-text");
    text.append(el("span", "item-name", item.name), el("span", "item-detail", item.detail || ""));
    open.append(kind, text);
    open.addEventListener("click", async () => {
      const res = await api("open", { path: item.path });
      if (!res || !res.ok) toast("That item can’t be opened any more.");
    });
    row.append(open);
    if (item.kind !== "link" && item.kind !== "app") {
      const reveal = el("button", "item-reveal", "Reveal");
      reveal.type = "button";
      reveal.title = "Show in Finder";
      reveal.addEventListener("click", () => api("open", { path: item.path, reveal: true }));
      row.append(reveal);
    }
    return row;
  }

  function renderTool(node, entry) {
    node.dataset.status = entry.status;
    const head = el("div", "tool-head");
    const ic = el("span", "tool-icon");
    ic.append(icon(entry.icon));
    head.append(ic, el("span", "tool-title", entry.title + (entry.status === "running" ? "…" : "")));
    if (entry.detail) head.append(el("span", "tool-detail", entry.detail));
    node.replaceChildren(head);
    const items = entry.items || [];
    if (items.length) {
      const list = el("ul", "items");
      const LIMIT = 5, expanded = node.dataset.expanded === "1";
      (expanded ? items : items.slice(0, LIMIT)).forEach((it) => list.append(itemRow(it)));
      if (!expanded && items.length > LIMIT) {
        const li = el("li");
        const more = el("button", "items-more", `Show ${items.length - LIMIT} more`);
        more.type = "button";
        more.addEventListener("click", () => { node.dataset.expanded = "1"; renderTool(node, entry); });
        li.append(more);
        list.append(li);
      }
      node.append(list);
    }
  }

  function upsertEntry(entry) {
    let node = nodes.get(entry.id);
    const fresh = !node;
    const stick = nearBottom();
    if (fresh) {
      node = el("li", `entry ${entry.kind}`);
      nodes.set(entry.id, node);
      entriesEl.append(node);
      $("empty").hidden = true;
    }
    if (entry.kind === "user") {
      const glyph = icon(entry.source === "voice" ? "mic" : "keyboard");
      glyph.classList.add("glyph");
      const time = el("time", null, entry.time || "");
      node.replaceChildren(glyph, el("span", "text", entry.text), time);
    } else if (entry.kind === "assistant") {
      node.classList.toggle("streaming", !!entry.streaming);
      let body = node.querySelector(".body");
      if (!body) { body = el("div", "body"); node.append(body); }
      node._text = entry.text || "";
      if (entry.streaming) body.textContent = node._text; else renderRich(body, node._text);
      if (!entry.streaming && !node._text) { node.remove(); nodes.delete(entry.id); }
    } else if (entry.kind === "tool") {
      renderTool(node, entry);
      if (entry.status === "running" && phase === "thinking") $("subline").textContent = `${entry.title}…`;
    } else if (entry.kind === "notice") {
      node.dataset.level = entry.level || "error";
      node.textContent = entry.text;
    }
    if (stick || fresh) scrollDown(true);
  }

  function appendDelta(id, text) {
    const node = nodes.get(id);
    if (!node) return;
    const stick = nearBottom();
    node._text = (node._text || "") + text;
    const body = node.querySelector(".body");
    if (body) body.textContent = node._text;
    if (stick) scrollDown(true);
  }

  function clearThread() {
    nodes.clear();
    entriesEl.replaceChildren();
    $("empty").hidden = false;
  }

  // ---------------------------------------------------------------- composer
  const input = $("input"), sendBtn = $("send");

  function updateSend() {
    const mode = busy ? "stop" : input.value.trim() ? "send" : "idle";
    if (sendBtn.dataset.mode === mode) return;
    sendBtn.dataset.mode = mode;
    sendBtn.replaceChildren(icon(mode === "stop" ? "stop" : "up"));
    sendBtn.setAttribute("aria-label", mode === "stop" ? "Stop" : "Send");
  }
  function autosize() {
    input.style.height = "auto";
    input.style.height = Math.min(132, input.scrollHeight) + "px";
  }
  function send(text) {
    const value = (text ?? input.value).trim();
    if (!value) return;
    if (text == null) { input.value = ""; autosize(); }
    api("send", { text: value });
    scrollDown(true);
    updateSend();
  }

  $("composer").addEventListener("submit", (e) => {
    e.preventDefault();
    if (busy && !input.value.trim()) api("stop"); else send();
  });
  input.addEventListener("input", () => { autosize(); updateSend(); });
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); send(); }
  });

  for (const [ic, text] of SUGGESTIONS) {
    const li = el("li"), btn = el("button");
    btn.type = "button";
    const go = icon("arrow"); go.classList.add("go");
    btn.append(icon(ic), el("span", null, `…${text}`), go);
    btn.addEventListener("click", () => send(text));
    li.append(btn);
    $("suggestions").append(li);
  }

  // ---------------------------------------------------------------- settings sheet
  const sheet = $("settings"), scrim = $("scrim");
  let typingUrl = false;

  function openSettings(focusKey) {
    sheet.classList.add("open");
    sheet.removeAttribute("inert");
    sheet.setAttribute("aria-hidden", "false");
    scrim.hidden = false;
    (focusKey ? $("api-key") : $("close-settings")).focus();
  }
  function closeSettings() {
    sheet.classList.remove("open");
    sheet.setAttribute("inert", "");
    sheet.setAttribute("aria-hidden", "true");
    scrim.hidden = true;
  }
  const change = (changes) => api("settings", { changes });

  function fillSelect(select, options, value) {
    const sig = JSON.stringify(options);
    if (select.dataset.sig !== sig) {
      select.dataset.sig = sig;
      select.replaceChildren(...options.map(([v, label]) => {
        const o = el("option", null, label); o.value = v; return o;
      }));
    }
    select.value = value;
  }

  function renderSettings() {
    const s = status.settings;
    for (const radio of document.querySelectorAll('input[name="engine"]')) {
      radio.checked = radio.value === s.engine;
      radio.closest(".card").classList.toggle("selected", radio.checked);
    }
    for (const box of document.querySelectorAll("[data-setting]")) box.checked = !!s[box.dataset.setting];

    // Local
    const lb = $("local-badge");
    if (!status.local.ok) { lb.textContent = "Not running"; lb.dataset.state = "warn"; }
    else if (!status.local.models.length) { lb.textContent = "No model loaded"; lb.dataset.state = "warn"; }
    else { lb.textContent = "Connected"; lb.dataset.state = "ok"; }
    const models = status.local.models.map((m) => [m, m]);
    fillSelect($("local-model"), [["", models.length ? "Automatic (first loaded model)" : "No models found"], ...models], s.local_model);
    if (!typingUrl) $("local-url").value = s.local_url;
    $("local-help").textContent = status.local.ok ? "" :
      "Open LM Studio, load a model, then start the server from the Developer tab. Cognix reconnects on its own.";

    // Claude
    const cb = $("claude-badge");
    cb.textContent = status.claude.ready ? "Ready" : "Needs a key";
    cb.dataset.state = status.claude.ready ? "ok" : "warn";
    $("save-key").textContent = status.claude.has_saved_key && !$("api-key").value ? "Remove" : "Save";
    $("api-key").placeholder = status.claude.has_saved_key ? "Saved in your Mac’s Keychain" : "sk-ant-…";
    $("claude-help").textContent = status.claude.has_saved_key
      ? "" : status.claude.ready
        ? "Using credentials from your environment."
        : "Create a key at console.anthropic.com. It is stored in your Mac’s Keychain, never in a file.";
    fillSelect($("claude-model"), status.claude.models.map((m) => [m.id, m.label]), s.claude_model);
    $("claude-model-hint").textContent = (status.claude.models.find((m) => m.id === s.claude_model) || {}).hint || "";

    // Microphone
    fillSelect($("mic-device"), [["", "Automatic (skips silent microphones)"], ...status.mic_devices.map((n) => [n, n])], s.mic_device);
    $("mic-help").textContent = status.mic_active ? `Listening with: ${status.mic_active}` : "";

    // Listening / voice
    fillSelect($("stt-model"), status.stt_models.map((m) => [m, m.endsWith(".en") ? `${m} (English)` : `${m} (multilingual)`]), s.stt_model);
    const voices = [...status.voices].sort((a, b) =>
      (b.lang.startsWith("en") - a.lang.startsWith("en")) || a.name.localeCompare(b.name));
    fillSelect($("voice"), [["", "System default"], ...voices.map((v) => [v.name, `${v.name} · ${v.lang.replace("_", "-")}`])], s.voice);
    if (document.activeElement !== $("rate")) $("rate").value = s.rate;
    $("rate-out").textContent = `${s.rate} wpm`;
    $("about").textContent = `Cognix ${status.version} · open source`;
  }

  $("open-settings").addEventListener("click", () => openSettings());
  $("close-settings").addEventListener("click", closeSettings);
  $("chip-engine").addEventListener("click", () => openSettings(status && status.settings.engine === "claude" && !status.claude.ready));
  scrim.addEventListener("click", closeSettings);

  function pickEngine(engine) {
    change({ engine });
    if (engine === "claude" && status && !status.claude.ready) openSettings(true);
  }
  for (const btn of document.querySelectorAll(".engine button")) btn.addEventListener("click", () => pickEngine(btn.dataset.engine));
  for (const radio of document.querySelectorAll('input[name="engine"]')) radio.addEventListener("change", () => change({ engine: radio.value }));
  for (const box of document.querySelectorAll("[data-setting]")) box.addEventListener("change", () => change({ [box.dataset.setting]: box.checked }));

  $("local-model").addEventListener("change", (e) => change({ local_model: e.target.value }));
  $("claude-model").addEventListener("change", (e) => change({ claude_model: e.target.value }));
  $("mic-device").addEventListener("change", (e) => change({ mic_device: e.target.value }));
  $("stt-model").addEventListener("change", (e) => change({ stt_model: e.target.value }));
  $("voice").addEventListener("change", (e) => change({ voice: e.target.value }));
  $("rate").addEventListener("input", (e) => { $("rate-out").textContent = `${e.target.value} wpm`; });
  $("rate").addEventListener("change", (e) => change({ rate: Number(e.target.value) }));
  $("preview-voice").addEventListener("click", () => api("voice-preview"));
  $("local-url").addEventListener("focus", () => { typingUrl = true; });
  $("local-url").addEventListener("blur", (e) => {
    typingUrl = false;
    const url = e.target.value.trim().replace(/\/+$/, "");
    if (url && status && url !== status.settings.local_url) change({ local_url: url });
  });
  $("local-url").addEventListener("keydown", (e) => { if (e.key === "Enter") e.target.blur(); });

  async function saveKey() {
    const field = $("api-key");
    const key = field.value.trim();
    if (!key && !(status && status.claude.has_saved_key)) return field.focus();
    await api("key", { key });
    field.value = "";
    toast(key ? "API key saved to your Keychain." : "API key removed.");
  }
  $("save-key").addEventListener("click", saveKey);
  $("api-key").addEventListener("input", () => status && renderSettings());
  $("api-key").addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); saveKey(); } });

  // ---------------------------------------------------------------- top bar + keys
  $("new-chat").append(icon("plus"));
  $("open-settings").append(icon("sliders"));
  $("close-settings").append(icon("close"));
  $("mic-toggle").addEventListener("click", () => status && change({ mic_enabled: !status.settings.mic_enabled }));
  $("new-chat").addEventListener("click", () => api("new"));
  $("orb").addEventListener("click", () => api("wake"));

  document.addEventListener("keydown", (e) => {
    const mod = e.metaKey || e.ctrlKey;
    if (e.key === "Escape") {
      if (sheet.classList.contains("open")) closeSettings();
      else api("stop");
    } else if (mod && e.key.toLowerCase() === "k") {
      e.preventDefault(); input.focus();
    } else if (mod && e.key === ",") {
      e.preventDefault(); sheet.classList.contains("open") ? closeSettings() : openSettings();
    } else if (mod && e.key.toLowerCase() === "n") {
      e.preventDefault(); api("new");
    }
  });

  let toastTimer = 0;
  function toast(text) {
    const node = $("toast");
    node.textContent = text;
    node.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { node.hidden = true; }, 2600);
  }

  // ---------------------------------------------------------------- live connection
  async function loadState() {
    const res = await fetch("/api/state", { headers: { "X-Cognix-Token": TOKEN } });
    if (!res.ok) throw new Error("state");
    status = await res.json();
    phase = status.phase;
    clearThread();
    for (const entry of status.entries || []) upsertEntry(entry);
    renderStatus();
    scrollDown(true);
  }

  function connect() {
    const source = new EventSource("/events?t=" + encodeURIComponent(TOKEN));
    let lost = false;
    source.onopen = () => {
      if (lost) { lost = false; loadState().catch(() => {}); }
    };
    source.onerror = () => {
      if (lost) return;
      lost = true;
      phase = "muted";
      renderPhase("Lost the connection to Cognix. Reconnecting…");
    };
    source.onmessage = (msg) => {
      const ev = JSON.parse(msg.data);
      switch (ev.type) {
        case "level": orb.setLevel(ev.v); break;
        case "hearing": orb.setHearing(ev.active); break;
        case "phase": phase = ev.phase; if (status) status.detail = ev.detail; renderPhase(ev.detail); break;
        case "entry": upsertEntry(ev.entry); break;
        case "delta": appendDelta(ev.id, ev.text); break;
        case "status": status = { ...ev.status, entries: undefined }; renderStatus(); break;
        case "cleared": clearThread(); break;
      }
    };
  }

  updateSend();
  loadState().then(connect).catch(() => {
    $("headline").textContent = "Can’t reach Cognix";
    $("subline").textContent = "The app isn’t running. Start it again and this window will reconnect.";
    setTimeout(() => location.reload(), 3000);
  });
})();
