/* AEye — lógica da página (fetch para o backend local). */
"use strict";

const $ = (id) => document.getElementById(id);

const historyEl = $("history");
const statusEl = $("status");
let mode = "texto";
let selectedImage = null;
let pendingAction = null;

/* ---------- estado do modo ---------- */
document.querySelectorAll(".seg").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".seg").forEach((b) => {
      const active = b === btn;
      b.classList.toggle("active", active);
      b.setAttribute("aria-checked", String(active));
    });
    mode = btn.dataset.mode;
  });
});

/* ---------- imagem (centraliza preview + seleção) ---------- */
function setImage(file) {
  if (!file || !file.type.startsWith("image/")) {
    statusEl.textContent = "Apenas imagens são aceitas aqui.";
    return;
  }
  selectedImage = file;
  const reader = new FileReader();
  reader.onload = (ev) => {
    $("preview").src = ev.target.result;
    $("previewWrap").hidden = false;
  };
  reader.readAsDataURL(file);
}

$("imageInput").addEventListener("change", (e) => {
  const file = e.target.files && e.target.files[0];
  if (!file) return;
  setImage(file);
});
$("clearImage").addEventListener("click", () => {
  selectedImage = null;
  $("imageInput").value = "";
  $("previewWrap").hidden = true;
});

/* ---------- drag-and-drop na carta de imagem ---------- */
function initDragDrop() {
  const card = document.querySelector(".image-card");
  if (!card) return;
  let depth = 0;
  function addActive(e) { e.preventDefault(); depth++; card.classList.add("drop-active"); }
  function removeActive(e) { e.preventDefault(); depth--; if (depth <= 0) { depth = 0; card.classList.remove("drop-active"); } }
  card.addEventListener("dragenter", addActive);
  card.addEventListener("dragover", addActive);
  card.addEventListener("dragleave", removeActive);
  card.addEventListener("drop", (e) => {
    e.preventDefault();
    card.classList.remove("drop-active");
    depth = 0;
    const file = e.dataTransfer.files && e.dataTransfer.files[0];
    if (file) setImage(file);
  });
}

/* ---------- botão Colar da área de transferência (mobile/touch) ---------- */
function initPasteButton() {
  const pasteBtn = $("pasteBtn");
  if (!pasteBtn) return;
  const hiddenInput = document.createElement("input");
  hiddenInput.type = "file";
  hiddenInput.accept = "image/*";
  hiddenInput.hidden = true;
  document.body.appendChild(hiddenInput);
  function pick() { hiddenInput.value = ""; hiddenInput.click(); }
  pasteBtn.addEventListener("pointerdown", (e) => { e.preventDefault(); });
  pasteBtn.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); pick(); } });
  pasteBtn.addEventListener("click", pick);
  hiddenInput.addEventListener("change", () => {
    const file = hiddenInput.files && hiddenInput.files[0];
    if (file) setImage(file);
  });
}

/* ---------- Ctrl+V / Cmd+V: colar imagem da área de transferência ---------- */
function initPasteHandler() {
  const card = document.querySelector(".image-card");
  if (!card) return;
  function handlePaste(e) {
    e.preventDefault();
    const items = e.clipboardData && e.clipboardData.items;
    let found = false;
    if (items) {
      for (let i = 0; i < items.length; i++) {
        if (items[i].type.startsWith("image/")) {
          setImage(items[i].getAsFile());
          found = true;
          break;
        }
      }
    }
    if (!found) statusEl.textContent = "Nenhuma imagem encontrada na área de transferência.";
  }
  card.addEventListener("paste", handlePaste);
}

/* ---------- helpers ---------- */
function addMsg(role, text, meta) {
  const div = document.createElement("div");
  div.className = `msg ${role}`;
  div.textContent = text;
  if (meta) {
    const m = document.createElement("span");
    m.className = "meta";
    m.textContent = meta;
    div.appendChild(m);
  }
  historyEl.prepend(div);
}

