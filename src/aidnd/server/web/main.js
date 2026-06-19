// L9 фронтенд: WebSocket-клиент. Никакого browser storage — всё состояние на
// сервере в event log; фронт держит только отображение (main §11).

const $ = (id) => document.getElementById(id);
let ws, lastView = null;

function connect() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  ws = new WebSocket(`${proto}://${location.host}/ws`);
  ws.onmessage = (e) => render(JSON.parse(e.data));
  ws.onclose = () => logSystem("Соединение закрыто. Обнови страницу.");
}
function send(obj) { ws.send(JSON.stringify(obj)); }

// ----------------------------------------------------------------- log ----
function logEntry(html, cls) {
  const div = document.createElement("div");
  div.className = "entry " + (cls || "");
  div.innerHTML = html;
  $("log").appendChild(div);
  $("log").scrollTop = $("log").scrollHeight;
}
function logSystem(t) { logEntry(esc(t), "system"); }
function esc(s) { return (s || "").replace(/[&<>]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c])); }

// --------------------------------------------------------------- render ----
function render(r) {
  if (r.server_online !== undefined) {
    const b = $("server-badge");
    b.textContent = r.server_online ? "● модель ONLINE" : "○ модель OFFLINE (фоллбэки)";
    b.className = "badge " + (r.server_online ? "online" : "offline");
  }
  if (r.text) {
    const cls = r.kind === "system" ? "system"
      : r.kind === "narration" ? "narration"
      : r.kind === "look" ? "system" : "";
    const head = r.speaker ? `<span class="speaker">${esc(r.speaker)}</span> ` : "";
    logEntry(head + esc(r.text), cls);
  }
  if (r.rolled_faces) logEntry(`🎲 выпало: [${r.rolled_faces.join(", ")}]`, "mech");
  if (r.view) updateView(r.view);
  if (r.kind === "look") { renderExits(r.exits); renderNpcs(r.npcs); renderQuick(); }
  if (r.combat) renderCombat(r.combat);
  else if (r.view && !r.view.in_combat) $("combat").classList.add("hidden");

  // лоток кубов
  const rr = r.roll_request || (r.view && r.view.pending_roll);
  if (rr) showDice(rr); else hideDice();
}

function updateView(v) {
  lastView = v;
  $("place-name").textContent = v.place_name || "—";
  $("clock").textContent = "🕑 " + (v.time || "—");
  const p = v.player;
  $("char").innerHTML =
    `<b>${esc(p.name)}</b> — уровень ${p.level}<br>AC ${p.ac}`;
  const pct = Math.max(0, 100 * p.hp / (p.max_hp || 1));
  $("hpfill").style.width = pct + "%";
  $("hptext").textContent = `HP ${p.hp} / ${p.max_hp}`;
  $("context").textContent = v.context || "";
  $("quests").innerHTML = (v.quests || []).map(q =>
    `<li><span class="state">[${q.state}]</span> ${esc(q.title)}` +
    (q.objective ? `<br><span class="obj">${esc(q.objective)}</span>` : "") + `</li>`
  ).join("") || "<li class='state'>нет активных</li>";
  $("journal").innerHTML = (v.journal || []).slice().reverse().map(e =>
    `<div class="jentry">${esc(e)}</div>`).join("") || "<span class='state'>пусто</span>";
  renderConnectivity(v.connectivity);
}

// информационное представление связности локаций (вместо тайл-карты)
function renderConnectivity(c) {
  if (!c) return;
  const conns = (c.connections || []).map(x => {
    const who = x.occupants && x.occupants.length
      ? `<span class="occ">${esc(x.occupants.join(", "))}</span>` : "";
    const dir = x.dir_ru ? `<span class="dir">${esc(x.dir_ru)}</span> ` : "";
    return `<div class="loc-edge">${dir}<span class="chip exit" data-go="${x.id}">${esc(x.name)}</span>${who}</div>`;
  }).join("");
  $("connectivity").innerHTML =
    `<div class="loc-here">📍 ${esc(c.current.name)}</div>` +
    `<div class="loc-list">${conns || "<span class='state'>нет связей</span>"}</div>`;
  $("connectivity").querySelectorAll("[data-go]").forEach(el => el.onclick = () => {
    logEntry(`<span class="you">→ идти: ${esc(el.textContent)}</span>`, "you");
    send({ cmd: "input", text: "идти в " + el.textContent });
  });
}

