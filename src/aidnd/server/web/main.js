// L9 фронтенд: WebSocket-клиент. Никакого browser storage — всё состояние на
// сервере в event log; фронт держит только отображение (main §11).

const $ = (id) => document.getElementById(id);
let ws, lastView = null;
let ME = null;

function connect() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  ws = new WebSocket(`${proto}://${location.host}/ws`);   // cookie сессии уходит на хендшейк автоматически
  ws.onmessage = (e) => render(JSON.parse(e.data));
  ws.onclose = () => logSystem("Соединение закрыто. Обнови страницу.");
}
function send(obj) { ws.send(JSON.stringify(obj)); }

// ---------------------------------------------------------------- auth ----
async function logout() {
  await fetch("/auth/logout", { method: "POST" }).catch(() => {});
  location.href = "/login";
}
function updateAccountBtn() {
  const b = $("account-btn"); if (b) b.textContent = ME ? ("👤 " + (ME.email || "вы")) : "👤 Войти";
}
function renderUsage(u) {                                   // счётчик лимита в шапке + текст в настройках
  if (!u) return;
  const hud = $("usage-hud");
  if (hud) { hud.classList.remove("hidden"); hud.textContent = u.unlimited ? "∞ безлимит" : `⚡ ${u.requests.used}/${u.requests.free}`; }
  if ($("set-usage")) $("set-usage").textContent = u.unlimited
    ? "Тариф: безлимит ∞"
    : `Запросы ${u.requests.used}/${u.requests.free} · миры ${u.enrich.used}/${u.enrich.free}`;
}

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

// всплывающая «ачивка»: слайд-ин справа, авто-исчезание
function showToast(t) {
  const box = $("toasts"); if (!box) return;
  const el = document.createElement("div");
  el.className = "toast toast-" + (t.kind || "event");
  el.innerHTML = `<div class="toast-icon">${esc(t.icon || "🏆")}</div>`
    + `<div class="toast-body"><div class="toast-title">${esc(t.title || "")}</div>`
    + (t.text ? `<div class="toast-text">${esc(t.text)}</div>` : "") + `</div>`;
  box.appendChild(el);
  requestAnimationFrame(() => el.classList.add("in"));
  setTimeout(() => { el.classList.add("out"); setTimeout(() => el.remove(), 450); }, 4600);
}

// дебаг-трейс роутинга: в какие модели ушёл ввод (router→intent→narrator…), с длительностью
function shortModel(m) { return (m || "").replace(/:latest$/, "").replace(/^aidnd-/, ""); }
function showRouting(steps) {
  if (!steps || !steps.length) return;
  const chain = steps.map(s => `${s.role}·${shortModel(s.model)} ${s.ms}ms`).join("  →  ");
  logEntry("🔀 " + esc(chain), "routing");
}

// «мышление» в реальном времени: процент обработки ответа (всегда) + живой роутинг-чейн (в дебаге)
const ROLE_RU = { router: "маршрут", cognition: "память", narrator: "рассказчик", event_director: "события",
  arbiter: "арбитр", consequence: "последствия", plausibility: "проверка", lore_keeper: "знания", quest_writer: "квест" };
let thinkingEl = null;
function showThinking(f) {
  if (!thinkingEl) { thinkingEl = document.createElement("div"); thinkingEl.className = "entry thinking"; $("log").appendChild(thinkingEl); }
  const pct = Math.min(92, Math.round((f.step / (f.est || 5)) * 100));
  const dbg = $("dbg-routing") && $("dbg-routing").checked;
  const body = dbg
    ? (f.chain || []).map(s => `${ROLE_RU[s.role] || s.role}·${shortModel(s.model)}`).join(" → ")
    : "Обрабатываю ответ…";
  thinkingEl.innerHTML = `⏳ ${esc(body)} <span class="thinking-pct">${pct}%</span>`;
  $("log").scrollTop = $("log").scrollHeight;
}
function clearThinking() { if (thinkingEl) { thinkingEl.remove(); thinkingEl = null; } }
// журнал квестов — подробные записи (лор + стадии)
function openJournal() {
  openOverlay("questlog");
  $("jr-list").innerHTML = "<div class='state'>Загрузка…</div>";
  send({ cmd: "journal" });
}
function renderJournal(entries) {
  const box = $("jr-list");
  if (!entries || !entries.length) { box.innerHTML = "<div class='state'>Активных квестов пока нет.</div>"; return; }
  const tag = k => k === "main" ? "ОСНОВНОЙ" : k === "board" ? "ДОСКА" : "ПОБОЧКА";
  box.innerHTML = entries.map(q => {
    const stages = (q.stages || []).map(s =>
      `<li class="${s.done ? 'jr-done' : s.current ? 'jr-cur' : ''}">${s.done ? '✓' : s.current ? '▸' : '·'} ${esc(s.objective)}</li>`).join("");
    const meta = [q.giver ? "Даёт: " + esc(q.giver) : "", q.reward ? "Награда: " + esc(q.reward) : ""].filter(Boolean).join(" · ");
    return `<div class="jr-entry jr-${esc(q.kind)}">
      <div class="jr-head"><span class="jr-tag">${tag(q.kind)}</span><b>${esc(q.title)}</b>${q.state === "completed" ? " <span class='jr-ok'>✓ выполнен</span>" : ""}</div>
      <div class="jr-brief">${esc(q.brief || "")}</div>
      <ul class="jr-stages">${stages}</ul>${meta ? `<div class="jr-meta">${meta}</div>` : ""}</div>`;
  }).join("");
}
(() => {                                       // тумблер «роутинг» — состояние в localStorage
  const c = document.getElementById("dbg-routing"); if (!c) return;
  c.checked = localStorage.getItem("dbgRouting") === "1";
  c.addEventListener("change", () => localStorage.setItem("dbgRouting", c.checked ? "1" : "0"));
})();

