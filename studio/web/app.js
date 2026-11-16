// SPDX-FileCopyrightText: 2026 Panini-Animgx contributors
// SPDX-License-Identifier: MIT
"use strict";

const $ = (id) => document.getElementById(id);
const setText = (id, value) => { if ($(id).textContent !== value) $(id).textContent = value; };
const mathVisuals = new Set(["equation", "graph", "geometry", "calculus", "vectors"]);
const visuals = new Set(["composition", ...mathVisuals]);
const visualNames = { composition: "Custom composition", equation: "Equation steps", graph: "Function graph", geometry: "Right triangle", calculus: "Calculus", vectors: "Vector addition" };
const draftKey = "panini-animgx-studio-draft-v2";
const obsoleteDraftKeys = ["panini-animgx-studio-draft-v1", "panini-animgx-studio-retained-projects-v1"];
const runtimeProtocol = 2;
const restartMessage = "Studio was updated. Stop the running terminal with Ctrl+C, run .\\panini.cmd again, then refresh this page. Enter session API keys again after restarting.";
const settingsKey = "panini-animgx-studio-settings-v1";
const clone = (value) => JSON.parse(JSON.stringify(value));

let plan = { title: "Untitled video", mode: "math", scenes: [] };
let draftOrigin = "new";
let draftSource = "manual";
let runtimeReady = false;
let draftBrief = { prompt: "", mode: "math", duration: "30" };
let planningState = null;
let previousDraft = false;
let selectedScene = 0;
let busy = false;
let checkingStatus = false;
let services = { ollama: { connected: false, models: [], error: "Checking local services." }, engine: { available: false }, voices: [] };
let renderedFingerprint = null;
let activeRenderId = null;
let statusLoaded = false;
let saveTimer;
let busyKind = null;
let adminBusy = false;
let dialogOpener = null;
let toastTimer;
let providerTestController = null;
let previousProvider = "ollama";
let musicScoreError = "";
let musicScoreDraft = null;
const compositionEdits = new WeakMap();
const durationEdits = new WeakMap();
const equationEdits = new WeakMap();
const providerIds = new Set(["ollama", "openai", "gemini", "compatible"]);
const providerDefaults = [
  { id: "ollama", name: "Ollama", model: "", base_url: "http://127.0.0.1:11434", configured: true, key_set: false, scope: "local", requires_key: false },
  { id: "openai", name: "OpenAI", model: "", base_url: "", configured: false, key_set: false, scope: "cloud", requires_key: true },
  { id: "gemini", name: "Google Gemini", model: "", base_url: "", configured: false, key_set: false, scope: "cloud", requires_key: true },
  { id: "compatible", name: "Compatible API", model: "", base_url: "", configured: false, key_set: false, scope: "cloud", requires_key: true },
];
let providerSettings = { active_provider: "ollama", providers: clone(providerDefaults) };
const modelChoices = {};

function providerInfo(id) {
  return providerSettings.providers.find((item) => item.id === id) || providerDefaults.find((item) => item.id === id) || providerDefaults[0];
}

function selectedProvider() {
  return providerIds.has($("plannerProvider").value) ? $("plannerProvider").value : "ollama";
}

function planningPayload() {
  const provider = selectedProvider();
  return { prompt: $("prompt").value.trim(), provider, model: (provider === "ollama" ? $("model").value : $("cloudModel").value).trim(), mode: mode(), duration: Number($("duration").value) };
}

function adminSettingsPayload(activate = false) {
  const provider = $("adminProvider").value;
  const result = { provider, model: $("adminModel").value.trim() };
  if (provider === "compatible") result.base_url = $("adminBaseUrl").value.trim();
  const key = $("adminApiKey").value.trim();
  if (key && provider !== "ollama") result.api_key = key;
  if (activate) result.active_provider = provider;
  return result;
}

function showToast(message) {
  clearTimeout(toastTimer);
  $("toastText").textContent = message;
  $("toast").hidden = false;
  toastTimer = setTimeout(() => { $("toast").hidden = true; }, 3600);
}

function adoptProviderSettings(value, preferred) {
  if (!value || !Array.isArray(value.providers)) return;
  // Only public metadata enters browser state; API keys never return from the server.
  providerSettings = { active_provider: providerIds.has(value.active_provider) ? value.active_provider : "ollama", providers: value.providers.filter((item) => providerIds.has(item.id)).map((item) => ({ id: item.id, name: String(item.name || item.id), model: String(item.model || ""), base_url: String(item.base_url || ""), configured: !!item.configured, key_set: !!item.key_set, key_source: String(item.key_source || ""), scope: item.scope === "local" ? "local" : "cloud", requires_key: !!item.requires_key })), key_notice: typeof value.key_notice === "string" ? value.key_notice : "" };
  $("plannerProvider").value = providerIds.has(preferred) ? preferred : providerSettings.active_provider;
  if (providerSettings.key_notice) $("keyNotice").querySelector("span").textContent = providerSettings.key_notice;
  updatePlanner();
}

function updatePlanner() {
  const id = selectedProvider();
  previousProvider = id;
  const info = providerInfo(id);
  const local = id === "ollama";
  $("model").hidden = !local;
  $("cloudModel").hidden = local;
  $("modelLabel").htmlFor = local ? "model" : "cloudModel";
  $("modelLabel").textContent = local ? "Ollama model" : `${info.name} model ID`;
  if (!local) $("cloudModel").value = modelChoices[id] || info.model;
  $("providerNotice").textContent = info.scope === "local" ? "Your brief stays on this PC. Rendering, voice, and music also run locally." : `Planning sends your brief to ${info.name} and may incur API charges. Rendering, voice, and music stay on this PC.`;
  $("providerNotice").classList.toggle("cloud-notice", info.scope !== "local");
  $("modelHint").textContent = local ? !services.ollama.connected ? services.ollama.error || "Start Ollama, then refresh. You can add your own scenes without a model." : services.ollama.models.length ? "Choose an installed model. Smaller models usually plan faster." : "Install a model in Ollama, then refresh. You can add and render your own scenes." : !info.configured ? "Add the provider’s model and connection settings in Admin settings to start planning." : "Use a model ID supported by your provider. Admin settings can test the connection.";
  serviceBadge("ollamaStatus", local ? services.ollama.connected : info.configured, local ? services.ollama.connected ? "Ollama connected" : "Ollama offline" : `${info.name} ${info.configured ? "configured" : "needs setup"}`, local ? services.ollama.error : "Configured does not confirm connectivity. Test in Admin settings.");
  updateButtons();
}

function populateAdmin() {
  const id = $("adminProvider").value;
  const info = providerInfo(id);
  $("adminModel").value = info.model || (id === "ollama" ? $("model").value : "");
  $("adminModel").required = id !== "compatible";
  $("adminBaseUrl").value = info.base_url;
  $("baseUrlField").hidden = id !== "compatible";
  $("adminBaseUrl").required = id === "compatible";
  $("apiKeyField").hidden = id === "ollama";
  $("adminKeyLabel").textContent = info.requires_key ? "API key" : "API key · optional";
  $("adminApiKey").value = "";
  hideApiKey();
  $("keyState").textContent = info.key_set ? `Key configured${info.key_source === "environment" || info.key_source === "env" ? " from an environment variable" : " for this server run"}` : info.requires_key ? "No key configured" : "No key required";
  $("clearKey").disabled = !info.key_set || adminBusy;
  $("adminScope").textContent = info.scope === "local" ? "Local planning. Your brief stays on this computer." : "Cloud planning sends your brief to this provider. API charges may apply. Video rendering stays local.";
  $("adminModelHint").textContent = id === "ollama" ? "Use a model installed in Ollama." : id === "compatible" ? "Test connection to discover models, then choose an exact model ID before planning." : "Enter an exact model ID supported by your provider. Test connection can list available models.";
  $("adminFeedback").hidden = true;
}

function hideApiKey() {
  $("adminApiKey").type = "password";
  $("toggleKey").textContent = "Show";
  $("toggleKey").setAttribute("aria-label", "Show API key");
  $("toggleKey").setAttribute("aria-pressed", "false");
}

function setAdminBusy(value, button) {
  adminBusy = value;
  $("adminForm").setAttribute("aria-busy", String(value));
  $("adminForm").querySelectorAll("input, select, button").forEach((item) => { item.disabled = value; });
  for (const id of ["testProvider", "saveProvider", "clearKey"]) $(id).classList.toggle("loading", value && id === button);
  if (!value) $("clearKey").disabled = !providerInfo($("adminProvider").value).key_set;
  if (!value && button && $("adminDialog").open) {
    const target = $(button).disabled ? $("adminApiKey") : $(button);
    target.focus();
  }
}

function adminFeedback(message, success = false) {
  $("adminFeedback").hidden = false;
  $("adminFeedback").textContent = message;
  $("adminFeedback").classList.toggle("success", success);
}

function closeProfile(restoreFocus = false) {
  $("profileMenu").hidden = true;
  $("profileButton").setAttribute("aria-expanded", "false");
  if (restoreFocus) $("profileButton").focus();
}

async function openAdmin(opener) {
  dialogOpener = opener.id === "openAdmin" ? $("profileButton") : opener;
  closeProfile();
  $("adminProvider").value = selectedProvider();
  populateAdmin();
  const original = JSON.stringify({ provider: $("adminProvider").value, model: $("adminModel").value, base_url: $("adminBaseUrl").value });
  $("adminDialog").showModal();
  try {
    const result = await api("/api/settings");
    adoptProviderSettings(result, selectedProvider());
    if (!adminBusy && !$("adminApiKey").value && original === JSON.stringify({ provider: $("adminProvider").value, model: $("adminModel").value, base_url: $("adminBaseUrl").value })) populateAdmin();
  } catch (error) { adminFeedback(error.message); }
}

const workflowDetails = {
  plan: { scope: "Local or cloud", title: "A model turns your idea into scenes", text: "It suggests narration, text, equations, vector shapes, coordinates, colors, animation timing, and a music score. Cloud planning sends your brief to the selected provider and can incur API charges. Ollama runs locally." },
  review: { scope: "You are in control", title: "Review and shape the storyboard", text: "Edit each composition’s content and timeline, check the math and narration, reorder scenes, and change the music score. The model’s output is a draft. Examples load only when you choose one." },
  animate: { scope: "On this PC", title: "Your repository builds real animations", text: "Studio validates your scene descriptions, then ManimGX typesets your text and equations, draws the supplied geometry, and follows each element’s animation timeline. The native engine draws frames on your GPU." },
  sound: { scope: "On this PC", title: "Local voices and music bring it together", text: "The renderer narrates your words with installed Windows voices, adjusts scene lengths to fit speech, and synthesizes the reviewed music score at your chosen volume." },
  export: { scope: "Your local files", title: "Preview, download, and keep creating", text: "The engine encodes an MP4. Studio saves the video and subtitle files in this repository’s local output folder. Review the preview, edit your scenes, and render again whenever you like." },
};

