const FLOW_VEO_API = "http://127.0.0.1:8765";
const FLOW_VEO_UNUSUAL_PATTERNS = [
  "We noticed some unusual activity",
  "Please visit the Help Center",
  "unusual activity",
  "подозрительная активность",
  "необычная активность",
  "Flow is not available in your country",
  "not available in your country",
  "reCAPTCHA",
];

const ROUND_BATCH = 25;
const SUBMIT_DELAY_MIN_MS = 1000;
const SUBMIT_DELAY_MAX_MS = 2000;
const BATCH_WAIT_MIN_MS = 20000;
const BATCH_WAIT_MAX_MS = 30000;
const MAX_DOWNLOAD_PASSES = 5;
const PASS_INTERVAL_MS = 20000;
const PASS_MAX_MS = 300000;
const DOWNLOAD_PARALLEL = 1;
const ROUND_DOWNLOAD_MAX_MS = 240000;
const ROUND_DOWNLOAD_MAX_SCROLL_STEPS = 80;
const LOOP_STALE_SUBMIT_MS = 30000;

let flowVeoLoopRunning = false;
let flowVeoLoopStartedAt = 0;
let flowVeoLoopLastProgressAt = 0;
let flowVeoLastFlowErrorAt = 0;
const flowVeoSessionSubmitted = new Set();

async function logServer(message) {
  try {
    await api("/api/extension/log", { message });
  } catch (err) {
    /* ignore */
  }
}
const FLOW_VEO_ERROR_RELOAD_WAIT_MS = 10000;
const FLOW_VEO_ERROR_RELOAD_KEY = "flowVeoLastErrorReloadAt";

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function jitter(minMs, maxMs) {
  return minMs + Math.floor(Math.random() * Math.max(1, maxMs - minMs));
}

