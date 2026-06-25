"""Порт citygen.js (Watabou-стиль город) 1:1 на Python.

Генерация: mulberry32 → точки (спираль) → 2× Ллойд → Вороной (клип в рамку) →
городские клетки → площадь → граф улиц → кварталы (shrink) → рекурсивное subdivide →
дома → стены по граничным рёбрам + ворота + башни → рынок → лендмарки → река (безье) →
номерные бейджи + легенда. Рендер — в SVG (canvas-эквивалент без зависимостей).

CLI:  python citygen.py [seed] [W] [H] > city.svg
API:  build_city(seed,W,H,buildings) -> dict;  render_svg(model) -> str
"""
from __future__ import annotations
import math, sys

# ----------------------------------------------------------------- RNG (mulberry32, 1:1 с JS)
def mulberry32(a: int):
    """JS: a=a+0x6D2B79F5|0; t=imul(a^a>>>15,1|a); t=(t+imul(t^t>>>7,61|t))^t; ((t^t>>>14)>>>0)/2^32."""
    state = a & 0xFFFFFFFF
    def imul(x, y):
        return ((x & 0xFFFFFFFF) * (y & 0xFFFFFFFF)) & 0xFFFFFFFF
    def rng():
        nonlocal state
        state = (state + 0x6D2B79F5) & 0xFFFFFFFF
        a_ = state
        t = imul(a_ ^ (a_ >> 15), 1 | a_)
        t = ((t + imul(t ^ (t >> 7), 61 | t)) & 0xFFFFFFFF) ^ t
        return ((t ^ (t >> 14)) & 0xFFFFFFFF) / 4294967296.0
    return rng

# ----------------------------------------------------------------- геометрия
def area(p):
    s = 0.0
    n = len(p)
    for i in range(n):
        a, b = p[i], p[(i + 1) % n]
        s += a[0] * b[1] - b[0] * a[1]
    return abs(s) / 2

def centroid(p):
    x = y = a = 0.0
    n = len(p)
    for i in range(n):
        A, B = p[i], p[(i + 1) % n]
        cr = A[0] * B[1] - B[0] * A[1]
        x += (A[0] + B[0]) * cr
        y += (A[1] + B[1]) * cr
        a += cr
    a *= 3
    return [x / a, y / a] if a else list(p[0])

def dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])

def shrink(p, f):
    c = centroid(p)
    return [[c[0] + (q[0] - c[0]) * f, c[1] + (q[1] - c[1]) * f] for q in p]

def norm(v):
    L = math.hypot(v[0], v[1]) or 1
    return [v[0] / L, v[1] / L]

def longest_edge(p):
    bi, bl = 0, -1
    for i in range(len(p)):
        a, b = p[i], p[(i + 1) % len(p)]
        l = math.hypot(b[0] - a[0], b[1] - a[1])
        if l > bl:
            bl, bi = l, i
    return [p[bi], p[(bi + 1) % len(p)]]

def clip_half(poly, P, nx, ny, pos):
    out = []
    def sd(q):
        d = (q[0] - P[0]) * nx + (q[1] - P[1]) * ny
        return d >= -1e-9 if pos else d <= 1e-9
    n = len(poly)
    for i in range(n):
        a, b = poly[i], poly[(i + 1) % n]
        sa, sb = sd(a), sd(b)
        if sa:
            out.append(a)
        if sa != sb:
            da = (a[0] - P[0]) * nx + (a[1] - P[1]) * ny
            db = (b[0] - P[0]) * nx + (b[1] - P[1]) * ny
            t = da / (da - db)
            out.append([a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t])
    return out

def subdivide(poly, minA, rng, out, d):
    if d > 11 or area(poly) < minA:
        out.append(poly)
        return
    a, b = longest_edge(poly)
    dr = norm([b[0] - a[0], b[1] - a[1]])
    c = centroid(poly)
    sp = math.sqrt(area(poly))
    t = (rng() - 0.5) * 0.3 * sp
    P = [c[0] + dr[0] * t, c[1] + dr[1] * t]
    L = clip_half(poly, P, dr[0], dr[1], True)
    R = clip_half(poly, P, dr[0], dr[1], False)
    if len(L) >= 3 and len(R) >= 3:
        subdivide(L, minA, rng, out, d + 1)
        subdivide(R, minA, rng, out, d + 1)
    else:
        out.append(poly)

# ----------------------------------------------------------------- река (примитив, режущий клетки)
def _seg_int(a, b, c, d):
    r0, r1 = b[0] - a[0], b[1] - a[1]
    s0, s1 = d[0] - c[0], d[1] - c[1]
    den = r0 * s1 - r1 * s0
    if abs(den) < 1e-12:
        return None
    t = ((c[0] - a[0]) * s1 - (c[1] - a[1]) * s0) / den
    u = ((c[0] - a[0]) * r1 - (c[1] - a[1]) * r0) / den
    if -1e-9 <= t <= 1 + 1e-9 and -1e-9 <= u <= 1 + 1e-9:
        return [a[0] + r0 * t, a[1] + r1 * t]
    return None

def _dist_seg(p, a, b):
    vx, vy = b[0] - a[0], b[1] - a[1]
    L2 = vx * vx + vy * vy or 1
    t = max(0.0, min(1.0, ((p[0] - a[0]) * vx + (p[1] - a[1]) * vy) / L2))
    return math.hypot(p[0] - (a[0] + vx * t), p[1] - (a[1] + vy * t))

def dist_to_polyline(p, pts):
    return min(_dist_seg(p, pts[i], pts[i + 1]) for i in range(len(pts) - 1))

def on_ward_boundary(plot, ward, eps=2.5):
    """Есть ли у участка вершина на внешнем контуре квартала (примыкает к краю)."""
    n = len(ward)
    for v in plot:
        for i in range(n):
            if _dist_seg(v, ward[i], ward[(i + 1) % n]) < eps:
                return True
    return False

def river_dir_at(cp, pts):
    """Направление реки в ближайшем к cp сегменте (единичный вектор)."""
    bi, bd = 0, 1e18
    for i in range(len(pts) - 1):
        mx, my = (pts[i][0] + pts[i + 1][0]) / 2, (pts[i][1] + pts[i + 1][1]) / 2
        dd = (cp[0] - mx) ** 2 + (cp[1] - my) ** 2
        if dd < bd:
            bd, bi = dd, i
    return norm([pts[bi + 1][0] - pts[bi][0], pts[bi + 1][1] - pts[bi][1]])