function showWorkflowStep(step) {
  const detail = workflowDetails[step];
  if (!detail) return;
  setText("howScope", detail.scope);
  setText("howStepTitle", detail.title);
  setText("howStepText", detail.text);
  document.querySelectorAll("[data-how-step]").forEach((button) => button.setAttribute("aria-pressed", String(button.dataset.howStep === step)));
}

function openHow(opener) {
  dialogOpener = opener.id === "openHow" ? $("profileButton") : opener;
  closeProfile();
  $("howDialog").showModal();
}

function validColor(value, fallback) {
  return typeof value === "string" && /^#[0-9a-fA-F]{6}$/.test(value) ? value.toLowerCase() : fallback;
}

function sceneForeground(background) {
  const channels = [1, 3, 5].map((offset) => {
    const value = parseInt(background.slice(offset, offset + 2), 16) / 255;
    return value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
  });
  const luminance = channels[0] * 0.2126 + channels[1] * 0.7152 + channels[2] * 0.0722;
  return luminance > 0.3 ? "#18332e" : "#ffffff";
}

function renderOptions() {
  return { voice_enabled: $("voiceEnabled").checked, voice: $("voice").value, music_enabled: $("musicEnabled").checked, music_volume: Number($("musicVolume").value), quality: $("quality").value };
}

function validateMath(visual, value) {
  if (!mathVisuals.has(visual)) return undefined;
  const math = value;
  if (!math || typeof math !== "object" || Array.isArray(math)) throw new Error("Math settings must contain the values for the selected visual.");
  if (visual === "equation") {
    if (!Array.isArray(math.equations) || math.equations.length < 1 || math.equations.length > 6 || math.equations.some((line) => typeof line !== "string" || !line.trim() || line.length > 200)) {
      throw new Error("Use 1–6 equation steps, one LaTeX expression per line, with up to 200 characters each.");
    }
    return { equations: math.equations.map((line) => line.trim()) };
  }
  if (visual === "graph" || visual === "calculus") {
    const expression = math.expression;
    const tokens = typeof expression === "string" ? expression.match(/\d+(?:\.\d*)?(?:[eE][+-]?\d+)?|\.\d+(?:[eE][+-]?\d+)?|[A-Za-z_][A-Za-z_0-9]*/g) || [] : [];
    const names = tokens.filter((token) => /^[A-Za-z_]/.test(token));
    if (typeof expression !== "string" || !expression.trim() || expression.length > 120 || !/^[\dA-Za-z_\s.+*/()\-]+$/.test(expression) || names.some((name) => !["x", "sin", "cos", "tan", "sqrt", "exp", "log", "abs", "pi", "e"].includes(name))) {
      throw new Error("Use a function such as x**2 or sin(x), with x, pi, e, arithmetic, and supported function names.");
    }
    const result = { expression: expression.trim() };
    for (const axis of ["x", "y"]) {
      const min = math[`${axis}_min`];
      const max = math[`${axis}_max`];
      if (!Number.isFinite(min) || !Number.isFinite(max) || min < -20 || max > 20 || max - min < 0.1 - 1e-10) {
        throw new Error(`${axis.toUpperCase()} axis limits must be between −20 and 20, with the maximum at least 0.1 above the minimum.`);
      }
      result[`${axis}_min`] = min;
      result[`${axis}_max`] = max;
    }
    if (visual === "calculus") {
      if (!["derivative", "integral"].includes(math.operation)) throw new Error("Choose a derivative or an integral for the calculus scene.");
      if (math.operation === "integral" && (math.y_min > 0 || math.y_max < 0)) throw new Error("For an integral, include zero in the Y axis limits so the shaded area can meet the baseline.");
      result.operation = math.operation;
    }
    return result;
  }
  const fields = visual === "geometry" ? ["a", "b"] : ["ax", "ay", "bx", "by"];
  const [min, max] = visual === "geometry" ? [0.01, 10000] : [-4, 4];
  const result = {};
  for (const field of fields) {
    if (!Number.isFinite(math[field]) || math[field] < min || math[field] > max) throw new Error(`Keep ${visual === "geometry" ? "triangle sides between 0.01 and 10000" : "vector components between −4 and 4"}.`);
    result[field] = math[field];
  }
  return result;
}

const compositionKinds = new Set(["text", "equation", "rectangle", "circle", "line", "arrow", "polygon"]);
const compositionFields = {
  text: ["x", "y", "color", "font_size", "text"],
  equation: ["x", "y", "color", "font_size", "text"],
  rectangle: ["x", "y", "color", "fill_color", "fill_opacity", "stroke_width", "width", "height"],
  circle: ["x", "y", "color", "fill_color", "fill_opacity", "stroke_width", "radius"],
  line: ["color", "stroke_width", "points"],
  arrow: ["color", "stroke_width", "points"],
  polygon: ["color", "fill_color", "fill_opacity", "stroke_width", "points"],
};

function compositionObject(value, allowed, name) {
  if (!value || typeof value !== "object" || Array.isArray(value) || Object.keys(value).some((key) => !allowed.includes(key))) throw new Error(`${name} contains an unsupported field or must be a JSON object.`);
  return value;
}

function compositionNumber(value, min, max, name) {
  if (!Number.isFinite(value) || value < min || value > max) throw new Error(`${name} must be a number between ${min} and ${max}.`);
  return value;
}

function compositionInterval(value, minimum, name) {
  const result = {
    start: compositionNumber(value.start, minimum, 1, `${name} start`),
    end: compositionNumber(value.end, minimum, 1, `${name} end`),
  };
  if (result.end <= result.start) throw new Error(`${name} end must be greater than its start.`);
  return result;
}

