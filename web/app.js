/* AEye — lógica da página (fetch para o backend local). */
"use strict";

const $ = (id) => document.getElementById(id);

const historyEl = $("history");
const statusEl = $("status");
let mode = "texto";
let selectedImage = null;
let pendingAction = null;
let pendingCommand = null;

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
  announce("Imagem carregada. Pronta para processar.");
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
function addMsg(role, text, meta, retry) {
  const div = document.createElement("div");
  div.className = `msg ${role}`;
  div.textContent = text;
  if (meta) {
    const m = document.createElement("span");
    m.className = "meta";
    m.textContent = meta;
    div.appendChild(m);
  }
  if (role === "assistant") {
    _attachResultControls(div, text, retry);
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

/* ---------- avisos de estado: região ARIA (#status) + voz opcional ---------- */
function announce(message) {
  statusEl.textContent = message;   // atualiza a região ARIA live (role="status")
  speak(message);                    // lê em voz alta se o toggle "Ler em voz alta" estiver ativo
}

/* ---------- controles por resultado: reouvir / copiar / reenviar ---------- */
function _attachResultControls(msgEl, text, retry) {
  const row = document.createElement("div");
  row.className = "result-controls";

  function ctl(label, ariaLabel, onClick) {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "result-ctl ghost";
    b.setAttribute("aria-label", ariaLabel);
    b.textContent = label;
    b.addEventListener("click", () => onClick(b));
    row.appendChild(b);
  }

  ctl("🗣️ Reouvir", "Ouvir a resposta novamente", (b) => {
    b.disabled = true;
    statusEl.textContent = "Lendo a resposta em voz alta...";
    postJSON("/api/read", { text }).then(() => {
      statusEl.textContent = "Resposta lida em voz alta.";
    }).catch(() => {
      statusEl.textContent = "Não foi possível ler em voz alta agora.";
    }).finally(() => {
      b.disabled = false;
    });
  });

  ctl("📋 Copiar", "Copiar a resposta para a área de transferência", () => {
    const done = () => { statusEl.textContent = "Resposta copiada para a área de transferência."; };
    const fail = () => { statusEl.textContent = "Não foi possível copiar. Selecione o texto manualmente."; };
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(done).catch(fail);
    } else {
      fail();
    }
  });

  if (retry) {
    ctl("↻ Reenviar", "Reenviar esta solicitação", (b) => {
      b.disabled = true;
      if (retry.kind === "ocr") runOcrFlow(retry);
      else if (retry.kind === "chat") runChatFlow(retry.message);
      else if (retry.kind === "act") runActFlow(retry.command);
      else b.disabled = false;
    });
  }

  msgEl.appendChild(row);
}

/* ---------- processar imagem ou texto ---------- */
async function runOcrFlow({ file, m, instruction, strong }) {
  const fd = new FormData();
  fd.append("file", file);
  fd.append("mode", m);
  fd.append("instruction", instruction);
  fd.append("strong", strong ? "true" : "false");
  const res = await authedFetch("/api/ocr", { method: "POST", body: fd }, 600000);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || `Erro ${res.status}`);
  return data;
}

async function runChatFlow(message) {
  return postJSON("/api/chat", { message });
}

async function runActFlow(command) {
  const data = await postJSON("/api/act", {
    command,
    approved: false,
    strong: $("actStrongToggle").checked,
  });
  pendingAction = data.action;
  pendingCommand = command;
  $("approvalText").textContent = _approvalText(pendingAction);
  $("approval").hidden = false;
  $("approveBtn").focus();
  announce("Ação aguardando aprovação. Leia a descrição e confirme.");
}

function _approvalText(action) {
  const params = action.params && Object.keys(action.params).length
    ? Object.entries(action.params)
        .map(([k, v]) => `${k}: ${typeof v === "object" ? JSON.stringify(v) : v}`)
        .join(", ")
    : "(sem parâmetros)";
  const lines = [];
  if (action.description) {
    lines.push(`O computador vai: ${action.description}`);
  } else {
    lines.push(`O computador vai usar a ferramenta "${action.tool}".`);
  }
  lines.push(`Parâmetros: ${params}`);
  if (action.rationale) lines.push(`Motivo: ${action.rationale}`);
  return lines.join("\n");
}