// --------------------------------------------------------------- render ----
function render(r) {
  if (r.user) { ME = r.user; updateAccountBtn(); }                  // авторизованы → имя в кнопке
  if (r.usage) renderUsage(r.usage);                                // шкала лимитов
  if (r.kind === "auth_required") { location.href = "/login"; return; }
  if (r.kind === "limit") { logSystem(r.text || "Лимит исчерпан."); openOverlay("settings-ov"); return; }
  if (r.kind === "redeem") { logSystem(r.text || ""); if ($("set-msg")) $("set-msg").textContent = r.text || ""; return; }
  if (r.server_online !== undefined) {
    const b = $("server-badge");
    b.textContent = r.server_online ? "● модель ONLINE" : "○ модель OFFLINE (фоллбэки)";
    b.className = "badge " + (r.server_online ? "online" : "offline");
  }
  if (r.kind === "loading") {                            // ползунок генерации новой игры
    $("loading").classList.remove("hidden");
    const pct = (r.total > 0) ? Math.round(100 * r.done / r.total) : null;
    const fill = $("load-fill");
    fill.classList.toggle("indet", pct === null);
    fill.style.width = (pct === null ? 100 : Math.max(4, pct)) + "%";
    $("load-label").textContent = r.label || "Генерация…";
    $("load-pct").textContent = pct === null ? "" : pct + "%";
    return;
  }
  if (r.kind === "thinking") { showThinking(r); return; }         // живой прогресс/роутинг ответа
  clearThinking();                                                // любой реальный результат — убираем индикатор
  if (r.toasts && r.toasts.length) r.toasts.forEach(showToast);   // «ачивки»
  if (r.kind === "menu") {                                        // панель миров (только для залогиненных)
    if (!r.user) { location.href = "/login"; return; }            // не залогинен → страница логина
    menuShown = true; hasGame = false; setMenuMode(false);
    lobbyGames = r.games || []; lobbySaves = r.saves || null;
    showLobby();
  }
  if (r.kind === "journal") renderJournal(r.journal);             // подробный журнал квестов
  if (r.text) {
    const cls = r.kind === "system" ? "system"
      : r.kind === "narration" ? "narration"
      : r.kind === "look" ? "system" : "";
    const head = r.speaker ? `<span class="speaker">${esc(r.speaker)}</span> ` : "";
    logEntry(head + esc(r.text), cls);
  }
  document.querySelectorAll(".record-signs").forEach(b => b.remove());   // прошлый офер вывесок истёк
  if (r.signs_offer && r.signs_offer.length) {            // увидел вывески → кнопка «записать на карту»
    const b = document.createElement("button");
    b.className = "cbtn record-signs";
    b.textContent = "📍 Записать на карту";
    b.onclick = () => { b.disabled = true; send({ cmd: "record_signs" }); };
    $("log").appendChild(b); $("log").scrollTop = $("log").scrollHeight;
  }
  if (r.routing && $("dbg-routing") && $("dbg-routing").checked) showRouting(r.routing);  // дебаг роутинга
  if (r.clarify_places && r.clarify_places.length) {     // уточнение «куда именно» → кнопки выбора
    const div = document.createElement("div");
    div.className = "entry system"; div.style.cssText = "display:flex;gap:6px;flex-wrap:wrap";
    r.clarify_places.forEach(o => {
      const b = document.createElement("button"); b.className = "cbtn"; b.textContent = o.name;
      b.onclick = () => { logEntry(`<span class="you">→ ${esc(o.name)}</span>`, "you"); send({ cmd: "travel", place: o.id }); };
      div.appendChild(b);
    });
    $("log").appendChild(div); $("log").scrollTop = $("log").scrollHeight;
  }
  if (r.rolled_faces) logEntry(`🎲 выпало: [${r.rolled_faces.join(", ")}]`, "mech");
  if (r.kind === "house" && r.house) renderHouse(r.house);
  if (r.kind === "saved") { logSystem(`💾 Сохранено: «${r.card ? (r.card.title || r.card.name || "") : ""}»`); if (r.games) { lobbyGames = r.games; if (!$("lobby").classList.contains("hidden")) renderLobby(); } }
  if (r.kind === "saves") { if (r.games) lobbyGames = r.games; if (!$("lobby").classList.contains("hidden")) renderLobby(); }
  if (r.view) updateView(r.view);
  if (r.travel_far) openOverlay("mapview");           // «далеко — открой карту»: сразу показываем карту для маршрута
  if (r.kind === "error" && !$("levelup").classList.contains("hidden")) $("lvl-msg").textContent = r.text;
  if (r.kind === "look") {                               // игра началась/загружена — прячем стартовые экраны
    ["loading", "lobby", "newgame", "loadgame"].forEach(id => { const e = $(id); if (e) e.classList.add("hidden"); });
    hasGame = true; setMenuMode(true);
    renderExits(r.exits); renderNpcs(r.npcs); renderQuick();
  }
  if (r.combat) renderCombat(r.combat);
  else if (r.view && !r.view.in_combat) $("combat").classList.add("hidden");

  // лоток кубов
  const rr = r.roll_request || (r.view && r.view.pending_roll);
  if (rr) showDice(rr); else hideDice();
}

function updateView(v) {
  lastView = v;
  $("place-name").textContent = v.place_path || v.place_name || "—";   // хлебные крошки: Здание → Комната
  $("clock").textContent = "🕑 " + (v.time || "—");
  const p = v.player, pr = v.progression;
  const xppct = p.xp_next ? Math.min(100, 100 * p.xp / p.xp_next) : 100;
  const xpline = p.xp_next ? `XP ${p.xp} / ${p.xp_next}` : `XP ${p.xp} (макс.)`;
  let sheet = `<b>${esc(p.name)}</b><br>${p.class_name ? esc(p.class_name) + " · " : ""}${p.level} ур. · AC ${p.ac}`
    + `<div class="xpbar"><i style="width:${xppct}%"></i></div>`
    + `<div style="font-size:11px;color:var(--muted)">${xpline}</div>`;
  if (pr && pr.features && pr.features.length)
    sheet += `<div class="sheet-feats"><b>Умения:</b> ${pr.features.map(esc).join(", ")}${pr.subclass ? " · " + esc(pr.subclass) : ""}</div>`;
  if (pr && pr.spells && pr.spells.length) {
    const slots = Object.entries(pr.slots || {}).map(([l, n]) => `${l}🔹${n}`).join(" ");
    sheet += `<div class="sheet-feats"><b>Заклинания:</b> ${pr.spells.map(s => esc(s.name)).join(", ")}`
      + (slots ? `<br><span style="color:var(--gold)">ячейки ${slots}</span>` : "") + `</div>`;
  }
  if (v.levelup) sheet += `<button class="lvl-btn" id="char-levelup">⬆ Повысить уровень${v.levelup.remaining > 1 ? " (" + v.levelup.remaining + ")" : ""}</button>`;
  $("char").innerHTML = sheet;
  if (v.levelup) $("char-levelup").onclick = () => openLevelup(v.levelup);
  if (!$("levelup").classList.contains("hidden")) {        // живое обновление открытого диалога апа
    if (v.levelup) renderLevelup(v.levelup); else closeOverlay("levelup");
  }
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
  renderFactionsPanel(v.factions);
  if (!$("trade").classList.contains("hidden")) renderTrade(v.shop);   // живое обновление при открытом окне
  if (!$("mapview").classList.contains("hidden")) renderMap(v.map_levels);
  if (!$("factionview").classList.contains("hidden")) renderFactionsOverlay(v.factions);
  if (!$("board").classList.contains("hidden")) renderBoard(v.board);
  if (!$("inv").classList.contains("hidden")) renderInventory(v.inventory);
}

// ------------------------------------------------ доска объявлений ---------
function renderBoard(b) {
  const box = $("board-list");
  if (!b || !b.quests || !b.quests.length) { box.innerHTML = "<div class='saves-empty'>Объявлений нет.</div>"; return; }
  box.innerHTML = b.quests.map(q => {
    let act;
    if (q.can_accept) act = `<button data-accept="${q.id}">Взять</button>`;
    else if (q.can_turn_in) act = `<button data-turnin="${q.id}">Сдать</button>`;
    else if (q.state === "active") act = `<span class="note">в работе…</span>`;
    else if (q.state === "completed") act = `<span class="note">✓ сдано</span>`;
    else act = "";
    return `<div class="fac-card ${q.state === "completed" ? "member" : ""}"><h3>📜 ${esc(q.title)}<span class="sp"></span>`
      + `<span class="stand" style="color:var(--gold)">${esc(q.reward)}</span></h3>`
      + `<div class="blurb">${esc(q.framing)}</div>`
      + `<div class="meta"><b>Задача:</b> ${esc(q.objective)}</div>`
      + `<div class="acts">${act}</div></div>`;
  }).join("");
  box.querySelectorAll("[data-accept]").forEach(el => el.onclick = () => send({ cmd: "quest_accept", quest: el.dataset.accept }));
  box.querySelectorAll("[data-turnin]").forEach(el => el.onclick = () => send({ cmd: "quest_turnin", quest: el.dataset.turnin }));
}