function validateComposition(value, allowEmpty = false) {
  const composition = compositionObject(value, ["elements"], "Composition");
  if (!Array.isArray(composition.elements) || composition.elements.length < (allowEmpty ? 0 : 1) || composition.elements.length > 24) throw new Error("A composition needs 1–24 elements. Add text, equations, or vector shapes before rendering.");
  return { elements: composition.elements.map((value, index) => {
    const name = `Element ${index + 1}`;
    if (!compositionKinds.has(value?.kind)) throw new Error(`${name} must use text, equation, rectangle, circle, line, arrow, or polygon.`);
    const element = compositionObject(value, ["kind", "start", "end", "entrance", "motion", "exit", ...compositionFields[value.kind]], name);
    const result = { kind: element.kind, ...compositionInterval(element, 0, name) };
    for (const [key, min, max] of [["x", -6, 6], ["y", -3, 3], ["font_size", 12, 100], ["fill_opacity", 0, 1], ["stroke_width", 0, 12]]) {
      if (key in element) result[key] = compositionNumber(element[key], min, max, `${name} ${key}`);
    }
    for (const key of ["color", "fill_color"]) {
      if (key in element) {
        if (typeof element[key] !== "string" || !/^#[0-9a-fA-F]{6}$/.test(element[key])) throw new Error(`${name} ${key} must be a six-digit hex color.`);
        result[key] = element[key].toUpperCase();
      }
    }
    if (["text", "equation"].includes(element.kind)) {
      if (typeof element.text !== "string" || !element.text.trim() || element.text.length > 300 || /[\x00-\x09\x0B-\x1F]/.test(element.text)) throw new Error(`${name} needs printable text up to 300 characters.`);
      if (element.kind === "equation" && element.text.includes("\n")) throw new Error(`${name} equation must be one line of LaTeX.`);
      result.text = element.text;
    }
    if (element.kind === "rectangle") {
      result.width = compositionNumber(element.width, 0.1, 12, `${name} width`);
      result.height = compositionNumber(element.height, 0.1, 6, `${name} height`);
    }
    if (element.kind === "circle") result.radius = compositionNumber(element.radius, 0.05, 3, `${name} radius`);
    if (["line", "arrow", "polygon"].includes(element.kind)) {
      const min = element.kind === "polygon" ? 3 : 2;
      const max = element.kind === "polygon" ? 16 : 2;
      if (!Array.isArray(element.points) || element.points.length < min || element.points.length > max) throw new Error(`${name} needs ${min === max ? min : `${min}–${max}`} [x, y] points.`);
      result.points = element.points.map((point) => {
        if (!Array.isArray(point) || point.length !== 2) throw new Error(`${name} points must be [x, y] pairs.`);
        return [compositionNumber(point[0], -6, 6, `${name} point x`), compositionNumber(point[1], -3, 3, `${name} point y`)];
      });
      if (element.kind === "polygon") {
        const area = Math.abs(result.points.reduce((sum, point, position, points) => sum + point[0] * points[(position + 1) % points.length][1] - points[(position + 1) % points.length][0] * point[1], 0)) / 2;
        if (area < 0.001) throw new Error(`${name} polygon must have a nonzero area.`);
      } else if (Math.hypot(result.points[1][0] - result.points[0][0], result.points[1][1] - result.points[0][1]) < 0.01) throw new Error(`${name} endpoints must be at least 0.01 units apart.`);
    }
    if ("entrance" in element) {
      if (!["fade", "write", "create", "none"].includes(element.entrance)) throw new Error(`${name} entrance must be fade, write, create, or none.`);
      result.entrance = element.entrance;
    }
    let latest = result.end;
    if ("motion" in element) {
      const motion = compositionObject(element.motion, ["start", "end", "x", "y"], `${name} motion`);
      result.motion = { ...compositionInterval(motion, 0, `${name} motion`), x: compositionNumber(motion.x, -6, 6, `${name} motion x`), y: compositionNumber(motion.y, -3, 3, `${name} motion y`) };
      latest = Math.max(latest, result.motion.end);
    }
    if ("exit" in element) result.exit = compositionInterval(compositionObject(element.exit, ["start", "end"], `${name} exit`), latest, `${name} exit`);
    return result;
  }) };
}

function emptyMath(visual) {
  if (visual === "equation") return { equations: [] };
  if (["graph", "calculus"].includes(visual)) return { expression: "", x_min: "", x_max: "", y_min: "", y_max: "", ...(visual === "calculus" ? { operation: "derivative" } : {}) };
  return Object.fromEntries((visual === "geometry" ? ["a", "b"] : ["ax", "ay", "bx", "by"]).map((field) => [field, ""]));
}

function validateMathDraft(visual, value) {
  const fields = Object.keys(emptyMath(visual));
  const math = compositionObject(value, fields, "Math settings");
  const result = {};
  for (const field of fields) {
    const item = math[field];
    if (field === "equations") {
      if (!Array.isArray(item) || item.length > 6 || item.some((line) => typeof line !== "string" || line.length > 200)) throw new Error("Saved equation steps are invalid.");
      result[field] = [...item];
    } else if (field === "expression") {
      if (typeof item !== "string" || item.length > 120) throw new Error("The saved function is invalid.");
      result[field] = item;
    } else if (field === "operation") {
      if (!["derivative", "integral"].includes(item)) throw new Error("The saved calculus operation is invalid.");
      result[field] = item;
    } else {
      if (item !== "" && !Number.isFinite(item)) throw new Error("Saved math values must be numbers.");
      result[field] = item;
    }
  }
  return result;
}

function validateMusic(value) {
  const music = compositionObject(value, ["tempo", "chords"], "Music score");
  const tempo = compositionNumber(music.tempo, 40, 180, "Music tempo");
  if (!Array.isArray(music.chords) || music.chords.length < 1 || music.chords.length > 16) throw new Error("Use 1–16 chords in the music score.");
  const chords = music.chords.map((chord) => {
    if (!Array.isArray(chord) || chord.length < 1 || chord.length > 8 || chord.some((note) => !Number.isInteger(note) || note < 36 || note > 84)) throw new Error("Each chord needs 1–8 MIDI note numbers between 36 and 84.");
    return [...chord];
  });
  return { tempo, chords };
}

function validatePlan(value, allowIncomplete = false) {
  if (!value || typeof value !== "object" || typeof value.title !== "string" || (!allowIncomplete && !value.title.trim()) || !["math", "anime", "explainer"].includes(value.mode) || !Array.isArray(value.scenes) || value.scenes.length < (allowIncomplete ? 0 : 1) || value.scenes.length > 8) {
    throw new Error("The storyboard format is invalid. Try planning again or edit your own scenes.");
  }
  if (!allowIncomplete && value.scenes.reduce((total, scene) => total + Number(scene?.duration || 0), 0) > 120) {
    throw new Error("Keep the storyboard within 120 seconds. Shorten a scene or remove one before rendering.");
  }
  return {
    title: value.title.slice(0, 120),
    mode: value.mode,
    ...("music" in value ? { music: validateMusic(value.music) } : {}),
    scenes: value.scenes.map((scene) => {
      if (!scene || typeof scene.title !== "string" || (!allowIncomplete && !scene.title.trim()) || typeof scene.narration !== "string" || !visuals.has(scene.visual) || !Number.isFinite(scene.duration) || scene.duration < 3 || scene.duration > 20) {
        throw new Error("One scene has invalid words, timing, or visuals. Try planning again.");
      }
      if (value.mode === "math" && !mathVisuals.has(scene.visual) && scene.visual !== "composition") throw new Error("Math / Manim storyboards use custom compositions, equations, graphs, geometry, calculus, or vectors. Choose one of these visuals for every scene.");
      const result = { title: scene.title.slice(0, 100), narration: scene.narration.slice(0, 600), visual: scene.visual, duration: scene.duration, background: validColor(scene.background, "#173d42"), accent: validColor(scene.accent, "#a9dfb8") };
      if (mathVisuals.has(scene.visual)) result.math = allowIncomplete ? validateMathDraft(scene.visual, scene.math) : validateMath(scene.visual, scene.math);
      if (scene.visual === "composition") result.composition = validateComposition(scene.composition, allowIncomplete);
      return result;
    }),
  };
}

function showNotice(message, success = false) {
  $("noticeText").textContent = message;
  $("notice").classList.toggle("success", success);
  $("notice").hidden = false;
}

function mode() {
  return document.querySelector('input[name="mode"]:checked').value;
}

function currentBrief() {
  return { prompt: $("prompt").value.trim(), mode: mode(), duration: $("duration").value };
}

function updateDraftContext() {
  const brief = currentBrief();
  if (!plan.scenes.length) {
    plan.mode = brief.mode;
    draftBrief = brief;
  }
  previousDraft = plan.scenes.length > 0 && (planningState === "pending" || planningState === "failed" || brief.prompt !== draftBrief.prompt || brief.mode !== draftBrief.mode || brief.duration !== draftBrief.duration);
  updateDraftBadge();
  updateButtons();
}

function recordDraftBrief() {
  draftBrief = currentBrief();
  planningState = null;
  previousDraft = false;
}

function updateModeHint() {
  const selected = mode();
  $("workspaceTitle").textContent = ({ math: "Make mathematics move.", anime: "Bring your story into motion.", explainer: "Make your ideas clear." })[selected];
  $("workspaceDescription").textContent = ({ math: "Plan your own equations, graphs, and proofs. Your local ManimGX engine animates the content you review.", anime: "Describe your story and its movement. Your local ManimGX engine renders the model's editable vector composition.", explainer: "Describe what your audience should understand. Your local ManimGX engine animates your diagrams and words." })[selected];
  $("prompt").placeholder = ({ math: "Describe the mathematical concept, equations, and explanation you want to animate…", anime: "Describe your characters, setting, story, and the movement you want to see…", explainer: "Describe the idea, audience, and diagrams or movements that would explain it…" })[selected];
  $("modeHint").textContent = ({ math: "Your equations, graphs, geometry, and custom compositions, animated by ManimGX.", anime: "Illustrated stories use text and vector shapes with model-authored animation. This workflow does not run a generative anime image or video model.", explainer: "Your model describes the diagrams, text, shapes, and animation for each scene." })[selected];
}

function setMode(value) {
  const input = document.querySelector(`input[name="mode"][value="${["math", "anime", "explainer"].includes(value) ? value : "math"}"]`);
  input.checked = true;
  updateModeHint();
}

function persistDraft() {
  try {
    localStorage.setItem(draftKey, JSON.stringify(draftSnapshot()));
    $("saveStatus").innerHTML = '<svg class="icon"><use href="#i-check"/></svg> Draft saved locally';
    $("saveStatus").classList.remove("saved-tick");
    requestAnimationFrame(() => $("saveStatus").classList.add("saved-tick"));
    return true;
  } catch {
    $("saveStatus").textContent = "Draft storage unavailable";
    return false;
  }
}

function draftSnapshot() {
  const sceneEdits = plan.scenes.map((scene) => {
    const composition = compositionEdits.get(scene);
    const duration = durationEdits.get(scene);
    const equations = equationEdits.get(scene);
    return composition?.error || duration !== undefined || equations !== undefined ? { ...(composition?.error ? { composition: composition.text } : {}), ...(duration !== undefined ? { duration } : {}), ...(equations !== undefined ? { equations } : {}) } : null;
  });
  return { schema_version: 2, provenance: draftSource, plan, origin: draftOrigin, ...currentBrief(), draftBrief, planningState: planningState === "failed" ? "failed" : null, model: $("model").value, ...(sceneEdits.some(Boolean) ? { sceneEdits } : {}), ...(musicScoreError ? { musicEdit: musicScoreDraft } : {}) };
}

function restoreEditorInputs(savedDraft, restoredPlan) {
  const edits = savedDraft.sceneEdits;
  if (edits !== undefined) {
    if (!Array.isArray(edits) || edits.length !== restoredPlan.scenes.length) throw new Error("Saved scene edits are invalid.");
    edits.forEach((value, index) => {
      if (value === null) return;
      const edit = compositionObject(value, ["composition", "duration", "equations"], "Saved scene edits");
      const scene = restoredPlan.scenes[index];
      if ("composition" in edit) {
        if (scene.visual !== "composition" || typeof edit.composition !== "string" || edit.composition.length > 40000) throw new Error("Saved composition edits are invalid.");
        let message = "";
        try { validateComposition(JSON.parse(edit.composition), true); }
        catch (error) { message = error instanceof SyntaxError ? "Enter a valid JSON composition. No code or HTML is executed." : error.message; }
        if (message) compositionEdits.set(scene, { text: edit.composition, error: message });
      }
      if ("duration" in edit) {
        if (typeof edit.duration !== "string" || edit.duration.length > 100) throw new Error("Saved duration edits are invalid.");
        const number = Number(edit.duration);
        if (!edit.duration.trim() || !Number.isFinite(number) || number < 3 || number > 20) durationEdits.set(scene, edit.duration);
      }
      if ("equations" in edit) {
        if (scene.visual !== "equation" || typeof edit.equations !== "string" || edit.equations.length > 1205) throw new Error("Saved equation edits are invalid.");
        const lines = edit.equations.split("\n").map((line) => line.trim()).filter(Boolean);
        if (lines.length > 6 || lines.some((line) => line.length > 200)) equationEdits.set(scene, edit.equations);
      }
    });
  }
  musicScoreDraft = null;
  musicScoreError = "";
  if ("musicEdit" in savedDraft) {
    if (typeof savedDraft.musicEdit !== "string" || savedDraft.musicEdit.length > 40000) throw new Error("Saved music edits are invalid.");
    try { validateMusic(JSON.parse(savedDraft.musicEdit)); }
    catch (error) {
      musicScoreDraft = savedDraft.musicEdit;
      musicScoreError = error instanceof SyntaxError ? "Enter a valid JSON music score." : error.message;
    }
  }
}

function persistSettings() {
  try {
    localStorage.setItem(settingsKey, JSON.stringify({ voice_enabled: $("voiceEnabled").checked, voice: $("voice").value, music_enabled: $("musicEnabled").checked, music_volume: $("musicVolume").value, quality: $("quality").value }));
  } catch {
    // A private browser can disallow storage; rendering still works for this visit.
  }
}

function readStored(key) {
  try {
    return JSON.parse(localStorage.getItem(key) || "null");
  } catch {
    return null;
  }
}

function eraseStoredKeys(keys) {
  let removed = true;
  for (const key of keys) {
    try { localStorage.removeItem(key); }
    catch { removed = false; }
  }
  return removed;
}

function storageDeletionNotice() {
  showNotice("Browser storage prevented deleting project data. Clear this site's storage in your browser to finish removing it. This visit uses your current in-memory draft.");
}

function purgeObsoleteDrafts() {
  const removed = eraseStoredKeys(obsoleteDraftKeys);
  if (!removed) storageDeletionNotice();
  return removed;
}

function restoreDraft(savedDraft) {
  try {
    const storedBrief = savedDraft.draftBrief;
    if (savedDraft.schema_version !== 2 || !["model", "manual"].includes(savedDraft.provenance) || !storedBrief || typeof storedBrief.prompt !== "string" || !["math", "anime", "explainer"].includes(storedBrief.mode) || !["30", "45", "60", "90"].includes(storedBrief.duration)) throw new Error("The saved project's original brief is unverified.");
    const restoredPlan = validatePlan(savedDraft.plan, true);
    if (storedBrief.mode !== restoredPlan.mode) throw new Error("The saved storyboard's style does not match its original brief.");
    restoreEditorInputs(savedDraft, restoredPlan);
    plan = restoredPlan;
    draftOrigin = "saved";
    draftSource = savedDraft.provenance;
    draftBrief = { prompt: storedBrief.prompt.slice(0, 4000).trim(), mode: storedBrief.mode, duration: storedBrief.duration };
    planningState = savedDraft.planningState === "failed" ? "failed" : null;
    if (typeof savedDraft.prompt === "string") $("prompt").value = savedDraft.prompt.slice(0, 4000);
    if (["30", "45", "60", "90"].includes(savedDraft.duration)) $("duration").value = savedDraft.duration;
    setMode(["math", "anime", "explainer"].includes(savedDraft.mode) ? savedDraft.mode : plan.mode);
    return true;
  } catch {
    const removed = eraseStoredKeys([draftKey]);
    plan = { title: "Untitled video", mode: mode(), scenes: [] };
    draftOrigin = "new";
    draftSource = "manual";
    musicScoreDraft = null;
    musicScoreError = "";
    $("prompt").value = "";
    recordDraftBrief();
    if (removed) showNotice("The invalid saved project was discarded. Start with your own idea or add a scene.");
    else storageDeletionNotice();
    return false;
  }
}

function loadSavedDraft() {
  purgeObsoleteDrafts();
  const savedDraft = readStored(draftKey);
  if (savedDraft) return restoreDraft(savedDraft);
  // Remove malformed JSON and empty storage values rather than loading an old version.
  if (!eraseStoredKeys([draftKey])) storageDeletionNotice();
  setMode(plan.mode);
  return false;
}

function newProject() {
  if (busy) return;
  clearTimeout(saveTimer);
  const removed = eraseStoredKeys([draftKey]);
  plan = { title: "Untitled video", mode: mode(), scenes: [] };
  draftOrigin = "new";
  draftSource = "manual";
  musicScoreDraft = null;
  musicScoreError = "";
  selectedScene = 0;
  $("prompt").value = "";
  recordDraftBrief();
  activeRenderId = null;
  renderedFingerprint = null;
  $("video").pause();
  $("video").removeAttribute("src");
  $("video").replaceChildren();
  $("video").load();
  for (const id of ["downloadVideo", "downloadSubtitles", "jobPanel"]) $(id).hidden = true;
  for (const id of ["downloadVideo", "downloadSubtitles"]) $(id).removeAttribute("href");
  $("notice").hidden = true;
  const saved = refreshPlan();
  updateDraftContext();
  showSketch();
  if (!removed && !saved) storageDeletionNotice();
  $("prompt").focus();
}

function markEdited() {
  if (["generated", "new"].includes(draftOrigin)) draftOrigin = "edited";
  updateDraftBadge();
  updateSummary();
  updateSketch();
  updateVideoCaption();
  updateButtons();
  scheduleDraftSave();
}

function scheduleDraftSave() {
  clearTimeout(saveTimer);
  $("saveStatus").textContent = "Saving draft…";
  saveTimer = setTimeout(persistDraft, 250);
}

function updateDraftBadge() {
  const labels = { generated: "Model draft", edited: "Edited draft", saved: "Saved draft" };
  const style = { math: "Math / Manim", anime: "Illustrated story", explainer: "Explainer" }[plan.mode];
  $("draftBadge").textContent = previousDraft ? "Previous draft" : labels[draftOrigin] || "Your draft";
  $("draftBadge").classList.toggle("generated", !previousDraft && draftOrigin !== "new");
  $("draftBadge").classList.toggle("previous", previousDraft);
  $("draftContext").hidden = !previousDraft;
  $("draftContextText").textContent = planningState === "pending" ? `Planning a new storyboard. The ${style} draft below is kept until the new plan is ready.` : planningState === "failed" ? `No new storyboard was loaded. The ${style} draft below is your previous draft. Retry planning or start a new project.` : `Your brief or style has changed. The ${style} draft below belongs to the previous brief. Plan again or start a new project to replace it.`;
  $("draftStyle").textContent = style;
  $("sketchBadge").textContent = previousDraft ? "PREVIOUS DRAFT SKETCH" : "SCHEMATIC SKETCH";
  updateVideoCaption();
}

function updateSummary() {
  const duration = plan.scenes.reduce((total, scene) => total + scene.duration, 0);
  $("sceneSummary").textContent = `${plan.scenes.length} ${plan.scenes.length === 1 ? "scene" : "scenes"} · ${Number(duration.toFixed(1))} seconds`;
  $("addScene").disabled = busy || plan.scenes.length >= 8;
  $("sceneLimit").textContent = plan.scenes.length >= 8 ? "8 scene limit reached" : "Up to 8 scenes";
}

function compositionSummary(scene) {
  const elements = scene.composition?.elements || [];
  if (!elements.length) return "No visual content yet. Add the intended elements, or ask your model to plan this scene.";
  return elements.map((element) => {
    const content = element.text !== undefined ? element.text : element.points ? element.points.map((point) => `(${point.join(", ")})`).join(" → ") : element.kind === "rectangle" ? `${element.width} × ${element.height}` : element.kind === "circle" ? `radius ${element.radius}` : "";
    const time = (value) => Number((value * scene.duration).toFixed(2));
    let timing = `${time(element.start)}–${time(element.end)}s entrance`;
    if (element.motion) timing += `; moves to (${element.motion.x}, ${element.motion.y}) ${time(element.motion.start)}–${time(element.motion.end)}s`;
    if (element.exit) timing += `; exit ${time(element.exit.start)}–${time(element.exit.end)}s`;
    return `${element.kind}: ${content}\n${timing}`;
  }).join("\n\n");
}

function mathArtElements(scene) {
  let math;
  try { math = validateMath(scene.visual, scene.math); }
  catch { return []; }
  if (scene.visual === "equation") return math.equations.map((text, index, lines) => ({ kind: "text", text, x: 0, y: (lines.length - 1) * 0.45 - index * 0.9, font_size: 24 }));
  if (["graph", "calculus"].includes(scene.visual)) {
    return [
      { kind: "line", points: [[-5, -2], [5, -2]], stroke_width: 1 },
      { kind: "line", points: [[0, -2.5], [0, 1.7]], stroke_width: 1 },
      { kind: "text", text: scene.visual === "calculus" ? `${math.operation}: ${math.expression}` : `y = ${math.expression}`, x: 0, y: 2.5, font_size: 24 },
    ];
  }
  if (scene.visual === "geometry") {
    const scale = Math.min(8 / math.a, 4 / math.b);
    const width = math.a * scale;
    const height = math.b * scale;
    return [
      { kind: "polygon", points: [[-width / 2, -height / 2], [width / 2, -height / 2], [-width / 2, height / 2]] },
      { kind: "text", text: `a = ${math.a}`, x: 0, y: -height / 2 - 0.5, font_size: 20 },
      { kind: "text", text: `b = ${math.b}`, x: -width / 2 - 0.7, y: 0, font_size: 20 },
    ];
  }
  const points = [[0, 0], [math.ax, math.ay], [math.ax + math.bx, math.ay + math.by]];
  const scale = Math.min(1, 5 / Math.max(...points.map((point) => Math.abs(point[0])), 1), 2.5 / Math.max(...points.map((point) => Math.abs(point[1])), 1));
  const fitted = points.map((point) => point.map((coordinate) => coordinate * scale));
  return [{ kind: "arrow", points: [fitted[0], fitted[1]] }, { kind: "arrow", points: [fitted[1], fitted[2]] }, { kind: "arrow", points: [fitted[0], fitted[2]], stroke_width: 1 }];
}

function setSceneArt(container, scene) {
  container.replaceChildren();
  const elements = mathVisuals.has(scene.visual) ? mathArtElements(scene) : scene.composition?.elements || [];
  if (mathVisuals.has(scene.visual) && !elements.length) {
    const placeholder = document.createElement("span");
    placeholder.textContent = "Add math content";
    container.append(placeholder);
    return;
  }
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 142.22 80");
  svg.setAttribute("aria-hidden", "true");
  const position = (point) => [71.11 + point[0] * 10, 40 - point[1] * 10];
  const node = (tag, attributes, text) => {
    const shape = document.createElementNS("http://www.w3.org/2000/svg", tag);
    for (const [key, value] of Object.entries(attributes)) shape.setAttribute(key, String(value));
    if (text !== undefined) shape.textContent = text;
    svg.append(shape);
    return shape;
  };
  for (const element of elements) {
    const [x, y] = position([element.x || 0, element.y || 0]);
    const color = element.color || (["text", "equation"].includes(element.kind) ? sceneForeground(scene.background) : scene.accent);
    const fill = element.fill_color || color;
    const style = `stroke:${color};stroke-width:${(element.stroke_width ?? 2) / 5};fill:${fill};fill-opacity:${element.fill_opacity ?? 0}`;
    if (["text", "equation"].includes(element.kind)) {
      const text = node("text", { x, y, "font-size": (element.font_size ?? 36) / 5, "text-anchor": "middle", "dominant-baseline": "middle", style: `fill:${color};stroke:none;font-family:Segoe UI,Arial,sans-serif` });
      const lines = element.text.split("\n");
      lines.forEach((line, index) => {
        const span = document.createElementNS("http://www.w3.org/2000/svg", "tspan");
        span.setAttribute("x", String(x));
        span.setAttribute("dy", String(index === 0 ? -(lines.length - 1) * (element.font_size ?? 36) / 10 : (element.font_size ?? 36) / 5));
        span.textContent = line;
        text.append(span);
      });
    } else if (element.kind === "rectangle") node("rect", { x: x - element.width * 5, y: y - element.height * 5, width: element.width * 10, height: element.height * 10, style });
    else if (element.kind === "circle") node("circle", { cx: x, cy: y, r: element.radius * 10, style });
    else if (element.kind === "polygon") node("polygon", { points: element.points.map((point) => position(point).join(",")).join(" "), style });
    else if (["line", "arrow"].includes(element.kind)) {
      const [[x1, y1], [x2, y2]] = element.points.map(position);
      node("line", { x1, y1, x2, y2, style });
      if (element.kind === "arrow") {
        const angle = Math.atan2(y2 - y1, x2 - x1);
        const points = [[x2 - 2 * Math.cos(angle - 0.5), y2 - 2 * Math.sin(angle - 0.5)], [x2, y2], [x2 - 2 * Math.cos(angle + 0.5), y2 - 2 * Math.sin(angle + 0.5)]];
        node("polyline", { points: points.map((point) => point.join(",")).join(" "), style: `${style};fill:none` });
      }
    }
  }
  container.append(svg);
}

function updateSketch() {
  if (!plan.scenes.length) {
    $("sketchArt").innerHTML = "";
    $("sketchTitle").textContent = "Your scenes will appear here";
    $("sketchIndex").textContent = "00 / 00";
    $("sketchMath").textContent = "";
    $("sketchMath").hidden = true;
    $("previewTitle").textContent = "Start with your idea";
    $("previewNarration").textContent = "Plan a storyboard from your idea, or add and edit your own scenes.";
    return;
  }
  selectedScene = Math.min(Math.max(selectedScene, 0), plan.scenes.length - 1);
  const scene = plan.scenes[selectedScene];
  $("sceneSketch").style.setProperty("--scene-background", scene.background);
  $("sceneSketch").style.setProperty("--scene-accent", scene.accent);
  $("sceneSketch").style.setProperty("--scene-foreground", sceneForeground(scene.background));
  setSceneArt($("sketchArt"), scene);
  const math = scene.math;
  const details = scene.visual === "composition" ? compositionSummary(scene) : !math ? "" : scene.visual === "equation" ? math.equations.join("\n") : scene.visual === "geometry" ? `a = ${math.a}, b = ${math.b}` : scene.visual === "vectors" ? `a = (${math.ax}, ${math.ay})\nb = (${math.bx}, ${math.by})` : `${scene.visual === "calculus" ? `${math.operation} of ` : "y = "}${math.expression}\nx: ${math.x_min} … ${math.x_max}; y: ${math.y_min} … ${math.y_max}`;
  $("sketchMath").textContent = details;
  $("sketchMath").hidden = !details;
  $("sketchTitle").textContent = scene.title;
  $("sketchIndex").textContent = `${String(selectedScene + 1).padStart(2, "0")} / ${String(plan.scenes.length).padStart(2, "0")}`;
  $("previewTitle").textContent = scene.title || `Scene ${selectedScene + 1}`;
  $("previewNarration").textContent = scene.narration || "No narration for this scene.";
  document.querySelectorAll(".scene-card").forEach((card, index) => {
    card.classList.toggle("selected", index === selectedScene);
    card.querySelector(".scene-thumbnail").setAttribute("aria-pressed", String(index === selectedScene));
  });
}

function showSketch() {
  $("video").pause();
  $("video").hidden = true;
  $("sceneSketch").hidden = false;
  $("sketchCaption").hidden = false;
  $("showSketch").hidden = true;
  $("showVideo").hidden = !activeRenderId;
  $("videoCaption").hidden = true;
}

function showRenderedVideo() {
  if (!activeRenderId) return;
  $("video").hidden = false;
  $("sceneSketch").hidden = true;
  $("sketchCaption").hidden = true;
  $("showSketch").hidden = false;
  $("showVideo").hidden = true;
  $("videoCaption").hidden = false;
  updateVideoCaption();
}

function updateFieldError(input, feedback, message) {
  input.setCustomValidity(message);
  input.setAttribute?.("aria-invalid", String(!!message));
  if (feedback) {
    feedback.textContent = message;
    feedback.hidden = !message;
  }
}

function editComposition(input, scene, card) {
  try {
    scene.composition = validateComposition(JSON.parse(input.value), true);
    updateFieldError(input, card?.querySelector(".composition-error"), "");
    compositionEdits.set(scene, { text: input.value, error: "" });
    if (card) setSceneArt(card.querySelector(".thumbnail-art"), scene);
    markEdited();
  } catch (error) {
    const message = error instanceof SyntaxError ? "Enter a valid JSON composition. No code or HTML is executed." : error.message;
    updateFieldError(input, card?.querySelector(".composition-error"), message);
    compositionEdits.set(scene, { text: input.value, error: message });
    markEdited();
  }
}

function renderCompositionControls(controls, card, scene, index) {
  const legend = document.createElement("legend");
  legend.textContent = "Your scene content and animation";
  const wrapper = document.createElement("div");
  wrapper.className = "math-field math-field-wide";
  const label = document.createElement("label");
  const input = document.createElement("textarea");
  const hint = document.createElement("p");
  const feedback = document.createElement("p");
  input.id = `scene-${index}-composition`;
  input.className = "equation-input";
  input.rows = 9;
  input.maxLength = 40000;
  input.spellcheck = false;
  input.required = true;
  const edit = compositionEdits.get(scene);
  input.value = edit?.text ?? JSON.stringify(scene.composition, null, 2);
  input.setCustomValidity(edit?.error || "");
  input.setAttribute("aria-invalid", String(!!edit?.error));
  label.htmlFor = input.id;
  label.textContent = "Composition · editable JSON";
  hint.id = `scene-${index}-composition-hint`;
  hint.className = "math-field-hint";
  hint.textContent = "Use 1–24 elements with kind text, equation, rectangle, circle, line, arrow, or polygon. Text needs text; rectangles need width/height; circles need radius; lines/arrows/polygons need [x,y] points. Coordinates: x −6…6, y −3…3. Every element needs start/end entrance times from 0 to 1 as fractions of this scene. Optional motion {start,end,x,y} uses its own window and can overlap entrance; x/y are its final center. Optional exit {start,end} begins after both entrance and motion finish. No scene content is filled in for you.";
  input.setAttribute("aria-describedby", hint.id);
  feedback.id = `${input.id}-error`;
  feedback.className = "field-error composition-error";
  feedback.setAttribute("role", "status");
  feedback.textContent = edit?.error || "";
  feedback.hidden = !edit?.error;
  input.setAttribute("aria-describedby", `${hint.id} ${feedback.id}`);
  input.addEventListener("input", () => editComposition(input, scene, card));
  wrapper.append(label, input, feedback);
  controls.append(legend, wrapper, hint);
}

function renderMathControls(card, scene, index) {
  const controls = card.querySelector(".math-controls");
  controls.replaceChildren();
  controls.hidden = !mathVisuals.has(scene.visual) && scene.visual !== "composition";
  if (controls.hidden) return;
  if (scene.visual === "composition") {
    renderCompositionControls(controls, card, scene, index);
    return;
  }
  scene.math ??= emptyMath(scene.visual);
  const legend = document.createElement("legend");
  legend.textContent = `${visualNames[scene.visual]} settings`;
  controls.append(legend);
  const addField = (key, labelText, options = {}) => {
    const wrapper = document.createElement("div");
    wrapper.className = `math-field ${options.wide ? "math-field-wide" : ""}`;
    const label = document.createElement("label");
    const input = document.createElement(options.multiline ? "textarea" : options.choices ? "select" : "input");
    input.id = `scene-${index}-math-${key}`;
    label.htmlFor = input.id;
    label.textContent = labelText;
    if (options.choices) {
      for (const [value, text] of options.choices) {
        const option = document.createElement("option");
        option.value = value;
        option.textContent = text;
        input.append(option);
      }
    } else if (options.multiline) {
      input.rows = 3;
      input.maxLength = 1205;
      input.className = "equation-input";
      input.spellcheck = false;
    } else {
      input.type = options.number ? "number" : "text";
      if (options.number) {
        input.min = options.min;
        input.max = options.max;
        input.step = "any";
      } else {
        input.maxLength = 120;
        input.spellcheck = false;
        input.className = "expression-input";
      }
    }
    input.required = true;
    input.value = options.multiline ? equationEdits.get(scene) ?? scene.math[key].join("\n") : scene.math[key];
    if (options.multiline && equationEdits.has(scene)) input.setCustomValidity("Use 1–6 equation lines, with up to 200 characters each.");
    input.addEventListener("input", () => {
      editMathValue(input, scene, key, options);
    });
    wrapper.append(label, input);
    controls.append(wrapper);
  };
  if (scene.visual === "equation") {
    addField("equations", "Equation steps · one LaTeX expression per line", { multiline: true, wide: true });
  } else if (scene.visual === "graph" || scene.visual === "calculus") {
    addField("expression", "Function of x", { wide: true });
    if (scene.visual === "calculus") addField("operation", "Show", { wide: true, choices: [["derivative", "Derivative · moving tangent"], ["integral", "Integral · shaded area"]] });
    for (const axis of ["x", "y"]) {
      addField(`${axis}_min`, `${axis.toUpperCase()} minimum`, { number: true, min: -20, max: 20 });
      addField(`${axis}_max`, `${axis.toUpperCase()} maximum`, { number: true, min: -20, max: 20 });
    }
  } else if (scene.visual === "geometry") {
    addField("a", "Side a", { number: true, min: 0.01, max: 10000 });
    addField("b", "Side b", { number: true, min: 0.01, max: 10000 });
  } else {
    for (const [key, label] of [["ax", "Vector a · x"], ["ay", "Vector a · y"], ["bx", "Vector b · x"], ["by", "Vector b · y"]]) addField(key, label, { number: true, min: -4, max: 4 });
  }
  const hint = document.createElement("p");
  hint.className = "math-field-hint";
  hint.textContent = scene.visual === "equation" ? "1–6 steps. ManimGX typesets and animates these equations when rendered." : ["graph", "calculus"].includes(scene.visual) ? "Use x**2, sin(x), cos(x), tan(x), sqrt(x), exp(x), log(x), or abs(x). Choose limits where the function is defined. Integral shading spans the chosen X limits." : scene.visual === "geometry" ? "The right triangle and its side squares follow these lengths." : "The animation adds these two vectors tip to tail.";
  controls.append(hint);
}

function editMathValue(input, scene, key, options) {
  if (options.multiline) {
    const lines = input.value.split("\n").map((line) => line.trim()).filter(Boolean);
    if (lines.length > 6 || lines.some((line) => line.length > 200)) equationEdits.set(scene, input.value);
    else {
      equationEdits.delete(scene);
      scene.math[key] = lines;
    }
    input.setCustomValidity(lines.length < 1 || lines.length > 6 || lines.some((line) => line.length > 200) ? "Use 1–6 equation lines, with up to 200 characters each." : "");
  } else if (options.number) {
    const number = Number(input.value);
    scene.math[key] = input.value.trim() && Number.isFinite(number) ? number : "";
  } else scene.math[key] = input.value;
  input.setAttribute?.("aria-invalid", String(input.validity?.valid === false));
  markEdited();
}

function sceneKind(scene) {
  return visualNames[scene.visual] || "Unsupported saved visual";
}

function changeSceneVisual(scene, visual) {
  if (!visuals.has(visual)) throw new Error("Choose a supported scene visual.");
  compositionEdits.delete(scene);
  equationEdits.delete(scene);
  scene.visual = visual;
  if (mathVisuals.has(visual)) scene.math = emptyMath(visual);
  else delete scene.math;
  if (visual === "composition") scene.composition = { elements: [] };
  else delete scene.composition;
}

function removeScene(index) {
  if (busy || !Number.isInteger(index) || index < 0 || index >= plan.scenes.length) return;
  plan.scenes.splice(index, 1);
  if (index < selectedScene) selectedScene -= 1;
  selectedScene = Math.max(0, Math.min(selectedScene, plan.scenes.length - 1));
  renderScenes();
  updateDraftContext();
  markEdited();
  $("addScene").focus();
}

function renderScenes() {
  $("scenes").replaceChildren();
  plan.scenes.forEach((scene, index) => {
    const fragment = $("sceneTemplate").content.cloneNode(true);
    const card = fragment.querySelector(".scene-card");
    card.classList.add("scene-enter");
    card.style.setProperty("--scene-order", String(index));
    const field = (name) => card.querySelector(`.scene-${name}`);
    card.setAttribute("aria-label", `Scene ${index + 1}`);
    card.querySelector(".scene-number").textContent = `SCENE ${String(index + 1).padStart(2, "0")}`;
    card.querySelector(".scene-kind").textContent = sceneKind(scene);
    const thumbnail = card.querySelector(".scene-thumbnail");
    thumbnail.style.setProperty("--scene-background", scene.background);
    thumbnail.style.setProperty("--scene-accent", scene.accent);
    thumbnail.style.setProperty("--scene-foreground", sceneForeground(scene.background));
    thumbnail.setAttribute("aria-label", `Preview scene ${index + 1}: ${scene.title}`);
    thumbnail.addEventListener("click", () => { selectedScene = index; updateSketch(); showSketch(); });
    setSceneArt(card.querySelector(".thumbnail-art"), scene);


    ["title", "narration", "visual", "duration", "background", "accent"].forEach((name) => {
      const input = field(name);
      input.id = `scene-${index}-${name}`;
      input.value = scene[name];
      if (name === "duration") {
        if (durationEdits.has(scene)) input.value = durationEdits.get(scene);
        input.setAttribute("aria-invalid", String(durationEdits.has(scene)));
      }
      const label = card.querySelector(`.${name}-label`);
      label.htmlFor = input.id;
      if (name === "background" || name === "accent") card.querySelector(`.${name}-value`).textContent = scene[name];
      input.addEventListener("input", () => {
        if (name === "duration") {
          editSceneDuration(input, scene);
          return;
        } else {
          scene[name] = input.value;
        }
        if (name === "title") thumbnail.setAttribute("aria-label", `Preview scene ${index + 1}: ${scene.title}`);
        if (name === "background" || name === "accent") {
          thumbnail.style.setProperty(`--scene-${name}`, input.value);
          if (name === "background") thumbnail.style.setProperty("--scene-foreground", sceneForeground(input.value));
          card.querySelector(`.${name}-value`).textContent = input.value;
        }
        if (name === "visual") {
          changeSceneVisual(scene, input.value);
          card.querySelector(".scene-kind").textContent = sceneKind(scene);
          setSceneArt(card.querySelector(".thumbnail-art"), scene);
          renderMathControls(card, scene, index);
        }
        markEdited();
      });
    });

    renderMathControls(card, scene, index);
    const up = card.querySelector(".move-up");
    const down = card.querySelector(".move-down");
    const remove = card.querySelector(".remove-scene");
    up.disabled = index === 0 || busy;
    down.disabled = index === plan.scenes.length - 1 || busy;
    remove.disabled = busy;
    up.setAttribute("aria-label", `Move scene ${index + 1} earlier`);
    down.setAttribute("aria-label", `Move scene ${index + 1} later`);
    remove.setAttribute("aria-label", `Remove scene ${index + 1}`);
    up.addEventListener("click", () => moveScene(index, -1));
    down.addEventListener("click", () => moveScene(index, 1));
    remove.addEventListener("click", () => removeScene(index));
    $("scenes").append(fragment);
  });
  updateSummary();
  updateSketch();
}

function editSceneDuration(input, scene) {
  const value = Number(input.value);
  if (!input.value.trim() || !Number.isFinite(value) || value < 3 || value > 20 || input.validity?.badInput) durationEdits.set(scene, input.value);
  else {
    durationEdits.delete(scene);
    scene.duration = value;
  }
  input.setAttribute("aria-invalid", String(durationEdits.has(scene)));
  markEdited();
}

function moveScene(index, direction) {
  const destination = index + direction;
  if (destination < 0 || destination >= plan.scenes.length || busy) return;
  [plan.scenes[index], plan.scenes[destination]] = [plan.scenes[destination], plan.scenes[index]];
  if (selectedScene === index) selectedScene = destination;
  else if (selectedScene === destination) selectedScene = index;
  renderScenes();
  markEdited();
  const movedButton = $("scenes").children[destination].querySelector(direction < 0 ? ".move-up" : ".move-down");
  (movedButton.disabled ? $("scenes").children[destination].querySelector(".scene-title") : movedButton).focus();
}

function refreshPlan() {
  $("planTitle").value = plan.title;
  $("musicScore").value = musicScoreDraft ?? (plan.music ? JSON.stringify(plan.music, null, 2) : "");
  updateFieldError($("musicScore"), $("musicScoreError"), musicScoreError);
  updateDraftBadge();
  renderScenes();
  return persistDraft();
}

function editMusicScore(input, feedback) {
  try {
    if (input.value.trim()) plan.music = validateMusic(JSON.parse(input.value));
    else delete plan.music;
    musicScoreError = "";
    musicScoreDraft = null;
    updateFieldError(input, feedback, "");
    markEdited();
  } catch (error) {
    musicScoreError = error instanceof SyntaxError ? "Enter a valid JSON music score." : error.message;
    musicScoreDraft = input.value;
    updateFieldError(input, feedback, musicScoreError);
    markEdited();
  }
}

function renderReadiness() {
  if (musicScoreError) return musicScoreError;
  if (plan.scenes.some((scene) => durationEdits.has(scene))) return "Scene duration must be between 3 and 20 seconds. Finish the edited value before rendering.";
  if (plan.scenes.some((scene) => equationEdits.has(scene))) return "Use 1–6 equation lines, with up to 200 characters each.";
  if (plan.scenes.some((scene) => scene.visual === "composition" && compositionEdits.get(scene)?.error)) return "Finish the composition JSON before rendering.";
  if (!plan.scenes.length) return "Describe your idea and plan a storyboard, or add your first scene.";
  try { validatePlan(plan); return ""; }
  catch (error) { return error.message; }
}

function updateButtons() {
  const id = selectedProvider();
  const info = providerInfo(id);
  const modelsAvailable = id === "ollama" ? services.ollama.connected && services.ollama.models.length > 0 && $("model").value : info.configured && $("cloudModel").value.trim();
  $("planButton").disabled = busy || !runtimeReady || !modelsAvailable;
  const readiness = renderReadiness();
  $("renderButton").disabled = busy || !runtimeReady || !services.engine.available || !!readiness;
  $("newProject").disabled = busy;
  $("refreshStatus").disabled = checkingStatus || busy;
  $("refreshStatus").classList.toggle("loading", checkingStatus);
  $("model").disabled = busy || !services.ollama.models.length;
  $("cloudModel").disabled = busy;
  $("cloudModel").required = id !== "ollama";
  $("plannerProvider").disabled = busy || !statusLoaded;
  $("briefAdmin").disabled = busy;
  $("voiceEnabled").disabled = busy || !services.voices.length;
  $("voice").disabled = busy || !$("voiceEnabled").checked || !services.voices.length;
  $("musicVolume").disabled = busy || !$("musicEnabled").checked;
  $("musicScore").disabled = busy;
  $("musicOptions").style.opacity = $("musicEnabled").checked ? "1" : ".45";
  $("voiceOptions").style.opacity = $("voiceEnabled").checked ? "1" : ".45";
  $("renderHint").textContent = !statusLoaded ? "Checking the local rendering engine…" : services.engine.available ? "Review the words and timing, then render your video." : services.engine.error || "The local rendering engine is unavailable. See the Studio setup guide.";
  if (statusLoaded && services.engine.available && previousDraft) $("renderHint").textContent = "This renders the previous draft shown above. Plan again to use your new brief.";
  if (statusLoaded && services.engine.available && readiness) $("renderHint").textContent = readiness;
  if (!runtimeReady) $("renderHint").textContent = statusLoaded ? restartMessage : "Checking the Studio server version…";
  $("renderLabel").textContent = previousDraft ? "Render previous draft" : "Render video";
  updateSummary();
}

function setBusy(value, kind = busyKind) {
  busy = value;
  busyKind = value ? kind : null;
  document.body.classList.toggle("studio-busy", value);
  document.body.classList.toggle("studio-planning", value && kind === "plan");
  $("planningSkeleton").hidden = !(value && kind === "plan");
  $("planButton").classList.toggle("loading", value && kind === "plan");
  $("renderButton").classList.toggle("loading", value && kind === "render");
  $("planButton").setAttribute("aria-busy", String(value && kind === "plan"));
  $("renderButton").setAttribute("aria-busy", String(value && kind === "render"));
  $("storyboard").setAttribute("aria-busy", String(value));
  document.querySelectorAll("#briefForm input, #briefForm textarea, #briefForm select, #editorForm input, #editorForm textarea, #editorForm select, #editorForm button, #settings input, #settings textarea, #settings select").forEach((input) => { input.disabled = value; });
  $("newProject").disabled = value;
  if (!value) {
    document.querySelectorAll(".scene-card").forEach((card, index) => {
      card.querySelector(".move-up").disabled = index === 0;
      card.querySelector(".move-down").disabled = index === plan.scenes.length - 1;
      card.querySelector(".remove-scene").disabled = false;
    });
  }
  updateButtons();
}

async function api(path, body, timeoutMs = 20000, externalSignal) {
  const controller = new AbortController();
  const abort = () => controller.abort();
  externalSignal?.addEventListener("abort", abort, { once: true });
  if (externalSignal?.aborted) abort();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(path, { method: body === undefined ? "GET" : "POST", headers: body === undefined ? {} : { "Content-Type": "application/json" }, body: body === undefined ? undefined : JSON.stringify(body), signal: controller.signal, cache: "no-store" });
    let data;
    try { data = await response.json(); }
    catch { throw new Error("The Studio server returned an unexpected response. Check that the local server is running."); }
    if (!response.ok) throw new Error(data.error || data.message || `The server returned HTTP ${response.status}.`);
    return data;
  } catch (error) {
    if (error.name === "AbortError") throw new Error(externalSignal?.aborted ? "Connection test cancelled. No storyboard generation was requested." : "The local server took too long to respond. Check the server terminal; a submitted job may still be running.");
    if (error instanceof TypeError) throw new Error("Cannot reach the local Studio server. Start it, then refresh service status.");
    throw error;
  } finally {
    clearTimeout(timeout);
    externalSignal?.removeEventListener("abort", abort);
  }
}