def ray_to_border(p, d, W, H, pad=2):
    """Точка выхода луча p+d*t на край канваса."""
    ts = []
    if d[0] > 1e-6:   ts.append((W - pad - p[0]) / d[0])
    elif d[0] < -1e-6: ts.append((pad - p[0]) / d[0])
    if d[1] > 1e-6:   ts.append((H - pad - p[1]) / d[1])
    elif d[1] < -1e-6: ts.append((pad - p[1]) / d[1])
    pos = [t for t in ts if t > 0]
    t = min(pos) if pos else 300
    return [p[0] + d[0] * t, p[1] + d[1] * t]

def make_river(seed, W, H, CX, CY):
    """Извилистая осевая реки через город (отдельный rng-поток, чтобы не сдвигать раскладку)."""
    rng = mulberry32((seed * 2654435761) & 0xFFFFFFFF)
    off = (rng() - 0.5) * H * 0.30            # смещение от центра — не резать рынок пополам
    slope = (rng() - 0.5) * 0.5
    a1, f1, p1 = H * (0.04 + rng() * 0.05), (1.0 + rng() * 1.4) * 6.2832 / W, rng() * 6.2832
    a2, f2, p2 = H * (0.02 + rng() * 0.03), (2.4 + rng() * 2.0) * 6.2832 / W, rng() * 6.2832
    pts = []
    for i in range(81):
        x = -20 + i / 80 * (W + 40)
        y = CY + off + (x - CX) * slope + a1 * math.sin(x * f1 + p1) + a2 * math.sin(x * f2 + p2)
        pts.append([x, y])
    return pts, max(9.0, min(W, H) * 0.022)

def cell_river_hits(pts, poly):
    hits = []
    n = len(poly)
    for i in range(len(pts) - 1):
        a, b = pts[i], pts[i + 1]
        for j in range(n):
            x = _seg_int(a, b, poly[j], poly[(j + 1) % n])
            if x:
                hits.append((i, x))
    hits.sort(key=lambda h: h[0])
    return [h[1] for h in hits]

def seg_cross_polyline(a, b, pts):
    """Точка пересечения отрезка a-b с рекой (ломаной), или None."""
    for i in range(len(pts) - 1):
        x = _seg_int(a, b, pts[i], pts[i + 1])
        if x:
            return x
    return None

def order_loop(bnd):
    """Упорядочить граничные рёбра в замкнутый контур (полигон вершин)."""
    if not bnd:
        return []
    by_start = {(round(e['a'][0]), round(e['a'][1])): e for e in bnd}
    start_key = (round(bnd[0]['a'][0]), round(bnd[0]['a'][1]))
    poly, e = [], bnd[0]
    for _ in range(len(bnd) + 2):
        poly.append([e['a'][0], e['a'][1]])
        nb = (round(e['b'][0]), round(e['b'][1]))
        if nb == start_key:
            break
        e = by_start.get(nb)
        if e is None:
            break
    return poly

def simplify_loop(poly, thr):
    """Схлопнуть рёбра короче thr в одну вершину (нет наслоения вершин/башен)."""
    pts = [list(p) for p in poly]
    changed = True
    while changed and len(pts) > 4:
        changed = False
        n = len(pts)
        for i in range(n):
            a, b = pts[i], pts[(i + 1) % n]
            if dist(a, b) < thr:
                a[0], a[1] = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
                pts.pop((i + 1) % n)
                changed = True
                break
    return pts


# ----------------------------------------------------------------- Вороной (Bowyer–Watson + клип в рамку)
class _Pt:
    __slots__ = ('x', 'y')
    def __init__(self, x, y):
        self.x = x; self.y = y

class _Tri:
    __slots__ = ('a', 'b', 'c', 'cx', 'cy', 'r2')
    def __init__(self, a, b, c):
        if (b.x - a.x) * (c.y - a.y) - (b.y - a.y) * (c.x - a.x) < 0:   # привести к CCW
            b, c = c, b
        self.a, self.b, self.c = a, b, c
        ax, ay, bx, by, cx, cy = a.x, a.y, b.x, b.y, c.x, c.y
        d = 2 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
        if d == 0:
            d = 1e-12
        ux = ((ax * ax + ay * ay) * (by - cy) + (bx * bx + by * by) * (cy - ay) + (cx * cx + cy * cy) * (ay - by)) / d
        uy = ((ax * ax + ay * ay) * (cx - bx) + (bx * bx + by * by) * (ax - cx) + (cx * cx + cy * cy) * (bx - ax)) / d
        self.cx, self.cy = ux, uy
        self.r2 = (ax - ux) ** 2 + (ay - uy) ** 2
    def in_circum(self, p):
        return (p.x - self.cx) ** 2 + (p.y - self.cy) ** 2 < self.r2 - 1e-9
    def has_edge(self, u, v):
        return ((self.a is u and self.b is v) or (self.b is u and self.c is v) or (self.c is u and self.a is v))

def _clip_rect(poly, x0, y0, x1, y1):
    """Сазерленд–Ходжман: клип выпуклого polygon к прямоугольнику."""
    def clip(poly, inside, inter):
        out = []
        n = len(poly)
        for i in range(n):
            a, b = poly[i], poly[(i + 1) % n]
            ia, ib = inside(a), inside(b)
            if ia:
                out.append(a)
                if not ib:
                    out.append(inter(a, b))
            elif ib:
                out.append(inter(a, b))
        return out
    p = poly
    p = clip(p, lambda q: q[0] >= x0, lambda a, b: [x0, a[1] + (b[1] - a[1]) * (x0 - a[0]) / (b[0] - a[0])])
    if not p: return p
    p = clip(p, lambda q: q[0] <= x1, lambda a, b: [x1, a[1] + (b[1] - a[1]) * (x1 - a[0]) / (b[0] - a[0])])
    if not p: return p
    p = clip(p, lambda q: q[1] >= y0, lambda a, b: [a[0] + (b[0] - a[0]) * (y0 - a[1]) / (b[1] - a[1]), y0])
    if not p: return p
    p = clip(p, lambda q: q[1] <= y1, lambda a, b: [a[0] + (b[0] - a[0]) * (y1 - a[1]) / (b[1] - a[1]), y1])
    return p

