const state = {
  configs: [],
  config: null,
  prompts: {},
  activePrompt: "step1",
  inputVideo: "",
  jobId: null,
  pollTimer: null,
};

const promptLabels = {
  step1: "Step 1 剧本",
  step2: "Step 2 规划",
  step3_asset: "Step 3 素材",
  step3_reference: "Step 3 参考",
  step4: "Step 4 视频",
};

const el = (id) => document.getElementById(id);

document.addEventListener("DOMContentLoaded", async () => {
  bindEvents();
  await loadConfigs();
});

function bindEvents() {
  document.querySelectorAll(".tabs button").forEach((button) => {
    button.addEventListener("click", () => switchTab(button.dataset.tab));
  });
  el("configSelect").addEventListener("change", () => loadConfig(el("configSelect").value));
  el("videoFile").addEventListener("change", uploadVideo);
  el("saveBtn").addEventListener("click", saveConfig);
  el("runBtn").addEventListener("click", runPipeline);
  el("refreshResultsBtn").addEventListener("click", loadResults);
  el("promptEditor").addEventListener("input", () => {
    state.prompts[state.activePrompt] = el("promptEditor").value;
  });
}

async function loadConfigs() {
  const payload = await api("/api/configs");
  state.configs = payload.configs || [];
  el("configSelect").innerHTML = state.configs
    .map((item) => `<option value="${escapeAttr(item.path)}">${escapeHtml(item.video_name)} - ${escapeHtml(item.name)}</option>`)
    .join("");
  if (state.configs[0]) {
    await loadConfig(state.configs[0].path);
  }
}

async function loadConfig(configPath) {
  const payload = await api(`/api/config?config=${encodeURIComponent(configPath)}`);
  state.config = payload;
  state.inputVideo = payload.input_video || "";
  el("configSelect").value = payload.config_path;
  el("videoName").value = payload.video_name || "";
  el("aspectRatio").value = payload.aspect_ratio || "";
  el("userQuery").value = payload.user_query || "";
  el("inputVideoPath").textContent = state.inputVideo ? `当前输入视频：${state.inputVideo}` : "尚未设置输入视频";
  el("subtitle").textContent = payload.config_path;
  renderModels(payload.providers || []);
  renderPrompts(payload.prompts || {});
  await loadResults();
}

function renderModels(providers) {
  el("modelList").innerHTML = providers
    .map(
      (provider) => `
        <div class="model-row">
          <span>${escapeHtml(provider.label)}</span>
          <input data-model="${escapeAttr(provider.key)}" value="${escapeAttr(provider.model || "")}" />
        </div>
      `,
    )
    .join("");
}

function renderPrompts(prompts) {
  state.prompts = {};
  Object.entries(prompts).forEach(([key, value]) => {
    state.prompts[key] = value.content || "";
  });
  state.activePrompt = Object.keys(state.prompts)[0] || "step1";
  el("promptTabs").innerHTML = Object.keys(state.prompts)
    .map((key) => `<button type="button" data-prompt="${escapeAttr(key)}">${promptLabels[key] || key}</button>`)
    .join("");
  el("promptTabs").querySelectorAll("button").forEach((button) => {
    button.addEventListener("click", () => {
      state.prompts[state.activePrompt] = el("promptEditor").value;
      state.activePrompt = button.dataset.prompt;
      updatePromptEditor();
    });
  });
  updatePromptEditor();
}

function updatePromptEditor() {
  el("promptTabs").querySelectorAll("button").forEach((button) => {
    button.classList.toggle("active", button.dataset.prompt === state.activePrompt);
  });
  el("promptEditor").value = state.prompts[state.activePrompt] || "";
}

async function uploadVideo() {
  const file = el("videoFile").files[0];
  if (!file) return;
  const videoName = el("videoName").value.trim() || file.name.replace(/\.[^.]+$/, "");
  if (!el("videoName").value.trim()) {
    el("videoName").value = videoName;
  }
  const form = new FormData();
  form.append("video", file);
  const payload = await api(`/api/upload-video?video_name=${encodeURIComponent(videoName)}`, {
    method: "POST",
    body: form,
  });
  state.inputVideo = payload.input_video;
  el("inputVideoPath").textContent = `已上传：${payload.input_video}`;
  toast("视频已上传");
}

async function saveConfig() {
  state.prompts[state.activePrompt] = el("promptEditor").value;
  const models = {};
  document.querySelectorAll("[data-model]").forEach((input) => {
    models[input.dataset.model] = input.value.trim();
  });
  const payload = await api("/api/save-config", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      source_config: state.config?.config_path || el("configSelect").value,
      video_name: el("videoName").value.trim(),
      aspect_ratio: el("aspectRatio").value.trim(),
      user_query: el("userQuery").value,
      input_video: state.inputVideo,
      models,
      prompts: state.prompts,
    }),
  });
  toast(`配置已保存：${payload.config_path}`);
  await loadConfigs();
  await loadConfig(payload.config_path);
  return payload.config_path;
}

async function runPipeline() {
  const configPath = await saveConfig();
  const step = el("stepSelect").value;
  const payload = await api("/api/run", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ config: configPath, step }),
  });
  state.jobId = payload.job_id;
  switchTab("logs");
  el("logOutput").textContent = "";
  el("jobStatus").textContent = "运行中";
  startJobPolling();
}

