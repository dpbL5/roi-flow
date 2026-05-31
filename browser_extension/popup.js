const API = "http://127.0.0.1:8765";
let refreshTimer = null;

const statusLabels = {
  idle: "Đang chờ",
  running: "Đang chạy",
  paused: "Tạm dừng",
  completed: "Hoàn tất",
  stopped: "Đã dừng",
  stopping: "Đang dừng",
  error: "Lỗi",
};

const phaseLabels = {
  idle: "Đang chờ",
  waiting_for_flow_tab: "Chờ tab Flow",
  submitting: "Đang gửi prompt",
  awaiting_download: "Chờ tải xuống",
  downloading: "Đang tải xuống",
  awaiting_regen: "Chờ tạo lại",
  flow_error_wait: "Chờ cảnh báo Flow biến mất",
  wrong_project: "Sai dự án Flow",
  completed: "Hoàn tất",
  stopped: "Đã dừng",
};

function statusLabel(value) {
  return statusLabels[value] || value || "Đang chờ";
}

function phaseLabel(value) {
  return phaseLabels[value] || value || "Đang chờ";
}

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
      el.textContent = `Lỗi thao tác:\n${err.message}`;
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
    actions.appendChild(actionButton("▶ Bắt đầu tải xuống", "start_download"));
    return;
  }

  if (data.pending_action === "start_regen") {
    const count = data.unresolved?.regenerable_count ?? 0;
    actions.appendChild(actionButton(`🔄 Tạo lại ${count}`, "start_regen"));
    actions.appendChild(actionButton("✓ Hoàn tất", "complete"));
    return;
  }

  if (data.pending_action === "complete") {
    actions.appendChild(actionButton("✓ Hoàn tất", "complete"));
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
      `Trạng thái: ${statusLabel(data.status)}`,
      `Pha: ${phaseLabel(data.phase)}`,
      data.message || "",
      `sẵn sàng: ${counts.prompt_ready ?? 0}, đã gửi: ${counts.submitted ?? 0}, đã tải: ${counts.downloaded ?? 0}`,
      data.project_path ? `frames: ${data.project_path}` : "Chưa chọn dự án trong UI local.",
    ].filter(Boolean).join("\n");
    renderActions(data);
  } catch (err) {
    el.textContent = `Server local không khả dụng:\n${err.message}`;
    document.getElementById("actions").replaceChildren();
  }
}

document.getElementById("refresh").addEventListener("click", loadStatus);
loadStatus();
refreshTimer = setInterval(loadStatus, 3000);
window.addEventListener("unload", () => {
  if (refreshTimer) clearInterval(refreshTimer);
});