async function api(path, body) {
  const response = await fetch(`${FLOW_VEO_API}${path}`, {
    method: body ? "POST" : "GET",
    headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
  return data;
}

async function playBeep(kind) {
  const patterns = {
    submit_done: { frequency: 440, duration: 200, count: 2 },
    download_done: { frequency: 660, duration: 200, count: 3 },
    all_done: { frequency: 880, duration: 800, count: 1 },
  };
  const pattern = patterns[kind];
  if (!pattern) return;

  try {
    const AudioContextCtor = window.AudioContext || window.webkitAudioContext;
    if (!AudioContextCtor) throw new Error("Web Audio is not available");
    const context = new AudioContextCtor();
    if (context.state === "suspended") {
      await context.resume();
    }
    for (let i = 0; i < pattern.count; i += 1) {
      const oscillator = context.createOscillator();
      const gain = context.createGain();
      oscillator.frequency.value = pattern.frequency;
      oscillator.type = "sine";
      oscillator.connect(gain);
      gain.connect(context.destination);
      const startAt = context.currentTime + i * 0.32;
      gain.gain.setValueAtTime(0.0001, startAt);
      gain.gain.exponentialRampToValueAtTime(0.18, startAt + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.0001, startAt + pattern.duration / 1000);
      oscillator.start(startAt);
      oscillator.stop(startAt + pattern.duration / 1000 + 0.03);
    }
    await sleep(pattern.count * 330 + pattern.duration);
    await context.close();
  } catch (err) {
    console.log(`Flow Veo audio cue: ${kind}`, err);
    document.title = `🔔 Flow Veo: ${kind}`;
  }
}

async function handleAudioCue(status) {
  const cue = status && status.audio_cue;
  if (!cue) return;
  await playBeep(cue);
  await api("/api/extension/audio-cue/ack", {}).catch(() => {});
}

function clean(value) {
  return (value || "").replace(/\s+/g, " ").trim();
}

async function waitAfterFlowErrorReload() {
  const lastReloadAt = Number(sessionStorage.getItem(FLOW_VEO_ERROR_RELOAD_KEY) || 0);
  const remaining = FLOW_VEO_ERROR_RELOAD_WAIT_MS - (Date.now() - lastReloadAt);
  if (remaining > 0) {
    await sleep(remaining);
  }
}

async function handleVisibleFlowWarning(tag = "flow") {
  await waitAfterFlowErrorReload();
  const errors = visibleFlowErrors();
  if (!errors.length) return false;
  if (Date.now() - flowVeoLastFlowErrorAt > FLOW_VEO_ERROR_RELOAD_WAIT_MS) {
    flowVeoLastFlowErrorAt = Date.now();
    await api("/api/extension/flow-error", errors[0]).catch(() => {});
  }
  await logServer(`[${tag}] Flow warning detected; reloading and waiting 10 seconds.`);
  sessionStorage.setItem(FLOW_VEO_ERROR_RELOAD_KEY, String(Date.now()));
  location.reload();
  await sleep(FLOW_VEO_ERROR_RELOAD_WAIT_MS);
  return true;
}

function isVisible(el) {
  if (!el) return false;
  const style = window.getComputedStyle(el);
  const rect = el.getBoundingClientRect();
  return style.visibility !== "hidden" && style.display !== "none" && rect.width > 0 && rect.height > 0;
}

function elementText(el) {
  if (!el) return "";
  if ("value" in el) return el.value || "";
  return el.innerText || el.textContent || "";
}

function dispatchHumanClickAt(x, y) {
  const target = document.elementFromPoint(x, y) || document.body || document.documentElement;
  const opts = { bubbles: true, cancelable: true, clientX: x, clientY: y, button: 0, view: window };
  target.dispatchEvent(new PointerEvent("pointerdown", { ...opts, pointerType: "mouse" }));
  target.dispatchEvent(new MouseEvent("mousedown", opts));
  target.dispatchEvent(new PointerEvent("pointerup", { ...opts, pointerType: "mouse" }));
  target.dispatchEvent(new MouseEvent("mouseup", opts));
  target.dispatchEvent(new MouseEvent("click", opts));
}

async function maybeHumanMissClick() {
  if (Math.random() > 0.18) return;
  for (let attempt = 0; attempt < 5; attempt += 1) {
    const x = jitter(Math.floor(window.innerWidth * 0.15), Math.floor(window.innerWidth * 0.85));
    const y = jitter(Math.floor(window.innerHeight * 0.12), Math.floor(window.innerHeight * 0.62));
    const el = document.elementFromPoint(x, y);
    if (!el || el.closest("button, a, input, textarea, [contenteditable='true'], [role='button'], [role='textbox']")) {
      continue;
    }
    dispatchHumanClickAt(x, y);
    await sleep(jitter(120, 300));
    return;
  }
}

function setElementText(el, text) {
  el.focus();
  if ("value" in el) {
    el.value = "";
    el.dispatchEvent(new InputEvent("input", { bubbles: true, inputType: "deleteContentBackward" }));
    el.value = text;
    el.dispatchEvent(new InputEvent("input", { bubbles: true, inputType: "insertText", data: text }));
    return;
  }

  const selection = window.getSelection();
  const range = document.createRange();
  range.selectNodeContents(el);
  selection.removeAllRanges();
  selection.addRange(range);
  document.execCommand("insertText", false, text);
  el.dispatchEvent(new InputEvent("input", { bubbles: true, inputType: "insertText", data: text }));

  if (clean(elementText(el)) !== clean(text)) {
    el.textContent = text;
    el.dispatchEvent(new InputEvent("input", { bubbles: true, inputType: "insertText", data: text }));
  }
}

function findPromptInput() {
  const candidates = [...document.querySelectorAll("textarea, input, [contenteditable='true'], [role='textbox']")]
    .filter(isVisible)
    .map((el) => {
      const rect = el.getBoundingClientRect();
      const label = clean([
        el.getAttribute("placeholder"),
        el.getAttribute("aria-label"),
        el.getAttribute("title"),
        elementText(el),
      ].join(" "));
      return { el, rect, label };
    })
    .filter((item) => item.rect.width > 180 && item.rect.height > 16);

  const preferred = candidates
    .filter((item) => /что вы хотите создать|what do you want to create|prompt|запрос/i.test(item.label))
    .sort((a, b) => b.rect.top - a.rect.top)[0];
  if (preferred) return preferred.el;

  return candidates.sort((a, b) => b.rect.top - a.rect.top)[0]?.el || null;
}

async function submitPromptText(prompt) {
  const input = findPromptInput();
  if (!input) throw new Error("Flow prompt input was not found in this tab.");

  input.scrollIntoView({ block: "center", inline: "nearest" });
  await sleep(jitter(150, 420));
  input.focus();
  await insertPromptAndPressEnter(input, prompt);
  await sleep(jitter(1200, 1800));

  if (clean(elementText(input)) === clean(prompt)) {
    throw new Error("Flow did not submit the prompt; the text stayed in the composer.");
  }
}

async function insertPromptAndPressEnter(input, prompt) {
  const rect = input.getBoundingClientRect();
  const message = {
    type: "flowVeoInsertPromptAndEnter",
    prompt,
    rect: {
      x: Math.max(1, Math.min(window.innerWidth - 1, rect.left + Math.min(rect.width / 2, 280))),
      y: Math.max(1, Math.min(window.innerHeight - 1, rect.top + Math.min(rect.height / 2, 80))),
    },
  };

  try {
    const response = await chrome.runtime.sendMessage(message);
    if (!response || !response.ok) {
      throw new Error((response && response.error) || "debugger insert failed");
    }
  } catch (err) {
    setElementText(input, prompt);
    await sleep(jitter(180, 520));
    await pressEnterFromFocusedInput(input);
  }
}

async function pressEnterFromFocusedInput(input) {
  input.focus();
  try {
    const response = await chrome.runtime.sendMessage({ type: "flowVeoPressEnter" });
    if (!response || !response.ok) {
      throw new Error((response && response.error) || "debugger Enter failed");
    }
    return;
  } catch (err) {
    input.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", code: "Enter", bubbles: true }));
    input.dispatchEvent(new KeyboardEvent("keypress", { key: "Enter", code: "Enter", bubbles: true }));
    input.dispatchEvent(new KeyboardEvent("keyup", { key: "Enter", code: "Enter", bubbles: true }));
  }
}

function visibleFlowErrors() {
  const bodyText = clean(document.body ? document.body.innerText : "");
  const matched = FLOW_VEO_UNUSUAL_PATTERNS.find((pattern) => bodyText.toLowerCase().includes(pattern.toLowerCase()));
  if (!matched) return [];
  return [{ index: null, message: matched, card_text: bodyText.slice(0, 1000) }];
}

function normalizeMediaUrl(value) {
  if (!value || !/media\.getMediaUrlRedirect/.test(value)) return "";
  const url = new URL(value, location.href);
  url.searchParams.delete("mediaUrlType");
  return url.href;
}

function mediaUrlFromElement(el) {
  return normalizeMediaUrl(el.currentSrc || el.src || el.getAttribute("src") || "");
}

function flowScrollTarget() {
  const scrollables = [...document.querySelectorAll("*")]
    .filter((el) => {
      const style = window.getComputedStyle(el);
      return /(auto|scroll)/.test(style.overflowY) && el.scrollHeight > el.clientHeight + 50;
    })
    .sort((a, b) => (b.scrollHeight - b.clientHeight) - (a.scrollHeight - a.clientHeight));
  return scrollables[0] || document.scrollingElement || document.documentElement;
}

// ─── Card detection ───────────────────────────────────────────────────────────

function nearestCardCandidate(downloadEl) {
  let node = downloadEl;
  let best = null;
  for (let depth = 0; node && depth < 18; depth += 1) {
    const text = clean(node.innerText || node.textContent || "");
    const rect = node.getBoundingClientRect();
    const indexTokens = text.match(/#\d{3}/g) || [];
    const indexMatch = indexTokens.length === 1 ? indexTokens[0].match(/#(\d{3})/) : null;
    const media = [...node.querySelectorAll("video, source, img")]
      .map((el) => ({ el, url: mediaUrlFromElement(el), rect: el.getBoundingClientRect() }))
      .filter((item) => item.url && item.rect.width > 20 && item.rect.height > 20);

    if (indexMatch && media.length) {
      best = { root: node, index: Number(indexMatch[1]), media, rect, depth };
      if (rect.width < window.innerWidth * 0.95 && rect.height < window.innerHeight * 0.85) break;
    }
    node = node.parentElement;
  }
  return best;
}

function nearestIndexedCardCandidate(startEl) {
  let node = startEl;
  for (let depth = 0; node && depth < 18; depth += 1) {
    const text = clean(node.innerText || node.textContent || "");
    const rect = node.getBoundingClientRect();
    const indexTokens = text.match(/#\d{3}/g) || [];
    const indexMatch = indexTokens.length === 1 ? indexTokens[0].match(/#(\d{3})/) : null;
    if (
      indexMatch &&
      rect.width > 180 &&
      rect.height > 80 &&
      rect.width < window.innerWidth * 0.98 &&
      rect.height < window.innerHeight * 0.9
    ) {
      const media = [...node.querySelectorAll("video, source, img")]
        .map((el) => ({ el, url: mediaUrlFromElement(el), rect: el.getBoundingClientRect() }))
        .filter((item) => item.url && item.rect.width > 20 && item.rect.height > 20);
      return { root: node, index: Number(indexMatch[1]), media, rect, depth };
    }
    node = node.parentElement;
  }
  return null;
}

function chooseCardMedia(card, downloadEl) {
  const buttonRect = downloadEl.getBoundingClientRect();
  const rootRect = card.rect;
  const rootCenterY = rootRect.top + rootRect.height / 2;
  const scored = card.media.map((item) => {
    const rect = item.rect;
    const centerY = rect.top + rect.height / 2;
    const centerX = rect.left + rect.width / 2;
    const outsidePenalty = (
      centerY < rootRect.top - 20 ||
      centerY > rootRect.bottom + 20 ||
      centerX < rootRect.left - 20 ||
      centerX > rootRect.right + 20
    ) ? 100000 : 0;
    const yDistance = Math.min(Math.abs(centerY - rootCenterY), Math.abs(centerY - buttonRect.top));
    const areaBonus = Math.min(rect.width * rect.height / 1000, 5000);
    return { ...item, score: outsidePenalty + yDistance - areaBonus };
  }).sort((a, b) => a.score - b.score);
  return scored[0] || null;
}

function isDownloadControl(el) {
  return /download|save|export|скач|загруз/i.test([
    el.innerText,
    el.textContent,
    el.getAttribute("aria-label"),
    el.getAttribute("title"),
    el.getAttribute("href"),
  ].join(" "));
}

// Detect if a card is in an unrecoverable error state (no media URL available).
function cardIsErrorState(cardRoot) {
  const text = clean(cardRoot.innerText || cardRoot.textContent || "");
  // Error indicators: explicit error text, or generation stuck at low % for too long.
  const hasErrorText = /ошибк|error|failed|не удал|unavailable/i.test(text);
  // No media found anywhere inside the card.
  const hasMedia = [...cardRoot.querySelectorAll("video, source, img")]
    .some((el) => !!mediaUrlFromElement(el));
  return hasErrorText && !hasMedia;
}

// ─── Media fetch ──────────────────────────────────────────────────────────────

function arrayBufferToBase64(buffer) {
  const bytes = new Uint8Array(buffer);
  const chunkSize = 0x8000;
  let binary = "";
  for (let i = 0; i < bytes.length; i += chunkSize) {
    binary += String.fromCharCode.apply(null, bytes.subarray(i, i + chunkSize));
  }
  return btoa(binary);
}

async function fetchMediaThroughExtension(mediaUrl) {
  const response = await chrome.runtime.sendMessage({
    type: "flowVeoFetchMedia",
    media_url: mediaUrl,
  });
  if (!response || !response.ok) {
    throw new Error((response && response.error) || "Extension media fetch failed");
  }
  return response.data_base64;
}

// ─── Submit all prompt_ready items in human-like batches ─────────────────────

async function submitPhase() {
  flowVeoLoopLastProgressAt = Date.now();
  let totalSubmitted = 0;
  let batchNumber = 1;

  while (true) {
    const status = await api("/api/extension/status");
    if (status.status !== "running") return { stop: true, submitted: totalSubmitted };
    if (status.phase !== "submitting") return { stop: false, submitted: totalSubmitted };
    if ((status.counts?.prompt_ready || 0) <= 0) break;

    let submittedInBatch = 0;
    await logServer(`[submit] batch ${batchNumber}: up to ${ROUND_BATCH} prompts.`);

    for (let i = 0; i < ROUND_BATCH; i += 1) {
      if (await handleVisibleFlowWarning("submit")) {
        return { stop: false, submitted: totalSubmitted, reloaded: true };
      }

      const next = await api("/api/extension/next-prompt", {});
      if (next.stop_requested || next.status === "stopped") {
        return { stop: true, submitted: totalSubmitted };
      }
      if (!next.prompt) {
        if (next.reason === "wait_phase") return { stop: false, submitted: totalSubmitted };
        break;
      }

      try {
        await maybeHumanMissClick();
        await submitPromptText(next.prompt.veo_prompt);
        await api("/api/extension/mark-submitted", { index: next.prompt.index });
        flowVeoSessionSubmitted.add(Number(next.prompt.index));
        flowVeoLoopLastProgressAt = Date.now();
        submittedInBatch += 1;
        totalSubmitted += 1;
      } catch (err) {
        if (await handleVisibleFlowWarning("submit-error")) {
          return { stop: false, submitted: totalSubmitted, reloaded: true };
        }
        await api("/api/extension/flow-error", { message: err.message || String(err) }).catch(() => {});
        await sleep(FLOW_VEO_ERROR_RELOAD_WAIT_MS);
        break;
      }

      await sleep(jitter(SUBMIT_DELAY_MIN_MS, SUBMIT_DELAY_MAX_MS));
    }

    if (submittedInBatch <= 0) break;
    await logServer(`[submit] submitted ${submittedInBatch} prompts; waiting before next batch.`);
    await sleep(jitter(BATCH_WAIT_MIN_MS, BATCH_WAIT_MAX_MS));
    batchNumber += 1;
  }

  await api("/api/extension/report-phase-done", { phase: "submit" }).catch(() => {});
  return { stop: false, submitted: totalSubmitted };
}

// ─── Download bottom-up without archiving Flow cards ─────────────────────────

function collectVisibleCards(submittedIndexes, seenIndexes) {
  const byIndex = new Map();
  const downloadButtons = [...document.querySelectorAll("button, a[href], [role='button']")]
    .filter(isVisible)
    .filter(isDownloadControl);

  for (const button of downloadButtons) {
    const card = nearestCardCandidate(button);
    if (!card) continue;
    if (!submittedIndexes.has(card.index)) continue;
    if (seenIndexes.has(card.index)) continue;
    if (byIndex.has(card.index)) continue;

    const media = cardIsErrorState(card.root) ? null : chooseCardMedia(card, button);
    byIndex.set(card.index, { index: card.index, root: card.root, media, anchorButton: button });
  }
  return [...byIndex.values()];
}

function collectVisibleErrorCards(submittedIndexes, seenIndexes) {
  const byIndex = new Map();
  const candidates = [...document.querySelectorAll("div, article, section, [role='group'], [data-testid]")]
    .filter(isVisible)
    .filter((el) => /#\d{3}/.test(el.innerText || el.textContent || ""));

  for (const el of candidates) {
    const card = nearestIndexedCardCandidate(el);
    if (!card) continue;
    if (!submittedIndexes.has(card.index)) continue;
    if (seenIndexes.has(card.index)) continue;
    if (byIndex.has(card.index)) continue;
    if (!cardIsErrorState(card.root)) continue;
    byIndex.set(card.index, { index: card.index, root: card.root, media: null, anchorButton: null });
  }
  return [...byIndex.values()];
}

async function downloadCardMedia(item) {
  if (!item.media) {
    return { item, status: "no_media" };
  }
  try {
    const dataBase64 = await fetchMediaThroughExtension(item.media.url);
    const result = await api("/api/extension/download-media", {
      index: item.index,
      media_url: item.media.url,
      data_base64: dataBase64,
    });
    const status = (result.downloaded || [])[0]?.status;
    if (status === "downloaded") {
      await logServer(`Downloaded clip #${String(item.index).padStart(3, "0")} in this pass.`);
      return { item, status: "downloaded" };
    }
    if (status === "skipped_existing") return { item, status: "skipped_existing" };
    return { item, status: status || "skip" };
  } catch (err) {
    await logServer(`Download failed for #${String(item.index).padStart(3, "0")}: ${err.message || String(err)}`);
    return { item, status: "error" };
  }
}

async function processDownloadBatch(batch) {
  return Promise.all(batch.map(downloadCardMedia));
}

async function markErrorCardsForRetry(cards, tag) {
  let marked = 0;
  for (const card of cards) {
    const result = await api("/api/extension/mark-retry-failed", {
      index: card.index,
      reason: "flow_generation_error",
    }).catch(() => null);
    if (result) {
      marked += 1;
    }
  }
  if (marked) await logServer(`[${tag}] marked ${marked} visible error cards for retry.`);
  return marked;
}

async function downloadRound(candidateIndexes, options = {}) {
  if (!candidateIndexes.size) return 0;

  const maxMs = options.maxMs ?? ROUND_DOWNLOAD_MAX_MS;
  const maxScrollSteps = options.maxScrollSteps ?? ROUND_DOWNLOAD_MAX_SCROLL_STEPS;
  const startedAt = Date.now();
  const tag = options.tag || "round";

  await logServer(`[${tag}] bottom-up download phase started: ${candidateIndexes.size} indexes to look for.`);

  const target = flowScrollTarget();
  const stepSize = Math.max(600, Math.floor(window.innerHeight * 0.8));
  const seenDownloadIndexes = new Set();
  const seenErrorIndexes = new Set();
  const downloadedThisPass = new Set();

  target.scrollTop = target.scrollHeight;
  await sleep(jitter(400, 700));

  let found = 0;
  let errorMarked = 0;
  let stuckSteps = 0;

  for (let step = 0; step < maxScrollSteps; step++) {
    if (Date.now() - startedAt > maxMs) break;
    if (await handleVisibleFlowWarning(`${tag}/download`)) break;

    const cards = collectVisibleCards(candidateIndexes, seenDownloadIndexes);
    for (const card of cards) seenDownloadIndexes.add(card.index);
    if (cards.length) {
      found += cards.length;
      await logServer(`[${tag}] processing ${cards.length} visible cards at scroll step ${step + 1}.`);
      for (let i = 0; i < cards.length; i += DOWNLOAD_PARALLEL) {
        if (Date.now() - startedAt > maxMs) {
          await logServer(`[${tag}] time limit hit at step ${step + 1}.`);
          break;
        }
        const results = await processDownloadBatch(cards.slice(i, i + DOWNLOAD_PARALLEL));
        for (const result of results) {
          if (result.status === "downloaded") downloadedThisPass.add(result.item.index);
        }
      }
      await sleep(jitter(200, 350));
    }

    const errorCards = collectVisibleErrorCards(candidateIndexes, seenErrorIndexes);
    for (const card of errorCards) seenErrorIndexes.add(card.index);
    if (errorCards.length) {
      errorMarked += await markErrorCardsForRetry(errorCards, tag);
      await sleep(jitter(200, 350));
    }

    if (seenDownloadIndexes.size >= candidateIndexes.size) break;
    if (target.scrollTop <= 0) break;

    const before = target.scrollTop;
    target.scrollBy(0, -stepSize);
    await sleep(jitter(280, 480));
    if (Math.abs(target.scrollTop - before) < 4) {
      stuckSteps += 1;
      if (stuckSteps >= 2) break;
    } else {
      stuckSteps = 0;
    }
  }

  if (!found) {
    await logServer(`[${tag}] no matching cards found in Flow.`);
  }

  await logServer(`[${tag}] phase complete: downloaded ${downloadedThisPass.size}, marked_errors ${errorMarked}.`);
  return downloadedThisPass.size;
}

async function downloadPhase() {
  flowVeoLoopLastProgressAt = Date.now();
  let previousDownloaded = -1;
  let stagnantPasses = 0;

  for (let pass = 1; pass <= MAX_DOWNLOAD_PASSES; pass += 1) {
    const status = await api("/api/extension/status");
    if (status.status !== "running" || status.phase !== "downloading") {
      return { stop: status.status !== "running" };
    }
    const candidateIndexes = unresolvedIndexesFromStatus(status);
    if (!candidateIndexes.size) break;

    await logServer(`[download] pass ${pass}/${MAX_DOWNLOAD_PASSES}: looking for ${candidateIndexes.size} unresolved prompt(s).`);
    await downloadRound(candidateIndexes, {
      tag: `download-${pass}`,
      maxMs: PASS_MAX_MS,
      maxScrollSteps: ROUND_DOWNLOAD_MAX_SCROLL_STEPS,
    });

    const after = await api("/api/extension/status");
    if (after.status !== "running") return { stop: true };
    const unresolved = unresolvedIndexesFromStatus(after);
    if (!unresolved.size) break;

    const downloadedNow = after.counts?.downloaded || 0;
    if (downloadedNow === previousDownloaded) {
      stagnantPasses += 1;
    } else {
      stagnantPasses = 0;
      flowVeoLoopLastProgressAt = Date.now();
    }
    if (stagnantPasses >= 2) {
      await logServer("[download] stopping after 2 consecutive passes without download progress.");
      break;
    }
    previousDownloaded = downloadedNow;
    if (pass < MAX_DOWNLOAD_PASSES) {
      await sleep(PASS_INTERVAL_MS);
    }
  }

  await api("/api/extension/report-phase-done", { phase: "download" }).catch(() => {});
  return { stop: false };
}

// ─── Final reporting ─────────────────────────────────────────────────────────

function unresolvedIndexesFromStatus(st) {
  return new Set([
    ...(st.submitted_indexes || []).map(Number),
    ...(st.prompt_ready_indexes || []).map(Number),
    ...(st.failed_indexes || []).map(Number),
  ]);
}

// ─── Main loop ────────────────────────────────────────────────────────────────

function sameFlowProject(currentUrl, expectedUrl) {
  if (!expectedUrl) return true;
  const normalize = (value) => String(value || "")
    .split("?")[0]
    .split("#")[0]
    .replace(/\/$/, "")
    .replace(/\/fx\/[a-z]{2}(?=\/tools)/, "/fx");
  return normalize(currentUrl).startsWith(normalize(expectedUrl));
}

async function flowVeoLoop() {
  if (flowVeoLoopRunning) return;
  flowVeoLoopRunning = true;
  flowVeoLoopStartedAt = Date.now();
  flowVeoLoopLastProgressAt = flowVeoLoopStartedAt;
  try {
    while (true) {
      const status = await api("/api/extension/status");
      if (status.status !== "running") {
        break;
      }
      await handleAudioCue(status);

      if (!sameFlowProject(location.href, status.flow_project_url || "")) {
        await api("/api/extension/flow-error", {
          message: `Wrong Flow project tab: ${location.href}`,
        });
        break;
      }

      if (await handleVisibleFlowWarning(status.phase || "loop")) {
        continue;
      }

      if (status.phase === "submitting") {
        const { stop, reloaded } = await submitPhase();
        if (stop) break;
        if (reloaded) continue;
        await sleep(1000);
        continue;
      }

      if (status.phase === "downloading") {
        const { stop } = await downloadPhase();
        if (stop) break;
        await sleep(1000);
        continue;
      }

      if (status.phase === "awaiting_download" || status.phase === "awaiting_regen") {
        await sleep(2000);
        continue;
      }

      if (status.phase === "completed" || status.phase === "stopped") {
        break;
      }

      await sleep(2000);
    }
  } catch (err) {
    await api("/api/extension/flow-error", { message: err.message || String(err) }).catch(() => {});
  } finally {
    flowVeoLoopRunning = false;
    flowVeoLoopStartedAt = 0;
    flowVeoLoopLastProgressAt = 0;
  }
}

// ─── Heartbeat ────────────────────────────────────────────────────────────────

async function heartbeat() {
  try {
    const status = await api("/api/extension/connect", {
      tab_url: location.href,
      user_agent: navigator.userAgent,
    });
    const staleSubmitLoop = (
      flowVeoLoopRunning &&
      status.status === "running" &&
      status.phase === "submitting" &&
      (status.counts?.prompt_ready || 0) > 0 &&
      flowVeoLoopLastProgressAt &&
      Date.now() - flowVeoLoopLastProgressAt > LOOP_STALE_SUBMIT_MS
    );
    if (staleSubmitLoop) {
      await logServer("[watchdog] submit phase stalled in the Flow tab; restarting content loop.");
      flowVeoLoopRunning = false;
    }
    if (status.status === "running") flowVeoLoop();
  } catch (err) {
    /* Local server may be closed. */
  }
}

heartbeat();
setInterval(heartbeat, 2000);
