const $ = (id) => document.getElementById(id);

let currentPreview = [];
let currentProjectStatus = null;
let extensionPollTimer = null;
let loadedFlowProjectUrl = "";
let lastExtensionJob = null;
let lastDownloadedCount = null;
let lastSubmittedCount = null;
let lastReadyCount = null;
let composerBusyTimer = null;
let composerBusyStartedAt = 0;
let composerBusyMessage = "";
let generateComposerBtnText = "";

const composerState = {
  platform: "veo_3_1",
  mode: "text_to_video",
  orientation: "landscape",
  images: [],
};

const platforms = {
  veo_3_1: {
    label: "Veo 3.1",
    provider: "Google Flow",
  },
};

const statusLabels = {
  idle: "Đang chờ",
  running: "Đang chạy",
  paused: "Tạm dừng",
  completed: "Hoàn tất",
  stopped: "Đã dừng",
  stopping: "Đang dừng",
  error: "Lỗi",
  recovering: "Đang khôi phục",
};

const phaseLabels = {
  idle: "Đang chờ",
  waiting_for_flow_tab: "Chờ tab Flow",
  submitting: "Đang gửi prompt",
  awaiting_download: "Chờ tải xuống",
  downloading: "Đang tải xuống",
  awaiting_regen: "Chờ tạo lại",
  flow_error_wait: "Chờ Flow ổn định",
  wrong_project: "Sai dự án Flow",
  completed: "Hoàn tất",
  stopped: "Đã dừng",
  starting: "Đang khởi động",
  open_flow: "Đang mở Flow",
  queue: "Đang kiểm tra queue",
  download: "Đang tải xuống",
  submit: "Đang gửi prompt",
  wait_after_submit: "Chờ sau khi gửi",
  flow_recovery: "Đang khôi phục Flow",
  flow_error: "Cảnh báo Flow",
  download_timeout: "Tải quá thời gian",
  submit_empty: "Flow không nhận prompt",
  browser_closed: "Trình duyệt đã đóng",
};

const pendingActionLabels = {
  start_download: "Bắt đầu tải xuống",
  start_regen: "Tạo lại",
  complete: "Hoàn tất",
};

const statusTexts = {
  no_prompt: "Chưa tạo",
  prompt_ready: "Sẵn sàng",
  submitted: "Đang tạo",
  downloaded: "Đã tải",
  failed: "Lỗi",
  other: "Khác",
};

function statusLabel(value) {
  return statusLabels[value] || value || "Đang chờ";
}

function phaseLabel(value) {
  return phaseLabels[value] || value || "Đang chờ";
}

function pendingActionLabel(value) {
  return pendingActionLabels[value] || value || "";
}

function api(path, body) {
  return fetch(path, {
    method: body ? "POST" : "GET",
    headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined,
  }).then(async (res) => {
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
    return data;
  });
}

function setStatus(text, isError = false) {
  const el = $("status");
  el.textContent = text || "";
  el.classList.toggle("error", Boolean(isError));
  if (isError && composerBusyTimer) {
    setComposerStatus(text, true);
  }
}

function setComposerStatus(text, isError = false, isBusy = false) {
  const el = $("composerStatus");
  if (!el) return;
  el.textContent = text || "";
  el.classList.toggle("error", Boolean(isError));
  el.classList.toggle("busy", Boolean(isBusy));
}

function waitForPaint() {
  return new Promise((resolve) => {
    requestAnimationFrame(() => requestAnimationFrame(resolve));
  });
}

function setGenerateComposerBusy(isBusy) {
  const button = $("generateComposerBtn");
  if (!button) return;
  if (isBusy) {
    generateComposerBtnText = generateComposerBtnText || button.textContent;
    button.textContent = "Đang tạo...";
    button.classList.add("is-loading");
    button.setAttribute("aria-busy", "true");
  } else {
    button.textContent = generateComposerBtnText || "Tạo prompt";
    button.classList.remove("is-loading");
    button.removeAttribute("aria-busy");
    generateComposerBtnText = "";
  }
}