// ----------------------------------------------- инвентарь / экипировка ----
function renderInventory(inv) {
  if (!inv) return;
  $("inv-ac").textContent = "КД " + inv.ac;
  $("inv-wallet").textContent = "Кошелёк: " + inv.wallet;
  $("inv-slots").innerHTML = Object.entries(inv.slots).map(([slot, name]) =>
    `<div class="inv-slot"><div class="sl">${esc(slot)}</div><div class="it">${name ? esc(name) : '<span class="empty">— пусто —</span>'}</div></div>`).join("");
  const box = $("inv-list");
  box.innerHTML = inv.items.map(it => {
    let act = "";
    if (it.equipped) act += `<button class="leave" data-uneq="${it.id}">Снять</button>`;
    else if (it.equippable) act += `<button data-eq="${it.id}">Надеть</button>`;
    if (it.usable) act += `<button data-use="${it.id}">Использовать</button>`;
    const tag = it.equipped ? ` · надето (${esc(it.slot_ru)})` : "";
    return `<div class="fac-card ${it.equipped ? "member" : ""}"><h3>${esc(it.name)}<span class="sp"></span>`
      + `<span class="stand" style="color:var(--muted)">${esc(it.category)}${tag}</span></h3>`
      + (it.desc ? `<div class="blurb">${esc(it.desc)}</div>` : "")
      + (act ? `<div class="acts">${act}</div>` : "") + `</div>`;
  }).join("") || "<div class='saves-empty'>Сумка пуста.</div>";
  box.querySelectorAll("[data-eq]").forEach(b => b.onclick = () => send({ cmd: "equip", item: b.dataset.eq }));
  box.querySelectorAll("[data-uneq]").forEach(b => b.onclick = () => send({ cmd: "unequip", item: b.dataset.uneq }));
  box.querySelectorAll("[data-use]").forEach(b => b.onclick = () => send({ cmd: "use_item", item: b.dataset.use }));
}

// ----------------------------------------------------------- фракции -------
function facName(f, id) { const x = (f.list || []).find(y => y.id === id); return x ? x.name : id; }
function renderFactionsPanel(f) {
  const box = $("factions");
  if (!f || !f.list || !f.list.length) { box.innerHTML = "<span class='state'>пока ничего не известно — узнавай в разговорах</span>"; return; }
  box.innerHTML = f.list.map(x =>
    `<div class="fac-mini" data-fac="${x.id}"><span class="em">${x.emblem}</span>`
    + `<span class="nm">${esc(x.name)}${x.member ? ' <span class="you">✓</span>' : ""}</span>`
    + `<span class="stand" style="color:${x.standing_color}">${esc(x.standing_label)}</span></div>`).join("");
  box.querySelectorAll("[data-fac]").forEach(el => el.onclick = () => openFactions(el.dataset.fac));
}
function openFactions(focusId) {
  openOverlay("factionview");
  if (lastView && lastView.factions) renderFactionsOverlay(lastView.factions);
  if (focusId) send({ cmd: "faction_inspect", faction: focusId });    // ленивое LLM-обогащение
}
function renderFactionsOverlay(f) {
  if (!f) return;
  $("fac-membership").textContent = f.membership ? "— ты в «" + facName(f, f.membership) + "»" : "— ты вне фракций";
  if (!f.list.length) { $("fac-list").innerHTML = "<div class='saves-empty'>Ты пока не слышал ни об одной фракции. О них узнают в разговорах с местными и из книг.</div>"; return; }
  $("fac-list").innerHTML = f.list.map(x => {
    const goals = x.goals.length ? `<div class="meta"><b>Цели:</b> ${x.goals.map(esc).join("; ")}</div>` : "";
    const vals = x.values.length ? `<div class="meta"><b>Ценности:</b> ${x.values.map(esc).join(", ")}</div>` : "";
    const rel = x.relations.length ? `<div class="meta">Отношения: ${x.relations.map(r => `${esc(r.name)} ${r.value > 0 ? "+" : ""}${r.value}`).join(", ")}</div>` : "";
    let act;
    if (x.member) act = `<button class="leave" data-leave="1">Покинуть</button><span class="note">ранг: ${esc(x.rank || "—")}</span>`;
    else if (!x.joinable) act = `<span class="note">вступление невозможно</span>`;
    else if (x.can_join) act = `<button data-join="${x.id}">Вступить</button>`;
    else act = `<button disabled>Вступить</button><span class="note">нужна репутация ≥ ${x.join_min_rep}</span>`;
    return `<div class="fac-card ${x.member ? "member" : ""}"><h3><span>${x.emblem}</span> ${esc(x.name)}<span class="sp"></span>`
      + `<span class="stand" style="color:${x.standing_color}">${esc(x.standing_label)} ${x.standing > 0 ? "+" : ""}${x.standing}</span></h3>`
      + `<div class="blurb" data-inspect="${x.id}" title="нажми — описать подробнее">${esc(x.blurb || "…")}</div>`
      + goals + vals + rel + `<div class="acts">${act}</div></div>`;
  }).join("");
  $("fac-list").querySelectorAll("[data-join]").forEach(b => b.onclick = () => send({ cmd: "faction_join", faction: b.dataset.join }));
  $("fac-list").querySelectorAll("[data-leave]").forEach(b => b.onclick = () => send({ cmd: "faction_leave" }));
  $("fac-list").querySelectorAll("[data-inspect]").forEach(b => b.onclick = () => send({ cmd: "faction_inspect", faction: b.dataset.inspect }));
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
  const cmds = [["осмотреться", "осмотреться"], ["обыскать", "обыскать комнату"], ["ждать", "ждать"]];
  $("quick").innerHTML = cmds.map(([l, c]) => `<span class="chip" data-cmd="${c}">${l}</span>`).join("")
    + `<span class="chip" data-open="inv">🎒 инвентарь</span>`
    + `<span class="chip" data-open="mapview">🗺 карта</span>`
    + `<span class="chip" data-open="trade">🛒 лавка</span>`
    + ((lastView && lastView.board) ? `<span class="chip" data-open="board">📜 доска</span>` : "");
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
  document.querySelectorAll("[data-open]").forEach(c => c.onclick = () => openOverlay(c.dataset.open));
}

// ---------------------------------------------------- торговля + карта ----
function openOverlay(id) {
  if (id === "trade") {
    if (!lastView || !lastView.shop) { logSystem("Рядом нет лавки."); return; }
    renderTrade(lastView.shop);
  }
  if (id === "mapview" && lastView) renderMap(lastView.map_levels);
  if (id === "board" && lastView) renderBoard(lastView.board);
  if (id === "inv" && lastView) renderInventory(lastView.inventory);
  $(id).classList.remove("hidden");
}
function closeOverlay(id) { $(id).classList.add("hidden"); }

// ----------------------------------------------- меню / новая игра / сейвы ----
let ngOpts = null, ngSel = { scenario: null, klass: null, kit: null, skills: [], l1: {} }, lvlSel = {}, menuShown = false, hasGame = false;
let lobbyGames = null, lobbySaves = null;                // что показывать в «Загрузить»: игры юзера или файловые сейвы

// «Продолжить»/«Сохранить» в лобби — только когда игра уже есть
function setMenuMode(game) {
  ["lb-continue", "lb-save"].forEach(id => { const e = $(id); if (e) e.style.display = game ? "" : "none"; });
}
function showLobby() {                                   // показать панель миров (скрыв подэкраны)
  ["newgame", "loadgame"].forEach(id => $(id).classList.add("hidden"));
  renderLobby();
  $("lobby").classList.remove("hidden");
}
function renderLobby() {                                 // панель управления мирами (карточки игр юзера)
  const box = $("lobby-list"); if (!box) return;
  const games = lobbyGames || [];
  if (!games.length) {
    box.innerHTML = '<div class="lobby-empty">Пока нет миров. Нажми «Новый мир», чтобы начать.</div>';
    return;
  }
  box.innerHTML = games.map(g => {
    const m = g.meta || {};
    return `<div class="world-card"><div class="info"><div class="nm">${esc(g.title || "Мир")}</div>`
      + `<div class="sub2">${esc(m.klass || "")}${m.klass ? " · " : ""}${esc(m.place || "")}${m.time ? " · 🕑 " + esc(m.time) : ""}</div></div>`
      + `<div class="world-acts"><button data-play="${g.id}">▶ Играть</button>`
      + `<button class="del" data-del="${g.id}" title="Удалить">✕</button></div></div>`;
  }).join("");
  box.querySelectorAll("[data-play]").forEach(b => b.onclick = () => { send({ cmd: "load", game_id: +b.dataset.play }); logSystem("📂 Загрузка мира…"); });
  box.querySelectorAll("[data-del]").forEach(b => b.onclick = () => send({ cmd: "delete_save", game_id: +b.dataset.del }));
}