function serviceBadge(id, connected, label, error) {
  const badge = $(id);
  badge.className = `service-badge ${connected ? "connected" : "unavailable"}`;
  badge.replaceChildren();
  const dot = document.createElement("span");
  dot.className = "status-dot";
  badge.append(dot, document.createTextNode(label));
  badge.title = error || label;
}

function setOptions(select, values, emptyLabel, preferred) {
  const previous = preferred || select.value;
  select.replaceChildren();
  if (values.length === 0) {
    const option = document.createElement("option");
    option.value = "";
    option.textContent = emptyLabel;
    select.append(option);
  } else {
    values.forEach((value) => {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = value;
      select.append(option);
    });
    if (values.includes(previous)) select.value = previous;
  }
}

async function loadStatus() {
  if (checkingStatus) return;
  checkingStatus = true;
  runtimeReady = false;
  updateButtons();
  try {
    let runtime;
    try { runtime = await api("/api/runtime"); }
    catch { throw new Error(restartMessage); }
    if (runtime?.protocol !== runtimeProtocol || runtime.restart_required !== false) throw new Error(restartMessage);
    runtimeReady = true;
    $("runtimeNotice").hidden = true;
    const result = await api("/api/status");
    services = { ollama: { connected: !!result.ollama?.connected, models: Array.isArray(result.ollama?.models) ? result.ollama.models.filter((value) => typeof value === "string") : [], error: result.ollama?.error }, engine: { available: !!result.engine?.available, error: result.engine?.error }, voices: Array.isArray(result.voices) ? result.voices.filter((value) => typeof value === "string") : [] };
    serviceBadge("engineStatus", services.engine.available, services.engine.available ? "Engine ready" : "Engine unavailable", services.engine.error);
    const draft = readStored(draftKey);
    const settings = readStored(settingsKey);
    setOptions($("model"), services.ollama.models, services.ollama.connected ? "No models installed" : "Ollama unavailable", $("model").value || draft?.model);
    setOptions($("voice"), services.voices, "No local voices available", $("voice").value || settings?.voice);
    adoptProviderSettings(result.settings || result, statusLoaded ? selectedProvider() : undefined);
    updatePlanner();
    $("voiceHint").textContent = services.voices.length ? "Uses a voice installed on this computer." : "No local voices found. Voice-over is unavailable; you can render with music.";
    if (!services.voices.length) $("voiceEnabled").checked = false;
    persistDraft();
  } catch (error) {
    if (!runtimeReady) {
      $("runtimeNoticeText").textContent = restartMessage;
      $("runtimeNotice").hidden = false;
    }
    services = { ollama: { connected: false, models: [], error: error.message }, engine: { available: false, error: error.message }, voices: [] };
    serviceBadge("ollamaStatus", false, "Server unavailable", error.message);
    serviceBadge("engineStatus", false, "Engine unverified", error.message);
    setOptions($("model"), [], "Server unavailable");
    setOptions($("voice"), [], "Server unavailable");
    $("modelHint").textContent = error.message;
    $("voiceHint").textContent = "Local voices could not be checked.";
    showNotice(error.message);
  } finally {
    checkingStatus = false;
    statusLoaded = true;
    updateButtons();
  }
}

