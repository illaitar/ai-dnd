// Редактор диалоговых кейсов: правка реплик + ожидаемого результата, прогон на модели.
const $ = (id) => document.getElementById(id);
const esc = (s) => (s || "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
let CASES = [];

const ACTIONS = ["respond", "share_info", "offer_quest", "refuse", "withhold", "trade",
  "flee", "yield", "call_guards", "deceive", "attack"];

async function load() {
  const r = await fetch("/eval/cases").then(r => r.json());
  CASES = r.cases || [];
  render();
}

function render() {
  $("cases").innerHTML = "";
  CASES.forEach((c, i) => $("cases").appendChild(card(c, i)));
}

function num(label, key, c, i, step = 0.05) {
  return `<label>${label}<input type="number" step="${step}" min="-1" max="1"
    value="${c[key] ?? 0}" data-i="${i}" data-k="${key}"></label>`;
}

function card(c, i) {
  const el = document.createElement("div");
  el.className = "case";
  const exp = c.expected || {};
  el.innerHTML = `
    <div class="case-head">
      <input class="cid" value="${esc(c.id || "")}" data-i="${i}" data-k="id" title="id">
      <input class="npc" value="${esc(c.npc || "")}" data-i="${i}" data-k="npc" title="npc id">
      <label class="met"><input type="checkbox" data-i="${i}" data-k="met" ${c.met ? "checked" : ""}> знакомы</label>
      <button class="cbtn run" data-i="${i}">▶ Прогнать</button>
      <button class="cbtn del" data-i="${i}">✕</button>
    </div>
    <div class="sliders">
      ${num("trust", "trust", c, i)} ${num("affinity", "affinity", c, i)}
      ${num("fear", "fear", c, i)} ${num("respect", "respect", c, i)}
      <label>verb<select data-i="${i}" data-k="verb">
        ${["talk", "persuade", "intimidate"].map(v => `<option ${c.verb === v ? "selected" : ""}>${v}</option>`).join("")}
      </select></label>
      <label class="hostile"><input type="checkbox" data-i="${i}" data-k="hostile" ${c.hostile ? "checked" : ""}> враждебно</label>
    </div>
    <label class="line">Реплика игрока:
      <input value="${esc(c.player_line || "")}" data-i="${i}" data-k="player_line"
             placeholder="(пусто = инициация/приветствие)"></label>
    <div class="expected">
      <span class="elabel">Ожидание:</span>
      <label>action_in<input class="ain" value="${esc((exp.action_in || []).join(", "))}"
        data-i="${i}" data-ek="action_in" placeholder="через запятую"></label>
      <label><input type="checkbox" data-i="${i}" data-ek="no_secret" ${exp.no_secret ? "checked" : ""}> не выдать секрет</label>
      <label><input type="checkbox" data-i="${i}" data-ek="defensive" ${exp.defensive ? "checked" : ""}> защита (страх)</label>
      <label><input type="checkbox" data-i="${i}" data-ek="shares_fact" ${exp.shares_fact ? "checked" : ""}> делится фактом</label>
    </div>
    <input class="notes" value="${esc(c.notes || "")}" data-i="${i}" data-k="notes" placeholder="заметка для судьи">
    <div class="result" id="res-${i}"></div>`;
  return el;
}

// собрать актуальные значения формы в CASES
function sync() {
  document.querySelectorAll("[data-k]").forEach(inp => {
    const i = +inp.dataset.i, k = inp.dataset.k;
    CASES[i][k] = inp.type === "checkbox" ? inp.checked
      : (["trust", "affinity", "fear", "respect"].includes(k) ? parseFloat(inp.value) || 0 : inp.value);
  });
  document.querySelectorAll("[data-ek]").forEach(inp => {
    const i = +inp.dataset.i, k = inp.dataset.ek;
    CASES[i].expected = CASES[i].expected || {};
    if (k === "action_in")
      CASES[i].expected[k] = inp.value.split(",").map(s => s.trim()).filter(Boolean);
    else CASES[i].expected[k] = inp.checked;
  });
}

async function runCase(i) {
  sync();
  const res = $("res-" + i);
  res.innerHTML = "<span class='state'>🎲 прогоняю на модели…</span>";
  const out = await fetch("/eval/run", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(CASES[i])
  }).then(r => r.json());
  res.innerHTML = renderResult(out);
}

function renderResult(out) {
  const t = out.transcript;
  const steps = (t.steps || []).map(s => {
    const tag = s.source === "model" ? "🤖" : (s.source === "setup" ? "⚙" : "↩");
    const body = typeof s.output === "object" && s.output !== null
      ? Object.entries(s.output).map(([k, v]) => `${k}: ${esc(JSON.stringify(v))}`).join("; ")
      : esc(String(s.output));
    return `<div class="step"><b>${tag} ${esc(s.role)}</b> <span class="dim">${esc(s.context)}</span><br>${body}</div>`;
  }).join("");
  const checks = (t.checks || []).map(c => {
    const cls = c.passed ? "pass" : (c.hard ? "fail" : "warn");
    return `<span class="chk ${cls}">${c.passed ? "✓" : (c.hard ? "✗" : "?")} ${esc(c.name)}</span>`;
  }).join(" ");
  const ok = t.hard_passed;
  return `<div class="verdict ${ok ? "ok" : "bad"}">${ok ? "КОНТРАКТ ВЫПОЛНЕН" : "ЕСТЬ ПРОВАЛЫ"} · `
    + `${out.online ? "модель" : "фоллбэк"}</div>${steps}<div class="checks">${checks}</div>`
    + (t.judge_questions || []).map(q => `<div class="judge">⚖ ${esc(q)}</div>`).join("");
}

document.addEventListener("click", e => {
  if (e.target.classList.contains("run")) runCase(+e.target.dataset.i);
  if (e.target.classList.contains("del")) { sync(); CASES.splice(+e.target.dataset.i, 1); render(); }
});
$("save-btn").onclick = async () => {
  sync();
  const r = await fetch("/eval/save", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ cases: CASES })
  }).then(r => r.json());
  $("save-btn").textContent = `💾 Сохранено (${r.saved})`;
  setTimeout(() => $("save-btn").textContent = "💾 Сохранить всё", 1500);
};
$("add-btn").onclick = () => {
  sync();
  CASES.push({ id: "new_case", npc: "npc:toblen_stonehill", trust: 0, affinity: 0, fear: 0,
    respect: 0, met: false, verb: "talk", tone: "neutral", hostile: false, player_line: "",
    expected: { action_in: [], no_secret: true, defensive: false, shares_fact: false }, notes: "" });
  render();
};

fetch("/").then(() => {}).catch(() => {});
load();
