"""Пошаговый боевой движок (5e-lite): инициатива d20+dex, ход = движение (клетки, BFS) + одно
действие (attack / dodge / flee / end). Атака d20+to_hit против AC (dodge = помеха), урон кости+бонус,
резист/иммун по типу. Мораль: слабые бегут. Детерминирован сидом. Лог сухой, как у мастера за столом.
"""

from __future__ import annotations

import re
from collections import deque
from random import Random

from .model import Combatant

MAX_ROUNDS = 40
MORALE_HP = 0.3                      # ниже этой доли hp слабые (cr<2) проверяют мораль
MORALE_DC = 8


def roll_dice(spec: str, rng: Random) -> int:
    m = re.fullmatch(r"(\d+)d(\d+)", spec or "1d4")
    n, d = (int(m.group(1)), int(m.group(2))) if m else (1, 4)
    return sum(rng.randint(1, d) for _ in range(n))


class Encounter:
    def __init__(self, party: list, foes: list, seed: str, w: int = 12, h: int = 9,
                 obstacles: set | None = None, waves: list | None = None):
        self.rng = Random(f"enc|{seed}")
        self.w, self.h = w, h
        self.obstacles = obstacles if obstacles is not None else self._gen_obstacles()
        self.pending_waves = list(waves or [])             # накаты 2..n (первый — уже в foes)
        self.units: dict[str, Combatant] = {}
        for i, c in enumerate(party):
            c.side = "party"
            self._spawn(c, left=True, slot=i)
        for i, c in enumerate(foes):
            c.side = "foes"
            self._spawn(c, left=False, slot=i)
        order = sorted(self.units.values(),
                       key=lambda c: -(self.rng.randint(1, 20) + c.init_mod))
        self.order = [c.id for c in order]
        self.ti = 0                                        # индекс хода в order
        self.round = 1
        self.log: list[str] = []
        self.moved: int = 0                                # клетки, потраченные в текущем ходу
        self.acted: bool = False
        self._log(f"Инициатива: {', '.join(self.units[i].name for i in self.order)}.")

    def foes_cleared(self) -> bool:
        return not any(u.side == "foes" and not u.down() for u in self.units.values())

    def next_wave(self) -> bool:
        """Если текущие враги повержены, а накаты остались — выпустить следующий у дальней стены."""
        if not self.pending_waves or not self.foes_cleared():
            return False
        wave = self.pending_waves.pop(0)
        base = len(self.units)
        for i, c in enumerate(wave):
            c.side = "foes"
            c.id = f"{c.id}:w{len(self.pending_waves)}:{i}"    # уникальный id в накате
            self._spawn(c, left=False, slot=base + i)
            self.order.append(c.id)
        self._log(f"Из темноты накатывает подмога врага: {', '.join(c.name for c in wave)}.")
        return True

    # ------------------------------------------------------------ сетап --- #
    def _gen_obstacles(self) -> set:
        out = set()
        for _ in range(self.w * self.h // 10):
            x, y = self.rng.randrange(2, self.w - 2), self.rng.randrange(self.h)
            out.add((x, y))
        return out

    def _spawn(self, c: Combatant, left: bool, slot: int) -> None:
        xs = range(0, 2) if left else range(self.w - 2, self.w)
        for _ in range(200):
            x, y = self.rng.choice(list(xs)), self.rng.randrange(self.h)
            if (x, y) not in self.obstacles and not self._occupied(x, y):
                c.x, c.y = x, y
                break
        self.units[c.id] = c

    # ------------------------------------------------------------ гео ----- #
    def _occupied(self, x, y, ignore=None):
        return any(u.x == x and u.y == y and not u.down() and u.id != ignore
                   for u in self.units.values())

    def dist(self, a: Combatant, b: Combatant) -> int:
        return max(abs(a.x - b.x), abs(a.y - b.y))

    def path_len(self, c: Combatant, tx: int, ty: int) -> int | None:
        """BFS по клеткам (8 направлений), препятствия и занятые клетки непроходимы."""
        if (tx, ty) in self.obstacles or self._occupied(tx, ty, ignore=c.id):
            return None
        seen, q = {(c.x, c.y)}, deque([(c.x, c.y, 0)])
        while q:
            x, y, d = q.popleft()
            if (x, y) == (tx, ty):
                return d
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    nx, ny = x + dx, y + dy
                    if (dx or dy) and 0 <= nx < self.w and 0 <= ny < self.h \
                            and (nx, ny) not in seen and (nx, ny) not in self.obstacles \
                            and not self._occupied(nx, ny, ignore=c.id):
                        seen.add((nx, ny))
                        q.append((nx, ny, d + 1))
        return None

    # ------------------------------------------------------------ ход ----- #
    def current(self) -> Combatant | None:
        alive = [i for i in self.order if not self.units[i].down()]
        if not alive:
            return None
        while self.units[self.order[self.ti % len(self.order)]].down():
            self.ti += 1
        return self.units[self.order[self.ti % len(self.order)]]

    def status(self) -> str:
        party = any(u.side == "party" and not u.down() for u in self.units.values())
        foes = any(u.side == "foes" and not u.down() for u in self.units.values())
        if party and foes and self.round <= MAX_ROUNDS:
            return "active"
        if party and not foes:
            return "won"
        if foes and not party:
            return "lost"
        return "draw"

    def end_turn(self) -> None:
        c = self.current()
        if c:
            c.dodging = False if self.acted or self.moved else c.dodging
            for k in list(c.status):                       # статусы тают на исходе СВОЕГО хода
                if c.status[k] > 0:
                    c.status[k] -= 1
                if c.status[k] <= 0:
                    del c.status[k]
        self.ti += 1
        self.moved, self.acted = 0, False
        if self.ti % len(self.order) == 0:
            self.round += 1

    def _log(self, s: str) -> None:
        self.log.append(s)
        if len(self.log) > 200:
            self.log = self.log[-120:]

    # ------------------------------------------------------------ действия - #
    def act_move(self, c: Combatant, tx: int, ty: int) -> str | None:
        d = self.path_len(c, tx, ty)
        if d is None:
            return "туда не пройти"
        if d > c.speed - self.moved:
            return "слишком далеко для этого хода"
        c.x, c.y = tx, ty
        self.moved += d
        return None

    def act_attack(self, c: Combatant, target_id: str) -> str | None:
        if self.acted:
            return "действие уже потрачено"
        t = self.units.get(target_id)
        if not t or t.down() or t.side == c.side:
            return "не цель"
        if self.dist(c, t) > c.range:
            return "не дотянуться"
        self.acted = True
        # дальнобой в упор (враг вплотную) — стрелять несподручно: помеха
        crowded = c.range > 1 and any(u.side != c.side and not u.down() and self.dist(c, u) <= 1
                                      for u in self.units.values())
        r1 = self.rng.randint(1, 20)
        roll = min(r1, self.rng.randint(1, 20)) if (t.dodging or crowded) else r1
        total = roll + c.to_hit
        if roll == 1 or (roll != 20 and total < t.ac):
            self._log(f"{c.name} атакует: промах ({total} против AC {t.ac} у {t.name}).")
            return None
        dmg = roll_dice(c.dmg_dice, self.rng) + c.dmg_bonus
        if roll == 20:
            dmg += roll_dice(c.dmg_dice, self.rng)
        if c.dmg_type in t.immune:
            dmg = 0
        elif c.dmg_type in t.resist:
            dmg //= 2
        t.hp -= dmg
        if dmg > 0 and t.status.pop("asleep", 0):          # удар будит спящего
            self._log(f"{t.name} просыпается от удара.")
        crit = " (крит!)" if roll == 20 else ""
        if t.hp <= 0:
            t.alive = False
            self._log(f"{c.name} атакует: {t.name} получает {dmg} урона{crit} и падает.")
        else:
            self._log(f"{c.name} атакует: {t.name} получает {dmg} урона{crit} [{t.hp}/{t.max_hp}]")
        return None

    def act_dodge(self, c: Combatant) -> str | None:
        if self.acted:
            return "действие уже потрачено"
        self.acted, c.dodging = True, True
        self._log(f"{c.name} уходит в глухую защиту.")
        return None

    def act_flee(self, c: Combatant) -> str | None:
        if self.acted:
            return "действие уже потрачено"
        edge = min(c.x, c.y, self.w - 1 - c.x, self.h - 1 - c.y)
        if edge > 0:
            return "до края не добраться — сперва отойди"
        self.acted, c.fled = True, True
        self._log(f"{c.name} покидает бой.")
        return None

    # ------------------------------------------------------------ ИИ ------ #
    def ai_turn(self, c: Combatant) -> None:
        """Простая тактика: мораль → бегство; иначе к ближайшему врагу и бить.
        Статусы: связан/спит — ход пропущен; напуган — держится подальше, не атакует."""
        foes = [u for u in self.units.values() if u.side != c.side and not u.down()]
        if not foes:
            self.end_turn()
            return
        if c.incapacitated():
            self._log(f"{c.name} {'связан' if c.status.get('bound') else 'спит'} — ход потерян.")
            self.end_turn()
            return
        if c.status.get("afraid", 0) > 0:                   # напуган: пятится к краю, не бьёт
            nearest = min(foes, key=lambda u: self.dist(c, u))
            spot = self._kite(c, nearest)
            if spot:
                c.x, c.y = spot
            self._log(f"{c.name} в ужасе пятится прочь.")
            self.end_turn()
            return
        if c.kind == "monster" and c.cr < 2 and c.hp < c.max_hp * MORALE_HP \
                and self.rng.randint(1, 20) < MORALE_DC:
            edge_cell = min(((x, y) for x in range(self.w) for y in range(self.h)
                             if min(x, y, self.w - 1 - x, self.h - 1 - y) == 0
                             and self.path_len(c, x, y) is not None),
                            key=lambda p: self.path_len(c, p[0], p[1]), default=None)
            if edge_cell:
                d = self.path_len(c, *edge_cell)
                if d is not None and d <= c.speed:
                    c.x, c.y = edge_cell
                    self.act_flee(c)
                    self.end_turn()
                    return
        t = min(foes, key=lambda u: self.dist(c, u))
        if c.range > 1:                                     # ДАЛЬНОБОЙ: держать дистанцию, стрелять
            if any(self.dist(c, u) <= 1 for u in foes):     # кто-то в упор — отойти (кайт)
                spot = self._kite(c, min(foes, key=lambda u: self.dist(c, u)))
                if spot:
                    c.x, c.y = spot
            elif self.dist(c, t) > c.range:                 # цель дальше выстрела — сблизиться
                spot = self._approach(c, t, c.range)
                if spot:
                    c.x, c.y = spot
        elif self.dist(c, t) > c.range:                     # ближний: подойти вплотную
            spot = self._approach(c, t, c.range)
            if spot:
                c.x, c.y = spot
        if self.dist(c, t) <= c.range:
            self.act_attack(c, t.id)
        self.end_turn()

    def _approach(self, c: Combatant, t: Combatant, stop: int):
        """Клетка в пределах хода, приближающая к t (стоп при dist ≤ stop). None если некуда."""
        best, bd = None, self.dist(c, t)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                if not (dx or dy):
                    continue
                steps, x, y = 0, c.x, c.y
                while steps < c.speed:
                    nx, ny = x + dx, y + dy
                    if not (0 <= nx < self.w and 0 <= ny < self.h) \
                            or (nx, ny) in self.obstacles or self._occupied(nx, ny, ignore=c.id):
                        break
                    x, y, steps = nx, ny, steps + 1
                    nd = max(abs(x - t.x), abs(y - t.y))
                    if nd < bd:
                        best, bd = (x, y), nd
                    if nd <= stop:
                        break
        return best

    def _kite(self, c: Combatant, foe: Combatant):
        """Отойти от foe (до 3 клеток), максимизируя дистанцию. None если зажат."""
        best, bd, lim = None, self.dist(c, foe), min(c.speed, 3)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                if not (dx or dy):
                    continue
                steps, x, y = 0, c.x, c.y
                while steps < lim:
                    nx, ny = x + dx, y + dy
                    if not (0 <= nx < self.w and 0 <= ny < self.h) \
                            or (nx, ny) in self.obstacles or self._occupied(nx, ny, ignore=c.id):
                        break
                    x, y, steps = nx, ny, steps + 1
                if steps:
                    nd = max(abs(x - foe.x), abs(y - foe.y))
                    if nd > bd:
                        best, bd = (x, y), nd
        return best

    def view(self) -> dict:
        cur = self.current()
        return {"w": self.w, "h": self.h, "obstacles": sorted(self.obstacles),
                "units": [u.view() for u in self.units.values()],
                "order": self.order, "turn": (cur.id if cur else None), "round": self.round,
                "moved": self.moved, "acted": self.acted,
                "status": self.status(), "log": self.log[-14:]}