def voronoi_cells(pts, box):
    """Клетки Вороного для pts (в порядке pts), клипнутые в box=(x0,y0,x1,y1). None если пусто."""
    x0, y0, x1, y1 = box
    P = [_Pt(p[0], p[1]) for p in pts]
    # супер-рамка далеко за box
    span = max(x1 - x0, y1 - y0) * 1000 + 1000
    midx, midy = (x0 + x1) / 2, (y0 + y1) / 2
    f1, f2, f3, f4 = _Pt(midx - span, midy - span), _Pt(midx - span, midy + span), _Pt(midx + span, midy - span), _Pt(midx + span, midy + span)
    tris = [_Tri(f1, f2, f3), _Tri(f2, f3, f4)]
    for p in P:
        bad = [t for t in tris if t.in_circum(p)]
        edges = []
        for t1 in bad:
            for (u, v) in ((t1.a, t1.b), (t1.b, t1.c), (t1.c, t1.a)):
                shared = False
                for t2 in bad:
                    if t2 is not t1 and t2.has_edge(v, u):
                        shared = True
                        break
                if not shared:
                    edges.append((u, v))
        bset = set(id(t) for t in bad)
        tris = [t for t in tris if id(t) not in bset]
        for (u, v) in edges:
            tris.append(_Tri(u, v, p))
    # карта вершина -> инцидентные треугольники
    inc = {id(p): [] for p in P}
    for t in tris:
        for v in (t.a, t.b, t.c):
            lst = inc.get(id(v))
            if lst is not None:
                lst.append(t)
    cells = []
    for p in P:
        ts = inc[id(p)]
        if len(ts) < 3:
            cells.append(None)
            continue
        verts = [(t.cx, t.cy) for t in ts]
        # сортировка по углу вокруг p (CCW)
        verts.sort(key=lambda c: math.atan2(c[1] - p.y, c[0] - p.x))
        poly = _clip_rect([[v[0], v[1]] for v in verts], x0, y0, x1, y1)
        cells.append(poly if len(poly) >= 3 else None)
    return cells

# ----------------------------------------------------------------- палитры/хелперы стиля
ROOFS = ['#a8542f', '#b56a3c', '#8a5630', '#9c6b44', '#7a4a30', '#86603e', '#94472a', '#a36240']
# базовые цвета крыш по районам (мегакварталам) — разные приглушённые тона
DISTRICT_ROOFS = ['#a8542f', '#8a5630', '#b08a3e', '#6f6c74', '#5f7080', '#5f7d52', '#9c6b44', '#8a6a72']
DISTRICT_NAMES = ['Старый город', 'Купеческий', 'Ремесленный', 'Гончарный ряд', 'Кузнечный',
                  'Рыбацкий', 'Храмовый', 'Верхний город', 'Нижний город', 'Садовый', 'Дозорный', 'Портовый']
LM_ROOF = {'inn': '#b07a1e', 'drink': '#b07a1e', 'shop': '#2f6fb0', 'shrine': '#d8d0e0',
           'townhall': '#9a7b30', 'manor': '#7a3a3a', 'farm': '#5f7d42'}

def kind_from_aff(a):
    a = a or []
    if 'inn' in a or 'drink' in a:
        return 'inn'
    for k in ('shop', 'shrine', 'townhall', 'manor', 'farm'):
        if k in a:
            return k
    return 'manor' if 'hideout' in a else 'home'

def shade(hexc, f):
    n = int(hexc[1:], 16)
    c = lambda v: max(0, min(255, int(v * f)))
    return f"rgb({c(n >> 16)},{c((n >> 8) & 255)},{c(n & 255)})"

