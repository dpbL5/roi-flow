const API = "http://127.0.0.1:8765";
let refreshTimer = null;

function actionButton(label, action) {
  const button = document.createElement("button");
  button.type = "button";
  button.textContent = label;
  button.addEventListener("click", async () => {
    button.disabled = true;
    try {
      const response = await fetch(`${API}/api/extension/phase-action`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
      await loadStatus();
    } catch (err) {
      const el = document.getElementById("status");
      el.textContent = `Ошибка действия:\n${err.message}`;
    } finally {
      button.disabled = false;
    }
  });
  return button;
}

function renderActions(data) {
  const actions = document.getElementById("actions");
  actions.replaceChildren();

  if (data.pending_action === "start_download") {
    actions.appendChild(actionButton("▶ Начать скачивание", "start_download"));
    return;
  }

  if (data.pending_action === "start_regen") {
    const count = data.unresolved?.regenerable_count ?? 0;
    actions.appendChild(actionButton(`🔄 Регенерировать ${count}`, "start_regen"));
    actions.appendChild(actionButton("✓ Завершить", "complete"));
    return;
  }

  if (data.pending_action === "complete") {
    actions.appendChild(actionButton("✓ Завершить", "complete"));
  }
}

async function loadStatus() {
  const el = document.getElementById("status");
  try {
    const response = await fetch(`${API}/api/extension/status`);
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
    const counts = data.counts || {};
    el.textContent = [
      `Статус: ${data.status || "idle"}`,
      `Фаза: ${data.phase || "idle"}`,
      data.message || "",
      `ready: ${counts.prompt_ready ?? 0}, submitted: ${counts.submitted ?? 0}, downloaded: ${counts.downloaded ?? 0}`,
      data.project_path ? `frames: ${data.project_path}` : "Проект не выбран в локальном UI.",
    ].filter(Boolean).join("\n");
    renderActions(data);
  } catch (err) {
    el.textContent = `Локальный сервер недоступен:\n${err.message}`;
    document.getElementById("actions").replaceChildren();
  }
}

document.getElementById("refresh").addEventListener("click", loadStatus);
loadStatus();
refreshTimer = setInterval(loadStatus, 3000);
window.addEventListener("unload", () => {
  if (refreshTimer) clearInterval(refreshTimer);
});
