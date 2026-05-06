const $ = (id) => document.getElementById(id);

let library = { root: "", channels: [] };
let currentPreview = [];
let currentProjectStatus = null;
let extensionPollTimer = null;
let loadedFlowProjectUrl = "";

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

  const typed = window.prompt("Для этой папки frames еще не сохранен URL проекта Flow. Вставьте URL проекта Flow:");
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
  $("summary").textContent = `${items.length} строк`;
}

function renderProjectStatus(status) {
  currentProjectStatus = status;
  const next = status.next_start_index === null ? "готово" : `#${String(status.next_start_index).padStart(3, "0")}`;
  const counts = status.counts || {};
  $("projectStats").textContent =
    `Фрагментов: ${status.total}. Промптов готово: ${status.generated_count}. Осталось: ${status.missing_count}. ` +
    `Следующий: ${next}. Очередь: ready ${counts.prompt_ready || 0}, submitted ${counts.submitted || 0}, downloaded ${counts.downloaded || 0}. ` +
    `MP4: ${status.mp4_count || 0}.`;
}

function renderFlowStatus(status) {
  const counts = status.counts || {};
  const browser = status.browser || {};
  const openText = browser.open ? "Flow открыт" : "Flow закрыт";
  const ready = counts.prompt_ready ?? 0;
  const submitted = counts.submitted ?? 0;
  const next = status.next_ready_index === null || status.next_ready_index === undefined
    ? "нет"
    : `#${String(status.next_ready_index).padStart(3, "0")}`;
  $("flowStatus").textContent = `${openText}. Готово к отправке: ${ready}. Отправлено: ${submitted}. Следующий: ${next}.`;
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
    holder.appendChild(makeExtensionActionButton("Начать скачивание", "start_download", "primary"));
    return;
  }
  if (job.pending_action === "start_regen") {
    const count = job.unresolved?.regenerable_count ?? 0;
    holder.appendChild(makeExtensionActionButton(`Регенерировать ${count}`, "start_regen", "primary"));
    holder.appendChild(makeExtensionActionButton("Завершить", "complete"));
    return;
  }
  if (job.pending_action === "complete") {
    holder.appendChild(makeExtensionActionButton("Завершить", "complete"));
  }
}

function renderExtensionControls(job) {
  const active = isExtensionActive(job);
  const visualActive = Boolean(job.visual_job_active);
  $("extensionVisualBtn").disabled = active || visualActive;
  $("extensionStopBtn").disabled = !active;
  renderExtensionActions(job);
}

function renderExtensionStatus(job) {
  const counts = job.counts || {};
  const connected = job.connected_at ? "вкладка подключена" : "ждет вкладку Flow";
  const ready = counts.prompt_ready ?? 0;
  const submitted = counts.submitted ?? 0;
  const downloaded = counts.downloaded ?? 0;
  const blocked = job.visual_job_active ? " Старый visual worker активен." : "";
  $("extensionStatus").textContent =
    `${job.status || "idle"} / ${job.phase || "idle"}: ${connected}. ` +
    `ready ${ready}, submitted ${submitted}, downloaded ${downloaded}.${blocked}`;
}

function formatVisualJobStatus(job) {
  const counts = job.counts || {};
  const lines = [
    `Автовизуал: ${job.status || "idle"} - ${job.phase_label || job.phase || "idle"}`,
    job.message || "",
  ];
  if (job.next_action) lines.push(`Что делать: ${job.next_action}`);
  lines.push(
    `Готово к отправке: ${counts.prompt_ready ?? 0}. ` +
    `Отправлено: ${counts.submitted ?? 0}. Скачано: ${counts.downloaded ?? 0}.`
  );
  const log = (job.log || []).slice(-6).map((item) => `- ${item.message}`);
  if (log.length) {
    lines.push("Последние действия:");
    lines.push(...log);
  }
  return lines.filter(Boolean).join("\n");
}

function formatExtensionStatus(job) {
  const counts = job.counts || {};
  const lines = [
    `Расширение: ${job.status || "idle"} - ${job.phase || "idle"}`,
    job.message || "",
    `Готово к отправке: ${counts.prompt_ready ?? 0}. Отправлено: ${counts.submitted ?? 0}. Скачано: ${counts.downloaded ?? 0}.`,
  ];
  if (job.tab_url) lines.push(`Вкладка: ${job.tab_url}`);
  if (job.pending_action) lines.push(`Ожидает действия: ${job.pending_action}`);
  if (job.unresolved?.total) {
    lines.push(`Нерешено: ${job.unresolved.total}. Можно регенерировать: ${job.unresolved.regenerable_count ?? 0}.`);
  }
  if (job.visual_job_active) lines.push("Старый visual worker активен: сначала остановите его, затем запускайте расширение.");
  const log = (job.log || []).slice(-6).map((item) => `- ${item.message}`);
  if (log.length) {
    lines.push("Последние действия:");
    lines.push(...log);
  }
  return lines.filter(Boolean).join("\n");
}