# ----------------------------------------------------------------- генерация города
def build_city(seed=1, W=980, H=700, buildings=None, key_houses=None, title='Фэндалин'):
    buildings = buildings or []
    key_map = {h['id']: h for h in (key_houses or [])}
    CX, CY = W / 2, H / 2
    rng = mulberry32(seed)

    # точки + Ллойд + Вороной
    N = round(110 * min(1.6, (W * H) / (980 * 700))) + 30
    pts = []
    for _ in range(N):
        a = rng() * 6.2832
        r = (rng() ** 0.7) * min(W, H) * 0.52
        pts.append([CX + math.cos(a) * r, CY + math.sin(a) * r * 0.92])
    box = (6, 6, W - 6, H - 6)
    for _ in range(2):
        cs = voronoi_cells(pts, box)
        for i, q in enumerate(cs):
            if q:
                pts[i] = centroid(q)
    vcs = voronoi_cells(pts, box)
    cells = []
    for i, q in enumerate(vcs):
        if not q:
            continue
        cells.append({'site': pts[i], 'poly': q, 'city': False, 'lm': None, 'roof': None})

    Rcity = min(W, H) * 0.40
    def on_edge(q):
        return any(p[0] <= 8 or p[0] >= W - 8 or p[1] <= 8 or p[1] >= H - 8 for p in q)
    for c in cells:
        c['city'] = dist(c['site'], [CX, CY]) < Rcity and not on_edge(c['poly'])
    city = [c for c in cells if c['city']]
    if not city:
        return None
    square = city[0]
    for c in city:
        if dist(c['site'], [CX, CY]) < dist(square['site'], [CX, CY]):
            square = c

    # РАТУША — крупный квартал, граничащий с площадью; ЗАМОК — компактный квартал на краю города
    sqset = set((round(v[0]), round(v[1])) for v in square['poly'])
    th_cands = [c for c in city if c is not square
                and any((round(v[0]), round(v[1])) in sqset for v in c['poly'])]
    if th_cands:
        max(th_cands, key=lambda c: area(c['poly']))['special'] = 'townhall'
    ca_cands = [c for c in city if c is not square and not c.get('special') and area(c['poly']) > 180
                and 80 < centroid(c['poly'])[0] < W - 80 and 80 < centroid(c['poly'])[1] < H - 80
                and dist(c['site'], [CX, CY]) < min(W, H) * 0.34]
    if ca_cands:
        max(ca_cands, key=lambda c: dist(c['site'], [CX, CY]))['special'] = 'castle'   # на краю города, в кадре

    # РЕКА: извилистая осевая режет городские клетки на берега (канал шириной river_w)
    river_pts, river_w = make_river(seed, W, H, CX, CY)
    hw = river_w / 2
    wall_cells = list(city)        # стена — по контуру ДО разреза рекой (иначе внутри города обрубки)
    new_city = []
    for c in city:
        if c is square or c.get('special'):               # рынок/ратушу/замок не режем
            new_city.append(c); continue
        hits = cell_river_hits(river_pts, c['poly'])
        if len(hits) >= 2:
            E, Q = hits[0], hits[-1]
            d = norm([Q[0] - E[0], Q[1] - E[1]])
            nx, ny = -d[1], d[0]                            # нормаль к руслу
            left = clip_half(c['poly'], [E[0] + nx * hw, E[1] + ny * hw], nx, ny, True)
            right = clip_half(c['poly'], [E[0] - nx * hw, E[1] - ny * hw], nx, ny, False)
            if len(left) >= 3 and len(right) >= 3 and area(left) > 60 and area(right) > 60:
                for half in (left, right):
                    new_city.append({'site': centroid(half), 'poly': half, 'city': True,
                                     'lm': None, 'roof': None, 'bank': True})
                continue
        new_city.append(c)
    city = new_city

    # граф улиц
    nmap, nodes, adj = {}, [], []
    def nkey(p):
        return f"{round(p[0])},{round(p[1])}"
    def nid(p):
        k = nkey(p)
        if k in nmap:
            return nmap[k]
        i = len(nodes)
        nmap[k] = i
        nodes.append([round(p[0]), round(p[1])])
        adj.append([])
        return i
    for c in city:
        p = c['poly']
        for i in range(len(p)):
            a, b = nid(p[i]), nid(p[(i + 1) % len(p)])
            if a != b:
                if b not in adj[a]:
                    adj[a].append(b)
                if a not in adj[b]:
                    adj[b].append(a)
    sc0 = centroid(square['poly'])
    start, sd = 0, 1e9
    for i, nd in enumerate(nodes):
        d = math.hypot(nd[0] - sc0[0], nd[1] - sc0[1])
        if d < sd:
            sd, start = d, i
    streets = {'nodes': nodes, 'adj': adj, 'start': start}

    # лендмарк-кварталы по сторонам света
    used = {id(square)}
    Rl = min(W, H) * 0.30
    for b in buildings:
        if b.get('kind') != 'building':
            continue
        Ln = math.hypot(b.get('dx', 0), b.get('dy', 0)) or 0
        tgt = [CX + b['dx'] / Ln * Rl, CY + b['dy'] / Ln * Rl * 0.92] if Ln else [CX, CY]
        best, bd = None, 1e9
        for c in city:
            if id(c) in used or c['lm']:
                continue
            d = dist(c['site'], tgt)
            if d < bd:
                bd, best = d, c
        if not best:
            continue
        used.add(id(best))
        best['lm'] = b
        roof = next((LM_ROOF[a] for a in (b.get('affordances') or []) if a in LM_ROOF), None)
        best['roof'] = roof or LM_ROOF.get(kind_from_aff(b.get('affordances')), '#9a7b30')

    # стены: граничные рёбра города ДО разреза рекой (контур, без внутренних обрубков)
    seen = {}
    def ekey(a, b):
        A, B = [round(a[0]), round(a[1])], [round(b[0]), round(b[1])]
        return (tuple(A), tuple(B)) if (A[0] < B[0] or (A[0] == B[0] and A[1] <= B[1])) else (tuple(B), tuple(A))
    for c in wall_cells:
        p = c['poly']
        for i in range(len(p)):
            a, b = p[i], p[(i + 1) % len(p)]
            k = ekey(a, b)
            if k in seen:
                seen[k]['n'] += 1
            else:
                seen[k] = {'a': a, 'b': b, 'n': 1}
    bnd = [e for e in seen.values() if e['n'] == 1]
    wall_poly = simplify_loop(order_loop(bnd), 12)        # контур стены: рёбра короче 12 схлопнуты в одно

    # ВОРОТА: несколько по периметру (разнесены по направлениям, не у реки) → из каждого дорога наружу
    rng_r = mulberry32((seed ^ 0x27D4EB2F) & 0xFFFFFFFF)
    nwp = len(wall_poly)
    gcand = []
    for i in range(nwp):
        a, b = wall_poly[i], wall_poly[(i + 1) % nwp]
        gm = [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2]
        if dist_to_polyline(gm, river_pts) < river_w * 1.1 or seg_cross_polyline(a, b, river_pts):
            continue                                      # не у воды
        gcand.append((i, gm, math.atan2(gm[1] - CY, gm[0] - CX)))
    gate_edges, roads_out = [], []
    NG = 5
    for k in range(NG):
        target = math.pi / 2 + k * 2 * math.pi / NG        # юг + равномерно по кругу
        best, bd = None, 9.9
        for (i, gm, ang) in gcand:
            if i in gate_edges:
                continue
            da = abs((ang - target + math.pi) % (2 * math.pi) - math.pi)
            if da < bd:
                bd, best = da, (i, gm)
        if best is not None and bd < 0.7:
            gi2, gm = best
            gate_edges.append(gi2)
            od = norm([gm[0] - CX, gm[1] - CY])
            endp = ray_to_border(gm, od, W, H)
            perp = [-od[1], od[0]]
            off = (rng_r() - 0.5) * dist(gm, endp) * 0.16   # лёгкий извив
            midp = [(gm[0] + endp[0]) / 2 + perp[0] * off, (gm[1] + endp[1]) / 2 + perp[1] * off]
            roads_out.append([gm, midp, endp])

    # МОСТЫ: внутренние рёбра-улицы (n==2), пересекающие реку → мост идёт ИЗ дороги В дорогу
    Rc = min(W, H) * 0.40
    crossings = []
    for ed in seen.values():
        if ed['n'] != 2:
            continue
        x = seg_cross_polyline(ed['a'], ed['b'], river_pts)
        if x and dist(x, [CX, CY]) < Rc * 0.9:
            crossings.append({'a': list(ed['a']), 'b': list(ed['b']), 'cross': x})
    crossings.sort(key=lambda c: c['cross'][0])
    bridges = []
    for c in crossings:
        if all(dist(c['cross'], b['cross']) > 75 for b in bridges):
            bridges.append(c)
        if len(bridges) >= 3:
            break

    # дома по кварталам
    wards, marks, hits = [], [], []
    near_river_b = lambda p: dist_to_polyline(p, river_pts) < river_w * 1.15
    # центры районов (мегакварталов) для цветовой гаммы крыш (отдельный rng — не сдвигает раскладку)
    rng_d = mulberry32((seed ^ 0x1B873593) & 0xFFFFFFFF)
    dseeds = []
    for k in range(7):
        ang = (k / 7) * 6.2832 + rng_d() * 0.9
        rr = Rc * (0.15 + rng_d() * 0.8)
        dseeds.append(([CX + math.cos(ang) * rr, CY + math.sin(ang) * rr], DISTRICT_ROOFS[k % len(DISTRICT_ROOFS)]))
    def district_color(p):
        best, col = 1e18, DISTRICT_ROOFS[0]
        for dp, dc in dseeds:
            dd = (p[0] - dp[0]) ** 2 + (p[1] - dp[1]) ** 2
            if dd < best:
                best, col = dd, dc
        return col
    for c in city:
        if c is square:
            continue
        sp = c.get('special')
        if sp == 'townhall':
            blk = shrink(c['poly'], 0.60); cc = centroid(blk)
            wards.append({'special': 'townhall', 'building': blk, 'roof': '#9a7b30', 'cc': cc})
            marks.append({'c': cc, 'name': 'Ратуша', 'roof': '#9a7b30',
                          'id': f'townhall@{round(cc[0])},{round(cc[1])}', 'kind': 'townhall', 'go': None})
            hits.append({'x': cc[0], 'y': cc[1], 'r': 16, 'id': f'townhall@{round(cc[0])},{round(cc[1])}',
                         'name': 'Ратуша', 'kind': 'townhall', 'key': True})
            continue
        if sp == 'castle':
            cc = centroid(c['poly'])
            cw = shrink(c['poly'], 0.93)
            for v in cw:                                  # снап опорных точек замка к близким точкам городской стены
                for wv in wall_poly:
                    if dist(v, wv) < 14:
                        v[0], v[1] = wv[0], wv[1]
                        break
            cw = simplify_loop(cw, 12)                    # слить короткие рёбра по трешхолду (как у городской стены)
            wards.append({'special': 'castle', 'wall': cw,
                          'keep': simplify_loop(shrink(c['poly'], 0.40), 8), 'cc': cc})
            marks.append({'c': cc, 'name': 'Замок', 'roof': '#5f6470',
                          'id': f'castle@{round(cc[0])},{round(cc[1])}', 'kind': 'castle', 'go': None})
            hits.append({'x': cc[0], 'y': cc[1], 'r': 20, 'id': f'castle@{round(cc[0])},{round(cc[1])}',
                         'name': 'Замок', 'kind': 'castle', 'key': True})
            continue
        ward = shrink(c['poly'], 0.86)
        lm = c['lm']
        dcolor = district_color(c['site'])                  # цвет района
        plots = []
        subdivide(ward, 120 + rng() * 90, rng, plots, 0)
        key_plot = None
        if lm:
            ba = -1
            for pl in plots:
                if len(pl) < 3:
                    continue
                a = area(shrink(pl, 0.82))
                if a > ba:
                    ba, key_plot = a, pl
        houses = []
        for pl in plots:
            if len(pl) < 3:
                continue
            inset = shrink(pl, 0.82)
            if area(inset) < 18:
                continue
            if near_river_b(centroid(inset)) and area(inset) < 70:
                continue                                   # мелочь у воды убираем — полосу закрасим набережной
            is_lm = bool(lm) and pl is key_plot
            if not is_lm and not on_ward_boundary(pl, ward):
                continue                                   # центральные участки не застраиваем — пустой двор
            if not is_lm and rng() < 0.07:
                houses.append({'garden': True, 'poly': inset})
                continue
            cc = centroid(inset)
            hid = f"house:{seed}:{round(cc[0])}_{round(cc[1])}"
            promo = key_map.get(hid) if not is_lm else None
            if is_lm:
                key = {'name': lm['name'], 'kind': kind_from_aff(lm.get('affordances')),
                       'roof': c['roof'], 'id': lm['id'], 'go': lm.get('go')}
            elif promo:
                key = {'name': promo['name'], 'kind': promo.get('kind', 'home'),
                       'roof': LM_ROOF.get(promo.get('kind'), '#9a7b30'), 'id': hid, 'go': None}
            else:
                key = None
            roof = key['roof'] if key else shade(dcolor, 0.88 + rng() * 0.24)   # оттенок цвета района
            a, b = longest_edge(inset)
            d = norm([b[0] - a[0], b[1] - a[1]])
            Lr = math.sqrt(area(inset)) * 0.42
            houses.append({'garden': False, 'poly': inset, 'roof': roof, 'cc': cc,
                           'ridge': [[cc[0] - d[0] * Lr, cc[1] - d[1] * Lr], [cc[0] + d[0] * Lr, cc[1] + d[1] * Lr]],
                           'key': key, 'id': (key['id'] if key else hid)})
            r = max(7, math.sqrt(area(inset)) * 0.55)
            if key:
                marks.append({'c': cc, 'name': key['name'], 'roof': key['roof'], 'id': key['id'], 'kind': key['kind'], 'go': key['go']})
                hits.append({'x': cc[0], 'y': cc[1], 'r': max(r, 12), 'id': key['id'], 'name': key['name'],
                             'kind': key['kind'], 'go': key['go'], 'landmark': bool(key['go']), 'key': True})
            else:
                hits.append({'x': cc[0], 'y': cc[1], 'r': r, 'id': hid, 'kind': 'home', 'house': True})
        wards.append({'ward': ward, 'fill': shade(c['roof'], 1.72) if lm else '#cdb585',
                      'houses': houses, 'lm': lm, 'roof': c['roof']})

    # мегакварталы = цветовые районы. Группируем кварталы по ближайшему dseed, одна надпись на район.
    groups = {}
    for c in city:
        if c is square or c.get('special'):
            continue
        bi, bd = 0, 1e18
        for k, (dp, _) in enumerate(dseeds):
            dd = (c['site'][0] - dp[0]) ** 2 + (c['site'][1] - dp[1]) ** 2
            if dd < bd:
                bd, bi = dd, k
        groups.setdefault(bi, []).append(c)
    dnames = DISTRICT_NAMES[:]
    for i in range(len(dnames) - 1, 0, -1):
        j = int(rng_d() * (i + 1)); dnames[i], dnames[j] = dnames[j], dnames[i]
    dist_labels = []
    for k, gc in sorted(groups.items(), key=lambda kv: -sum(area(c['poly']) for c in kv[1])):
        tot = sum(area(c['poly']) for c in gc)
        if tot < 4500:                                    # мелкий район — без надписи
            continue
        sx = sy = sa = 0.0
        minx = miny = 1e9; maxx = maxy = -1e9
        for c in gc:
            a = area(c['poly']); cc = centroid(c['poly'])
            sx += cc[0] * a; sy += cc[1] * a; sa += a
            for v in c['poly']:
                minx = min(minx, v[0]); maxx = max(maxx, v[0]); miny = min(miny, v[1]); maxy = max(maxy, v[1])
        dist_labels.append({'name': dnames[len(dist_labels) % len(dnames)], 'c': [sx / sa, sy / sa],
                            'w': maxx - minx, 'h': maxy - miny})
        if len(dist_labels) >= 6:
            break

    # бейджи/легенда (сверху-вниз, слева-направо)
    marks.sort(key=lambda m: (m['c'][1], m['c'][0]))
    legend = []
    for i, m in enumerate(marks):
        legend.append({'n': i + 1, 'name': m['name'], 'kind': m['kind'], 'go': m['go'],
                       'id': m['id'], 'x': m['c'][0], 'y': m['c'][1]})

    Rcity = min(W, H) * 0.40
    return {'W': W, 'H': H, 'CX': CX, 'CY': CY, 'seed': seed, 'title': title,
            'cells': cells, 'city': city, 'square': square, 'wards': wards,
            'wall_poly': wall_poly, 'marks': marks, 'legend': legend, 'hits': hits,
            'streets': streets, 'river_pts': river_pts, 'river_w': river_w, 'Rcity': Rcity,
            'bridges': bridges, 'dist_labels': dist_labels,
            'gate_edges': gate_edges, 'roads_out': roads_out}