function updateBrandFallback(brand, images) {
  brand.classList.toggle("image-unavailable", images.some((image) => image.complete && image.naturalWidth === 0));
}

function initializeBranding() {
  const brand = document.querySelector(".brand");
  if (!brand) return;
  const images = Array.from(brand.querySelectorAll("img"));
  for (const image of images) {
    image.addEventListener("load", () => updateBrandFallback(brand, images));
    image.addEventListener("error", () => { brand.classList.add("image-unavailable"); });
  }
  updateBrandFallback(brand, images);
}

function jobProgress(job) {
  if (job.status === "complete") return 1;
  const completed = Number(job.completed_scenes);
  const total = Number(job.total_scenes);
  if (job.stage === "render" && Number.isInteger(completed) && Number.isInteger(total) && total > 0 && completed >= 0 && completed <= total) return completed / total;
  return null;
}

function updateJob(kind, status, message, job = {}) {
  if (kind === "plan" && status === "failed") {
    planningState = "failed";
    previousDraft = plan.scenes.length > 0;
    updateDraftBadge();
  }
  $("jobPanel").hidden = false;
  const titles = { plan: "Planning your storyboard", render: "Rendering your video" };
  setText("jobTitle", status === "complete" ? kind === "plan" ? "Your storyboard is ready" : "Your video is ready" : status === "failed" ? kind === "plan" ? "Planning needs attention" : "Rendering needs attention" : titles[kind]);
  const stages = { queued: "Queued", planning: "Model planning", review: "Ready to review", audio: "Adding voice", music: "Mixing music", render: "Preparing scenes", export: "Encoding MP4" };
  setText("jobState", status === "complete" ? "Complete" : status === "failed" ? "Failed" : stages[job.stage] || ({ queued: "Queued", running: "Running" })[status] || "Working");
  setText("jobMessage", message || (status === "queued" ? "Waiting for the local worker…" : "Your computer is working on it."));
  $("jobProgress").className = `progress-track ${status === "complete" ? "complete" : status === "failed" ? "failed" : ""}`;
  const fraction = jobProgress({ ...job, status });
  const progress = $("jobProgress");
  progress.setAttribute("role", "progressbar");
  progress.setAttribute("aria-label", kind === "plan" ? "Storyboard planning progress" : "Video rendering progress");
  progress.setAttribute("aria-valuemin", "0");
  progress.setAttribute("aria-valuemax", "100");
  progress.classList.toggle("determinate", fraction !== null);
  if (fraction === null) {
    progress.removeAttribute("aria-valuenow");
    progress.querySelector("span").style.width = "";
    progress.setAttribute("aria-valuetext", status === "failed" ? "Needs attention" : "Working; completion time is not yet known");
  } else {
    progress.setAttribute("aria-valuenow", String(Math.round(fraction * 100)));
    progress.querySelector("span").style.width = `${fraction * 100}%`;
    progress.setAttribute("aria-valuetext", status === "complete" ? "Complete" : `${job.completed_scenes} of ${job.total_scenes} scenes prepared`);
  }
  $("stepPlan").className = kind === "plan" && status !== "complete" ? "current" : "done";
  $("stepEdit").className = kind === "plan" && status === "complete" ? "current" : kind === "render" ? "done" : "";
  $("stepRender").className = kind === "render" ? "current" : "";
}

