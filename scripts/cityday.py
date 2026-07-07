"""ГИФ «день города»: прокрутить сутки по 30 мин, снять позиции всех NPC, склеить."""
import os
import subprocess

from aidnd import society
from aidnd.server.play.engine.core import _S, _store, _wid
from aidnd.server.play.engine.world import _play
from aidnd.server.play.engine.worldsim import routine_step

OUT = "/private/tmp/claude-501/-Users-nik-Desktop-dnd-ai/cbd3c8c1-7cbc-4d30-a9af-cdad304d38a4/scratchpad/cityframes"
os.makedirs(OUT, exist_ok=True)
city, people, crof, cr2b, loc = _play()
xy = _S["geom"]["_xy"]; vb = _S["geom"]["viewBox"]; keynode = _S.get("keynode") or {}
W, H = vb[2], vb[3]

# узел → тип заведения (для классификации активности)
node_kind = {}
for bid, node in keynode.items():
    data = (_store().get_building(_wid(), bid) or {}).get("data") or {}
    ks = society.kinds_of(data)
    node_kind[node] = ks[0] if ks else "work"
work_node = {pid: keynode.get(p.work) for pid, p in people.items() if p.work}
home_of = {pid: p.home for pid, p in people.items()}

COL = {"home":"#3f6fbf","work":"#e0932a","tavern":"#c0392b","temple":"#8e5bd0",
       "market":"#3aa657","street":"#9a9a9a","patrol":"#2b7d8c","prowl":"#7a1f5c","other":"#9a9a9a"}
KMAP = {"home":"home","work":"work","tavern":"tavern","temple":"temple","market":"market",
        "street":"street","patrol":"patrol","prowl":"prowl","appointment":"work"}
def activity(pid, node):
    k = _S.get("crof_kind",{}).get(pid)
    return KMAP.get(k, "street")

def frame(i, gt):
    _S["gt"] = gt; _S.pop("live", None)
    routine_step(people, crof)
    acts = {}
    import math
    from collections import Counter, defaultdict
    per_node = defaultdict(Counter)                  # узел → {активность: сколько}
    for pid, p in people.items():
        node = crof.get(pid)
        if node not in xy: continue
        a = activity(pid, node)
        acts[a] = acts.get(a, 0) + 1
        per_node[node][a] += 1
    dots = []
    for node, cnt in per_node.items():
        x, yy = xy[node]
        tot = sum(cnt.values())
        dom = cnt.most_common(1)[0][0]               # доминирующая активность узла
        r = 2.2 + math.sqrt(tot) * 1.7               # пузырь ∝ √числа
        dots.append((x, yy, COL[dom], r, tot))
    hh, mm = gt//60%24, gt%60
    ph = ("ночь" if hh<6 or hh>=22 else "утро" if hh<11 else "день" if hh<17 else "вечер")
    dark = 0.12 if (hh<6 or hh>=22) else 0.06 if (hh>=19 or hh<7) else 0.0
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" font-family="Georgia,serif">',
           f'<rect width="{W}" height="{H}" fill="#efe7d3"/>',
           f'<rect width="{W}" height="{H}" fill="#0a1836" opacity="{dark}"/>']
    for n,(x,yy) in xy.items():          # граф-подложка бледно
        out.append(f'<circle cx="{x:.0f}" cy="{yy:.0f}" r="1" fill="#bcae8e"/>')
    for node,k in node_kind.items():     # заведения — метки
        if node in xy:
            x,yy = xy[node]
            out.append(f'<rect x="{x-3:.0f}" y="{yy-3:.0f}" width="6" height="6" fill="none" stroke="#7a6b48" stroke-width="1"/>')
    for x,yy,c,r,tot in sorted(dots, key=lambda d:-d[3]):
        out.append(f'<circle cx="{x:.1f}" cy="{yy:.1f}" r="{r:.1f}" fill="{c}" '
                   f'opacity="0.8" stroke="#2a2016" stroke-width="0.4"/>')
    # часы + легенда
    out.append(f'<text x="18" y="38" font-size="30" fill="#2a2016">{hh:02d}:{mm:02d} · {ph}</text>')
    lx = 18
    for lbl,k in (("дома","home"),("работа","work"),("таверна","tavern"),("рынок","market"),("храм","temple"),("улица","street"),("дозор","patrol"),("промысел","prowl")):
        n = acts.get(k,0)
        out.append(f'<circle cx="{lx+6}" cy="{H-22}" r="5" fill="{COL[k]}"/>'
                   f'<text x="{lx+16}" y="{H-17}" font-size="15" fill="#2a2016">{lbl} {n}</text>')
        lx += 42 + len(lbl)*8
    out.append("</svg>")
    svg = "".join(out)
    fn = f"{OUT}/f{i:03d}"
    open(fn+".svg","w").write(svg)
    subprocess.run(["rsvg-convert","-w","980",fn+".svg","-o",fn+".png"], check=True)
    return acts

# сутки с 06:00, шаг 30 мин (48 кадров)
_S["needs_gt"] = {}
for i in range(48):
    gt = 6*60 + i*30
    a = frame(i, gt)
    if i % 6 == 0:
        print(f"{gt//60%24:02d}:{gt%60:02d}", {k:a.get(k,0) for k in ('home','work','tavern','market','street')})
# склейка
subprocess.run(f"ffmpeg -y -framerate 4 -i {OUT}/f%03d.png -vf scale=980:-1 "
               f"-loop 0 {OUT}/../cityday.gif", shell=True, check=True,
               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
print("GIF готов")
