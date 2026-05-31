const $ = (id) => document.getElementById(id);

let library = { root: "", channels: [] };
let currentPreview = [];
let currentProjectStatus = null;
let extensionPollTimer = null;
let loadedFlowProjectUrl = "";
let lastExtensionJob = null;
let scriptLoadedPath = "";

const visualProviders = [
  {
    id: "google_flow",
    label: "Google Flow (đang hỗ trợ)",
    extensionMode: true,
    description: "Dùng project Flow đang mở trong trình duyệt thường cùng tiện ích Flow Veo Studio Bridge.",
  },
  {
    id: "sora",
    label: "Sora (chuẩn bị)",
    extensionMode: false,
    description: "Sora là lựa chọn định hướng. Phiên bản này chưa có adapter gửi prompt/tải clip.",
  },
  {
    id: "runway",
    label: "Runway (chuẩn bị)",
    extensionMode: false,
    description: "Runway chưa được nối API/tự động hoá. Chọn Google Flow để chạy pipeline hiện tại.",
  },
  {
    id: "pika",
    label: "Pika (chuẩn bị)",
    extensionMode: false,
    description: "Pika đang ở trạng thái giữ chỗ để mở rộng sau.",
  },
];

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
  awaiting_download: "Chờ bắt đầu tải xuống",
  downloading: "Đang tải xuống",
  awaiting_regen: "Chờ quyết định tạo lại",
  flow_error_wait: "Chờ cảnh báo Flow biến mất",
  wrong_project: "Sai dự án Flow",
  completed: "Hoàn tất",
  stopped: "Đã dừng",
  starting: "Đang khởi động",
  open_flow: "Đang mở Flow",
  queue: "Đang kiểm tra hàng đợi",
  download: "Đang tải xuống",
  submit: "Đang gửi prompt",
  wait_after_submit: "Chờ sau khi gửi",
  flow_recovery: "Đang khôi phục Flow",
  flow_error: "Cảnh báo Flow",
  download_timeout: "Tải xuống quá thời gian",
  submit_empty: "Flow không nhận prompt",
  browser_closed: "Trình duyệt đã đóng",
};