function _abortMessage() {
  return "Ainda processando... a resposta demorou demais. Tente de novo (ou use uma imagem menor).";
}

$("processBtn").addEventListener("click", () => _processFromInputs(false));

async function _processFromInputs(isRetry) {
  const instruction = $("promptInput").value.trim();
  if (!isRetry && !selectedImage && !instruction) {
    statusEl.textContent = "Envie uma imagem ou digite uma mensagem.";
    return;
  }
  $("processBtn").disabled = true;
  statusEl.textContent = "Processando...";
  try {
    if (selectedImage) {
      const data = await runOcrFlow({
        file: selectedImage,
        m: mode,
        instruction,
        strong: $("strongToggle").checked,
      });
      addMsg("assistant", data.text,
        `via ${data.provider} · origem: ${data.source}${data.warning ? " · ⚠ " + data.warning : ""}`,
        { kind: "ocr", file: selectedImage, m: mode, instruction, strong: $("strongToggle").checked });
      speak(data.text);
    } else if (instruction) {
      const data = await runChatFlow(instruction);
      addMsg("assistant", data.text, `via ${data.provider}${data.escalated ? " (fallback)" : ""}`,
        { kind: "chat", message: instruction });
      speak(data.text);
    } else {
      statusEl.textContent = "Envie uma imagem ou digite uma mensagem.";
    }
    announce("Processamento concluído. A resposta está no histórico.");
  } catch (err) {
    announce(err.name === "AbortError" ? _abortMessage() : "Erro ao processar: " + err.message);
  } finally {
    $("processBtn").disabled = false;
  }
}

/* ---------- controle do computador ---------- */
$("actBtn").addEventListener("click", () => {
  const command = $("actionInput").value.trim();
  if (!command) return;
  _runAct(command);
});

async function _runAct(command) {
  $("actBtn").disabled = true;
  statusEl.textContent = "Interpretando comando...";
  try {
    await runActFlow(command);   // anuncia "Ação aguardando aprovação" ao final
  } catch (err) {
    announce("Erro ao interpretar o comando: " + err.message);
  } finally {
    $("actBtn").disabled = false;
  }
}

$("approveBtn").addEventListener("click", async () => {
  const command = pendingCommand || $("actionInput").value.trim();
  $("approveBtn").disabled = true;
  statusEl.textContent = "Executando...";
  try {
    const data = await postJSON("/api/act", { command, approved: true, action: pendingAction });
    if (data.status === "cancelled") {
      addMsg("assistant", "⏹️ Ação cancelada (kill switch).",
        `ferramenta: ${data.action ? data.action.tool : "?"}`,
        { kind: "act", command });
      announce("Ação cancelada pelo kill switch.");
    } else {
      addMsg("assistant", "✅ Ação executada:\n" + (data.result || "ok"),
        `ferramenta: ${data.action ? data.action.tool : "?"}`,
        { kind: "act", command });
      announce("Ação executada com sucesso.");
    }
    $("approval").hidden = true;
    pendingAction = null;
    pendingCommand = null;
  } catch (err) {
    announce("Erro ao executar a ação: " + err.message);
  } finally {
    $("approveBtn").disabled = false;
  }
});

$("rejectBtn").addEventListener("click", () => {
  pendingAction = null;
  pendingCommand = null;
  $("approval").hidden = true;
  announce("Ação cancelada pelo usuário.");
  postJSON("/api/cancel", {}).catch(() => {});
});

/* ---------- entrada por voz (Web Speech API) ---------- */
let recognition = null;            // instância única do SpeechRecognition
let currentVoiceField = null;      // id do campo que está sendo ditado

const VOICE_LABELS = {
  micPromptBtn: "Usar microfone para ditar texto",
  micActionBtn: "Usar microfone para ditar comando",
};

function _voiceBtn(fieldId) {
  return fieldId === "micPromptBtn" ? $("micPromptBtn") : $("micActionBtn");
}

