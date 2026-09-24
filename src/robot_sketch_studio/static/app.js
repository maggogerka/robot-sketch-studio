const $ = (selector) => document.querySelector(selector);
const UI_VERSION = "0.3.1";
const input = $("#imageInput");
const dropZone = $("#dropZone");
const processButton = $("#processButton");
const statusBox = $("#status");
const errorBox = $("#error");
let selectedFile = null;
let currentJob = null;
let objectUrls = [];
let previewUrls = {};
let backendReady = false;
let backendError = "Checking backend compatibility...";

function updateProcessAvailability() {
  processButton.disabled = !selectedFile || !backendReady;
}

$("#apiToken").value = sessionStorage.getItem("robotSketchApiToken") || "";
$("#apiToken").addEventListener("input", (event) => {
  sessionStorage.setItem("robotSketchApiToken", event.target.value.trim());
});
$("#remoteApiKey").value = sessionStorage.getItem("robotSketchRemoteApiKey") || "";
$("#remoteApiKey").addEventListener("input", (event) => {
  sessionStorage.setItem("robotSketchRemoteApiKey", event.target.value.trim());
});
$("#remoteUrl").value = localStorage.getItem("robotSketchRemoteUrl") || "";
$("#remoteModel").value = localStorage.getItem("robotSketchRemoteModel") || "";
$("#remoteBackend").value = localStorage.getItem("robotSketchRemoteBackend") || "openai_images";
$("#remoteUrl").addEventListener("change", (event) => {
  localStorage.setItem("robotSketchRemoteUrl", event.target.value.trim());
});
$("#remoteModel").addEventListener("change", (event) => {
  localStorage.setItem("robotSketchRemoteModel", event.target.value.trim());
});
$("#remoteBackend").addEventListener("change", (event) => {
  localStorage.setItem("robotSketchRemoteBackend", event.target.value);
});