const pendingActionLabels = {
  start_download: "Bắt đầu tải xuống",
  start_regen: "Tạo lại",
  complete: "Hoàn tất",
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

function setStatus(text, isError = false) {
  const el = $("status");
  el.textContent = text;
  el.classList.toggle("error", isError);
}

function disableIfExists(id, isBusy) {
  const el = $(id);
  if (el) el.disabled = isBusy;
}

function setBusy(isBusy) {
  [
    "loadScriptBtn",
    "saveScriptBtn",
    "previewBtn",
    "generateAllBtn",
    "extensionVisualBtn",
    "extensionStopBtn",
  ].forEach((id) => disableIfExists(id, isBusy));
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

function flowProjectUrlKey() {
  return `flowProjectUrl::${$("projectPath").value || ""}`;
}

function loadFlowProjectUrl() {
  try {
    const value = localStorage.getItem(flowProjectUrlKey()) || "";
    $("flowProjectUrl").value = value;
    loadedFlowProjectUrl = value;
  } catch (err) {
    /* ignore */
  }
}

function saveFlowProjectUrl(value) {
  loadedFlowProjectUrl = value || "";
  try {
    localStorage.setItem(flowProjectUrlKey(), value || "");
  } catch (err) {
    /* ignore */
  }
}

async function saveFlowProjectUrlForProject(value) {
  const url = (value || "").trim();
  const data = await api("/api/project/flow-url", {
    project_path: $("projectPath").value,
    flow_project_url: url,
  });
  if (data.flow_project_url !== undefined) {
    const cleanUrl = data.flow_project_url || "";
    $("flowProjectUrl").value = cleanUrl;
    saveFlowProjectUrl(cleanUrl);
  }
  return data.flow_project_url || "";
}

function applySavedFlowProjectUrl(url, force = false) {
  const cleanUrl = (url || "").trim();
  const currentUrl = $("flowProjectUrl").value.trim();
  if (!cleanUrl) {
    if (force || currentUrl === loadedFlowProjectUrl) {
      $("flowProjectUrl").value = "";
      saveFlowProjectUrl("");
    }
    return;
  }
  if (force || !currentUrl || currentUrl === loadedFlowProjectUrl) {
    $("flowProjectUrl").value = cleanUrl;
    saveFlowProjectUrl(cleanUrl);
  }
}

async function ensureFlowProjectUrl() {
  let url = $("flowProjectUrl").value.trim();
  if (url) {
    return await saveFlowProjectUrlForProject(url);
  }

  const typed = window.prompt("Chưa lưu URL dự án Flow cho thư mục frames này. Hãy dán URL dự án Flow:");
  url = (typed || "").trim();
  if (!url) return "";

  $("flowProjectUrl").value = url;
  return await saveFlowProjectUrlForProject(url);
}

function safeProjectName(value) {
  return (value || "default_project").replace(/[^a-zA-Z0-9_.-]+/g, "_").replace(/^_+|_+$/g, "") || "default_project";
}

function selectedLibraryChannel() {
  return library.channels.find((item) => item.id === $("channelFolder").value) || null;
}

function selectedSeries() {
  const channel = selectedLibraryChannel();
  if (!channel) return null;
  return (channel.series || []).find((item) => item.id === $("seriesFolder").value) || null;
}

function selectedStyle() {
  const channel = selectedLibraryChannel();
  if (!channel) return null;
  return (channel.styles || []).find((item) => item.id === $("channel").value) || null;
}

function selectedVisualProvider() {
  const select = $("visualProvider");
  if (!select) return visualProviders[0];
  return visualProviders.find((item) => item.id === select.value) || visualProviders[0];
}

function visualProviderSupportsExtension() {
  return Boolean(selectedVisualProvider().extensionMode);
}

function renderProviderStatus() {
  const provider = selectedVisualProvider();
  const status = $("providerStatus");
  if (!status) return;
  status.textContent = provider.description;
  status.classList.toggle("warning", !provider.extensionMode);
}

function populateVisualProviders() {
  const select = $("visualProvider");
  if (!select) return;
  select.innerHTML = "";
  for (const provider of visualProviders) {
    const option = document.createElement("option");
    option.value = provider.id;
    option.textContent = provider.label;
    select.appendChild(option);
  }
  select.value = "google_flow";
  renderProviderStatus();
}

function renderRows(items) {
  const rows = $("rows");
  rows.innerHTML = "";
  for (const item of items) {
    const tr = document.createElement("tr");
    const index = String(item.index).padStart(3, "0");
    tr.innerHTML = `
      <td>#${index}</td>
      <td></td>
      <td></td>
      <td></td>
    `;
    tr.children[1].textContent = item.source_text || item.text || "";
    tr.children[2].textContent = item.flow_title || item.title_slug || "";
    tr.children[3].textContent = item.veo_prompt || "";
    rows.appendChild(tr);
  }
  $("summary").textContent = `${items.length} dòng`;
}

function renderScriptInfo(text) {
  const count = (text || "").split(/\r?\n/).map((line) => line.trim()).filter(Boolean).length;
  $("scriptInfo").textContent = count
    ? `Kịch bản hiện có ${count} đoạn.`
    : "Bạn có thể tải kịch bản hiện có hoặc dán nội dung mới vào đây.";
}

function renderProjectStatus(status) {
  currentProjectStatus = status;
  const next = status.next_start_index === null ? "xong" : `#${String(status.next_start_index).padStart(3, "0")}`;
  const counts = status.counts || {};
  $("projectStats").textContent =
    `Đoạn: ${status.total}. Prompt đã sẵn sàng: ${status.generated_count}. Còn lại: ${status.missing_count}. ` +
    `Tiếp theo: ${next}. Hàng đợi: sẵn sàng ${counts.prompt_ready || 0}, đã gửi ${counts.submitted || 0}, đã tải ${counts.downloaded || 0}. ` +
    `MP4: ${status.mp4_count || 0}.`;
}

function renderFlowStatus(status) {
  const counts = status.counts || {};
  const browser = status.browser || {};
  const openText = browser.open ? "Flow đang mở" : "Flow đang đóng";
  const ready = counts.prompt_ready ?? 0;
  const submitted = counts.submitted ?? 0;
  const next = status.next_ready_index === null || status.next_ready_index === undefined
    ? "không có"
    : `#${String(status.next_ready_index).padStart(3, "0")}`;
  $("flowStatus").textContent = `${openText}. Sẵn sàng gửi: ${ready}. Đã gửi: ${submitted}. Tiếp theo: ${next}.`;
}

function isVisualJobActive(job) {
  return ["running", "recovering", "stopping"].includes(job.status);
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
  const visualActive = Boolean(job.visual_job_active);
  $("extensionVisualBtn").disabled = active || visualActive || !visualProviderSupportsExtension();
  $("extensionStopBtn").disabled = !active;
  renderExtensionActions(job);
}

function renderExtensionStatus(job) {
  const counts = job.counts || {};
  const connected = job.connected_at ? "tab đã kết nối" : "đang chờ tab Flow";
  const ready = counts.prompt_ready ?? 0;
  const submitted = counts.submitted ?? 0;
  const downloaded = counts.downloaded ?? 0;
  const blocked = job.visual_job_active ? " Visual worker cũ đang hoạt động." : "";
  $("extensionStatus").textContent =
    `${statusLabel(job.status)} / ${phaseLabel(job.phase)}: ${connected}. ` +
    `sẵn sàng ${ready}, đã gửi ${submitted}, đã tải ${downloaded}.${blocked}`;
}

function formatVisualJobStatus(job) {
  const counts = job.counts || {};
  const lines = [
    `Tự động tạo hình ảnh: ${statusLabel(job.status)} - ${job.phase_label || phaseLabel(job.phase)}`,
    job.message || "",
  ];
  if (job.next_action) lines.push(`Việc cần làm: ${job.next_action}`);
  lines.push(
    `Sẵn sàng gửi: ${counts.prompt_ready ?? 0}. ` +
    `Đã gửi: ${counts.submitted ?? 0}. Đã tải: ${counts.downloaded ?? 0}.`
  );
  const log = (job.log || []).slice(-6).map((item) => `- ${item.message}`);
  if (log.length) {
    lines.push("Hành động gần đây:");
    lines.push(...log);
  }
  return lines.filter(Boolean).join("\n");
}

function formatExtensionStatus(job) {
  const counts = job.counts || {};
  const lines = [
    `Tiện ích: ${statusLabel(job.status)} - ${phaseLabel(job.phase)}`,
    job.message || "",
    `Sẵn sàng gửi: ${counts.prompt_ready ?? 0}. Đã gửi: ${counts.submitted ?? 0}. Đã tải: ${counts.downloaded ?? 0}.`,
  ];
  if (job.tab_url) lines.push(`Tab: ${job.tab_url}`);
  if (job.pending_action) lines.push(`Đang chờ thao tác: ${pendingActionLabel(job.pending_action)}`);
  if (job.unresolved?.total) {
    lines.push(`Chưa xử lý: ${job.unresolved.total}. Có thể tạo lại: ${job.unresolved.regenerable_count ?? 0}.`);
  }
  if (job.visual_job_active) lines.push("Visual worker cũ đang hoạt động: hãy dừng nó trước, sau đó khởi động tiện ích.");
  const log = (job.log || []).slice(-6).map((item) => `- ${item.message}`);
  if (log.length) {
    lines.push("Hành động gần đây:");
    lines.push(...log);
  }
  return lines.filter(Boolean).join("\n");
}

function formatBlockedPrompts(items) {
  if (!items || !items.length) return "";
  const indexes = items.map((item) => `#${String(item.index).padStart(3, "0")}`).join(", ");
  return `\nCảnh báo unusual activity của Flow: ${indexes} đã được đưa về prompt_ready.`;
}

function applyStyle(style) {
  if (!style) return;
  $("model").value = style.default_model || "gpt-5.4-mini";
  $("count").value = style.prompt_batch_size || 20;
  $("stylePrompt").value = style.style_prompt || "";
}

function updateProjectFromSelection() {
  const channel = selectedLibraryChannel();
  const series = selectedSeries();
  if (!channel) return;
  if (series) {
    $("projectPath").value = series.frames_path;
    $("projectName").value = safeProjectName(`${channel.id}_${series.id}`);
  } else {
    $("projectPath").value = "";
    $("projectName").value = safeProjectName(channel.id);
  }
  loadFlowProjectUrl();
}

function populateStyles(channel) {
  const select = $("channel");
  select.innerHTML = "";
  for (const style of channel.styles || []) {
    const option = document.createElement("option");
    option.value = style.id;
    option.textContent = style.name || style.id;
    select.appendChild(option);
  }
  select.value = channel.default_style_id || (channel.styles && channel.styles[0] && channel.styles[0].id) || "";
  applyStyle(selectedStyle());
}

function populateSeries(channel) {
  const select = $("seriesFolder");
  select.innerHTML = "";
  for (const series of channel.series || []) {
    const option = document.createElement("option");
    option.value = series.id;
    const markers = [];
    if (series.has_frames) markers.push("frames");
    if (series.has_sentences) markers.push("sentences");
    option.textContent = markers.length ? `${series.name} (${markers.join(", ")})` : series.name;
    select.appendChild(option);
  }
  if (!select.options.length) {
    const option = document.createElement("option");
    option.value = "";
    option.textContent = "Không tìm thấy series";
    select.appendChild(option);
  }
  select.value = channel.default_series_id || (channel.series && channel.series[0] && channel.series[0].id) || "";
}

function populateChannelFolders() {
  const select = $("channelFolder");
  select.innerHTML = "";
  for (const channel of library.channels || []) {
    const option = document.createElement("option");
    option.value = channel.id;
    option.textContent = channel.configured ? channel.name : `${channel.name} (chưa có phong cách)`;
    select.appendChild(option);
  }
  const preferred = (library.channels || []).find((item) => item.id.toLowerCase() === "erifan") || library.channels[0];
  if (preferred) select.value = preferred.id;
}

async function refreshProjectStatus(updateStartIndex = false) {
  const status = await api("/api/project/status", { path: $("projectPath").value });
  renderProjectStatus(status);
  applySavedFlowProjectUrl(status.flow_project_url);
  if (updateStartIndex && status.next_start_index !== null) {
    $("startIndex").value = status.next_start_index;
  }
  return status;
}

async function refreshFlowQueue() {
  const status = await api("/api/flow/queue", { project_path: $("projectPath").value });
  renderFlowStatus(status);
  return status;
}

async function loadScriptEditor(showStatus = true) {
  const data = await api("/api/sentences/load", { project_path: $("projectPath").value });
  $("scriptEditor").value = data.script_text || "";
  scriptLoadedPath = data.sentences_path || "";
  renderScriptInfo($("scriptEditor").value);
  if (showStatus) {
    setStatus(
      data.exists
        ? `Đã tải kịch bản từ: ${data.sentences_path}`
        : "Chưa có sentences.json trong thư mục frames. Hãy dán kịch bản rồi bấm Lưu kịch bản."
    );
  }
  return data;
}

async function saveScriptEditor() {
  setBusy(true);
  try {
    const data = await api("/api/sentences/save", {
      project_path: $("projectPath").value,
      script_text: $("scriptEditor").value,
    });
    $("scriptEditor").value = data.script_text || "";
    scriptLoadedPath = data.sentences_path || "";
    renderScriptInfo($("scriptEditor").value);
    await refreshProjectStatus(true).catch((err) => setStatus(err.message, true));
    await refreshFlowQueue().catch(() => {});
    setStatus(
      `Đã lưu kịch bản: ${data.sentences_path}\n` +
      `Tổng số đoạn: ${data.total}.` +
      (data.backup_path ? `\nBackup file cũ: ${data.backup_path}` : "")
    );
  } catch (err) {
    setStatus(err.message, true);
  } finally {
    setBusy(false);
  }
}

async function selectChannelFolder(refresh = true) {
  const channel = selectedLibraryChannel();
  if (!channel) return;
  populateStyles(channel);
  populateSeries(channel);
  updateProjectFromSelection();
  if (refresh) {
    await refreshProjectStatus(true).catch((err) => setStatus(err.message, true));
    await loadScriptEditor(false).catch(() => {
      $("scriptEditor").value = "";
      renderScriptInfo("");
    });
    await refreshFlowQueue().catch(() => {});
    await refreshVisualJobStatus(false).catch(() => {});
    await refreshExtensionStatus(false).catch(() => {});
  }
}

async function loadInitial() {
  const health = await api("/api/health");
  $("health").textContent = health.openai_key ? "Đã tìm thấy OPENAI_API_KEY" : "Không tìm thấy OPENAI_API_KEY";
  $("health").style.borderColor = health.openai_key ? "#9bc7aa" : "#d89b93";

  populateVisualProviders();
  library = await api("/api/library");
  $("libraryRoot").textContent = library.root || "";
  populateChannelFolders();
  await selectChannelFolder(false);
  await refreshProjectStatus(true).catch((err) => setStatus(err.message, true));
  await loadScriptEditor(false).catch(() => {
    $("scriptEditor").value = "";
    renderScriptInfo("");
  });
  await refreshFlowQueue().catch(() => {});
  await refreshVisualJobStatus(false).catch(() => {});
  await refreshExtensionStatus(false).catch(() => {});
}

async function preview() {
  setStatus("Đang đọc sentences.json...");
  const data = await api("/api/sentences/preview", {
    path: $("projectPath").value,
    start_index: Number($("startIndex").value),
    count: Number($("count").value),
  });
  currentPreview = data.items;
  renderRows(currentPreview);
  const status = await refreshProjectStatus(false);
  const counts = status.counts || {};
  setStatus(
    `Đã đọc tệp: ${data.sentences_path}\n` +
    `Prompt được lưu tại: ${data.prompts_path}\n` +
    `Clip được lưu tại: ${data.clips_dir}\n` +
    `Đoạn: ${data.total}. Đang hiển thị: ${data.items.length}.\n` +
    `Trạng thái: sẵn sàng ${counts.prompt_ready || 0}, đã gửi ${counts.submitted || 0}, đã tải ${counts.downloaded || 0}, lỗi ${counts.failed || 0}. MP4: ${status.mp4_count || 0}.`
  );
}

async function generateAllPrompts() {
  setBusy(true);
  const batchSize = Math.max(1, Math.min(80, Number($("count").value || 20)));
  const allGenerated = [];
  try {
    let status = await refreshProjectStatus(true);
    if (status.next_start_index === null) {
      setStatus("Tất cả prompt cho sentences.json này đã sẵn sàng.");
      return;
    }

    let batchNumber = 1;
    while (status.next_start_index !== null) {
      const startIndex = status.next_start_index;
      const totalBatches = Math.ceil(status.missing_count / batchSize);
      setStatus(
        `Đang tạo tất cả prompt: lô ${batchNumber}/${totalBatches}, bắt đầu từ #${String(startIndex).padStart(3, "0")}.\n` +
        `OpenAI API được gọi theo từng phần ${batchSize}. Còn lại trước lô này: ${status.missing_count}.`
      );

      const data = await api("/api/prompts/generate", {
        channel_id: $("channel").value || $("channelFolder").value,
        model: $("model").value,
        project_path: $("projectPath").value,
        project_name: $("projectName").value,
        start_index: startIndex,
        count: batchSize,
        missing_only: true,
        style_prompt: $("stylePrompt").value,
      });

      allGenerated.push(...data.generated);
      renderRows(data.prompts || allGenerated);
      await refreshFlowQueue().catch(() => {});
      status = await refreshProjectStatus(true);
      batchNumber += 1;
    }

    setStatus(
      `Xong. Đã tạo prompt mới: ${allGenerated.length}.\n` +
      `Tất cả prompt đã được lưu trong veo_prompts.json bên trong thư mục frames đã chọn.`
    );
  } catch (err) {
    setStatus(err.message, true);
  } finally {
    setBusy(false);
  }
}

async function refreshVisualJobStatus(writeStatus = false) {
  const job = await api("/api/flow/visual/status");
  if (job.counts) {
    renderFlowStatus({ browser: job.browser || {}, counts: job.counts });
  } else {
    await refreshFlowQueue().catch(() => {});
  }
  if (writeStatus) {
    setStatus(formatVisualJobStatus(job), job.status === "error" || job.status === "paused");
  }
  return job;
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
    renderFlowStatus({ browser: {}, counts: job.counts, next_ready_index: job.next_ready_index });
  }
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
  const count = Number($("flowBatchCount").value || 20);
  try {
    const provider = selectedVisualProvider();
    if (!provider.extensionMode) {
      setStatus(`${provider.label} chưa được tích hợp tự động. Hãy chọn Google Flow để chạy pipeline hiện tại.`, true);
      return;
    }

    const currentVisualJob = await refreshVisualJobStatus(false);
    if (isVisualJobActive(currentVisualJob)) {
      setStatus(
        `${formatVisualJobStatus(currentVisualJob)}\n\nHãy dừng visual worker cũ trước, sau đó khởi động chế độ tiện ích.`,
        true
      );
      return;
    }

    let projectUrl = $("flowProjectUrl").value.trim();
    if (!projectUrl) {
      projectUrl = await ensureFlowProjectUrl();
    }
    if (!projectUrl) {
      setStatus("Trước tiên hãy mở đúng dự án trong Flow và lưu URL.", true);
      return;
    }
    projectUrl = await saveFlowProjectUrlForProject(projectUrl);
    const job = await api("/api/extension/start", {
      project_path: $("projectPath").value,
      count,
      flow_project_url: projectUrl,
    });
    renderExtensionControls(job);
    renderExtensionStatus(job);
    setStatus(
      `${formatExtensionStatus(job)}\n\nHãy mở dự án Flow này trong trình duyệt thường có cài tiện ích. Tiện ích sẽ tự nhận phiên chạy.`
    );
    startExtensionPolling();
  } catch (err) {
    setStatus(err.message, true);
  } finally {
    setBusy(false);
    refreshExtensionStatus(false).catch(() => {});
  }
}

async function stopExtensionGeneration() {
  setStatus("Đang dừng chế độ tiện ích sau thao tác hiện tại...");
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

$("channelFolder").addEventListener("change", () => {
  selectChannelFolder(true);
});

$("seriesFolder").addEventListener("change", () => {
  updateProjectFromSelection();
  loadScriptEditor(false).catch(() => {
    $("scriptEditor").value = "";
    renderScriptInfo("");
  });
  refreshProjectStatus(true).catch((err) => setStatus(err.message, true));
  refreshFlowQueue().catch(() => {});
  refreshExtensionStatus(false).catch(() => {});
});

$("channel").addEventListener("change", () => {
  applyStyle(selectedStyle());
});

$("visualProvider").addEventListener("change", () => {
  renderProviderStatus();
  if (lastExtensionJob) renderExtensionControls(lastExtensionJob);
});

$("projectPath").addEventListener("change", () => {
  loadFlowProjectUrl();
  loadScriptEditor(false).catch(() => {
    $("scriptEditor").value = "";
    renderScriptInfo("");
  });
  refreshProjectStatus(true).catch((err) => setStatus(err.message, true));
  refreshFlowQueue().catch(() => {});
  refreshExtensionStatus(false).catch(() => {});
});

$("flowProjectUrl").addEventListener("change", () => {
  saveFlowProjectUrlForProject($("flowProjectUrl").value.trim()).catch((err) => setStatus(err.message, true));
});

$("scriptEditor").addEventListener("input", () => {
  renderScriptInfo($("scriptEditor").value);
});

$("previewBtn").addEventListener("click", () => {
  preview().catch((err) => setStatus(err.message, true));
});
$("loadScriptBtn").addEventListener("click", () => {
  loadScriptEditor(true).catch((err) => setStatus(err.message, true));
});
$("saveScriptBtn").addEventListener("click", saveScriptEditor);
$("generateAllBtn").addEventListener("click", generateAllPrompts);
$("extensionVisualBtn").addEventListener("click", startExtensionGeneration);
$("extensionStopBtn").addEventListener("click", stopExtensionGeneration);

loadInitial().catch((err) => setStatus(err.message, true));