function beginJob(kind, message) {
  if (kind === "plan") {
    planningState = "pending";
    previousDraft = plan.scenes.length > 0;
    updateDraftBadge();
  }
  setBusy(true, kind);
  updateJob(kind, "queued", message);
  $("jobPanel").scrollIntoView({ behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "start" });
}

async function waitForJob(id, kind) {
  if (typeof id !== "string" || !id) throw new Error("The server did not return a valid job ID.");
  let failures = 0;
  for (;;) {
    let job;
    try {
      job = await api(`/api/jobs/${encodeURIComponent(id)}`);
      failures = 0;
    } catch (error) {
      failures += 1;
      if (failures >= 3) throw new Error(`${error.message} The submitted job may still be running; check the server terminal before retrying.`);
      updateJob(kind, "running", "The connection was interrupted. Reconnecting to the local worker…");
      await new Promise((resolve) => setTimeout(resolve, 1800));
      continue;
    }
    updateJob(kind, job.status, job.message, job);
    if (job.status === "complete") return job;
    if (job.status === "failed") throw new Error(job.error || job.message || "The local job failed. Check the Studio terminal for details.");
    if (!["queued", "running"].includes(job.status)) throw new Error("The server returned an unknown job state.");
    await new Promise((resolve) => setTimeout(resolve, 1200));
  }
}

