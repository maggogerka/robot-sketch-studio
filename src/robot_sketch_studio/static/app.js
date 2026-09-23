const $ = (selector) => document.querySelector(selector);
const input = $("#imageInput");
const dropZone = $("#dropZone");
const processButton = $("#processButton");
const statusBox = $("#status");
const errorBox = $("#error");
let selectedFile = null;
let currentJob = null;
let objectUrls = [];

$("#apiToken").value = sessionStorage.getItem("robotSketchApiToken") || "";
$("#apiToken").addEventListener("input", (event) => {
  sessionStorage.setItem("robotSketchApiToken", event.target.value.trim());
});

function authHeaders() {
  const token = $("#apiToken").value.trim();
  return token ? { Authorization: `Bearer ${token}` } : {};
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
  processButton.disabled = false;
  showError("");
  setStatus("Ready to process", 0, "idle");
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
$("#paper").addEventListener("change", (event) => {
  const custom = event.target.value === "custom";
  $("#pageWidth").disabled = !custom;
  $("#pageHeight").disabled = !custom;
  if (event.target.value === "a4_portrait") [$("#pageWidth").value, $("#pageHeight").value] = [210, 297];
  if (event.target.value === "a4_landscape") [$("#pageWidth").value, $("#pageHeight").value] = [297, 210];
});

function options() {
  return {
    engine: $("#engine").value,
    background: $("#background").value,
    profile: $("#profile").value,
    detail: Number($("#detail").value),
    threshold: Number($("#threshold").value),
    min_line_length_mm: Number($("#minLine").value),
    smoothing: Number($("#smoothing").value),
    paper: $("#paper").value,
    page_width_mm: Number($("#pageWidth").value),
    page_height_mm: Number($("#pageHeight").value),
    margin_mm: Number($("#margin").value),
    stroke_width_mm: Number($("#strokeWidth").value)
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
  const sketchBlob = await artifactBlob("sketch.png");
  const sketchUrl = URL.createObjectURL(sketchBlob);
  objectUrls.push(sketchUrl);
  $("#sketchPreview").src = sketchUrl;

  const svgBlob = await artifactBlob("drawing.svg");
  const svgText = await svgBlob.text();
  $("#svgPreview").innerHTML = svgText;
  const stats = job.stats;
  $("#statStrokes").textContent = stats.stroke_count.toLocaleString();
  $("#statDraw").textContent = `${stats.drawing_length_mm.toFixed(1)} mm`;
  $("#statTravel").textContent = `${stats.travel_length_mm.toFixed(1)} mm`;
  $("#statTime").textContent = `${stats.estimated_time_seconds.toFixed(1)} s`;
  $("#simulateButton").disabled = !stats.stroke_count;
  document.querySelectorAll(".download").forEach((button) => { button.disabled = false; });
  $("#warnings").hidden = !job.warnings.length;
  $("#warnings").textContent = job.warnings.join(" ");
  setStatus("Completed", 100, "done");
}

processButton.addEventListener("click", async () => {
  if (!selectedFile) return;
  processButton.disabled = true;
  showError("");
  setStatus("Uploading", 3, "working");
  try {
    const form = new FormData();
    form.append("image", selectedFile);
    form.append("options", JSON.stringify(options()));
    const response = await fetch("/api/v1/jobs", { method: "POST", headers: authHeaders(), body: form });
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
$("#apiToken").addEventListener("change", refreshModels);
refreshModels();