function startJobPolling() {
  if (state.pollTimer) {
    clearInterval(state.pollTimer);
  }
  const poll = async () => {
    if (!state.jobId) return;
    const job = await api(`/api/jobs/${state.jobId}`);
    el("jobStatus").textContent = `${job.status}${job.returncode === null ? "" : ` / ${job.returncode}`}`;
    el("logOutput").textContent = (job.lines || []).join("\n");
    el("logOutput").scrollTop = el("logOutput").scrollHeight;
    if (job.status === "succeeded" || job.status === "failed") {
      clearInterval(state.pollTimer);
      state.pollTimer = null;
      if (job.status === "succeeded") {
        toast("生成完成");
        await loadResults();
      } else {
        toast("生成失败，请看日志", true);
      }
    }
  };
  poll();
  state.pollTimer = setInterval(poll, 2000);
}

async function loadResults() {
  if (!state.config) return;
  const payload = await api(`/api/results?config=${encodeURIComponent(state.config.config_path)}`);
  const assetCount = countAssets(payload.generated_assets);
  const segmentCount = payload.video_segments?.segments?.length || 0;
  el("resultsSummary").textContent = `${payload.video_name || ""} / 素材 ${assetCount} / 分幕 ${segmentCount}`;
  renderScript(payload.script);
  renderAssets(payload.generated_assets);
  renderReferences(payload.generated_assets);
  renderSegments(payload.video_segments);
  renderFinalVideo(payload.final_video);
}

function renderScript(script) {
  el("scriptView").textContent = script ? JSON.stringify(script, null, 2) : "暂无 step1 输出";
}

function renderAssets(payload) {
  const container = el("assetImages");
  if (!payload?.asset_images) {
    container.innerHTML = `<div class="empty">暂无素材图</div>`;
    return;
  }
  const cards = [];
  const groups = [
    ["character_images", "人物"],
    ["scene_images", "场景"],
    ["prop_images", "道具"],
  ];
  groups.forEach(([key, label]) => {
    (payload.asset_images[key] || []).forEach((item) => {
      cards.push(imageCard(item, label, item.name || item.output_path));
    });
  });
  container.innerHTML = cards.join("") || `<div class="empty">暂无素材图</div>`;
}

function renderReferences(payload) {
  const container = el("referenceImages");
  if (!payload?.reference_image_plan) {
    container.innerHTML = `<div class="empty">暂无参考图</div>`;
    return;
  }
  const cards = [];
  payload.reference_image_plan.forEach((segment) => {
    (segment.reference_images || []).forEach((item) => {
      cards.push(imageCard(item, `分幕 ${segment.segment_id}`, item.reference_image_id || item.output_path));
    });
  });
  container.innerHTML = cards.join("") || `<div class="empty">暂无参考图</div>`;
}

function renderSegments(payload) {
  const container = el("segmentVideos");
  if (!payload?.segments?.length) {
    container.innerHTML = `<div class="empty">暂无分幕视频</div>`;
    return;
  }
  container.innerHTML = payload.segments
    .map((item) => {
      if (!item.media_url) {
        return `
          <article class="media-card">
            <div class="media-meta">
              <strong>Segment ${escapeHtml(item.segment_id)}</strong>
              <span>${escapeHtml(item.status || "missing")}</span>
            </div>
          </article>
        `;
      }
      return `
        <article class="media-card">
          <video src="${escapeAttr(item.media_url)}" controls preload="metadata"></video>
          <div class="media-meta">
            <strong>Segment ${escapeHtml(item.segment_id)}</strong>
            <span>${escapeHtml(item.output_path || "")}</span>
          </div>
        </article>
      `;
    })
    .join("");
}

function renderFinalVideo(payload) {
  const container = el("finalVideo");
  if (!payload?.media_url) {
    container.innerHTML = `<div class="empty">暂无成片视频</div>`;
    return;
  }
  container.innerHTML = `
    <video src="${escapeAttr(payload.media_url)}" controls preload="metadata"></video>
    <div class="media-meta">
      <strong>final_video.mp4</strong>
      <span>${escapeHtml(payload.path || "")}</span>
    </div>
  `;
}

function imageCard(item, label, title) {
  if (!item.media_url) {
    return "";
  }
  return `
    <article class="media-card">
      <img src="${escapeAttr(item.media_url)}" alt="${escapeAttr(title || label)}" loading="lazy" />
      <div class="media-meta">
        <strong>${escapeHtml(title || label)}</strong>
        <span>${escapeHtml(label)} · ${escapeHtml(item.status || "ready")}</span>
      </div>
    </article>
  `;
}

function countAssets(payload) {
  if (!payload?.asset_images) return 0;
  return Object.values(payload.asset_images).reduce((total, items) => total + (Array.isArray(items) ? items.length : 0), 0);
}

function switchTab(tab) {
  document.querySelectorAll(".tabs button").forEach((button) => button.classList.toggle("active", button.dataset.tab === tab));
  document.querySelectorAll(".tab-panel").forEach((panel) => panel.classList.toggle("active", panel.id === tab));
}

async function api(url, options = {}) {
  const response = await fetch(url, options);
  const contentType = response.headers.get("Content-Type") || "";
  const payload = contentType.includes("application/json") ? await response.json() : await response.text();
  if (!response.ok) {
    const message = typeof payload === "object" ? payload.error : payload;
    toast(message || "请求失败", true);
    throw new Error(message || "Request failed");
  }
  return payload;
}

function toast(message, isError = false) {
  const node = el("toast");
  node.textContent = message;
  node.classList.toggle("error", isError);
  node.hidden = false;
  clearTimeout(node.timer);
  node.timer = setTimeout(() => {
    node.hidden = true;
  }, 3000);
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function escapeAttr(value) {
  return escapeHtml(value);
}