function formatBlockedPrompts(items) {
  if (!items || !items.length) return "";
  const indexes = items.map((item) => `#${String(item.index).padStart(3, "0")}`).join(", ");
  return `\nFlow unusual activity: ${indexes} возвращены в prompt_ready.`;
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
    option.textContent = "Серии не найдены";
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
    option.textContent = channel.configured ? channel.name : `${channel.name} (без стиля)`;
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

async function selectChannelFolder(refresh = true) {
  const channel = selectedLibraryChannel();
  if (!channel) return;
  populateStyles(channel);
  populateSeries(channel);
  updateProjectFromSelection();
  if (refresh) {
    await refreshProjectStatus(true).catch((err) => setStatus(err.message, true));
    await refreshFlowQueue().catch(() => {});
    await refreshVisualJobStatus(false).catch(() => {});
    await refreshExtensionStatus(false).catch(() => {});
  }
}

async function loadInitial() {
  const health = await api("/api/health");
  $("health").textContent = health.openai_key ? "OPENAI_API_KEY найден" : "OPENAI_API_KEY не найден";
  $("health").style.borderColor = health.openai_key ? "#9bc7aa" : "#d89b93";

  library = await api("/api/library");
  $("libraryRoot").textContent = library.root || "";
  populateChannelFolders();
  await selectChannelFolder(false);
  await refreshProjectStatus(true).catch((err) => setStatus(err.message, true));
  await refreshFlowQueue().catch(() => {});
  await refreshVisualJobStatus(false).catch(() => {});
  await refreshExtensionStatus(false).catch(() => {});
}

async function preview() {
  setStatus("Читаю sentences.json...");
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
    `Файл прочитан: ${data.sentences_path}\n` +
    `Промпты сохраняются сюда: ${data.prompts_path}\n` +
    `Клипы сохраняются сюда: ${data.clips_dir}\n` +
    `Фрагментов: ${data.total}. Показано: ${data.items.length}.\n` +
    `Статусы: prompt_ready ${counts.prompt_ready || 0}, submitted ${counts.submitted || 0}, downloaded ${counts.downloaded || 0}, failed ${counts.failed || 0}. MP4: ${status.mp4_count || 0}.`
  );
}

async function generateAllPrompts() {
  setBusy(true);
  const batchSize = Math.max(1, Math.min(80, Number($("count").value || 20)));
  const allGenerated = [];
  try {
    let status = await refreshProjectStatus(true);
    if (status.next_start_index === null) {
      setStatus("Все промпты для этого sentences.json уже готовы.");
      return;
    }

    let batchNumber = 1;
    while (status.next_start_index !== null) {
      const startIndex = status.next_start_index;
      const totalBatches = Math.ceil(status.missing_count / batchSize);
      setStatus(
        `Генерирую все промпты: пачка ${batchNumber} из ${totalBatches}, начиная с #${String(startIndex).padStart(3, "0")}.\n` +
        `OpenAI API вызывается порциями по ${batchSize}. Осталось перед пачкой: ${status.missing_count}.`
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
      `Готово. Сгенерировано новых промптов: ${allGenerated.length}.\n` +
      `Все промпты сохранены в veo_prompts.json внутри выбранной папки frames.`
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
    const currentVisualJob = await refreshVisualJobStatus(false);
    if (isVisualJobActive(currentVisualJob)) {
      setStatus(
        `${formatVisualJobStatus(currentVisualJob)}\n\nСначала остановите старый visual worker, потом запускайте режим расширения.`,
        true
      );
      return;
    }

    let projectUrl = $("flowProjectUrl").value.trim();
    if (!projectUrl) {
      projectUrl = await ensureFlowProjectUrl();
    }
    if (!projectUrl) {
      setStatus("Сначала откройте нужный проект в Flow и зафиксируйте URL.", true);
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
      `${formatExtensionStatus(job)}\n\nОткройте этот Flow проект в обычном браузере с установленным расширением. Расширение подхватит запуск само.`
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
  setStatus("Останавливаю режим расширения после текущего действия...");
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
  refreshProjectStatus(true).catch((err) => setStatus(err.message, true));
  refreshFlowQueue().catch(() => {});
  refreshExtensionStatus(false).catch(() => {});
});

$("channel").addEventListener("change", () => {
  applyStyle(selectedStyle());
});

$("projectPath").addEventListener("change", () => {
  loadFlowProjectUrl();
  refreshProjectStatus(true).catch((err) => setStatus(err.message, true));
  refreshFlowQueue().catch(() => {});
  refreshExtensionStatus(false).catch(() => {});
});

$("flowProjectUrl").addEventListener("change", () => {
  saveFlowProjectUrlForProject($("flowProjectUrl").value.trim()).catch((err) => setStatus(err.message, true));
});

$("previewBtn").addEventListener("click", () => {
  preview().catch((err) => setStatus(err.message, true));
});
$("generateAllBtn").addEventListener("click", generateAllPrompts);
$("extensionVisualBtn").addEventListener("click", startExtensionGeneration);
$("extensionStopBtn").addEventListener("click", stopExtensionGeneration);

loadInitial().catch((err) => setStatus(err.message, true));