function renderExits(exits) {
  $("exits").innerHTML = "<span class='state'>выходы:</span> " + (exits || []).map(e =>
    `<span class="chip exit" data-go="${e.id}">${esc(e.name)}</span>`).join("");
  bindChips();
}
function renderNpcs(npcs) {
  $("npcs").innerHTML = (npcs && npcs.length ? "<span class='state'>рядом:</span> " : "")
    + (npcs || []).map(n => `<span class="chip npc" data-talk="${n.id}" data-name="${esc(n.name)}">${esc(n.name)}</span>`).join("");
  bindChips();
}
function renderQuick() {
  $("quick").innerHTML = [
    ["осмотреться", "осмотреться"], ["обыскать", "обыскать комнату"],
    ["инвентарь", "инвентарь"], ["ждать", "ждать"],
  ].map(([l, c]) => `<span class="chip" data-cmd="${c}">${l}</span>`).join("");
  bindChips();
}
function bindChips() {
  document.querySelectorAll("[data-go]").forEach(c => c.onclick = () =>
    send({ cmd: "input", text: "идти в " + c.textContent }));
  document.querySelectorAll("[data-talk]").forEach(c => c.onclick = () => {
    logEntry(`<span class="you">→ заговорить с ${esc(c.dataset.name)}</span>`, "you");
    send({ cmd: "input", text: "поговорить с " + c.dataset.name });
  });
  document.querySelectorAll("[data-cmd]").forEach(c => c.onclick = () => {
    logEntry(`<span class="you">→ ${esc(c.dataset.cmd)}</span>`, "you");
    send({ cmd: "input", text: c.dataset.cmd });
  });
}

// --------------------------------------------------------------- combat ----
// Тактический бой на канвасе: сетка, поверхности, подсветка хода, токены.
const SURFACE_COLORS = { fire: "#d9622b", grease: "#6b5a36", water: "#3a78b0",
  ice: "#9fd0e0", poison: "#5aa05a" };
let battleImg = null, battleImgSrc = null, combatMode = "select", lastCV = null;

function renderCombat(cv) {
  lastCV = cv;
  $("combat").classList.toggle("hidden", cv.mode !== "active");
  $("round").textContent = cv.round;
  drawBattle(cv);
  // трекер инициативы
  $("initiative").innerHTML = cv.combatants.map(c => {
    const cls = [c.side === "party" ? "pc" : "enemy", c.current ? "current" : "",
      c.hp <= 0 ? "dead" : ""].join(" ");
    const cond = (c.conditions || []).length ? " · " + c.conditions.join(",") : "";
    return `<li class="${cls}"><span class="name">${c.current ? "▶ " : ""}${esc(c.name)}</span>
      <span class="hp">HP ${c.hp}/${c.max_hp} · AC ${c.ac}${esc(cond)}</span></li>`;
  }).join("");
  // панель действий
  const acts = $("combat-actions");
  if (cv.is_pc_turn && cv.mode === "active") {
    const labels = { attack: "⚔ Атака", move: "🦶 Движение", dash: "💨 Рывок",
      dodge: "🛡 Уклон", disengage: "↩ Отход", shove: "✋ Толчок", end_turn: "⏭ Конец хода" };
    let html = `<span class="state">движение: ${cv.movement} фт ·</span> `;
    html += (cv.actions || []).map(a =>
      `<span class="chip cbtn ${combatMode === a ? 'active' : ''}" data-act="${a}">${labels[a] || a}</span>`).join("");
    acts.innerHTML = html;
    acts.querySelectorAll("[data-act]").forEach(b => b.onclick = () => onCombatAction(b.dataset.act));
  } else {
    acts.innerHTML = cv.mode === "active" ? "<span class='state'>ход противника…</span>"
      : `<span class='state'>${cv.outcome === 'victory' ? 'Победа!' : cv.outcome === 'tpk' ? 'Поражение' : 'Бой окончен'}</span>`;
  }
  $("combat-log").textContent = (cv.log || []).join("\n");
}

function onCombatAction(act) {
  if (act === "end_turn") { combatMode = "select"; send({ cmd: "combat_end_turn" }); }
  else if (act === "dash" || act === "dodge" || act === "disengage")
    send({ cmd: "combat_action", action: act });
  else if (act === "attack") combatMode = "attack";
  else if (act === "shove") combatMode = "shove";
  else if (act === "move") combatMode = "move";
  if (lastCV) drawBattle(lastCV);
  // подсветить активную кнопку
  document.querySelectorAll("#combat-actions [data-act]").forEach(b =>
    b.classList.toggle("active", b.dataset.act === combatMode));
}