# ----------------------------------------------------------------- рендер в SVG
def _poly_d(p, close=True):
    d = "M" + f"{p[0][0]:.2f} {p[0][1]:.2f}"
    for q in p[1:]:
        d += f"L{q[0]:.2f} {q[1]:.2f}"
    return d + ("Z" if close else "")

def render_svg(m, chrome=True, interactive=False):
    W, H, CX, CY = m['W'], m['H'], m['CX'], m['CY']
    seed = m['seed']
    rngf = mulberry32(seed ^ 0x9E3779B9)   # отдельный поток для лесных кочек (детерминирован)
    e = []
    e.append(f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" font-family="Georgia, serif">')
    e.append('<defs><radialGradient id="vg" cx="50%" cy="47.5%" r="62%">'
             '<stop offset="55%" stop-color="rgba(0,0,0,0)"/><stop offset="100%" stop-color="rgba(40,28,12,.34)"/>'
             '</radialGradient></defs>')
    # фон
    e.append(f'<rect width="{W}" height="{H}" fill="#a9b878"/>')
    # лес (кочки на не-городских клетках)
    e.append('<g fill="#5f7d42">')
    for c in m['cells']:
        if not c['city'] and rngf() < 0.55:
            r = 3 + rngf() * 3
            e.append(f'<circle cx="{c["site"][0]:.1f}" cy="{c["site"][1]:.1f}" r="{r:.1f}"/>')
    e.append('</g>')
    # дороги снаружи в город (casing + центр) — рисуем до земли города, чтобы внутренний конец ушёл под кварталы
    for road in m.get('roads_out', []):
        dd = "M%.1f %.1f L%.1f %.1f L%.1f %.1f" % (road[0][0], road[0][1], road[1][0], road[1][1], road[2][0], road[2][1])
        e.append(f'<path d="{dd}" fill="none" stroke="#8c7038" stroke-width="9" stroke-linecap="round" stroke-linejoin="round"/>')
        e.append(f'<path d="{dd}" fill="none" stroke="#cdb585" stroke-width="6" stroke-linecap="round" stroke-linejoin="round"/>')
    # земля города
    e.append('<g fill="#d8c39a">')
    for c in m['city']:
        e.append(f'<path d="{_poly_d(c["poly"])}"/>')
    e.append('</g>')
    # кварталы и дома
    for w in m['wards']:
        if w.get('special') == 'townhall':
            d, cc = _poly_d(w['building']), w['cc']
            e.append(f'<path d="{d}" fill="{w["roof"]}" stroke="#2c2113" stroke-width="1.8"/>')
            e.append(f'<circle cx="{cc[0]:.1f}" cy="{cc[1]:.1f}" r="3.2" fill="#2c2113"/>')   # шпиль ратуши
            continue
        if w.get('special') == 'castle':
            wp, kp = w['wall'], w['keep']
            e.append(f'<path d="{_poly_d(wp)}" fill="#cdb585"/>')                                      # двор
            e.append(f'<path d="{_poly_d(wp)}" fill="none" stroke="#3a2c14" stroke-width="4.5" stroke-linejoin="round"/>')  # стена замка
            e.append('<g fill="#5a4a2c" stroke="#352a16" stroke-width="1">')
            for v in wp:
                e.append(f'<rect x="{v[0]-4:.1f}" y="{v[1]-4:.1f}" width="8" height="8"/>')             # угловые башни
            e.append('</g>')
            e.append(f'<path d="{_poly_d(kp)}" fill="#5f6470" stroke="#2c2113" stroke-width="1.8"/>')   # донжон
            continue
        e.append(f'<path d="{_poly_d(w["ward"])}" fill="{w["fill"]}"/>')
        for h in w['houses']:
            if h['garden']:
                e.append(f'<path d="{_poly_d(h["poly"])}" fill="#9fae6e" stroke="rgba(60,80,40,.4)" stroke-width="0.7"/>')
                continue
            d = _poly_d(h['poly'])
            # крыша (в интерактиве — кликабельный полигон дома с id)
            ha = f' class="h" data-id="{h.get("id","")}"' if interactive else ''
            e.append(f'<path d="{d}" fill="{h["roof"]}"{ha}/>')
            # конёк
            rg = h['ridge']
            e.append(f'<line x1="{rg[0][0]:.1f}" y1="{rg[0][1]:.1f}" x2="{rg[1][0]:.1f}" y2="{rg[1][1]:.1f}" stroke="rgba(0,0,0,.22)" stroke-width="1"/>')
            key = h['key']
            e.append(f'<path d="{d}" fill="none" stroke="{"#3a2c14" if key else "rgba(40,28,12,.5)"}" stroke-width="{1.3 if key else 0.8}"/>')
        if w['lm']:
            e.append(f'<path d="{_poly_d(w["ward"])}" fill="none" stroke="{w["roof"]}" stroke-width="1.6"/>')
    # рыночная площадь
    sq = shrink(m['square']['poly'], 0.9)
    e.append(f'<path d="{_poly_d(sq)}" fill="#c9b486"/>')
    sc, SR = centroid(sq), math.sqrt(area(sq))
    e.append('<g stroke="rgba(90,66,34,.25)" stroke-width="0.6">')
    g = -SR
    while g < SR:
        e.append(f'<line x1="{sc[0]+g:.1f}" y1="{sc[1]-SR:.1f}" x2="{sc[0]+g:.1f}" y2="{sc[1]+SR:.1f}"/>')
        e.append(f'<line x1="{sc[0]-SR:.1f}" y1="{sc[1]+g:.1f}" x2="{sc[0]+SR:.1f}" y2="{sc[1]+g:.1f}"/>')
        g += 9
    e.append('</g>')
    e.append(f'<circle cx="{sc[0]:.1f}" cy="{sc[1]:.1f}" r="5" fill="#7a6238"/><circle cx="{sc[0]:.1f}" cy="{sc[1]:.1f}" r="2.4" fill="#3a2c18"/>')
    # река: вода в каналах между берегами (над землёй, под стенами)
    rp, rw = m['river_pts'], m['river_w']
    rd = "M%.1f %.1f " % (rp[0][0], rp[0][1]) + " ".join("L%.1f %.1f" % (q[0], q[1]) for q in rp[1:])
    # НАБЕРЕЖНАЯ-ДОРОГА: прибрежную полосу города форсированно красим цветом дороги (закрывает фон кварталов от убранных домов)
    cityd = "".join(_poly_d(c['poly']) for c in m['city'])
    e.append(f'<clipPath id="cityclip"><path d="{cityd}"/></clipPath>')
    e.append(f'<path d="{rd}" fill="none" stroke="#caa46a" stroke-width="{rw*2.2:.1f}" stroke-linecap="round" stroke-linejoin="round" clip-path="url(#cityclip)"/>')
    e.append(f'<path d="{rd}" fill="none" stroke="#cdb98f" stroke-width="{rw:.1f}" stroke-linejoin="round" stroke-linecap="round"/>')   # песчаный берег у воды
    e.append(f'<path d="{rd}" fill="none" stroke="#37607c" stroke-width="{rw*0.66+2:.1f}" stroke-linejoin="round" stroke-linecap="round"/>')
    e.append(f'<path d="{rd}" fill="none" stroke="#4a7ba0" stroke-width="{rw*0.6:.1f}" stroke-linejoin="round" stroke-linecap="round"/>')   # вода уже русла
    e.append(f'<path d="{rd}" fill="none" stroke="rgba(150,200,225,.4)" stroke-width="2" stroke-linejoin="round"/>')
    near_river = lambda p: dist_to_polyline(p, rp) < rw * 0.95
    # стены по контуру wall_poly — РАЗРЫВ точно в точке пересечения ребра с рекой (проём-водяные-ворота)
    wp, nw = m['wall_poly'], len(m['wall_poly'])
    gate_set = set(m.get('gate_edges', []))                  # рёбра-ворота (под дороги)
    seg_gap = rw * 0.95                                      # полуразрыв стены под реку
    gate_gap = 7.0                                           # полуразрыв-ворота под дорогу (как у реки, но в середине ребра)
    wsegs, gate_posts = [], []
    for i in range(nw):
        a, b = wp[i], wp[(i + 1) % nw]
        d = norm([b[0] - a[0], b[1] - a[1]])
        if i in gate_set:                                    # ВОРОТА: разрыв в середине ребра (где выходит дорога)
            gm = [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2]
            A2 = [gm[0] - d[0] * gate_gap, gm[1] - d[1] * gate_gap]
            B2 = [gm[0] + d[0] * gate_gap, gm[1] + d[1] * gate_gap]
            if dist(a, A2) > 2:
                wsegs.append((a, A2)); gate_posts.append(A2)
            if dist(B2, b) > 2:
                wsegs.append((B2, b)); gate_posts.append(B2)
            continue
        X = seg_cross_polyline(a, b, rp)                     # РЕКА: разрыв в точке пересечения
        if X:
            A2 = [X[0] - d[0] * seg_gap, X[1] - d[1] * seg_gap]
            B2 = [X[0] + d[0] * seg_gap, X[1] + d[1] * seg_gap]
            if dist(a, A2) > 3:
                wsegs.append((a, A2))
            if dist(B2, b) > 3:
                wsegs.append((B2, b))
        else:
            wsegs.append((a, b))
    e.append('<g stroke-linecap="round">')
    for col, wdt in (('#6b5836', 6), ('#4a3c22', 2)):
        e.append(f'<g stroke="{col}" stroke-width="{wdt}">')
        for a, b in wsegs:
            e.append(f'<line x1="{a[0]:.1f}" y1="{a[1]:.1f}" x2="{b[0]:.1f}" y2="{b[1]:.1f}"/>')
        e.append('</g>')
    e.append('</g>')
    # башни на вершинах (не у воды) + башенки-стойки ворот
    e.append('<g fill="#5a4a2c" stroke="#352a16" stroke-width="1">')
    for i in range(nw):
        v = wp[i]
        if not near_river(v):
            e.append(f'<rect x="{v[0]-3.5:.1f}" y="{v[1]-3.5:.1f}" width="7" height="7"/>')
    for gp in gate_posts:
        e.append(f'<rect x="{gp[0]-3:.1f}" y="{gp[1]-3:.1f}" width="6" height="6"/>')   # стойка ворот
    e.append('</g>')
    # мосты через реку в черте города
    for br in m['bridges']:
        a, b, cp = br['a'], br['b'], br['cross']
        d = norm([b[0] - a[0], b[1] - a[1]]); nx, ny = -d[1], d[0]
        # мост тянется вдоль ребра-улицы ровно до кромок берегов (где начинаются дороги), не в дома
        rdir = river_dir_at(cp, rp)
        sin = max(0.4, abs(d[0] * rdir[1] - d[1] * rdir[0]))
        L = min(rw * 1.7, (rw * 0.5 + 1.5) / sin)
        hwd = 4.0
        P1, P2 = [cp[0] + d[0] * L, cp[1] + d[1] * L], [cp[0] - d[0] * L, cp[1] - d[1] * L]
        c0 = [P1[0] + nx * hwd, P1[1] + ny * hwd]; c1 = [P2[0] + nx * hwd, P2[1] + ny * hwd]
        c2 = [P2[0] - nx * hwd, P2[1] - ny * hwd]; c3 = [P1[0] - nx * hwd, P1[1] - ny * hwd]
        e.append(f'<path d="{_poly_d([c0, c1, c2, c3])}" fill="#caa46a"/>')                       # продолжение дороги
        e.append(f'<line x1="{c0[0]:.1f}" y1="{c0[1]:.1f}" x2="{c1[0]:.1f}" y2="{c1[1]:.1f}" stroke="#2c2113" stroke-width="1.4"/>')  # ребро вдоль реки
        e.append(f'<line x1="{c2[0]:.1f}" y1="{c2[1]:.1f}" x2="{c3[0]:.1f}" y2="{c3[1]:.1f}" stroke="#2c2113" stroke-width="1.4"/>')
    # названия мегакварталов — путь = доступная ширина района, кегль подобран чтобы строка влезла (центр → без обрезки)
    specials = [mk['c'] for mk in m['marks'] if mk.get('kind') in ('townhall', 'castle')]
    for li, lb in enumerate(m.get('dist_labels', [])):
        C, nm = lb['c'], lb['name']
        avail = lb['w'] * 0.80                              # сколько ширины района даём под надпись
        fs = min(18.0, avail / (len(nm) * 0.64), lb['h'] * 0.5)
        if fs < 8:                                          # район слишком тесный — пропускаем
            continue
        half = avail / 2                                    # путь во всю доступную ширину → текст не обрежется
        cx, ly = C[0], C[1]
        for spc in specials:                                # не наезжать на ратушу/замок — сдвиг по вертикали
            if cx - half - 14 < spc[0] < cx + half + 14 and abs(spc[1] - ly) < fs * 0.9 + 14:
                ly = spc[1] - (fs * 0.9 + 16) if ly <= spc[1] else spc[1] + (fs * 0.9 + 16)
        sag = min(half * 0.10, 13.0)
        RR = (half * half + sag * sag) / (2 * sag)
        sweep = 1 if ly < CY else 0
        pid = f"lp{li}"
        e.append(f'<path id="{pid}" d="M{cx-half:.1f} {ly:.1f} A{RR:.1f} {RR:.1f} 0 0 {sweep} {cx+half:.1f} {ly:.1f}" fill="none"/>')
        e.append(f'<text font-size="{fs:.1f}" font-weight="bold" letter-spacing="0.4" '
                 f'fill="#1a1410" stroke="#caa46a" stroke-width="{max(2.0, fs*0.18):.1f}" paint-order="stroke" stroke-linejoin="round">'
                 f'<textPath href="#{pid}" startOffset="50%" text-anchor="middle">{nm}</textPath></text>')
    # номерные бейджи
    e.append('<g text-anchor="middle" dominant-baseline="central">')
    for i, mk in enumerate(m['marks']):
        n, x, y = i + 1, mk['c'][0], mk['c'][1]
        e.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="9.5" fill="rgba(245,236,212,.97)" stroke="{mk["roof"]}" stroke-width="2"/>')
        e.append(f'<text x="{x:.1f}" y="{y+0.5:.1f}" fill="#2c2113" font-weight="bold" font-size="12">{n}</text>')
    e.append('</g>')
    # обрамление
    e.append(f'<rect width="{W}" height="{H}" fill="url(#vg)"/>')
    e.append(f'<rect x="5" y="5" width="{W-10}" height="{H-10}" fill="none" stroke="#4a3415" stroke-width="5"/>')
    if chrome:                                              # компас (без верхней подписи города)
        e.append(f'<g transform="translate({W-40},46)"><circle r="18" fill="rgba(233,216,175,.85)" stroke="#4a3415" stroke-width="1"/>'
                 f'<path d="M0 -20 L4 -3 L-4 -3 Z" fill="#4a3415"/>'
                 f'<text y="-22" text-anchor="middle" fill="#4a3415" font-weight="bold" font-size="9">С</text></g>')
    if interactive:                                         # клик по дому → яркое выделение полигона + событие cityHouse
        e.append('<style>.h{cursor:pointer}.h.sel{fill:#ffd23f !important;stroke:#7a3a00 !important;stroke-width:1.8 !important}</style>')
        e.append('<script><![CDATA['
                 'var sel=null;'
                 'function pick(el){if(sel)sel.classList.remove("sel");sel=el;el.classList.add("sel");'
                 'var id=el.getAttribute("data-id");'
                 'try{window.dispatchEvent(new CustomEvent("cityHouse",{detail:{id:id}}));}catch(e){}'
                 'if(window.onCityHouse)window.onCityHouse(id);}'
                 'document.querySelectorAll(".h").forEach(function(el){el.addEventListener("click",function(ev){ev.stopPropagation();pick(el);});});'
                 'window.selectCityHouse=function(id){var el=document.querySelector(\'.h[data-id="\'+id+\'"]\');if(el){pick(el);return true;}return false;};'
                 ']]></script>')
    e.append('</svg>')
    return "\n".join(e)


def render_page(seed=1, W=980, H=700, title='Фэндалин'):
    """Готовая HTML-страница с интерактивным городом (для встраивания/демо)."""
    m = build_city(seed, W, H, title=title)
    svg = render_svg(m, interactive=True) if m else '<svg/>'
    return ('<!DOCTYPE html><html lang="ru"><head><meta charset="utf-8">'
            '<style>body{margin:0;background:#15161a;font:14px system-ui;color:#e8ebf1;display:flex;flex-direction:column;align-items:center}'
            '#info{position:fixed;top:8px;left:8px;background:#1b1f27;border:1px solid #2f3641;padding:7px 11px;border-radius:8px}'
            'svg{max-width:98vw;height:auto}</style></head><body>'
            '<div id="info">Клик по дому — выделить</div>' + svg +
            '<script>window.addEventListener("cityHouse",function(e){document.getElementById("info").textContent="Выбран дом: "+e.detail.id;});</script>'
            '</body></html>')


if __name__ == "__main__":
    seed = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    W = int(sys.argv[2]) if len(sys.argv) > 2 else 980
    H = int(sys.argv[3]) if len(sys.argv) > 3 else 700
    if "html" in sys.argv:
        sys.stdout.write(render_page(seed, W, H))
    else:
        model = build_city(seed, W, H)
        sys.stdout.write(render_svg(model) if model else "<svg/>")