function updateComposerBusyStatus() {
  const elapsedSeconds = Math.max(0, Math.floor((Date.now() - composerBusyStartedAt) / 1000));
  setComposerStatus(`${composerBusyMessage}\nĐã chờ ${elapsedSeconds}s, request vẫn đang xử lý...`, false, true);
}

function startComposerBusy(message) {
  composerBusyMessage = message;
  composerBusyStartedAt = Date.now();
  setGenerateComposerBusy(true);
  updateComposerBusyStatus();
  if (composerBusyTimer) clearInterval(composerBusyTimer);
  composerBusyTimer = setInterval(updateComposerBusyStatus, 1000);
}

function stopComposerBusy() {
  if (composerBusyTimer) clearInterval(composerBusyTimer);
  composerBusyTimer = null;
  composerBusyStartedAt = 0;
  composerBusyMessage = "";
  setGenerateComposerBusy(false);
}

function disableIfExists(id, isBusy) {
  const el = $(id);
  if (el) el.disabled = isBusy;
}

function setBusy(isBusy) {
  if (!isBusy && composerBusyTimer) stopComposerBusy();
  [
    "generateComposerBtn",
    "clearComposerBtn",
    "saveSettingsBtn",
    "settingsBtn",
    "extensionVisualBtn",
    "extensionStopBtn",
  ].forEach((id) => disableIfExists(id, isBusy));
  if (!isBusy && lastExtensionJob) renderExtensionControls(lastExtensionJob);
}

function projectPath() {
  return $("projectPath").value.trim() || "";
}

function selectedPlatform() {
  return platforms[composerState.platform] || platforms.veo_3_1;
}

function renderAiSettings(settings) {
  const configured = Boolean(settings && settings.configured);
  const model = settings?.model || "gemini-3.5-flash";
  $("model").value = model;
  $("aiSettingsStatus").textContent = configured
    ? `Google AI Studio đã cấu hình (${settings.api_key_tail || "saved"}), model ${model}`
    : "Google AI Studio chưa có API key";
  $("health").textContent = configured ? "Google AI Studio: sẵn sàng" : "Google AI Studio: chưa cấu hình";
  $("health").style.borderColor = configured ? "rgba(22, 163, 74, 0.65)" : "rgba(239, 68, 68, 0.65)";
}

async function refreshAiSettings() {
  const settings = await api("/api/settings/ai");
  renderAiSettings(settings);
  return settings;
}

function updateFramesPathDisplay(path) {
  $("currentFramesPath").textContent = path || "Đang xác định...";
}

function renderProjectSettings(settings) {
  $("projectPath").value = settings.frames_path || "";
  $("flowProjectUrl").value = settings.flow_project_url || "";
  $("projectName").value = settings.project_name || "composer_project";
  $("count").value = settings.prompt_batch_count || 20;
  $("flowBatchCount").value = settings.visual_batch_count || 20;
  loadedFlowProjectUrl = settings.flow_project_url || "";
  updateFramesPathDisplay(settings.frames_path || "Mặc định");
}

async function refreshProjectSettings() {
  const settings = await api("/api/settings/project");
  renderProjectSettings(settings);
  return settings;
}

async function saveSettings() {
  setBusy(true);
  try {
    const aiPayload = { model: $("model").value.trim() || "gemini-3.5-flash" };
    const apiKey = $("googleAiApiKey").value.trim();
    if (apiKey) aiPayload.api_key = apiKey;
    const aiSettings = await api("/api/settings/ai", aiPayload);
    $("googleAiApiKey").value = "";
    renderAiSettings(aiSettings);

    const projectSettings = await api("/api/settings/project", {
      frames_path: projectPath(),
      flow_project_url: $("flowProjectUrl").value.trim(),
      project_name: $("projectName").value.trim() || "composer_project",
      prompt_batch_count: Number($("count").value || 20),
      visual_batch_count: Number($("flowBatchCount").value || 20),
    });
    renderProjectSettings(projectSettings);

    closeSettingsDialog();
    if (currentPreview.length) await refreshFlowQueue();
    setStatus("Đã lưu cài đặt.");
  } catch (err) {
    setStatus(err.message, true);
  } finally {
    setBusy(false);
  }
}