/* Fetch com PIN opcional (se o .env do PC tiver AEYE_PIN definido) e timeout. */
let pin = localStorage.getItem("aeye_pin") || "";
async function authedFetch(url, opts = {}, timeoutMs = 300000) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  const headers = Object.assign({}, opts.headers || {});
  if (pin) headers["X-AEYE-PIN"] = pin;
  try {
    let res = await fetch(url, Object.assign({}, opts, { headers, signal: controller.signal }));
    if (res.status === 401) {
      const entered = prompt("Digite o PIN do AEye (definido no .env do PC):");
      if (!entered) throw new Error("PIN necessário para acessar o AEye.");
      pin = entered.trim();
      localStorage.setItem("aeye_pin", pin);
      headers["X-AEYE-PIN"] = pin;
      res = await fetch(url, Object.assign({}, opts, { headers, signal: controller.signal }));
    }
    return res;
  } finally {
    clearTimeout(timer);
  }
}

async function postJSON(url, body) {
  const res = await authedFetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || `Erro ${res.status}`);
  return data;
}

function speak(text) {
  if ($("speakToggle").checked && text) {
    postJSON("/api/read", { text }).catch(() => {});
  }
}

/* ---------- processar imagem ou texto ---------- */
$("processBtn").addEventListener("click", async () => {
  const instruction = $("promptInput").value.trim();
  statusEl.textContent = "Processando...";
  $("processBtn").disabled = true;
  try {
    if (selectedImage) {
      const fd = new FormData();
      fd.append("file", selectedImage);
      fd.append("mode", mode);
      fd.append("instruction", instruction);
      fd.append("strong", $("strongToggle").checked ? "true" : "false");
      const res = await authedFetch("/api/ocr", { method: "POST", body: fd }, 600000);
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || `Erro ${res.status}`);
      addMsg("assistant", data.text,
        `via ${data.provider} · origem: ${data.source}${data.warning ? " · ⚠ " + data.warning : ""}`);
      speak(data.text);
      statusEl.textContent = "";
    } else if (instruction) {
      const data = await postJSON("/api/chat", { message: instruction });
      addMsg("assistant", data.text, `via ${data.provider}${data.escalated ? " (fallback)" : ""}`);
      speak(data.text);
      statusEl.textContent = "";
    } else {
      statusEl.textContent = "Envie uma imagem ou digite uma mensagem.";
    }
  } catch (err) {
    statusEl.textContent = err.name === "AbortError"
      ? "Ainda processando... a resposta demorou demais. Tente de novo (ou use uma imagem menor)."
      : "Erro: " + err.message;
  } finally {
    $("processBtn").disabled = false;
  }
});

/* ---------- controle do computador ---------- */
$("actBtn").addEventListener("click", async () => {
  const command = $("actionInput").value.trim();
  if (!command) return;
  statusEl.textContent = "Interpretando comando...";
  $("actBtn").disabled = true;
  try {
    const data = await postJSON("/api/act", { command, approved: false });
    pendingAction = data.action;
    $("approvalText").textContent =
      `Ferramenta: ${pendingAction.tool}\nParâmetros: ${JSON.stringify(pendingAction.params)}\n` +
      (pendingAction.rationale ? `Motivo: ${pendingAction.rationale}` : "");
    $("approval").hidden = false;
    $("approveBtn").focus();
    statusEl.textContent = "";
  } catch (err) {
    statusEl.textContent = "Erro: " + err.message;
  } finally {
    $("actBtn").disabled = false;
  }
});

$("approveBtn").addEventListener("click", async () => {
  const command = $("actionInput").value.trim();
  $("approveBtn").disabled = true;
  statusEl.textContent = "Executando...";
  try {
    const data = await postJSON("/api/act", { command, approved: true, action: pendingAction });
    if (data.status === "cancelled") {
      addMsg("assistant", "⏹️ Ação cancelada (kill switch).", JSON.stringify(data.action));
      statusEl.textContent = "Ação cancelada.";
    } else {
      addMsg("assistant", "✅ Ação executada:\n" + (data.result || "ok"), JSON.stringify(data.action));
      speak("Ação executada.");
      statusEl.textContent = "";
    }
    $("approval").hidden = true;
    pendingAction = null;
  } catch (err) {
    statusEl.textContent = "Erro: " + err.message;
  } finally {
    $("approveBtn").disabled = false;
  }
});

$("rejectBtn").addEventListener("click", () => {
  pendingAction = null;
  $("approval").hidden = true;
  statusEl.textContent = "Ação cancelada.";
  postJSON("/api/cancel", {}).catch(() => {});
});

initDragDrop();
initPasteButton();
initPasteHandler();