async function ensureNgOptions() {
  if (!ngOpts) {
    try { const r = await fetch("/new_game_options"); ngOpts = r.ok ? await r.json() : null; }
    catch (e) { ngOpts = { classes: [], kits: [], scenarios: [] }; }
  }
  renderNgForm();
}
function ngCard(grp, id, title, desc, sel) {
  return `<div class="ng-card ${sel ? "sel" : ""}" data-grp="${grp}" data-id="${id}">`
    + `<div class="t">${esc(title)}</div><div class="d">${esc(desc)}</div></div>`;
}
function renderNgForm() {
  if (!ngOpts) return;
  if (!ngSel.scenario && ngOpts.scenarios[0]) ngSel.scenario = ngOpts.scenarios[0].id;
  if (!ngSel.klass && ngOpts.classes[0]) { ngSel.klass = ngOpts.classes[0].id; ngSel.kit = ngOpts.classes[0].kit; }
  $("ng-scenarios").innerHTML = ngOpts.scenarios.map(s => ngCard("scenario", s.id, s.name, s.desc, s.id === ngSel.scenario)).join("");
  $("ng-classes").innerHTML = ngOpts.classes.map(c => ngCard("klass", c.id, c.name, c.desc, c.id === ngSel.klass)).join("");
  $("ng-kits").innerHTML = ngOpts.kits.map(k => ngCard("kit", k.id, k.name, k.blurb, k.id === ngSel.kit)).join("");
  const cls = ngOpts.classes.find(c => c.id === ngSel.klass), need = cls ? cls.skill_count : 0;
  $("ng-skill-hint").textContent = cls ? `выбери ${ngSel.skills.length} / ${need}` : "";
  $("ng-skills").innerHTML = cls ? cls.skills.map(sk => {
    const sel = ngSel.skills.includes(sk.id), dim = !sel && ngSel.skills.length >= need;
    return `<span class="ng-chip ${sel ? "sel" : ""} ${dim ? "dim" : ""}" data-skill="${sk.id}">${esc(sk.name)}</span>`;
  }).join("") : "";
  // особенность 1 уровня (стиль воина / домен жреца / экспертиза плута)
  const l1 = (cls && cls.l1) || [];
  $("ng-l1-wrap").style.display = l1.length ? "" : "none";
  $("ng-l1").innerHTML = l1.map(ch => {
    const opts = ch.from === "skills"
      ? ngSel.skills.map(sid => { const sk = cls.skills.find(x => x.id === sid); return { id: sid, name: sk ? sk.name : sid, desc: "" }; })
      : ch.options;
    const multi = ch.pick > 1 || ch.id === "expertise";
    const sel = ngSel.l1[ch.id];
    const cards = opts.length ? opts.map(o => {
      const on = multi ? (Array.isArray(sel) && sel.includes(o.id)) : sel === o.id;
      return `<div class="ng-card ${on ? "sel" : ""}" data-opt="${o.id}"><div class="t">${esc(o.name)}</div>${o.desc ? `<div class="d">${esc(o.desc)}</div>` : ""}</div>`;
    }).join("") : `<div class="d" style="color:var(--muted)">сначала выбери навыки</div>`;
    return `<div><h4>${esc(ch.label)}</h4><div class="ng-cards" data-l1="${ch.id}" data-pick="${ch.pick}" data-multi="${multi ? 1 : 0}">${cards}</div></div>`;
  }).join("");
  document.querySelectorAll("#newgame .ng-card[data-grp]").forEach(el => el.onclick = () => {
    const g = el.dataset.grp, id = el.dataset.id;
    if (g === "scenario") ngSel.scenario = id;
    else if (g === "klass") { ngSel.klass = id; ngSel.skills = []; ngSel.l1 = {}; const c = ngOpts.classes.find(x => x.id === id); if (c) ngSel.kit = c.kit; }  // класс сбрасывает навыки и особенность
    else ngSel.kit = id;
    renderNgForm();
  });
  document.querySelectorAll("#ng-skills .ng-chip").forEach(el => el.onclick = () => {
    const id = el.dataset.skill;
    if (ngSel.skills.includes(id)) ngSel.skills = ngSel.skills.filter(x => x !== id);
    else if (ngSel.skills.length < need) ngSel.skills.push(id);
    renderNgForm();
  });
  document.querySelectorAll("#ng-l1 .ng-cards").forEach(g => {
    const cid = g.dataset.l1, pick = +g.dataset.pick, multi = g.dataset.multi === "1";
    g.querySelectorAll(".ng-card").forEach(card => card.onclick = () => {
      const opt = card.dataset.opt;
      if (multi) { const arr = ngSel.l1[cid] || []; ngSel.l1[cid] = arr.includes(opt) ? arr.filter(x => x !== opt) : (arr.length < pick ? [...arr, opt] : arr); }
      else ngSel.l1[cid] = opt;
      renderNgForm();
    });
  });
}
function startNewGame() {
  send({ cmd: "new_game", scenario: ngSel.scenario, klass: ngSel.klass, kit: ngSel.kit,
         skills: ngSel.skills, l1: ngSel.l1, name: $("ng-name").value || "Герой" });
  closeOverlay("newgame"); $("lobby").classList.add("hidden");
  $("loading").classList.remove("hidden");              // сразу показываем ползунок
  $("load-fill").classList.add("indet"); $("load-fill").style.width = "100%";
  $("load-label").textContent = "Строю мир…"; $("load-pct").textContent = "";
  logSystem("🆕 Новая игра…");
}
// ---- повышение уровня (выборы 5e) ----
function openLevelup(lv) { openOverlay("levelup"); renderLevelup(lv); }
function renderLevelup(lv) {
  $("lvl-title").textContent = `${lv.class_name}: ${lv.from} → ${lv.to}` + (lv.remaining > 1 ? ` (ещё ${lv.remaining})` : "");
  lvlSel = {}; $("lvl-msg").textContent = "";
  const box = $("lvl-choices");
  if (!lv.choices.length) { box.innerHTML = '<div class="ng-card"><div class="d">Только улучшения уровня (HP, бонус мастерства). Нажми «Подтвердить».</div></div>'; return; }
  box.innerHTML = lv.choices.map(ch => {
    const multi = ch.id === "spells" || ch.id === "expertise" || ch.pick > 1;
    return `<div><h3>${esc(ch.label)}</h3><div class="ng-cards" data-choice="${ch.id}" data-pick="${ch.pick}" data-multi="${multi ? 1 : 0}">`
      + ch.options.map(o => `<div class="ng-card" data-opt="${esc(o.id)}"><div class="t">${esc(o.name)}</div>${o.desc ? `<div class="d">${esc(o.desc)}</div>` : ""}</div>`).join("") + `</div></div>`;
  }).join("");
  document.querySelectorAll("#lvl-choices .ng-cards").forEach(group => {
    const cid = group.dataset.choice, pick = +group.dataset.pick, multi = group.dataset.multi === "1";
    group.querySelectorAll(".ng-card").forEach(card => card.onclick = () => {
      const opt = card.dataset.opt;
      if (multi) {
        const arr = lvlSel[cid] || [];
        lvlSel[cid] = arr.includes(opt) ? arr.filter(x => x !== opt) : (arr.length < pick ? [...arr, opt] : arr);
      } else lvlSel[cid] = opt;
      group.querySelectorAll(".ng-card").forEach(c => {
        const on = multi ? (lvlSel[cid] || []).includes(c.dataset.opt) : lvlSel[cid] === c.dataset.opt;
        c.classList.toggle("sel", !!on);
      });
    });
  });
}
function applyLevelup() { send({ cmd: "levelup", selections: lvlSel }); }
async function openLoad() {
  $("lobby").classList.add("hidden"); openOverlay("loadgame");
  if (lobbyGames) { renderSaves(lobbyGames); return; }    // авторизован → игры из БД (пришли в меню)
  try { const r = await fetch("/saves"); if (r.ok) renderSaves((await r.json()).saves); } catch (e) {}
}
function fmtDate(ts) { if (!ts) return ""; try { return new Date(ts * 1000).toLocaleString("ru-RU", { dateStyle: "short", timeStyle: "short" }); } catch (e) { return ""; } }
function renderSaves(list) {
  const box = $("saves-list");
  if (!list || !list.length) { box.innerHTML = '<div class="saves-empty">Сохранений пока нет.</div>'; return; }
  box.innerHTML = list.map(s => {
    const m = s.meta || {}, isGame = s.id != null, key = isGame ? s.id : s.slug;
    return `<div class="save-row"><div class="info"><div class="nm">${esc(s.title || s.name || s.slug)}</div>`
      + `<div class="sub2">${esc(m.klass || "")} · ${esc(m.place || "")} · 🕑 ${esc(m.time || "")}</div></div>`
      + `<button data-load="${esc(key)}" data-game="${isGame ? 1 : 0}">Загрузить</button>`
      + `<button class="del" data-del="${esc(key)}" data-game="${isGame ? 1 : 0}">Удалить</button></div>`;
  }).join("");
  box.querySelectorAll("[data-load]").forEach(b => b.onclick = () => {
    send(b.dataset.game === "1" ? { cmd: "load", game_id: +b.dataset.load } : { cmd: "load", slug: b.dataset.load });
    closeOverlay("loadgame"); logSystem("📂 Загрузка…");
  });
  box.querySelectorAll("[data-del]").forEach(b => b.onclick = () =>
    send(b.dataset.game === "1" ? { cmd: "delete_save", game_id: +b.dataset.del } : { cmd: "delete_save", slug: b.dataset.del }));
}
function doSave() {
  const def = lastView ? `${(lastView.player && lastView.player.name) || "Герой"} — ${lastView.place_name || ""}` : "Сейв";
  const name = window.prompt("Название сохранения:", def);
  if (name) send({ cmd: "save", name });
}

