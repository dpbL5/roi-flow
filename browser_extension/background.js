async function withDebugger(tabId, callback) {
  const target = { tabId };
  await chrome.debugger.attach(target, "1.3");
  try {
    return await callback(target);
  } finally {
    await chrome.debugger.detach(target).catch(() => {});
  }
}

async function pressEnter(tabId) {
  return withDebugger(tabId, async (target) => {
    const base = {
      key: "Enter",
      code: "Enter",
      windowsVirtualKeyCode: 13,
      nativeVirtualKeyCode: 13,
      isKeypad: false,
    };
    await chrome.debugger.sendCommand(target, "Input.dispatchKeyEvent", {
      ...base,
      type: "rawKeyDown",
    });
    await chrome.debugger.sendCommand(target, "Input.dispatchKeyEvent", {
      ...base,
      type: "keyUp",
    });
  });
}

async function dispatchKey(target, key, code, windowsVirtualKeyCode, modifiers = 0) {
  const base = {
    key,
    code,
    windowsVirtualKeyCode,
    nativeVirtualKeyCode: windowsVirtualKeyCode,
    modifiers,
  };
  await chrome.debugger.sendCommand(target, "Input.dispatchKeyEvent", {
    ...base,
    type: "rawKeyDown",
  });
  await chrome.debugger.sendCommand(target, "Input.dispatchKeyEvent", {
    ...base,
    type: "keyUp",
  });
}

async function insertPromptAndEnter(tabId, prompt, rect) {
  return withDebugger(tabId, async (target) => {
    if (rect && Number.isFinite(rect.x) && Number.isFinite(rect.y)) {
      await chrome.debugger.sendCommand(target, "Input.dispatchMouseEvent", {
        type: "mousePressed",
        x: rect.x,
        y: rect.y,
        button: "left",
        clickCount: 1,
      });
      await chrome.debugger.sendCommand(target, "Input.dispatchMouseEvent", {
        type: "mouseReleased",
        x: rect.x,
        y: rect.y,
        button: "left",
        clickCount: 1,
      });
    }

    await dispatchKey(target, "a", "KeyA", 65, 2);
    await chrome.debugger.sendCommand(target, "Input.insertText", { text: prompt });
    await dispatchKey(target, "Enter", "Enter", 13, 0);
  });
}

function arrayBufferToBase64(buffer) {
  const bytes = new Uint8Array(buffer);
  const chunkSize = 0x8000;
  let binary = "";
  for (let i = 0; i < bytes.length; i += chunkSize) {
    binary += String.fromCharCode.apply(null, bytes.subarray(i, i + chunkSize));
  }
  return btoa(binary);
}

async function fetchMediaAsBase64(mediaUrl) {
  const response = await fetch(mediaUrl, {
    credentials: "include",
    cache: "no-store",
  });
  if (!response.ok) {
    throw new Error(`Media trả về HTTP ${response.status}`);
  }
  const buffer = await response.arrayBuffer();
  return {
    data_base64: arrayBufferToBase64(buffer),
    content_type: response.headers.get("content-type") || "",
    byte_length: buffer.byteLength,
  };
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (!message || !["flowVeoPressEnter", "flowVeoInsertPromptAndEnter", "flowVeoFetchMedia"].includes(message.type)) return false;

  if (message.type === "flowVeoFetchMedia") {
    fetchMediaAsBase64(message.media_url || "")
      .then((result) => sendResponse({ ok: true, ...result }))
      .catch((err) => sendResponse({ ok: false, error: err.message || String(err) }));
    return true;
  }

  const tabId = sender.tab && sender.tab.id;
  if (!tabId) {
    sendResponse({ ok: false, error: "Không có tab gửi yêu cầu." });
    return false;
  }

  const action = message.type === "flowVeoInsertPromptAndEnter"
    ? insertPromptAndEnter(tabId, message.prompt || "", message.rect || null)
    : pressEnter(tabId);

  action
    .then(() => sendResponse({ ok: true }))
    .catch((err) => sendResponse({ ok: false, error: err.message || String(err) }));
  return true;
});
