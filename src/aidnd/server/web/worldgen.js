// Карта мира/региона с ТЕРРЕЙНОМ (без Вороного): высотное поле (шум) + теневая
// отмывка по нормалям + гипсометрическая палитра + реки + побережье. Точки региона
// расставлены по сторонам света. drawWorld(ctx,W,H,{seed,nodes,chrome,title}) → hits.

const mul = a => () => { a |= 0; a = a + 0x6D2B79F5 | 0; let t = Math.imul(a ^ a >>> 15, 1 | a); t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296; };
const sm = t => t * t * (3 - 2 * t);
function noise(seed, sp, COLS, ROWS) {
  const r = mul(seed), gw = Math.ceil(COLS / sp) + 2, gh = Math.ceil(ROWS / sp) + 2, L = [];
  for (let i = 0; i < gw * gh; i++) L.push(r());
  return (cx, cy) => {
    const x = cx / sp, y = cy / sp, x0 = Math.floor(x), y0 = Math.floor(y), fx = sm(x - x0), fy = sm(y - y0), g = (i, j) => L[j * gw + i];
    const a = g(x0, y0), b = g(x0 + 1, y0), c = g(x0, y0 + 1), d = g(x0 + 1, y0 + 1), t1 = a + (b - a) * fx, t2 = c + (d - c) * fx;
    return t1 + (t2 - t1) * fy;
  };
}
const DRY = [[0.435, [223, 209, 167]], [0.52, [203, 196, 142]], [0.63, [187, 175, 122]], [0.74, [167, 149, 105]], [0.85, [141, 124, 100]], [0.92, [151, 147, 137]], [0.97, [243, 239, 229]], [1.02, [251, 249, 243]]];
const WET = [[0.435, [209, 203, 159]], [0.52, [126, 152, 90]], [0.63, [95, 125, 73]], [0.74, [103, 123, 80]], [0.85, [118, 117, 91]], [0.92, [151, 147, 137]], [0.97, [243, 239, 229]], [1.02, [251, 249, 243]]];
function ramp(s, e) { let i = 1; while (i < s.length && e > s[i][0]) i++; const a = s[i - 1], b = s[Math.min(i, s.length - 1)], t = b[0] > a[0] ? Math.max(0, Math.min(1, (e - a[0]) / (b[0] - a[0]))) : 0; return [a[1][0] + (b[1][0] - a[1][0]) * t, a[1][1] + (b[1][1] - a[1][1]) * t, a[1][2] + (b[1][2] - a[1][2]) * t]; }
const BELIEF = { explored: "#2e7d32", confirmed: "#2f6fb0", hearsay: "#b07a1e", debunked: "#a33327", unknown: "#9a8458" };