function renderTrade(shop) {
  if (!shop) { $("trade-goods").innerHTML = "<span class='state'>лавка закрыта</span>"; $("trade-sell").innerHTML = ""; return; }
  $("trade-merchant").textContent = shop.merchant;
  $("trade-wallet").textContent = `Кошелёк: ${shop.wallet} · торгует: ${shop.deals_in.join(", ") || "всем"}`;
  const row = (g, verb) => {
    const bare = g.name.split("×")[0].trim();
    const desc = g.desc ? `<small>${esc(g.desc)}</small>` : "";
    return `<div class="trade-row"><span class="nm">${esc(g.name)}${desc}</span>`
      + `<span class="pr">${g.price_gp} зм</span>`
      + `<button data-trade="${verb} ${esc(bare)}">${verb === "купить" ? "Купить" : "Продать"}</button></div>`;
  };
  $("trade-goods").innerHTML = (shop.goods || []).map(g => row(g, "купить")).join("") || "<span class='state'>пусто</span>";
  $("trade-sell").innerHTML = (shop.sellable || []).map(g => row(g, "продать")).join("") || "<span class='state'>нечего продать</span>";
  document.querySelectorAll("[data-trade]").forEach(b => b.onclick = () => {
    logEntry(`<span class="you">→ ${esc(b.dataset.trade)}</span>`, "you");
    send({ cmd: "input", text: b.dataset.trade });
  });
}