function initVoiceInput() {
  const micPrompt = $("micPromptBtn");
  const micAction = $("micActionBtn");
  if (!micPrompt && !micAction) return;

  /* Verifica suporte: se não existir, os botões permanecem como dica visual. */
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SpeechRecognition) {
    // degrade gracefully: avisa apenas se o usuário tentar ativar
    [micPrompt, micAction].forEach((btn) => {
      if (btn) btn.addEventListener("click", () => {
        statusEl.textContent = "A Web Speech API não está disponível neste navegador. Use Ctrl+V para colar ou digite o texto.";
      });
    });
    return;
  }

  recognition = new SpeechRecognition();
  recognition.lang = "pt-BR";
  recognition.interimResults = true;       // mostra resultados parciais enquanto fala
  recognition.maxAlternatives = 1;         // menos ruído na inserção

  /* Botão é toggle: clicar inicia a gravação; clicar de novo para. */
  function _startRecognition(fieldId) {
    if (currentVoiceField !== fieldId) {
      _stopRecognition(true);             // cancela gravação anterior, se houver
    }
    currentVoiceField = fieldId;
    const btn = _voiceBtn(fieldId);
    try {
      recognition.start();                // alguns navegadores lançam em vez de resolver com Promise
    } catch (err) {
      announce("Não foi possível iniciar a entrada por voz. Verifique a permissão do microfone.");
      _stopRecognition(true);
      return;
    }
    if (btn) {
      btn.classList.add("recording");
      btn.setAttribute("aria-label", "Parar gravação");
    }
    announce("Ouvindo, fale agora. Clique de novo para parar.");
  }

  function _stopRecognition(silent) {
    const fieldId = currentVoiceField;
    currentVoiceField = null;
    if (recognition) {
      try {
        recognition.stop();               // para a gravação em andamento
      } catch (_) { /* sessão já encerrada */ }
    }
    if (fieldId) {
      const btn = _voiceBtn(fieldId);
      if (btn) {
        btn.classList.remove("recording");
        btn.setAttribute("aria-label", VOICE_LABELS[fieldId]);
      }
    }
    if (!silent) {
      announce("Entrada por voz encerrada.");
    }
  }

  recognition.onresult = (event) => {
    const fieldId = currentVoiceField;
    if (!fieldId) return;
    const textarea = document.getElementById(fieldId === "micPromptBtn" ? "promptInput" : "actionInput");
    if (!textarea) return;

    let transcript = "";
    for (let i = event.resultIndex; i < event.results.length; i++) {
      transcript += event.results[i][0].transcript;
    }
    // Insere o texto ditado na posição do cursor, sem apagar o que já foi digitado.
    const start = textarea.selectionStart || 0;
    const end = textarea.selectionEnd || 0;
    const before = textarea.value.substring(0, start);
    const after = textarea.value.substring(end);
    const insert = transcript.trim();
    if (insert) {
      // normaliza espaços: garante uma única separação entre o texto existente e o ditado
      const sep = (before.length && !/\s$/.test(before)) ? " " : "";
      textarea.value = before + sep + insert + after;
      // move o cursor para o final do texto inserido
      const newCursorPos = start + sep.length + insert.length;
      textarea.setSelectionRange(newCursorPos, newCursorPos);
    }
  };

  recognition.onend = () => {
    const wasActive = currentVoiceField !== null;
    _stopRecognition(!wasActive);  // se onerror já encerrou, não sobrescreve a mensagem
  };
  recognition.onerror = (event) => {
    _stopRecognition(true);        // reseta o estado sem apagar a mensagem de erro
    announce("Erro na entrada por voz: " + event.error + ".");
  };

  if (micPrompt) micPrompt.addEventListener("click", () => {
    if (currentVoiceField === "micPromptBtn") {
      _stopRecognition();                 // toggle: para a gravação em curso
    } else {
      _startRecognition("micPromptBtn");
    }
  });
  if (micAction) micAction.addEventListener("click", () => {
    if (currentVoiceField === "micActionBtn") {
      _stopRecognition();
    } else {
      _startRecognition("micActionBtn");
    }
  });

  // Garante que a gravação pare se o usuário mudar de campo ou clicar em outro botão.
  document.getElementById("promptInput").addEventListener("focus", () => {
    if (currentVoiceField === "micActionBtn") _stopRecognition();
  });
  document.getElementById("actionInput").addEventListener("focus", () => {
    if (currentVoiceField === "micPromptBtn") _stopRecognition();
  });
}

initDragDrop();
initPasteButton();
initPasteHandler();
initVoiceInput();