function openSettingsDialog() {
  const dialog = $("settingsDialog");
  if (dialog.showModal) {
    dialog.showModal();
  } else {
    dialog.classList.add("open");
  }
}

function closeSettingsDialog() {
  const dialog = $("settingsDialog");
  if (dialog.close) {
    dialog.close();
  } else {
    dialog.classList.remove("open");
  }
}

function renderQueueSummary(counts = {}, mp4Count = null) {
  const ready = counts.prompt_ready ?? 0;
  const submitted = counts.submitted ?? 0;
  const downloaded = counts.downloaded ?? 0;
  const failed = counts.failed ?? 0;
  const mp4 = mp4Count === null || mp4Count === undefined ? "" : ` | MP4 ${mp4Count}`;
  $("queueSummary").textContent = `Ready ${ready} | Sent ${submitted} | Done ${downloaded} | Fail ${failed}${mp4}`;
}

function renderFlowStatus(status) {
  const counts = status.counts || {};
  const ready = counts.prompt_ready ?? 0;
  const submitted = counts.submitted ?? 0;
  const next = status.next_ready_index === null || status.next_ready_index === undefined
    ? "không có"
    : `#${String(status.next_ready_index).padStart(3, "0")}`;
  $("flowStatus").textContent = `Sẵn sàng ${ready}. Đã gửi ${submitted}. Tiếp theo ${next}.`;
  renderQueueSummary(counts, currentProjectStatus?.mp4_count);
}

function renderRows(items) {
  const rows = $("rows");
  rows.innerHTML = "";
  for (const item of items || []) {
    const tr = document.createElement("tr");
    const index = String(item.index ?? 0).padStart(3, "0");
    const status = item.status || "no_prompt";
    const platform = item.platform_label || platforms[item.platform]?.label || item.platform || "Veo";
    tr.innerHTML = `
      <td>#${index}</td>
      <td><span class="badge ${status}">${statusTexts[status] || status}</span></td>
      <td></td>
      <td></td>
      <td></td>
    `;
    tr.children[2].textContent = item.source_text || item.text || "";
    tr.children[3].textContent = platform;
    tr.children[4].textContent = item.veo_prompt || "";
    if (status === "failed" && item.flow_error) {
      const errEl = document.createElement("div");
      errEl.className = "row-error-msg";
      errEl.textContent = `Lỗi: ${item.flow_error}`;
      tr.children[4].appendChild(errEl);
    }
    rows.appendChild(tr);
  }
  $("summary").textContent = `${(items || []).length} prompt`;
}

async function refreshFlowQueue() {
  const status = await api("/api/flow/queue", { project_path: projectPath() });
  renderFlowStatus(status);
  return status;
}

async function refreshAllProjectState() {
  const settings = await api("/api/settings/project");
  renderProjectSettings(settings);
  updateFramesPathDisplay(settings.frames_path || "Mặc định");
  if (!settings.frames_path) {
    $("flowStatus").textContent = "Chưa có thư mục dự án";
    renderQueueSummary();
    return;
  }
  await refreshFlowQueue().catch(() => {});
  await refreshExtensionStatus(false).catch(() => {});
}

function isExtensionActive(job) {
  return ["running", "stopping"].includes(job.status);
}

function makeExtensionActionButton(label, action, className = "") {
  const button = document.createElement("button");
  button.type = "button";
  button.textContent = label;
  if (className) button.className = className;
  button.addEventListener("click", () => runExtensionPhaseAction(action));
  return button;
}

