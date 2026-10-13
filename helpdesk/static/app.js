"use strict";
const $ = (id) => document.getElementById(id);
let sessionId = null;
let busy = false;
let documents = [];
const welcome = $("welcome");
const agentLabels = { helpdesk_agent: "受付", it_agent: "IT担当", hr_agent: "人事担当", accounting_agent: "経理担当" };

function showDocument(id) {
  const doc = documents.find((item) => item.id === id);
  if (!doc) return;
  $("doc-id").textContent = `${doc.category} / ${doc.id}`;
  $("doc-title").textContent = doc.title;
  $("doc-content").textContent = doc.content;
  $("doc-dialog").showModal();
}

function addMessage(role, text, result = null) {
  welcome.remove();
  const row = document.createElement("div");
  row.className = `message ${role}`;
  if (role === "assistant") {
    const avatar = document.createElement("div");
    avatar.className = "avatar";
    avatar.textContent = "✳";
    row.append(avatar);
  }
  const bubble = document.createElement("div");
  bubble.className = "bubble";
  const paragraph = document.createElement("p");
  paragraph.textContent = text; // Render user/model output as text, never HTML.
  bubble.append(paragraph);
  if (result?.sources?.length) {
    const sources = document.createElement("div");
    sources.className = "sources";
    for (const source of result.sources) {
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = `${source.id} · ${source.title}`;
      button.addEventListener("click", () => showDocument(source.id));
      sources.append(button);
    }
    bubble.append(sources);
  }
  if (result?.agents_used?.length) {
    const route = document.createElement("p");
    route.className = "tool-note";
    route.textContent = `担当：${result.agents_used.map((name) => agentLabels[name] || name).join(" → ")}`;
    bubble.append(route);
  }
  const calculated = result?.tools_used?.includes("estimate_purchase");
  const searched = result?.tools_used?.some((name) => name.startsWith("search_") && name.endsWith("knowledge"));
  if (calculated || searched) {
    const note = document.createElement("p");
    note.className = "tool-note";
    note.textContent = calculated
      ? "購入金額の計算を行いました。"
      : "デモ規程を検索しました。";
    bubble.append(note);
  }
  row.append(bubble);
  $("conversation").append(row);
  $("conversation").scrollTop = $("conversation").scrollHeight;
  return row;
}

function setBusy(value) {
  busy = value;
  $("send").disabled = value;
  $("reset").disabled = value;
  $("message").disabled = value;
  document.querySelectorAll("[data-prompt]").forEach((button) => { button.disabled = value; });
}

function showError(message) {
  $("error").textContent = message;
  $("error").hidden = !message;
}

async function send(message) {
  if (busy || !message.trim()) return;
  setBusy(true);
  showError("");
  addMessage("user", message);
  $("message").value = "";
  const pending = addMessage("assistant", "規程を確認しています…");
  pending.classList.add("pending");
  try {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message, session_id: sessionId }),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(typeof result.detail === "string" ? result.detail : "入力内容を確認してください。");
    sessionId = result.session_id;
    pending.remove();
    addMessage("assistant", result.answer, result);
  } catch (error) {
    pending.remove();
    showError(error.message || "接続できませんでした。");
    $("message").value = message;
  } finally {
    setBusy(false);
    $("message").focus();
  }
}

$("chat-form").addEventListener("submit", (event) => {
  event.preventDefault();
  send($("message").value.trim());
});
$("message").addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    send($("message").value.trim());
  }
});
document.querySelectorAll("[data-prompt]").forEach((button) => {
  button.addEventListener("click", () => send(button.dataset.prompt));
});
$("reset").addEventListener("click", async () => {
  if (busy) return;
  setBusy(true);
  try {
    if (sessionId) {
      const response = await fetch(`/api/sessions/${encodeURIComponent(sessionId)}`, { method: "DELETE" });
      if (!response.ok && response.status !== 404) throw new Error("会話を削除できませんでした。もう一度お試しください。");
    }
    sessionId = null;
    $("conversation").replaceChildren(welcome);
    showError("");
  } catch (error) { showError(error.message); }
  finally { setBusy(false); $("message").focus(); }
});
$("close-dialog").addEventListener("click", () => $("doc-dialog").close());

async function initialize() {
  setBusy(true);
  try {
    const [configResponse, docsResponse] = await Promise.all([fetch("/api/config"), fetch("/api/knowledge")]);
    if (!configResponse.ok || !docsResponse.ok) throw new Error("アプリの設定を読み込めませんでした。ページを再読み込みしてください。");
    const [config, knowledge] = await Promise.all([configResponse.json(), docsResponse.json()]);
    const labels = { local: "ADK + Gemini", remote: "Agent Runtime" };
    $("mode").textContent = labels[config.backend] || config.backend;
    documents = knowledge.documents;
    $("doc-count").textContent = String(documents.length).padStart(2, "0");
    for (const doc of documents) {
      const button = document.createElement("button");
      button.type = "button";
      const label = document.createElement("small");
      label.textContent = `${doc.category} / ${doc.id}`;
      button.append(label, document.createTextNode(doc.title));
      button.addEventListener("click", () => showDocument(doc.id));
      $("documents").append(button);
    }
    setBusy(false);
  } catch (error) { showError(error.message); }
}
initialize();