export function drawWorld(ctx, W, H, opts = {}) {
  const seed = opts.seed || 1, nodes = opts.nodes || [], chrome = opts.chrome !== false;
  const CX = W / 2, CY = H / 2, hits = [];
  const CELL = 7, COLS = Math.ceil(W / CELL), ROWS = Math.ceil(H / CELL);
  const e1 = noise(seed * 7 + 1, 10, COLS, ROWS), e2 = noise(seed * 7 + 2, 4.5, COLS, ROWS),
    e3 = noise(seed * 7 + 3, 2, COLS, ROWS), e4 = noise(seed * 7 + 4, 1, COLS, ROWS),
    m1 = noise(seed * 7 + 5, 8, COLS, ROWS), m2 = noise(seed * 7 + 6, 3, COLS, ROWS);
  const EL = new Float32Array(W * H), MO = new Float32Array(W * H);
  for (let py = 0; py < H; py++) for (let px = 0; px < W; px++) {
    const gx = px / CELL, gy = py / CELL;
    let e = e1(gx, gy) * 0.55 + e2(gx, gy) * 0.28 + e3(gx, gy) * 0.12 + e4(gx, gy) * 0.05;
    const wc = Math.max(0, (COLS * 0.16 - gx) / (COLS * 0.16));          // море на западе (Мечовый Берег)
    const sc = Math.max(0, (gy - (ROWS - ROWS * 0.10)) / (ROWS * 0.10)) * 0.4;
    EL[py * W + px] = Math.max(0, Math.min(1, e - wc * 0.7 - sc * 0.3 + 0.1));
    MO[py * W + px] = m1(gx, gy) * 0.7 + m2(gx, gy) * 0.3;
  }
  // рельеф попиксельно в offscreen → drawImage (учитывает dpr-масштаб caller'а)
  let Lx = -1, Ly = -1, Lz = 1.15; const Ln = Math.hypot(Lx, Ly, Lz); Lx /= Ln; Ly /= Ln; Lz /= Ln;
  const Z = 240, AMB = 0.42, DIF = 0.78;
  const off = document.createElement("canvas"); off.width = W; off.height = H;
  const octx = off.getContext("2d"), img = octx.createImageData(W, H), D = img.data;
  for (let py = 0; py < H; py++) for (let px = 0; px < W; px++) {
    const i = py * W + px, e = EL[i]; let R, G, B;
    if (e < 0.40) { const td = Math.max(0, Math.min(1, (0.40 - e) / 0.12)), rip = Math.sin(px * 0.6 + py * 0.45) * 3.5; R = 120 + (44 - 120) * td + rip; G = 150 + (80 - 150) * td + rip; B = 170 + (112 - 170) * td + rip; }
    else {
      const dry = ramp(DRY, e), wet = ramp(WET, e), w = Math.max(0, Math.min(1, (MO[i] - 0.32) / 0.42));
      R = dry[0] + (wet[0] - dry[0]) * w; G = dry[1] + (wet[1] - dry[1]) * w; B = dry[2] + (wet[2] - dry[2]) * w;
      const xl = Math.max(0, px - 2), xr = Math.min(W - 1, px + 2), yt = Math.max(0, py - 2), yb = Math.min(H - 1, py + 2);
      const sx = (EL[py * W + xr] - EL[py * W + xl]) / (xr - xl) * Z, sy = (EL[yb * W + px] - EL[yt * W + px]) / (yb - yt) * Z;
      const nl = Math.max(0, (-sx * Lx - sy * Ly + Lz) / Math.sqrt(sx * sx + sy * sy + 1)), sh = AMB + DIF * nl;
      R *= sh; G *= sh; B *= sh;
      const fr = (e / 0.05) - Math.floor(e / 0.05); if (fr < 0.07) { R *= 0.9; G *= 0.9; B *= 0.9; }
      const mn = (((px * 131 + py * 57) % 17) / 17 - 0.5) * 6; R += mn; G += mn; B += mn;
    }
    const o = i * 4; D[o] = Math.max(0, Math.min(255, R)); D[o + 1] = Math.max(0, Math.min(255, G)); D[o + 2] = Math.max(0, Math.min(255, B)); D[o + 3] = 255;
  }
  octx.putImageData(img, 0, 0);
  ctx.clearRect(0, 0, W, H); ctx.imageSmoothingEnabled = true; ctx.drawImage(off, 0, 0, W, H);
  // реки
  function elc(cx, cy) { return EL[Math.min(H - 1, Math.round(cy * CELL)) * W + Math.min(W - 1, Math.round(cx * CELL))]; }
  function river(sx, sy) { let x = sx, y = sy; const p = [[x, y]]; for (let s = 0; s < 80; s++) { let bp = null, be = elc(x, y); for (const [dx, dy] of [[1, 0], [-1, 0], [0, 1], [0, -1], [1, 1], [-1, 1], [1, -1], [-1, -1]]) { const nx = x + dx, ny = y + dy; if (nx < 0 || nx >= COLS || ny < 0 || ny >= ROWS) continue; const ee = elc(nx, ny); if (ee < be) { be = ee; bp = [nx, ny]; } } if (!bp || elc(x, y) < 0.41) break; x = bp[0]; y = bp[1]; p.push([x, y]); } return p; }
  ctx.lineCap = "round"; ctx.lineJoin = "round";
  [[COLS * 0.55, ROWS * 0.12], [COLS * 0.75, ROWS * 0.1], [COLS * 0.4, ROWS * 0.3]].forEach(s => {
    const p = river(Math.round(s[0]), Math.round(s[1])); if (p.length < 3) return;
    ctx.strokeStyle = "rgba(48,96,138,.9)"; ctx.lineWidth = 2.6; ctx.beginPath();
    ctx.moveTo(p[0][0] * CELL, p[0][1] * CELL); for (let i = 1; i < p.length; i++) ctx.lineTo(p[i][0] * CELL, p[i][1] * CELL); ctx.stroke();
    ctx.strokeStyle = "rgba(150,200,225,.55)"; ctx.lineWidth = 1; ctx.stroke();
  });
  // виньетка + рамка
  const vg = ctx.createRadialGradient(CX, CY * 0.96, H * 0.34, CX, CY, H * 0.86); vg.addColorStop(0, "rgba(0,0,0,0)"); vg.addColorStop(1, "rgba(40,28,12,.4)"); ctx.fillStyle = vg; ctx.fillRect(0, 0, W, H);
  ctx.strokeStyle = "#4a3415"; ctx.lineWidth = 5; ctx.strokeRect(5, 5, W - 10, H - 10);
  // точки региона по сторонам света (город в центре)
  const Rx = W * 0.34, Ry = H * 0.32;
  // тракты от центра к известным точкам
  for (const n of nodes) { const Ln2 = Math.hypot(n.dx, n.dy); if (!Ln2 || n.display === "unknown") continue; const x = CX + n.dx / Ln2 * Rx, y = CY + n.dy / Ln2 * Ry; ctx.setLineDash(n.display === "hearsay" || n.display === "debunked" ? [5, 4] : []); ctx.strokeStyle = "rgba(74,52,22,.7)"; ctx.lineWidth = n.display === "explored" || n.display === "confirmed" ? 2 : 1.4; ctx.beginPath(); ctx.moveTo(CX, CY); ctx.lineTo(x, y); ctx.stroke(); }
  ctx.setLineDash([]);
  for (const n of nodes) {
    const Ln2 = Math.hypot(n.dx, n.dy), x = Ln2 ? CX + n.dx / Ln2 * Rx : CX, y = Ln2 ? CY + n.dy / Ln2 * Ry : CY;
    const col = n.current ? "#d8b15a" : (BELIEF[n.display] || "#9a8458");
    ctx.save(); ctx.shadowColor = "rgba(0,0,0,.35)"; ctx.shadowBlur = 4; ctx.shadowOffsetY = 1;
    ctx.beginPath(); ctx.arc(x, y, Ln2 ? 10 : 12, 0, 7); ctx.fillStyle = "rgba(244,232,200,.96)"; ctx.fill(); ctx.restore();
    ctx.lineWidth = n.current ? 3 : 2.2; ctx.strokeStyle = col; if (n.display === "hearsay") ctx.setLineDash([3, 2]); ctx.stroke(); ctx.setLineDash([]);
    ctx.font = "12px Georgia"; ctx.textAlign = "center"; ctx.textBaseline = "top";
    const nm = n.name.length > 18 ? n.name.slice(0, 17) + "…" : n.name, w = ctx.measureText(nm).width;
    ctx.fillStyle = "rgba(244,232,200,.92)"; ctx.strokeStyle = "#5a4222"; ctx.lineWidth = 0.7; rr(ctx, x - w / 2 - 5, y + 12, w + 10, 16, 4); ctx.fill(); ctx.stroke();
    ctx.fillStyle = "#2c2113"; ctx.fillText(nm, x, y + 14);
    if (n.go) hits.push({ x, y, r: 15, go: n.go, name: n.name });
  }
  // подпись моря + компас + картуш
  ctx.fillStyle = "rgba(30,55,78,.55)"; ctx.font = "italic 15px Georgia"; ctx.save(); ctx.translate(34, CY); ctx.rotate(-Math.PI / 2); ctx.textAlign = "center"; ctx.fillText("М О Р Е", 0, 0); ctx.restore();
  if (chrome) { compass(ctx, W); cartouche(ctx, W, opts.title || "Окрестности Фэндалина"); }
  return hits;
}
function rr(ctx, x, y, w, h, r) { ctx.beginPath(); ctx.moveTo(x + r, y); ctx.arcTo(x + w, y, x + w, y + h, r); ctx.arcTo(x + w, y + h, x, y + h, r); ctx.arcTo(x, y + h, x, y, r); ctx.arcTo(x, y, x + w, y, r); ctx.closePath(); }
function compass(ctx, W) { ctx.save(); ctx.translate(W - 42, 48); ctx.fillStyle = "rgba(244,232,200,.85)"; ctx.beginPath(); ctx.arc(0, 0, 18, 0, 7); ctx.fill(); ctx.strokeStyle = "#4a3415"; ctx.lineWidth = 1; ctx.stroke(); ctx.fillStyle = "#4a3415"; ctx.beginPath(); ctx.moveTo(0, -20); ctx.lineTo(4, -3); ctx.lineTo(-4, -3); ctx.fill(); ctx.font = "bold 9px Georgia"; ctx.textAlign = "center"; ctx.fillText("С", 0, -22); ctx.restore(); }
function cartouche(ctx, W, t) { ctx.fillStyle = "rgba(202,164,74,.92)"; ctx.strokeStyle = "#5a4222"; ctx.lineWidth = 1.4; rr(ctx, W / 2 - 150, 14, 300, 28, 5); ctx.fill(); ctx.stroke(); ctx.fillStyle = "#2c2113"; ctx.font = "italic 16px Georgia"; ctx.textAlign = "center"; ctx.textBaseline = "middle"; ctx.fillText(t, W / 2, 29); }

window.drawWorld = drawWorld;