function renderExtensionActions(job) {
  const holder = $("extensionActions");
  holder.innerHTML = "";
  if (job.pending_action === "start_download") {
    holder.appendChild(makeExtensionActionButton("Bắt đầu tải xuống", "start_download", "primary"));
    return;
  }
  if (job.pending_action === "start_regen") {
    const count = job.unresolved?.regenerable_count ?? 0;
    holder.appendChild(makeExtensionActionButton(`Tạo lại ${count}`, "start_regen", "primary"));
    holder.appendChild(makeExtensionActionButton("Hoàn tất", "complete"));
    return;
  }
  if (job.pending_action === "complete") {
    holder.appendChild(makeExtensionActionButton("Hoàn tất", "complete"));
  }
}

function renderExtensionControls(job) {
  const active = isExtensionActive(job);
  $("extensionVisualBtn").disabled = active;
  $("extensionStopBtn").disabled = !active;
  renderExtensionActions(job);
}

function renderExtensionStatus(job) {
  const counts = job.counts || {};
  const connected = job.connected_at ? "tab đã kết nối" : "chờ tab Flow";
  const ready = counts.prompt_ready ?? 0;
  const submitted = counts.submitted ?? 0;
  const downloaded = counts.downloaded ?? 0;
  $("extensionStatus").textContent =
    `${statusLabel(job.status)} / ${phaseLabel(job.phase)}: ${connected}. ` +
    `ready ${ready}, sent ${submitted}, done ${downloaded}.`;
}

function formatExtensionStatus(job) {
  const counts = job.counts || {};
  const lines = [
    `Tiện ích: ${statusLabel(job.status)} - ${phaseLabel(job.phase)}`,
    job.message || "",
    `Ready: ${counts.prompt_ready ?? 0}. Sent: ${counts.submitted ?? 0}. Done: ${counts.downloaded ?? 0}.`,
  ];
  if (job.tab_url) lines.push(`Tab: ${job.tab_url}`);
  if (job.pending_action) lines.push(`Đang chờ: ${pendingActionLabel(job.pending_action)}`);
  if (job.unresolved?.total) {
    lines.push(`Chưa xử lý: ${job.unresolved.total}. Có thể tạo lại: ${job.unresolved.regenerable_count ?? 0}.`);
  }
  const log = (job.log || []).slice(-5).map((item) => `- ${item.message}`);
  if (log.length) lines.push("Gần đây:", ...log);
  return lines.filter(Boolean).join("\n");
}

function startExtensionPolling() {
  if (extensionPollTimer) clearInterval(extensionPollTimer);
  extensionPollTimer = setInterval(() => {
    refreshExtensionStatus(true).catch((err) => {
      clearInterval(extensionPollTimer);
      extensionPollTimer = null;
      setStatus(err.message, true);
    });
  }, 3000);
}

async function refreshExtensionStatus(writeStatus = false) {
  const job = await api("/api/extension/status");
  lastExtensionJob = job;
  renderExtensionControls(job);
  renderExtensionStatus(job);
  if (job.counts) {
    renderFlowStatus({ counts: job.counts, next_ready_index: job.next_ready_index });
    const ready = job.counts.prompt_ready ?? 0;
    const submitted = job.counts.submitted ?? 0;
    const downloaded = job.counts.downloaded ?? 0;
    if (ready !== lastReadyCount || submitted !== lastSubmittedCount || downloaded !== lastDownloadedCount) {
      lastReadyCount = ready;
      lastSubmittedCount = submitted;
      lastDownloadedCount = downloaded;
    }
  }
  $("autoModeCheckbox").checked = Boolean(job.auto_mode);
  if (writeStatus) {
    setStatus(formatExtensionStatus(job), job.status === "error" || job.status === "paused");
  }
  if (!isExtensionActive(job) && extensionPollTimer) {
    clearInterval(extensionPollTimer);
    extensionPollTimer = null;
  }
  return job;
}