function localMediaURL(value) {
  if (typeof value !== "string") throw new Error("The server did not return a video URL.");
  const url = new URL(value, window.location.href);
  if (url.origin !== window.location.origin || !["http:", "https:"].includes(url.protocol)) throw new Error("The media URL must belong to the local Studio server.");
  return url.href;
}

function updateVideoCaption() {
  if (!activeRenderId) return;
  const unchanged = renderedFingerprint === JSON.stringify({ plan, options: renderOptions() });
  $("videoCaption").textContent = previousDraft ? "Previous render of the earlier draft. A new storyboard has not been loaded." : unchanged && !renderReadiness() ? "Your rendered video, with your chosen sound settings." : "Previous render. Your storyboard or output settings have changed; render again to update the video.";
}

function showVideo(job, renderedPlan, options) {
  const videoURL = localMediaURL(job.video_url);
  const video = $("video");
  video.pause();
  video.replaceChildren();
  video.src = videoURL;
  const captions = document.createElement("track");
  captions.kind = "captions";
  captions.label = "Narration";
  captions.srclang = "und";
  captions.src = localMediaURL(job.captions_url || `/media/${encodeURIComponent(job.id)}/project.vtt`);
  video.append(captions);
  video.load();
  $("downloadVideo").href = videoURL;
  $("downloadVideo").download = `${renderedPlan.title.replace(/[^a-z0-9_-]+/gi, "-") || "panini-video"}.mp4`;
  $("downloadVideo").hidden = false;
  $("downloadSubtitles").href = localMediaURL(job.subtitles_url || `/media/${encodeURIComponent(job.id)}/project.srt`);
  $("downloadSubtitles").hidden = false;
  $("sceneSketch").hidden = true;
  $("sketchCaption").hidden = true;
  video.hidden = false;
  $("showSketch").hidden = false;
  $("showVideo").hidden = true;
  $("videoCaption").hidden = false;
  renderedFingerprint = JSON.stringify({ plan: renderedPlan, options });
  activeRenderId = job.id;
  updateVideoCaption();
}