function authHeaders() {
  const token = $("#apiToken").value.trim();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

function remoteHeaders() {
  const key = $("#remoteApiKey").value.trim();
  return key ? { "X-Remote-API-Key": key } : {};
}

function setStatus(message, progress = 0, state = "working") {
  statusBox.className = `status ${state}`;
  statusBox.querySelector("span").textContent = message;
  statusBox.querySelector("b").textContent = `${progress}%`;
}

function showError(message) {
  errorBox.textContent = message;
  errorBox.hidden = !message;
  if (message) setStatus("Processing failed", 100, "failed");
}

function selectFile(file) {
  if (!file) return;
  if (!/^image\/(jpeg|png|webp)$/.test(file.type)) {
    showError("Choose a JPG, PNG, or WebP image.");
    return;
  }
  selectedFile = file;
  $("#fileName").textContent = file.name;
  $("#sourcePreview").src = URL.createObjectURL(file);
  updateProcessAvailability();
  showError(backendReady ? "" : backendError);
  if (backendReady) setStatus("Ready to process", 0, "idle");
}

input.addEventListener("change", () => selectFile(input.files[0]));
dropZone.addEventListener("keydown", (event) => {
  if (event.key === "Enter" || event.key === " ") input.click();
});
["dragenter", "dragover"].forEach((name) => dropZone.addEventListener(name, (event) => {
  event.preventDefault();
  dropZone.classList.add("dragging");
}));
["dragleave", "drop"].forEach((name) => dropZone.addEventListener(name, (event) => {
  event.preventDefault();
  dropZone.classList.remove("dragging");
}));
dropZone.addEventListener("drop", (event) => selectFile(event.dataTransfer.files[0]));

for (const name of ["detail", "threshold"]) {
  $(`#${name}`).addEventListener("input", (event) => {
    $(`#${name}Value`).value = event.target.value;
  });
}
$("#coverage").addEventListener("input", (event) => {
  $("#coverageValue").value = `${event.target.value}%`;
});
$("#paper").addEventListener("change", (event) => {
  const custom = event.target.value === "custom";
  $("#pageWidth").disabled = !custom;
  $("#pageHeight").disabled = !custom;
  if (event.target.value === "a4_portrait") [$("#pageWidth").value, $("#pageHeight").value] = [210, 297];
  if (event.target.value === "a4_landscape") [$("#pageWidth").value, $("#pageHeight").value] = [297, 210];
});

const presets = {
  dexarm_fidelity: { vectorMode: "plotter_fidelity", penWidth: 0.5, coverage: 97, fillStrategy: "contour", minPath: 0.25, joinDistance: 0.35, joinAngle: 25, minFeature: 0.15, curveTolerance: 0.08, maxPlotterPaths: 3000 },
  minimal: { vectorMode: "minimal", targetPaths: 16, minPath: 4, joinDistance: 2, joinAngle: 20, minFeature: 1.2, curveTolerance: 0.5 },
  balanced: { vectorMode: "centerline", targetPaths: 32, minPath: 2.5, joinDistance: 1.5, joinAngle: 25, minFeature: 0.8, curveTolerance: 0.3 },
  detailed: { vectorMode: "centerline", targetPaths: 64, minPath: 1.5, joinDistance: 1, joinAngle: 30, minFeature: 0.5, curveTolerance: 0.2 }
};

function applyPreset(name) {
  const values = presets[name];
  if (!values) return;
  Object.entries(values).forEach(([id, value]) => {
    document.querySelector("#" + id).value = value;
  });
  $("#coverageValue").value = `${$("#coverage").value}%`;
  updateVectorMode();
}

$("#drawingPreset").addEventListener("change", (event) => applyPreset(event.target.value));
function updateVectorMode() {
  const fidelity = $("#vectorMode").value === "plotter_fidelity";
  const minimal = $("#vectorMode").value === "minimal";
  $("#targetPaths").disabled = !minimal;
  $("#targetPathsField").classList.toggle("disabled-field", !minimal);
  $("#targetPathsHint").textContent = fidelity
    ? "Количество траекторий определяется автоматически для сохранения рисунка."
    : minimal
      ? "Жёсткий предел для художественного упрощения."
      : "В режиме центральных линий ограничение не применяется.";
  $("#fillStrategy").disabled = !fidelity;
  $("#maxPlotterPaths").disabled = !fidelity;
}
$("#vectorMode").addEventListener("change", updateVectorMode);
updateVectorMode();
$("#engine").addEventListener("change", (event) => {
  $("#remoteSettings").hidden = event.target.value !== "artistic_remote";
});

function options() {
  return {
    engine: $("#engine").value,
    background: $("#background").value,
    profile: $("#profile").value,
    drawing_preset: $("#drawingPreset").value,
    vectorization_mode: $("#vectorMode").value,
    detail: Number($("#detail").value),
    threshold: Number($("#threshold").value),
    target_paths: Number($("#targetPaths").value),
    pen_width_mm: Number($("#penWidth").value),
    ink_coverage_target: Number($("#coverage").value) / 100,
    fill_strategy: $("#fillStrategy").value,
    maximum_plotter_paths: Number($("#maxPlotterPaths").value),
    preserve_short_details: true,
    generate_difference_preview: true,
    minimum_path_length_mm: Number($("#minPath").value),
    join_distance_mm: Number($("#joinDistance").value),
    maximum_join_angle_deg: Number($("#joinAngle").value),
    minimum_feature_size_mm: Number($("#minFeature").value),
    curve_fit_tolerance_mm: Number($("#curveTolerance").value),
    paper: $("#paper").value,
    page_width_mm: Number($("#pageWidth").value),
    page_height_mm: Number($("#pageHeight").value),
    margin_mm: Number($("#margin").value),
    stroke_width_mm: Number($("#penWidth").value),
    remote_backend: $("#remoteBackend").value,
    remote_url: $("#engine").value === "artistic_remote" ? $("#remoteUrl").value.trim() : null,
    remote_model: $("#remoteModel").value.trim() || null
  };
}

async function apiError(response) {
  try {
    const body = await response.json();
    return typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
  } catch (_) {
    return `Request failed (${response.status})`;
  }
}

async function verifyBackend() {
  backendReady = false;
  updateProcessAvailability();
  try {
    const response = await fetch("/api/v1/capabilities", {
      cache: "no-store",
      headers: authHeaders()
    });
    if (!response.ok) throw new Error(await apiError(response));
    const capabilities = await response.json();
    const presets = capabilities.drawing_presets || [];
    const modes = capabilities.vectorization_modes || [];
    if (!presets.includes("dexarm_fidelity") || !modes.includes("plotter_fidelity")) {
      throw new Error(
        `Interface v${UI_VERSION} is connected to backend v${capabilities.version || "unknown"}. ` +
        "Close the old Robot Sketch Studio process, start v0.3.1, then press Ctrl+F5."
      );
    }
    backendReady = true;
    backendError = "";
    showError("");
    updateProcessAvailability();
    if (selectedFile) setStatus("Ready to process", 0, "idle");
  } catch (error) {
    backendError = error.message || String(error);
    showError(backendError);
  }
}

function modelCard(item) {
  const card = document.createElement("article");
  card.className = "model-card";
  const title = document.createElement("h3");
  title.textContent = item.name;
  const description = document.createElement("p");
  description.textContent = item.description;
  const meta = document.createElement("small");
  const dependency = item.dependency_available ? "dependency ready" : "dependency missing";
  meta.textContent = `${item.status.replace("_", " ")} · ${dependency} · ${item.license}`;
  const hint = document.createElement("code");
  hint.textContent = item.install_hint;
  const button = document.createElement("button");
  button.type = "button";
  button.dataset.modelId = item.id;
  button.disabled = item.status === "installed" || item.status === "downloading";
  button.textContent = item.status === "installed"
    ? "Installed"
    : item.status === "downloading"
      ? `Downloading ${item.progress}%`
      : "Download weights";
  if (item.error) {
    const error = document.createElement("b");
    error.textContent = item.error;
    card.append(title, description, meta, hint, error, button);
  } else {
    card.append(title, description, meta, hint, button);
  }
  button.addEventListener("click", () => downloadModel(item.id));
  return card;
}

async function refreshModels() {
  const list = $("#modelList");
  try {
    const response = await fetch("/api/v1/models", { headers: authHeaders() });
    if (!response.ok) throw new Error(await apiError(response));
    const body = await response.json();
    list.replaceChildren(...body.models.map(modelCard));
    return body.models;
  } catch (error) {
    list.textContent = `Model status unavailable: ${error.message || error}`;
    return [];
  }
}

async function downloadModel(modelId) {
  try {
    const response = await fetch(`/api/v1/models/${modelId}/download`, {
      method: "POST",
      headers: authHeaders()
    });
    if (!response.ok) throw new Error(await apiError(response));
    for (;;) {
      const models = await refreshModels();
      const current = models.find((item) => item.id === modelId);
      if (!current || current.status !== "downloading") break;
      await new Promise((resolve) => setTimeout(resolve, 700));
    }
  } catch (error) {
    $("#modelList").textContent = `Model download failed: ${error.message || error}`;
  }
}

$("#testRemote").addEventListener("click", async () => {
  const indicator = $("#remoteStatus");
  indicator.className = "";
  indicator.textContent = "Connecting…";
  try {
    const response = await fetch("/api/v1/remote/test", {
      method: "POST",
      headers: {
        ...authHeaders(),
        ...remoteHeaders(),
        "Content-Type": "application/json"
      },
      body: JSON.stringify({
        backend: $("#remoteBackend").value,
        url: $("#remoteUrl").value.trim(),
        model: $("#remoteModel").value.trim() || null
      })
    });
    if (!response.ok) throw new Error(await apiError(response));
    indicator.className = "ok";
    indicator.textContent = "Connection successful.";
  } catch (error) {
    indicator.className = "failed";
    indicator.textContent = error.message || String(error);
  }
});

async function pollJob(jobId) {
  for (;;) {
    await new Promise((resolve) => setTimeout(resolve, 450));
    const response = await fetch(`/api/v1/jobs/${jobId}`, { headers: authHeaders() });
    if (!response.ok) throw new Error(await apiError(response));
    const job = await response.json();
    setStatus(job.message, job.progress, "working");
    if (job.state === "failed") throw new Error(job.error || "Processing failed");
    if (job.state === "completed") return job;
  }
}

async function artifactBlob(name) {
  const response = await fetch(`/api/v1/jobs/${currentJob.id}/artifacts/${name}`, { headers: authHeaders() });
  if (!response.ok) throw new Error(await apiError(response));
  return response.blob();
}

async function showResult(job) {
  currentJob = job;
  objectUrls.forEach(URL.revokeObjectURL);
  objectUrls = [];
  const [sketchBlob, vectorBlob, differenceBlob, svgBlob] = await Promise.all([
    artifactBlob("sketch.png"),
    artifactBlob("vector-preview.png"),
    artifactBlob("difference-overlay.png"),
    artifactBlob("drawing.svg")
  ]);
  previewUrls = {
    sketch: URL.createObjectURL(sketchBlob),
    vector: URL.createObjectURL(vectorBlob),
    difference: URL.createObjectURL(differenceBlob)
  };
  objectUrls.push(...Object.values(previewUrls));
  $("#sketchPreview").src = previewUrls.sketch;
  $("#resultPreview").src = previewUrls.vector;
  const svgText = await svgBlob.text();
  $("#svgPreview").innerHTML = svgText;
  const stats = job.stats;
  $("#statStrokes").textContent = stats.stroke_count.toLocaleString();
  $("#statDraw").textContent = `${stats.drawing_length_mm.toFixed(1)} mm`;
  $("#statTravel").textContent = `${stats.travel_length_mm.toFixed(1)} mm`;
  $("#statTime").textContent = `${stats.estimated_time_seconds.toFixed(1)} s`;
  $("#statSimilarity").textContent = `${(stats.ink_iou * 100).toFixed(1)}%`;
  $("#statRecall").textContent = `${(stats.ink_recall * 100).toFixed(1)}%`;
  $("#statExtra").textContent = `${((1 - stats.ink_precision) * 100).toFixed(1)}%`;
  $("#statLifts").textContent = stats.pen_lifts.toLocaleString();
  $("#simulateButton").disabled = !stats.stroke_count;
  document.querySelectorAll(".download").forEach((button) => { button.disabled = false; });
  $("#warnings").hidden = !job.warnings.length;
  $("#warnings").textContent = job.warnings.join(" ");
  setStatus("Completed", 100, "done");
}

document.querySelectorAll("[data-preview]").forEach((button) => button.addEventListener("click", () => {
  const url = previewUrls[button.dataset.preview];
  if (!url) return;
  $("#resultRaster").hidden = false;
  $("#svgPreview").hidden = true;
  $("#resultPreview").src = url;
  document.querySelectorAll("[data-preview]").forEach((item) => item.classList.remove("active"));
  button.classList.add("active");
}));

processButton.addEventListener("click", async () => {
  if (!selectedFile) return;
  processButton.disabled = true;
  showError("");
  setStatus("Uploading", 3, "working");
  try {
    const form = new FormData();
    form.append("image", selectedFile);
    form.append("options", JSON.stringify(options()));
    const headers = {
      ...authHeaders(),
      ...($("#engine").value === "artistic_remote" ? remoteHeaders() : {})
    };
    const response = await fetch("/api/v1/jobs", { method: "POST", headers, body: form });
    if (!response.ok) throw new Error(await apiError(response));
    const created = await response.json();
    await showResult(await pollJob(created.id));
  } catch (error) {
    showError(error.message || String(error));
  } finally {
    processButton.disabled = false;
  }
});

document.querySelectorAll(".download").forEach((button) => button.addEventListener("click", async () => {
  try {
    const name = button.dataset.file;
    const blob = await artifactBlob(name);
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = name;
    anchor.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  } catch (error) {
    showError(error.message || String(error));
  }
}));

$("#simulateButton").addEventListener("click", () => {
  $("#resultRaster").hidden = true;
  $("#svgPreview").hidden = false;
  const paths = [...document.querySelectorAll("#svgPreview path")];
  let delay = 0;
  paths.forEach((path) => {
    const length = path.getTotalLength();
    path.getAnimations().forEach((animation) => animation.cancel());
    path.style.strokeDasharray = `${length}`;
    path.style.strokeDashoffset = `${length}`;
    const duration = Math.max(90, Math.min(850, length * 5));
    path.animate(
      [{ strokeDashoffset: length }, { strokeDashoffset: 0 }],
      { duration, delay, fill: "forwards", easing: "linear" }
    );
    delay += duration;
  });
});

$("#refreshModels").addEventListener("click", refreshModels);
$("#apiToken").addEventListener("change", () => {
  verifyBackend();
  refreshModels();
});
verifyBackend();
refreshModels();