async function runExtensionPhaseAction(action) {
  setBusy(true);
  try {
    const job = await api("/api/extension/phase-action", { action });
    renderExtensionControls(job);
    renderExtensionStatus(job);
    setStatus(formatExtensionStatus(job), job.status === "error" || job.status === "paused");
    startExtensionPolling();
  } catch (err) {
    setStatus(err.message, true);
  } finally {
    setBusy(false);
    refreshExtensionStatus(false).catch(() => {});
  }
}

async function startExtensionGeneration() {
  setBusy(true);
  try {
    let flowProjectUrl = $("flowProjectUrl").value.trim();
    if (!flowProjectUrl) {
      const typed = window.prompt("Dán URL dự án Flow:");
      flowProjectUrl = (typed || "").trim();
      if (!flowProjectUrl) {
        setStatus("Hãy lưu URL dự án Flow trước.", true);
        return;
      }
      $("flowProjectUrl").value = flowProjectUrl;
    }

    const job = await api("/api/extension/start", {
      project_path: projectPath(),
      count: Number($("flowBatchCount").value || 20),
      flow_project_url: flowProjectUrl,
    });
    renderExtensionControls(job);
    renderExtensionStatus(job);
    setStatus(formatExtensionStatus(job));
    startExtensionPolling();
  } catch (err) {
    setStatus(err.message, true);
  } finally {
    setBusy(false);
    refreshExtensionStatus(false).catch(() => {});
  }
}

async function stopExtensionGeneration() {
  setStatus("Đang dừng tiện ích sau thao tác hiện tại...");
  try {
    const job = await api("/api/extension/stop", {});
    renderExtensionControls(job);
    renderExtensionStatus(job);
    setStatus(formatExtensionStatus(job));
    startExtensionPolling();
  } catch (err) {
    setStatus(err.message, true);
  }
}

function setSegmentValue(containerId, dataKey, value) {
  const container = $(containerId);
  for (const button of container.querySelectorAll("button")) {
    const active = button.dataset[dataKey] === value;
    button.classList.toggle("active", active);
  }
}

function renderComposerState() {
  setSegmentValue("modeButtons", "mode", composerState.mode);
  setSegmentValue("orientationButtons", "orientation", composerState.orientation);
  $("platformStatus").textContent = selectedPlatform().label;
  $("providerStatus").textContent = selectedPlatform().provider;
  const imageMode = composerState.mode === "text_image_to_video";
  $("imageDropzone").classList.toggle("is-hidden", !imageMode);
  $("imageList").classList.toggle("is-hidden", !imageMode);
  $("promptInput").placeholder = imageMode
    ? "Optional: add motion, mood, or details to combine with the image..."
    : "Describe the video idea. AI will expand it into a Veo prompt...";
  if (lastExtensionJob) renderExtensionControls(lastExtensionJob);
}

function setupSegmentedControls() {
  $("modeButtons").addEventListener("click", (event) => {
    const button = event.target.closest("button[data-mode]");
    if (!button) return;
    composerState.mode = button.dataset.mode;
    renderComposerState();
  });

  $("orientationButtons").addEventListener("click", (event) => {
    const button = event.target.closest("button[data-orientation]");
    if (!button) return;
    composerState.orientation = button.dataset.orientation;
    renderComposerState();
  });
}

function setupImageDropzone() {
  const dropzone = $("imageDropzone");
  const input = $("imageInput");

  dropzone.addEventListener("click", () => input.click());
  dropzone.addEventListener("dragover", (event) => {
    event.preventDefault();
    dropzone.classList.add("dragging");
  });
  dropzone.addEventListener("dragleave", () => {
    dropzone.classList.remove("dragging");
  });
  dropzone.addEventListener("drop", (event) => {
    event.preventDefault();
    dropzone.classList.remove("dragging");
    handleImageFiles(Array.from(event.dataTransfer.files || []));
  });
  input.addEventListener("change", (event) => {
    handleImageFiles(Array.from(event.target.files || []));
    input.value = "";
  });
}