function addSceneToDraft() {
  if (busy || plan.scenes.length >= 8) return;
  if (!plan.scenes.length) {
    plan.mode = mode();
    recordDraftBrief();
  }
  const previous = plan.scenes[plan.scenes.length - 1];
  const scene = { title: "Untitled scene", narration: "", visual: "composition", composition: { elements: [] }, duration: previous?.duration || 6, background: previous?.background || "#101b2d", accent: previous?.accent || "#75d8f7" };
  plan.scenes.push(scene);
  selectedScene = plan.scenes.length - 1;
  renderScenes();
  markEdited();
  $("scenes").lastElementChild.querySelector(".scene-title").focus();
}

async function planVideo() {
  if (busy || !runtimeReady || $("planButton").disabled || !$("briefForm").reportValidity()) return;
  $("notice").hidden = true;
  beginJob("plan", `Sending your brief to ${providerInfo(selectedProvider()).name}…`);
  try {
    const response = await api("/api/plan", planningPayload());
    const job = await waitForJob(response.id, "plan");
    plan = validatePlan(job.plan);
    draftOrigin = "generated";
    draftSource = "model";
    musicScoreDraft = null;
    musicScoreError = "";
    selectedScene = 0;
    setMode(plan.mode);
    recordDraftBrief();
    refreshPlan();
    showSketch();
    showNotice("Your model drafted a storyboard. Review the math, narration, and scene timing before rendering.", true);
    showToast("Storyboard ready to review");
    $("storyboard").scrollIntoView({ behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "start" });
  } catch (error) {
    updateJob("plan", "failed", error.message);
    showNotice(error.message);
    persistDraft();
  } finally {
    setBusy(false);
  }
}

$("briefForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  await planVideo();
});

$("renderButton").addEventListener("click", async () => {
  if (busy || !runtimeReady || !services.engine.available || $("renderButton").disabled || !$("editorForm").reportValidity()) return;
  let renderedPlan;
  try { renderedPlan = validatePlan(plan); }
  catch (error) { showNotice(error.message); return; }
  const options = renderOptions();
  $("notice").hidden = true;
  beginJob("render", "Preparing your scenes, narration, and audio…");
  try {
    const response = await api("/api/render", { plan: renderedPlan, ...options });
    const job = await waitForJob(response.id, "render");
    showVideo(job, renderedPlan, options);
    showNotice("Your video is ready. Play it in the screening room or download the MP4.", true);
    showToast("Video ready · saved on this PC");
  } catch (error) {
    updateJob("render", "failed", error.message);
    showNotice(error.message);
  } finally {
    setBusy(false);
  }
});

$("newProject").addEventListener("click", newProject);

$("addScene").addEventListener("click", addSceneToDraft);

$("planTitle").addEventListener("input", () => { plan.title = $("planTitle").value; markEdited(); });
$("editorForm").addEventListener("submit", (event) => event.preventDefault());
$("dismissNotice").addEventListener("click", () => { $("notice").hidden = true; });
$("refreshStatus").addEventListener("click", loadStatus);
$("showSketch").addEventListener("click", showSketch);
$("showVideo").addEventListener("click", showRenderedVideo);
document.querySelectorAll('input[name="mode"]').forEach((input) => { input.addEventListener("change", () => { updateModeHint(); updateDraftContext(); persistDraft(); }); });
$("prompt").addEventListener("input", () => { updateDraftContext(); scheduleDraftSave(); });
$("duration").addEventListener("change", updateDraftContext);
[$("prompt"), $("duration"), $("model")].forEach((input) => { input.addEventListener("change", persistDraft); });
[$("voiceEnabled"), $("voice"), $("musicEnabled"), $("musicVolume"), $("quality")].forEach((input) => {
  input.addEventListener("change", () => { persistSettings(); updateButtons(); updateVideoCaption(); });
});
$("musicVolume").addEventListener("input", () => { $("volumeValue").textContent = `${Math.round(Number($("musicVolume").value) * 100)}%`; });
$("musicScore").addEventListener("input", () => editMusicScore($("musicScore"), $("musicScoreError")));
window.addEventListener("pagehide", persistDraft);
document.querySelectorAll(".rail-link").forEach((link) => {
  link.addEventListener("click", () => {
    document.querySelectorAll(".rail-link").forEach((item) => { item.classList.toggle("active", item === link); });
  });
});

$("profileButton").addEventListener("click", () => {
  const open = $("profileMenu").hidden;
  $("profileMenu").hidden = !open;
  $("profileButton").setAttribute("aria-expanded", String(open));
  if (open) $("openAdmin").focus();
});
$("profileButton").addEventListener("keydown", (event) => {
  if (event.key === "ArrowDown") { event.preventDefault(); $("profileMenu").hidden = false; $("profileButton").setAttribute("aria-expanded", "true"); $("openAdmin").focus(); }
});
document.addEventListener("click", (event) => { if (!event.target.closest(".profile-area")) closeProfile(); });
document.addEventListener("keydown", (event) => { if (event.key === "Escape" && !$("profileMenu").hidden) { event.preventDefault(); closeProfile(true); } });
for (const id of ["openAdmin", "briefAdmin"]) $(id).addEventListener("click", () => { openAdmin($(id)); });
for (const id of ["openHow", "workflowHelp"]) $(id).addEventListener("click", () => openHow($(id)));
$("closeAdmin").addEventListener("click", () => $("adminDialog").close());
for (const id of ["closeHow", "howDone"]) $(id).addEventListener("click", () => $("howDialog").close());
for (const id of ["adminDialog", "howDialog"]) {
  const dialog = $(id);
  dialog.addEventListener("click", (event) => {
    const bounds = dialog.getBoundingClientRect();
    if (event.target === dialog && (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom)) dialog.close();
  });
  dialog.addEventListener("close", () => {
    if (id === "adminDialog") { $("adminApiKey").value = ""; hideApiKey(); providerTestController?.abort(); }
    (dialogOpener?.isConnected ? dialogOpener : $("profileButton")).focus();
  });
}
$("adminProvider").addEventListener("change", () => { $("adminModels").replaceChildren(); populateAdmin(); });
$("toggleKey").addEventListener("click", () => {
  const show = $("adminApiKey").type === "password";
  $("adminApiKey").type = show ? "text" : "password";
  $("toggleKey").textContent = show ? "Hide" : "Show";
  $("toggleKey").setAttribute("aria-label", show ? "Hide API key" : "Show API key");
  $("toggleKey").setAttribute("aria-pressed", String(show));
});
$("adminForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (adminBusy || !$("adminForm").reportValidity()) return;
  const request = adminSettingsPayload(true);
  $("adminApiKey").value = "";
  hideApiKey();
  setAdminBusy(true, "saveProvider");
  try {
    const result = await api("/api/settings", request);
    delete modelChoices[request.provider];
    adoptProviderSettings(result, request.provider);
    populateAdmin();
    adminFeedback(`${providerInfo(request.provider).name} is selected. ${providerInfo(request.provider).configured ? "Ready for planning." : "Add the required settings before planning."}`, true);
    showToast("Planning provider saved");
  } catch (error) { adminFeedback(error.message); }
  finally { setAdminBusy(false, "saveProvider"); }
});
$("testProvider").addEventListener("click", async () => {
  if (adminBusy || !$("adminForm").reportValidity()) return;
  const request = adminSettingsPayload();
  $("adminApiKey").value = "";
  hideApiKey();
  setAdminBusy(true, "testProvider");
  providerTestController = new AbortController();
  adminFeedback("Checking the provider’s model list…");
  try {
    adoptProviderSettings(await api("/api/settings", request), selectedProvider());
    const result = await api("/api/providers/test", { provider: request.provider }, 90000, providerTestController.signal);
    const models = Array.isArray(result.models) ? result.models.filter((value) => typeof value === "string") : [];
    if (request.provider === "ollama" && result.connected) {
      services.ollama = { connected: true, models, error: "" };
      setOptions($("model"), models, "No models installed", request.model);
    }
    if (request.provider === selectedProvider() && request.provider !== "ollama") setOptions($("cloudModels"), models, "", request.model);
    populateAdmin();
    setOptions($("adminModels"), models, "", request.model);
    adminFeedback(`${result.message || (result.connected ? "Connection successful." : "Could not connect.")}${models.length ? ` ${models.length} models available. ${models.slice(0, 4).join(", ")}${models.length > 4 ? "…" : ""}` : ""}`, !!result.connected);
    updatePlanner();
  } catch (error) { adminFeedback(error.message); }
  finally { providerTestController = null; setAdminBusy(false, "testProvider"); }
});
$("clearKey").addEventListener("click", async () => {
  if (adminBusy) return;
  const provider = $("adminProvider").value;
  $("adminApiKey").value = "";
  hideApiKey();
  setAdminBusy(true, "clearKey");
  try {
    adoptProviderSettings(await api("/api/settings", { provider, clear_key: true }), selectedProvider());
    populateAdmin();
    adminFeedback("The provider key has been cleared from this server session.", true);
  } catch (error) { adminFeedback(error.message); }
  finally { setAdminBusy(false, "clearKey"); }
});
$("plannerProvider").addEventListener("change", () => {
  if (previousProvider !== "ollama") modelChoices[previousProvider] = $("cloudModel").value.trim();
  previousProvider = selectedProvider();
  $("cloudModels").replaceChildren();
  updatePlanner();
});
$("cloudModel").addEventListener("input", () => { modelChoices[selectedProvider()] = $("cloudModel").value.trim(); updateButtons(); });
document.querySelectorAll("[data-how-step]").forEach((button) => button.addEventListener("click", () => showWorkflowStep(button.dataset.howStep)));

initializeBranding();
loadSavedDraft();
const savedSettings = readStored(settingsKey);
if (savedSettings) {
  if (typeof savedSettings.voice_enabled === "boolean") $("voiceEnabled").checked = savedSettings.voice_enabled;
  if (typeof savedSettings.music_enabled === "boolean") $("musicEnabled").checked = savedSettings.music_enabled;
  if (["preview", "final"].includes(savedSettings.quality)) $("quality").value = savedSettings.quality;
  const volume = Number(savedSettings.music_volume);
  if (Number.isFinite(volume) && volume >= 0 && volume <= 0.3) $("musicVolume").value = String(volume);
}
$("volumeValue").textContent = `${Math.round(Number($("musicVolume").value) * 100)}%`;
updateDraftContext();
refreshPlan();
loadStatus();