let mapLevel = null, townBuildings = null, townSeed = null, mapHits = [];
async function ensureTown(seed) {
  if (townSeed === seed && townBuildings) return;
  try { const r = await fetch("/town_layout?seed=" + seed); if (r.ok) { townBuildings = (await r.json()).buildings || []; townSeed = seed; } }
  catch (e) { townBuildings = []; }
}
let mapMode = "region", citySel = null, cityState = null, cityCur = 0, cityStep = 0, cityQuiet = 2, cityMarks = [];
// HiDPI: рисуем во внутренний бэк-стор ~2× (CSS ужимает обратно) → резкие карты/подписи.
// Геометрия карт строится от W/H, поэтому больший бэк-стор просто увеличивает чёткость;
// citygen/worldgen масштабируют шрифты фактором s=W/560, чтобы подписи остались крупными.
const MAP_BASE_W = 560, MAP_BASE_H = 400;
function mapScale() { return Math.max(1.6, Math.min(2.2, (window.devicePixelRatio || 1) * 1.25)); }
function sizeMapStage() {
  const s = mapScale();
  for (const id of ["map-canvas", "map-fx"]) {
    const cv = $(id); if (cv) { cv.width = Math.round(MAP_BASE_W * s); cv.height = Math.round(MAP_BASE_H * s); }
  }
}
function renderMap(ml) {
  if (!ml || !ml.levels || !ml.levels.length) return;
  if (!mapLevel || !ml.levels.some(l => l.id === mapLevel)) mapLevel = ml.current_level;
  $("map-tabs").innerHTML = ml.levels.map(l =>
    `<span class="tab ${l.id === mapLevel ? "active" : ""}" data-lvl="${l.id}">${esc(l.title)}</span>`).join("");
  $("map-tabs").querySelectorAll("[data-lvl]").forEach(t => t.onclick = () => { mapLevel = t.dataset.lvl; citySel = null; renderMap(ml); });
  citySel = null;
  renderLegend(null);                                                // легенда только для town
  sizeMapStage();                                                    // HiDPI бэк-стор перед отрисовкой
  const svgHost = $("map-svg"); if (svgHost) { svgHost.innerHTML = ""; svgHost.classList.add("hidden"); }
  if (mapLevel === "town") drawCityLevel();                          // процедурный город (Python-SVG, фолбэк на canvas)
  else if (mapLevel === "region" && window.drawWorld) drawWorldLevel(ml);
  else drawMapNodes(ml.levels.find(l => l.id === mapLevel));          // нод-граф для интерьера
  $("map-actions").classList.add("hidden");
  bindFx();
}
let cityFullCache = {};
async function drawCityLevel(tick = -1) {
  const seed = (lastView && lastView.seed) || 1337;
  const cv = $("map-canvas"), host = $("map-svg");
  const CW = 980, CH = 700;                                    // фикс-размер генерации (аспект 1.4 == карта)
  const keyHouses = (lastView && lastView.key_houses) || [];   // дома, поднявшие важность → ключевые
  const tq = tick >= 0 ? "&tick=" + tick : "";                 // tick → город отражает мутации от событий
  const ck = seed + "|" + JSON.stringify(keyHouses) + "|" + tick;
  let data = cityFullCache[ck];
  if (!data) {
    try {
      const r = await fetch(`/city_full?seed=${seed}&w=${CW}&h=${CH}&keys=${encodeURIComponent(JSON.stringify(keyHouses))}${tq}`);
      if (!r.ok) throw new Error("city_full " + r.status);
      data = await r.json(); cityFullCache[ck] = data;
    } catch (e) {                                              // фолбэк: старый canvas-генератор
      if (host) { host.innerHTML = ""; host.classList.add("hidden"); }
      if (!window.drawCity) return;
      await ensureTown(seed);
      const out = window.drawCity(cv.getContext("2d"), cv.width, cv.height, { seed, buildings: townBuildings || [], keyHouses, chrome: true });
      mapHits = out.hits; cityState = { ...out, seed }; cityCur = out.streets.start;
      renderLegend(out.legend); mapMode = "city"; cityStep = 0; cityQuiet = 2; cityMarks = []; drawFx();
      return;
    }
  }
  host.innerHTML = data.svg; host.classList.remove("hidden");  // SVG-город как база карты
  cv.getContext("2d").clearRect(0, 0, cv.width, cv.height);    // canvas-базу для города гасим
  const k = cv.width / CW;                                     // SVG(980×700) → координаты FX-бэкстора (аспект совпадает)
  mapHits = data.hits.map(h => ({ ...h, x: h.x * k, y: h.y * k, r: (h.r || 14) * k }));
  cityState = { seed, streets: { start: data.streets.start, adj: data.streets.adj,
                                 nodes: data.streets.nodes.map(n => [n[0] * k, n[1] * k]) } };
  cityCur = cityState.streets.start;
  renderLegend(data.legend);                                   // нумерованная легенда справа
  mapMode = "city"; cityStep = 0; cityQuiet = 2; cityMarks = []; drawFx();
  ensureIncidentControls();                                    // дебаг-слой событий (тумблер + скраббер)
  if (incidentMode) fetchIncidents();
}
// подсветить выбранный дом прямо в SVG (яркая заливка); возвращает true, если дом найден
function highlightSvgHouse(id) {
  const host = $("map-svg"); if (!host) return false;
  host.querySelectorAll(".h.sel").forEach(el => el.classList.remove("sel"));
  if (id) { const el = host.querySelector('.h[data-id="' + String(id).replace(/["\\]/g, "\\$&") + '"]'); if (el) { el.classList.add("sel"); return true; } }
  return false;
}
// легенда ключевых мест справа от карты: номер → название; клик = выбрать дом на карте
function renderLegend(legend) {
  const el = $("map-legend"); if (!el) return;
  if (!legend || !legend.length) { el.innerHTML = ""; return; }
  el.innerHTML = "<h4>Ключевые места</h4><ol>" + legend.map(L =>
    `<li data-key="${esc(L.id)}"><span class="ln">${L.n}</span><span class="lname">${esc(L.name)}</span></li>`).join("") + "</ol>";
  el.querySelectorAll("[data-key]").forEach(li => li.onclick = () => {
    const h = mapHits.find(x => x.id === li.dataset.key); if (h) setSelection(h);
  });
}
function drawWorldLevel(ml) {
  const lvl = ml.levels.find(l => l.id === "region"); if (!lvl) return;
  const cv = $("map-canvas"), seed = (lastView && lastView.seed) || 1337;
  mapHits = window.drawWorld(cv.getContext("2d"), cv.width, cv.height, { seed, nodes: lvl.nodes, chrome: true });
  mapMode = "region"; drawFx();
}

// --- клик = выбрать+подсветить; идём только по кнопке «Отправиться» -------- #
function bindFx() {
  const fx = $("map-fx");
  fx.onclick = (e) => {
    const svg = $("map-svg") && $("map-svg").querySelector("svg");
    if (svg) {                                             // SVG-режим: точный дом-полигон ПОД курсором (не ближайший)
      const houseEl = document.elementsFromPoint(e.clientX, e.clientY).find(el => el.classList && el.classList.contains("h"));
      if (houseEl) { const hit = mapHits.find(h => h.id === houseEl.getAttribute("data-id")); if (hit) { setSelection(hit); return; } }
    }
    const r = fx.getBoundingClientRect(), W = fx.width, H = fx.height;
    const mx = (e.clientX - r.left) / r.width * W, my = (e.clientY - r.top) / r.height * H;
    let best = null, bd = 1e9;                             // ратуша/замок (бейджи, не .h) и canvas-фолбэк — по близости
    for (const h of mapHits) { if (svg && h.house) continue; const d = Math.hypot(mx - h.x, my - h.y); if (d < (h.r || 14) + 4 && d < bd) { bd = d; best = h; } }
    if (best) { setSelection(best); return; }
    if (mapMode === "city" && cityState) {                 // не дом → ближайший перекрёсток
      const i = nearestNode(cityState.streets, mx, my), p = cityState.streets.nodes[i];
      if (Math.hypot(mx - p[0], my - p[1]) < 24) setSelection({ crossroad: true, node: i, x: p[0], y: p[1] });
    }
  };
}
function setSelection(hit) {
  citySel = hit;
  $("map-sel").textContent = hit.crossroad ? "Выбрано: перекрёсток" : "Выбрано: «" + (hit.name || "дом") + "»";
  $("map-go").textContent = hit.crossroad ? "🚶 Идти сюда"
    : (mapMode === "city" && !hit.go) ? "🚶 Подойти и осмотреть" : "🚶 Отправиться";
  $("map-actions").classList.remove("hidden");
  highlightSvgHouse(hit && !hit.crossroad ? hit.id : null);   // яркая подсветка самого дома в SVG
  drawFx();
}
function clearSelection() { citySel = null; const a = $("map-actions"); if (a) a.classList.add("hidden"); highlightSvgHouse(null); drawFx(); }
function drawFx() {
  const fx = $("map-fx"); if (!fx) return; const c = fx.getContext("2d"); c.clearRect(0, 0, fx.width, fx.height);
  const s = fx.width / 560;
  for (const m of cityMarks) { c.fillStyle = "#e2604a"; c.font = `bold ${Math.round(16 * s)}px Inter`; c.textAlign = "center"; c.textBaseline = "middle"; c.fillText("❗", m[0], m[1] - 10 * s); }
  if (mapMode === "city" && cityState) { const p = cityState.streets.nodes[cityCur]; c.beginPath(); c.arc(p[0], p[1], 3.6 * s, 0, 7); c.fillStyle = "#3a78b0"; c.fill(); c.lineWidth = 1.4 * s; c.strokeStyle = "#eef4fb"; c.stroke(); }
  // кольцо-выбор показываем только для НЕ-домов (перекрёсток/ратуша/замок); дом подсвечивается заливкой в SVG
  const hl = $("map-svg") && $("map-svg").querySelector(".h.sel");
  if (citySel && !hl) { c.strokeStyle = "#e0a64d"; c.lineWidth = 3 * s; c.setLineDash([5 * s, 4 * s]); c.beginPath(); c.arc(citySel.x, citySel.y, (citySel.r || 14) + 6 * s, 0, 7); c.stroke(); c.setLineDash([]); }
  if (incidentMode && incidentData && mapMode === "city") drawIncidents(c, s);   // дебаг-слой событий
}
// ===== Дебаг-слой инцидентов: точки-источники, волны-кольца, пересечения ===== #
let incidentMode = false, incidentTick = 0, incidentData = null;
function drawIncidents(c, s) {
  const k = $("map-canvas").width / 980;                  // модель 980×700 → бэкстор FX
  for (const inc of incidentData.incidents) {
    const x = inc.x * k, y = inc.y * k, R = Math.max(2, inc.radius * k);
    for (const [rf, af] of [[1, 0.75], [0.66, 0.55], [0.33, 0.4]]) {   // 3 кольца — ощущение волны
      c.globalAlpha = Math.min(0.9, inc.intensity * 1.3) * af; c.strokeStyle = inc.color; c.lineWidth = 2.4 * s;
      c.beginPath(); c.arc(x, y, R * rf, 0, 7); c.stroke();
    }
    c.globalAlpha = 1; c.fillStyle = inc.color; c.strokeStyle = "#15161a"; c.lineWidth = 1.5 * s;
    c.beginPath(); c.arc(x, y, 5 * s, 0, 7); c.fill(); c.stroke();
  }
  for (const ix of incidentData.intersections) {          // пересечение → ромб
    const x = ix.x * k, y = ix.y * k; c.globalAlpha = 1;
    c.save(); c.translate(x, y); c.rotate(Math.PI / 4);
    c.fillStyle = "#A32D2D"; c.strokeStyle = "#15161a"; c.lineWidth = 1.5 * s;
    c.fillRect(-5 * s, -5 * s, 10 * s, 10 * s); c.strokeRect(-5 * s, -5 * s, 10 * s, 10 * s); c.restore();
  }
  c.globalAlpha = 1;
}
async function fetchIncidents() {
  const seed = (lastView && lastView.seed) || 1337;
  try {
    const r = await fetch(`/city_incidents?seed=${seed}&tick=${incidentTick}&w=980&h=700`);
    incidentData = await r.json();
  } catch (e) { incidentData = { incidents: [], intersections: [] }; }
  const lbl = $("inc-readout");
  if (lbl) lbl.textContent = `тик ${incidentTick} · событий ${incidentData.incidents.length} · пересечений ${incidentData.intersections.length}`;
  const list = $("inc-list");
  if (list) list.innerHTML = incidentData.incidents.map(i =>
    `<div class="inc-row"><span class="inc-dot" style="background:${i.color}"></span>`
    + `<span><b>${esc(i.label)}</b>${i.desc ? ` <span class="inc-desc">— ${esc(i.desc)}</span>` : ""}`
    + `${(i.effects && i.effects.rumor) ? ` <span class="inc-rumor">🗣 ${esc(i.effects.rumor)}</span>` : ""}</span></div>`).join("")
    + (incidentData.intersections.length ? `<div class="inc-row inc-react">◇ ${incidentData.intersections.map(x => esc(x.reaction)).join(", ")}</div>` : "");
  drawFx();
}
function ensureIncidentControls() {
  if ($("map-debug") || !$("map-actions")) return;
  const bar = document.createElement("div");
  bar.id = "map-debug"; bar.className = "map-debug";
  bar.innerHTML = `<label class="inc-toggle"><input type="checkbox" id="inc-on"> 🌐 слой событий (дебаг)</label>`
    + `<input type="range" id="inc-tick" min="0" max="200" value="0" step="1" disabled>`
    + `<span id="inc-readout" class="state">тик 0</span>`;
  $("map-actions").parentNode.insertBefore(bar, $("map-actions"));
  const list = document.createElement("div"); list.id = "inc-list"; list.className = "inc-list";
  $("map-actions").parentNode.insertBefore(list, $("map-actions"));
  $("inc-on").onchange = (e) => {
    incidentMode = e.target.checked; $("inc-tick").disabled = !incidentMode;
    if (incidentMode) fetchIncidents(); else { incidentData = null; drawFx(); $("inc-readout").textContent = "выкл"; $("inc-list").innerHTML = ""; }
  };
  let incTimer = null;                                  // дебаунс: перерисовка карты под тик + оверлей событий
  $("inc-tick").oninput = (e) => {
    incidentTick = +e.target.value;
    if (!incidentMode) return;
    clearTimeout(incTimer);
    incTimer = setTimeout(() => drawCityLevel(incidentTick), 120);   // перерисовка карты под тик (overlay внутри)
  };
}
function bfs(adj, s, t) { if (s === t) return [s]; const prev = new Array(adj.length).fill(-1); prev[s] = s; const q = [s]; while (q.length) { const u = q.shift(); for (const v of adj[u]) if (prev[v] < 0) { prev[v] = u; if (v === t) { const p = [t]; let x = t; while (x !== s) { x = prev[x]; p.push(x); } return p.reverse(); } q.push(v); } } return null; }
function nearestNode(s, x, y) { let bi = 0, bd = 1e9; s.nodes.forEach((n, i) => { const d = Math.hypot(n[0] - x, n[1] - y); if (d < bd) { bd = d; bi = i; } }); return bi; }
async function cityWalk(hit) {
  const s = cityState.streets, target = nearestNode(s, hit.x, hit.y), path = bfs(s.adj, cityCur, target);
  if (!path) { cityCur = target; return; }
  for (let k = 1; k < path.length; k++) {
    cityCur = path[k]; cityStep++; drawWalk(path, k);
    try {
      const r = await fetch(`/city_event?seed=${cityState.seed}&step=${cityStep}&quiet=${cityQuiet}&loc=frontier_town`), d = await r.json();
      if (d && d.beat) { const ic = { threat: "⚔️", find: "🔎", company: "🧍", ambient: "…" }[d.beat.event] || "•"; logEntry(`${ic} <i>${esc(d.beat.text)}</i>`, "mech"); cityQuiet = 2; cityMarks.push(s.nodes[cityCur].slice()); drawWalk(path, k); }
      else cityQuiet++;
    } catch (e) { cityQuiet++; }
    await new Promise(rs => setTimeout(rs, 430));
  }
}
function drawWalk(path, k) {
  const fx = $("map-fx"), c = fx.getContext("2d"); c.clearRect(0, 0, fx.width, fx.height);
  const N = cityState.streets.nodes, s = fx.width / 560;
  c.strokeStyle = "rgba(120,90,40,.5)"; c.setLineDash([6 * s, 4 * s]); c.lineWidth = 2 * s; c.beginPath();
  for (let i = 0; i < path.length; i++) { const p = N[path[i]]; i ? c.lineTo(p[0], p[1]) : c.moveTo(p[0], p[1]); } c.stroke(); c.setLineDash([]);
  c.strokeStyle = "#e0a64d"; c.lineWidth = 3 * s; c.beginPath();
  for (let i = 0; i <= k; i++) { const p = N[path[i]]; i ? c.lineTo(p[0], p[1]) : c.moveTo(p[0], p[1]); } c.stroke();
  for (const m of cityMarks) { c.fillStyle = "#e2604a"; c.font = `bold ${Math.round(16 * s)}px Inter`; c.textAlign = "center"; c.textBaseline = "middle"; c.fillText("❗", m[0], m[1] - 10 * s); }
  const p = N[cityCur]; c.beginPath(); c.arc(p[0], p[1], 3.6 * s, 0, 7); c.fillStyle = "#3a78b0"; c.fill(); c.lineWidth = 1.4 * s; c.strokeStyle = "#eef4fb"; c.stroke();
}
async function goSelection() {
  const hit = citySel; if (!hit) return;
  $("map-go").disabled = true;
  if (hit.crossroad) { await cityWalk(hit); $("map-go").disabled = false; clearSelection(); return; }  // просто дойти
  if (mapMode === "city") {
    await cityWalk(hit);                                          // дошли по перекрёсткам с событиями
    if (hit.go) {                                                 // лендмарк → санкционированный переход «через карту» (минует гейт расстояния)
      logEntry(`<span class="you">→ ${esc(hit.name || hit.go)}</span>`, "you"); send({ cmd: "travel", place: hit.id }); closeOverlay("mapview");
    } else send({ cmd: "materialize", place: hit.id, kind: hit.kind });   // дом → наполнить
  } else if (hit.go) {
    logEntry(`<span class="you">→ ${esc(hit.name || hit.go)}</span>`, "you"); send({ cmd: "travel", place: hit.id }); closeOverlay("mapview");
  }
  $("map-go").disabled = false; clearSelection();
}
function renderHouse(h) {
  const occ = (h.occupants || []).map(o => `<div class="occ">• <b>${esc(o.name)}</b> — ${esc(o.role)} <span class="tag">(${esc(o.trait)}, ${o.age})</span></div>`).join("") || '<div class="tag">никого нет</div>';
  $("house-body").innerHTML = `<h3>Дом <span class="tag">(${esc(h.kind)})</span></h3><div>${esc(h.description || "")}</div>`
    + `<div style="margin:6px 0"><b>Внутри:</b> ${esc((h.items || []).join(", ") || "—")}</div><b>Кто здесь:</b>${occ}`
    + (h.recorded ? '<div class="mem">✓ из памяти</div>' : '<div class="mem">✦ наполнен и сохранён</div>');
  $("house").classList.remove("hidden");
}
function drawMapNodes(level) {
  if (!level) return;
  const cv = $("map-canvas"), ctx = cv.getContext("2d"), W = cv.width, H = cv.height, s = W / 560;
  ctx.fillStyle = "#11141a"; ctx.fillRect(0, 0, W, H);
  const cx = W / 2, cy = H / 2, Rx = W * 0.34, Ry = H * 0.30;
  const pos = (n) => { const L = Math.hypot(n.dx, n.dy) || 0; return [L ? cx + n.dx / L * Rx : cx, L ? cy + n.dy / L * Ry : cy]; };
  for (const n of level.nodes) {                       // рёбра от хаба
    const L = Math.hypot(n.dx, n.dy); if (!L) continue;
    const [x, y] = pos(n);
    ctx.strokeStyle = "rgba(224,166,77,.32)"; ctx.lineWidth = 1.5 * s;
    ctx.beginPath(); ctx.moveTo(cx, cy); ctx.lineTo(x, y); ctx.stroke();
  }
  mapHits = [];
  for (const n of level.nodes) {
    const [x, y] = pos(n);
    const col = n.current ? "#e0a64d" : n.display === "unknown" ? "#6b7283"
      : n.kind === "settlement" ? "#5b8fc9" : n.kind === "site" ? "#c08a44" : "#5fb87f";
    ctx.beginPath(); ctx.arc(x, y, 14 * s, 0, 7); ctx.fillStyle = "#171b22"; ctx.fill();
    ctx.lineWidth = (n.current ? 3.5 : 2) * s; ctx.strokeStyle = col; ctx.stroke();
    ctx.fillStyle = "#e8ebf1"; ctx.font = `${Math.round(13 * s)}px Inter`; ctx.textAlign = "center"; ctx.textBaseline = "top";
    const nm = n.name.length > 18 ? n.name.slice(0, 17) + "…" : n.name;
    ctx.fillText(nm, x, y + 17 * s);
    if (n.dir_ru) { ctx.fillStyle = "#969db0"; ctx.font = `${Math.round(11 * s)}px Inter`; ctx.fillText(n.dir_ru, x, y - 27 * s); }
    if (n.occupants && n.occupants.length) { ctx.fillStyle = "#c08a44"; ctx.fillText("• " + n.occupants.length, x + 16 * s, y - 6 * s); }
    if (n.go) mapHits.push({ x, y, r: 17 * s, go: n.go, name: n.name });
  }
  mapMode = "interior"; drawFx();
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
  const Wb = cols * cell, Hb = rows * cell, dpr = Math.min(2.5, window.devicePixelRatio || 1);
  cv2.width = Math.round(Wb * dpr); cv2.height = Math.round(Hb * dpr);   // HiDPI бэк-стор
  cv2.style.width = Wb + "px"; cv2.style.height = Hb + "px";             // CSS-размер = логический
  const ctx = cv2.getContext("2d");
  const paint = () => {
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);                             // рисуем в логических координатах
    ctx.clearRect(0, 0, Wb, Hb);
    if (battleImg && battleImg.complete) ctx.drawImage(battleImg, 0, 0, Wb, Hb);
    else { ctx.fillStyle = "#11141a"; ctx.fillRect(0, 0, Wb, Hb); }
    // достижимость (ход PC)
    if (cv.is_pc_turn && (combatMode === "move" || combatMode === "select")) {
      ctx.fillStyle = "rgba(95,143,201,.32)";
      for (const [x, y] of cv.reachable || []) ctx.fillRect(x * cell, y * cell, cell, cell);
      ctx.strokeStyle = "rgba(150,190,240,.5)"; ctx.lineWidth = 1;
      for (const [x, y] of cv.reachable || []) ctx.strokeRect(x * cell + 0.5, y * cell + 0.5, cell - 1, cell - 1);
    }
    // поверхности
    for (const sf of cv.surfaces || []) {
      ctx.fillStyle = SURFACE_COLORS[sf.kind] || "#888"; ctx.globalAlpha = .45;
      ctx.fillRect(sf.pos[0] * cell, sf.pos[1] * cell, cell, cell); ctx.globalAlpha = 1;
    }
    // цели (рамка) в режиме атаки/толчка
    if (cv.is_pc_turn && (combatMode === "attack" || combatMode === "shove")) {
      ctx.strokeStyle = "#e2604a"; ctx.lineWidth = 2;
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
      ctx.fillStyle = c.hp <= 0 ? "#555c66" : (c.side === "party" ? "#3a78b0" : "#c0492c");
      ctx.fill();
      ctx.lineWidth = c.current ? 3 : 1.5;
      ctx.strokeStyle = c.current ? "#e0a64d" : "#e8ebf1"; ctx.stroke();
      ctx.fillStyle = "#fff"; ctx.font = `600 ${Math.floor(cell * 0.4)}px Inter`;
      ctx.textAlign = "center"; ctx.textBaseline = "middle";
      ctx.fillText((c.name || "?").trim()[0] || "?", cx, cy);
      // HP-полоска
      const bw = cell * 0.8, hp = Math.max(0, c.hp / (c.max_hp || 1));
      ctx.fillStyle = "rgba(0,0,0,.5)"; ctx.fillRect(cx - bw / 2, cy + r + 1, bw, 3.5);
      ctx.fillStyle = c.side === "party" ? "#5fb87f" : "#e0a64d";
      ctx.fillRect(cx - bw / 2, cy + r + 1, bw * hp, 3.5);
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

document.querySelectorAll("[data-close]").forEach(b => b.onclick = () => closeOverlay(b.dataset.close));
$("map-go").onclick = goSelection;
$("map-cancel").onclick = clearSelection;
window.__map = { hits: () => mapHits, mode: () => mapMode, pick: (i) => setSelection(mapHits[i]), go: goSelection };
$("menu-btn").onclick = () => showLobby();
$("journal-btn").onclick = openJournal;
$("lb-new").onclick = () => { $("lobby").classList.add("hidden"); openOverlay("newgame"); ensureNgOptions(); };
$("lb-continue").onclick = () => $("lobby").classList.add("hidden");
$("lb-save").onclick = doSave;
$("ng-back").onclick = () => showLobby();
$("lg-back").onclick = () => showLobby();
$("ng-start").onclick = startNewGame;
$("lvl-apply").onclick = applyLevelup;
$("fac-open").onclick = () => openFactions();
$("account-btn").onclick = () => { if (ME) openOverlay("settings-ov"); else location.href = "/login"; };
$("settings-btn").onclick = () => openOverlay("settings-ov");
$("set-redeem").onclick = () => { const c = $("set-code").value.trim(); if (c) send({ cmd: "redeem", code: c }); };
$("set-logout").onclick = logout;
updateAccountBtn();
connect();