function handleImageFiles(files) {
  for (const file of files) {
    if (!file.type.startsWith("image/")) continue;
    const reader = new FileReader();
    reader.onload = (event) => {
      composerState.images.push({
        filename: file.name,
        base64: event.target.result,
      });
      renderImages();
    };
    reader.readAsDataURL(file);
  }
}

function renderImages() {
  const list = $("imageList");
  list.innerHTML = "";
  composerState.images.forEach((image, index) => {
    const item = document.createElement("div");
    item.className = "image-thumb";

    const img = document.createElement("img");
    img.src = image.base64;
    img.alt = image.filename || `image ${index + 1}`;

    const remove = document.createElement("button");
    remove.type = "button";
    remove.textContent = "x";
    remove.addEventListener("click", (event) => {
      event.stopPropagation();
      composerState.images.splice(index, 1);
      renderImages();
    });

    item.appendChild(img);
    item.appendChild(remove);
    list.appendChild(item);
  });
}

async function generateComposerPrompt() {
  const prompt = $("promptInput").value.trim();
  if (!prompt && composerState.mode === "text_to_video") {
    setComposerStatus("Hãy nhập prompt trước.", true);
    setStatus("Hãy nhập prompt trước.", true);
    return;
  }
  if (composerState.mode === "text_image_to_video" && composerState.images.length === 0) {
    setComposerStatus("Hãy chọn ít nhất một hình ảnh.", true);
    setStatus("Hãy chọn ít nhất một hình ảnh.", true);
    return;
  }

  setBusy(true);
  setStatus(composerState.mode === "text_image_to_video" ? "Đang phân tích ảnh và tạo prompt..." : "Đang tạo prompt...");
  const busyMessage = composerState.mode === "text_image_to_video" ? "Đang phân tích ảnh và tạo prompt..." : "Đang tạo prompt...";
  setStatus(busyMessage);
  startComposerBusy(busyMessage);
  try {
    await waitForPaint();
    const data = await api("/api/composer/generate", {
      project_path: projectPath(),
      project_name: $("projectName").value || "composer_project",
      platform: composerState.platform,
      mode: composerState.mode,
      orientation: composerState.orientation,
      model: $("model").value || "",
      prompt,
      images: composerState.mode === "text_image_to_video" ? composerState.images : [],
    });
    currentPreview = data.prompts || data.generated || [];
    renderRows(currentPreview);
    await refreshFlowQueue().catch(() => {});
    const generatedCount = (data.generated || currentPreview || []).length;
    const doneMessage = `Đã tạo ${generatedCount} prompt.\nLưu tại: ${data.saved_to}`;
    setComposerStatus(doneMessage);
    setTimeout(() => setStatus(doneMessage), 0);
    setStatus(`Đã tạo ${data.generated.length} prompt.\nLưu tại: ${data.saved_to}`);
  } catch (err) {
    setStatus(err.message, true);
  } finally {
    setBusy(false);
  }
}

function clearComposer() {
  $("promptInput").value = "";
  composerState.images = [];
  renderImages();
}

async function loadInitial() {
  renderComposerState();

  await api("/api/health");
  await refreshAiSettings();
  await refreshProjectSettings();
  await refreshAllProjectState();
}

$("autoModeCheckbox").addEventListener("change", async () => {
  try {
    await api("/api/extension/auto-mode", { auto_mode: $("autoModeCheckbox").checked });
  } catch (err) {
    setStatus(err.message, true);
  }
});

$("generateComposerBtn").addEventListener("click", generateComposerPrompt);
$("clearComposerBtn").addEventListener("click", clearComposer);
$("settingsBtn").addEventListener("click", openSettingsDialog);
$("closeSettingsBtn").addEventListener("click", closeSettingsDialog);
$("saveSettingsBtn").addEventListener("click", saveSettings);
$("extensionVisualBtn").addEventListener("click", startExtensionGeneration);
$("extensionStopBtn").addEventListener("click", stopExtensionGeneration);

setupSegmentedControls();
setupImageDropzone();
loadInitial().catch((err) => setStatus(err.message, true));