function drawBattle(cv) {
  const cv2 = $("battle-canvas");
  if (!cv.grid) { cv2.style.display = "none"; return; }
  cv2.style.display = "block";
  const { cols, rows } = cv.grid;
  const cell = Math.floor(Math.min(700 / cols, 460 / rows));
  cv2.width = cols * cell; cv2.height = rows * cell;
  const ctx = cv2.getContext("2d");
  const paint = () => {
    ctx.clearRect(0, 0, cv2.width, cv2.height);
    if (battleImg && battleImg.complete) ctx.drawImage(battleImg, 0, 0, cv2.width, cv2.height);
    else { ctx.fillStyle = "#1a1712"; ctx.fillRect(0, 0, cv2.width, cv2.height); }
    // достижимость (ход PC)
    if (cv.is_pc_turn && (combatMode === "move" || combatMode === "select")) {
      ctx.fillStyle = "rgba(90,160,235,.34)";
      for (const [x, y] of cv.reachable || []) ctx.fillRect(x * cell, y * cell, cell, cell);
      ctx.strokeStyle = "rgba(150,200,255,.5)"; ctx.lineWidth = 1;
      for (const [x, y] of cv.reachable || []) ctx.strokeRect(x * cell + 0.5, y * cell + 0.5, cell - 1, cell - 1);
    }
    // поверхности
    for (const s of cv.surfaces || []) {
      ctx.fillStyle = SURFACE_COLORS[s.kind] || "#888"; ctx.globalAlpha = .45;
      ctx.fillRect(s.pos[0] * cell, s.pos[1] * cell, cell, cell); ctx.globalAlpha = 1;
    }
    // цели (красная рамка) в режиме атаки/толчка
    if (cv.is_pc_turn && (combatMode === "attack" || combatMode === "shove")) {
      ctx.strokeStyle = "#ff5a3c"; ctx.lineWidth = 2;
      for (const id of cv.targets || []) {
        const t = cv.combatants.find(c => c.id === id);
        if (t) ctx.strokeRect(t.pos[0] * cell + 2, t.pos[1] * cell + 2, cell - 4, cell - 4);
      }
    }
    // токены
    for (const c of cv.combatants) {
      if (c.fled) continue;
      const cx = c.pos[0] * cell + cell / 2, cy = c.pos[1] * cell + cell / 2, r = cell * 0.38;
      ctx.beginPath(); ctx.arc(cx, cy, r, 0, 7);
      ctx.fillStyle = c.hp <= 0 ? "#555" : (c.side === "party" ? "#3a6ea5" : "#b0402f");
      ctx.fill();
      ctx.lineWidth = c.current ? 3 : 1.5;
      ctx.strokeStyle = c.current ? "#d8b15a" : "#fff"; ctx.stroke();
      ctx.fillStyle = "#fff"; ctx.font = `bold ${Math.floor(cell * 0.4)}px serif`;
      ctx.textAlign = "center"; ctx.textBaseline = "middle";
      ctx.fillText((c.name || "?").trim()[0] || "?", cx, cy);
      // HP-полоска
      const bw = cell * 0.8, hp = Math.max(0, c.hp / (c.max_hp || 1));
      ctx.fillStyle = "#400"; ctx.fillRect(cx - bw / 2, cy + r + 1, bw, 3);
      ctx.fillStyle = c.side === "party" ? "#6abf4b" : "#d87a3a";
      ctx.fillRect(cx - bw / 2, cy + r + 1, bw * hp, 3);
    }
  };
  if (cv.battlemap && battleImgSrc !== cv.battlemap) {
    battleImgSrc = cv.battlemap; battleImg = new Image();
    battleImg.onload = paint; battleImg.src = cv.battlemap;
  }
  paint();
  cv2.onclick = (e) => onCanvasClick(e, cv, cell);
}

function onCanvasClick(e, cv, cell) {
  if (!cv.is_pc_turn) return;
  const rect = e.target.getBoundingClientRect();
  const x = Math.floor((e.clientX - rect.left) / cell);
  const y = Math.floor((e.clientY - rect.top) / cell);
  const onCell = cv.combatants.find(c => !c.fled && c.pos[0] === x && c.pos[1] === y);
  if ((combatMode === "attack" || combatMode === "select") && onCell && cv.targets.includes(onCell.id)) {
    send({ cmd: "combat_attack", target: onCell.id }); combatMode = "select";
  } else if (combatMode === "shove" && onCell && onCell.side === "enemy") {
    send({ cmd: "combat_action", action: "shove", target: onCell.id }); combatMode = "select";
  } else if (!onCell && (cv.reachable || []).some(c => c[0] === x && c[1] === y)) {
    send({ cmd: "combat_move", cell: [x, y] });
  }
}

// ----------------------------------------------------------------- dice ----
let pendingRoll = null;
function showDice(rr) {
  pendingRoll = rr;
  $("dice-tray").classList.remove("hidden");
  const dc = rr.dc != null ? ` · DC ${rr.dc}` : " · DC скрыт";
  $("dice-info").innerHTML = `${esc(rr.kind)}: <b>${rr.dice}</b> модификатор ${rr.modifier >= 0 ? "+" : ""}${rr.modifier}${dc}`
    + (rr.advantage > 0 ? " · преимущество" : rr.advantage < 0 ? " · помеха" : "");
  $("dice-result").innerHTML = "";
  $("roll-btn").disabled = false;
}
function hideDice() { $("dice-tray").classList.add("hidden"); pendingRoll = null; }
$("roll-btn").onclick = () => {
  $("roll-btn").disabled = true;
  $("dice-result").innerHTML = "<span>…</span>";
  // анимация к серверному результату (server-authoritative animated, док 07 §8)
  let ticks = 0;
  const faces = pendingRoll.dice.includes("d20") ? 20 : 8;
  const anim = setInterval(() => {
    $("dice-result").textContent = String(1 + Math.floor(Math.random() * faces));
    if (++ticks > 8) { clearInterval(anim); send({ cmd: "roll" }); }
  }, 60);
};

// ----------------------------------------------------------------- input ---
$("input-form").onsubmit = (e) => {
  e.preventDefault();
  const t = $("input").value.trim();
  if (!t) return;
  logEntry(`<span class="you">→ ${esc(t)}</span>`, "you");
  send({ cmd: "input", text: t });
  $("input").value = "";
};

connect();
