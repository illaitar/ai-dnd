"""Тактический боевой движок «как в Baldur's Gate» (док 09 + док 10).

Полная тактика: позиции на сетке, движение с pathfinding, дальность/реч, линия
видимости, укрытие (AC), высота (преимущество), поверхности, атаки по возможности
(AoO), Dodge/Disengage/Shove, заклинания, позиционный ИИ монстров.

Архитектура хода. Разрешение атаки (`_perform_attack`) НЕ трогает бюджет хода —
списание action/reaction делает вызывающий код: ход PC и монстра тратит action,
AoO тратит reaction. Это убирает дубль и спецслучаи. PC-ход многошаговый: команды
move_to/declare_attack/dash/dodge/disengage/shove/cast/end_turn; атака
приостанавливается на бросок игрока (RollRequest), монстры — авто-сидированно.
"""

from __future__ import annotations

from .. import ids
from ..inventory.container import armor_class, equipped_weapon_key, weapon_damage_expr
from ..rules.checks import ability_mod, attack_modifier, save_modifier, skill_modifier
from ..rules.conditions import Condition, is_incapacitated
from ..rules.dice import RollResult, double_dice
from ..rules.engine import d20_test
from ..rules.srd import WEAPONS, ability_modifier, get_stat_block
from ..world.components import Persona, Stats5e
from . import spells, surfaces, tactician
from .grid import BattleGrid
from .state import Combatant, CombatState, TurnBudget

RANGED_RANGE_SQ = {"shortbow": 16, "light_crossbow": 16}    # дальность в клетках
DEFAULT_RANGE_SQ = 12


class CombatEngine:
    def __init__(self, world, dice, model=None, cognition=None, lod=None) -> None:
        self.world = world
        self.dice = dice
        self.model = model
        self.cognition = cognition
        self.lod = lod
        self.state: CombatState | None = None
        self.pending: dict | None = None

    # --- стандартные ответы команд ---------------------------------------- #
    @staticmethod
    def _ok(outcome: str, **extra) -> dict:
        return {"kind": "combat", "outcome": outcome, "done": True, **extra}

    @staticmethod
    def _no(outcome: str) -> dict:
        return {"kind": "system", "outcome": outcome, "done": True}

    def _need_action(self) -> dict | None:
        return None if self.state.turn_budget.action else self._no("Действие уже потрачено.")

    # ============================================================ старт ====
    def start(self, party_ids, enemy_ids, grid: BattleGrid | None = None,
              init_surfaces: list | None = None) -> CombatState:
        cs = CombatState(grid=grid or BattleGrid.empty())
        self.state = cs
        rolls = []
        for side, group in (("party", party_ids), ("enemy", enemy_ids)):
            spawns = list(cs.grid.party_spawn if side == "party" else cs.grid.enemy_spawn)
            used = {c.pos for c in cs.combatants.values()}
            for i, eid in enumerate(group):
                dexm = ability_mod(self.world, eid, "dex")
                r = self.dice.roll_seeded("initiative", "1d20", modifier=dexm, roller=eid)
                pos = spawns[i] if i < len(spawns) else None
                if pos is None or pos in used:          # не ставить двоих на одну клетку
                    pos = self._free_cell(used)
                used.add(pos)
                cs.combatants[eid] = Combatant(
                    entity_id=eid, initiative=r.total, ac=armor_class(self.world, eid),
                    side=side, pos=pos)
                rolls.append((r.total, dexm, eid))
                self.world.commit("initiative", eid, roll=r.to_record("1d20"))
        rolls.sort(reverse=True)
        cs.initiative_order = [eid for _, _, eid in rolls]
        cs.turn_budget = TurnBudget.fresh(self._speed(cs.current()))
        for s in (init_surfaces or []):              # стартовые поверхности (напр. вода)
            surfaces.create(self, [tuple(c) for c in s.get("cells", [])],
                            s.get("type", "water"), rounds=99)
        cs.log.append("Инициатива: " + ", ".join(
            f"{ids.name_of(e)}({cs.combatants[e].initiative})" for e in cs.initiative_order))
        surfaces.on_turn_start(self, cs.current())
        return cs

    # ==================================================== опрос состояния ==
    def is_pc_turn(self) -> bool:
        cur = self.state.current()
        return bool(cur and ids.is_pc(cur) and self.world.is_alive(cur)
                    and not is_incapacitated(self.world.conditions.get(cur, [])))

    def _living(self, side: str) -> list[str]:
        return [c.entity_id for c in self.state.combatants.values()
                if c.side == side and not c.fled and self.world.is_alive(c.entity_id)]

    def alive_enemies(self) -> list[str]:
        return self._living("enemy")

    def alive_allies(self) -> list[str]:
        return self._living("party")

    # ==================================================== движение =========
    def reachable_cells(self, eid: str | None = None) -> dict:
        cs = self.state
        eid = eid or cs.current()
        return cs.grid.reachable(cs.combatants[eid].pos, cs.turn_budget.movement,
                                 cs.occupied(eid))

    def move_to(self, cell) -> dict:
        cs = self.state
        eid = cs.current()
        cell = tuple(cell)
        reach = self.reachable_cells(eid)
        if cell not in reach:
            return self._no("Недостижимо за оставшееся движение.")
        path = cs.grid.path(cs.combatants[eid].pos, cell, cs.occupied(eid))
        if not path:
            return self._no("Нет пути.")
        if self._walk_path(eid, path):              # True — погиб по пути (AoO/поверхность)
            self.advance_turn()
            return self._ok(f"{self._name(eid)} пал при движении.")
        cs.turn_budget.movement -= reach[cell]
        return self._ok(f"{self._name(eid)} перемещается.", moved=True)

    def _walk_path(self, eid: str, path: list) -> bool:
        """Идёт по клеткам пути: AoO при выходе из угрозы, эффекты поверхностей.
        Возвращает True, если боец погиб в процессе."""
        cs = self.state
        self._provoke_aoo(eid, cs.combatants[eid].pos, path[-1])
        if not self.world.is_alive(eid):
            return True
        for step in path:
            cs.combatants[eid].pos = step
            surfaces.on_enter(self, eid, step)
            if not self.world.is_alive(eid):
                return True
        return False

    def dash(self) -> dict:
        if (err := self._need_action()):
            return err
        cs = self.state
        cs.turn_budget.action = False
        cs.turn_budget.dashed = True
        cs.turn_budget.movement += self._speed(cs.current())
        return self._ok(f"{self._name(cs.current())} совершает рывок.")

    def dodge(self) -> dict:
        if (err := self._need_action()):
            return err
        self.state.turn_budget.action = False
        self.state.combatants[self.state.current()].dodging = True
        return self._ok(f"{self._name(self.state.current())} уклоняется (атаки по нему с помехой).")

    def disengage(self) -> dict:
        if (err := self._need_action()):
            return err
        self.state.turn_budget.action = False
        self.state.combatants[self.state.current()].disengaging = True
        return self._ok(f"{self._name(self.state.current())} отступает (без AoO).")

    # ==================================================== Shove (толчок) ===
    def shove(self, target_id: str) -> dict:
        if (err := self._need_action()):
            return err
        cs = self.state
        eid = cs.current()
        if not cs.grid.adjacent(cs.combatants[eid].pos, cs.combatants[target_id].pos):
            return self._no("Цель не в досягаемости.")
        cs.turn_budget.action = False
        atk = self.dice.roll_seeded("skill", "1d20", roller=eid,
                                    modifier=skill_modifier(self.world, eid, "athletics"))
        df = self.dice.roll_seeded("skill", "1d20", roller=target_id,
                                   modifier=max(skill_modifier(self.world, target_id, "athletics"),
                                                skill_modifier(self.world, target_id, "acrobatics")))
        if atk.total >= df.total:
            self._push(target_id, eid)
            return self._ok(f"{self._name(eid)} толкает {self._name(target_id)} ({atk.total} ≥ {df.total}).")
        return self._ok(f"{self._name(eid)} не смог столкнуть {self._name(target_id)} ({atk.total} < {df.total}).")

    def _push(self, target_id: str, from_id: str, dist: int = 1) -> None:
        cs = self.state
        tx, ty = cs.combatants[target_id].pos
        fx, fy = cs.combatants[from_id].pos
        dx, dy = (tx > fx) - (tx < fx), (ty > fy) - (ty < fy)
        for _ in range(dist):
            nc = (tx + dx, ty + dy)
            if cs.grid.is_passable(*nc) and not cs.at(nc):
                tx, ty = nc
        cs.combatants[target_id].pos = (tx, ty)
        surfaces.on_enter(self, target_id, (tx, ty))

    # ==================================================== Атака ===========
    def in_attack_range(self, attacker: str, target: str) -> bool:
        cs = self.state
        a, t = cs.combatants[attacker].pos, cs.combatants[target].pos
        if self._is_ranged(attacker):
            rng = RANGED_RANGE_SQ.get(equipped_weapon_key(self.world, attacker), DEFAULT_RANGE_SQ)
            return cs.grid.distance_squares(a, t) <= rng and cs.grid.has_los(a, t)
        return cs.grid.adjacent(a, t)

    def pc_declare_attack(self, target_id: str):
        cs = self.state
        attacker = cs.current()
        if (err := self._need_action()):
            return err
        if not self.in_attack_range(attacker, target_id):
            return self._no("Цель вне досягаемости/линии видимости.")
        mod, adv, ac = self._attack_context(attacker, target_id)
        cs.turn_budget.action = False
        req = self.dice.request_player("attack", "1d20", modifier=mod, advantage=adv, dc=ac,
                                       roller=attacker, context={"target": target_id, "kind": "attack"})
        self.pending = {"phase": "attack", "attacker": attacker, "target": target_id, "request": req}
        return req

    def submit_roll(self, result: RollResult) -> dict:
        """Возобновляет приостановленную атаку PC по броску игрока."""
        if not self.pending:
            return {"outcome": "нет ожидающего броска", "next_request": None, "done": True}
        p = self.pending
        attacker, target = p["attacker"], p["target"]
        if p["phase"] == "attack":
            self.world.commit("attack", attacker, target=target, roll=result.to_record(p["request"].dice))
            verdict = d20_test(result, p["request"].dc, is_attack=True)
            if not verdict["success"]:
                self.pending = None
                return {"outcome": f"{self._name(attacker)} промахивается по {self._name(target)}.",
                        "hit": False, "next_request": None, "done": True}
            expr, dmod = self._weapon_damage(attacker, verdict["crit"])
            req = self.dice.request_player("damage", expr, modifier=dmod, roller=attacker,
                                           context={"target": target})
            self.pending = {"phase": "damage", "attacker": attacker, "target": target,
                            "request": req, "crit": verdict["crit"]}
            return {"outcome": "Критическое попадание!" if verdict["crit"] else "Попадание!",
                    "hit": True, "crit": verdict["crit"], "next_request": req, "done": False}
        # фаза урона
        self._apply_damage(attacker, target, result.total, roll=result.to_record(p["request"].dice))
        self.pending = None
        weapon, dt = self._weapon_phrase(attacker)
        return {"outcome": f"{self._name(attacker)} наносит {result.total} {dt} урона "
                           f"{self._name(target)} ({weapon}).",
                "damage": result.total, "next_request": None, "done": True}

    def _perform_attack(self, attacker: str, target: str) -> str:
        """Полное авто-разрешение атаки (бросок попадания + урон + применение).
        НЕ трогает бюджет хода — это делает вызывающий код (action либо reaction)."""
        mod, adv, ac = self._attack_context(attacker, target)
        atk = self.dice.roll_seeded("attack", "1d20", modifier=mod, advantage=adv, dc=ac, roller=attacker)
        self.world.commit("attack", attacker, target=target, roll=atk.to_record("1d20"))
        verdict = d20_test(atk, ac, True)
        if not verdict["success"]:
            return f"{self._name(attacker)} промахивается по {self._name(target)}."
        expr, dmod = self._weapon_damage(attacker, verdict["crit"])
        dmg = self.dice.roll_seeded("damage", expr, modifier=dmod, roller=attacker)
        self._apply_damage(attacker, target, dmg.total, roll=dmg.to_record(expr))
        weapon, dt = self._weapon_phrase(attacker)
        return (f"{'крит! ' if verdict['crit'] else ''}{self._name(attacker)} наносит "
                f"{dmg.total} {dt} урона {self._name(target)} ({weapon}).")

    def _weapon_phrase(self, attacker: str) -> tuple[str, str]:
        """(имя оружия, тип урона по-русски) экипированного оружия — чтобы нарратор
        описывал ИМЕННО его, а не выдумывал стихию/дальность."""
        from ..inventory.container import equipped_weapon_key
        from ..rules.srd import WEAPONS
        w = WEAPONS.get(equipped_weapon_key(self.world, attacker), WEAPONS["unarmed"])
        dt = {"slashing": "рубящего", "piercing": "колющего",
              "bludgeoning": "дробящего"}.get(w.damage_type, "")
        return w.name, dt

    def _weapon_damage(self, attacker: str, crit: bool) -> tuple[str, int]:
        expr, ability, magic = weapon_damage_expr(self.world, attacker)
        if crit:
            expr = double_dice(expr)
        return expr, ability_mod(self.world, attacker, ability) + magic

    def _attack_context(self, attacker: str, target: str) -> tuple[int, int, int]:
        """(модификатор, преимущество, эффективный AC) с учётом позиции (док 07 §6)."""
        cs = self.state
        mod, adv = attack_modifier(self.world, attacker, target)
        ap, tp = cs.combatants[attacker].pos, cs.combatants[target].pos
        ac = cs.combatants[target].ac + cs.grid.cover_bonus(ap, tp)
        if cs.grid.elevation(*ap) > cs.grid.elevation(*tp):
            adv += 1                                      # высота — преимущество
        if cs.combatants[target].dodging:
            adv -= 1                                      # Dodge — помеха
        if self._is_ranged(attacker) and self._enemy_adjacent(attacker):
            adv -= 1                                      # дальний бой в ближнем — помеха
        if self._has_condition(target, "prone"):
            adv += -1 if self._is_ranged(attacker) else 1  # ничком: дальний −, ближний +
        return mod, max(-1, min(1, adv)), ac

    # ==================================================== Заклинания ======
    def cast(self, caster: str, spell_key: str, target=None, cell=None) -> dict:
        cs = self.state
        spell = spells.SPELLS.get(spell_key)
        if not spell:
            return self._no("Неизвестное заклинание.")
        st = self.world.ecs.get(caster, Stats5e)
        if spell.level > 0:
            slots = st.spell_slots if st else {}
            if slots.get(str(spell.level), 0) <= 0:
                return self._no("Нет ячейки заклинания.")
            self.world.commit("cast_spell", caster,
                              payload={"spell": spell_key, "level": spell.level})
        cs.turn_budget.action = False
        cast_mod = (st.proficiency if st else 2) + (ability_modifier(st.ability(st.spell_ability)) if st else 0)
        dc = 8 + cast_mod
        tcell = cell or (cs.combatants[target].pos if target and target in cs.combatants else None)
        out = f"{self._name(caster)} творит «{spell.name}»"

        if spell.kind == "attack" and target:
            atk = self.dice.roll_seeded("attack", "1d20", modifier=cast_mod,
                                        dc=cs.combatants[target].ac, roller=caster)
            if d20_test(atk, cs.combatants[target].ac, True)["success"]:
                dmg = self.dice.roll_seeded("damage", spell.damage, roller=caster)
                self._apply_damage(caster, target, dmg.total)
                out += f" — попадание, {dmg.total} урона ({spell.dtype})."
            else:
                out += " — промах."
        elif spell.kind == "auto" and target:
            dmg = self.dice.roll_seeded("damage", spell.damage, roller=caster)
            total = dmg.total * 3 if spell_key == "magic_missile" else dmg.total
            self._apply_damage(caster, target, total)
            out += f" — {total} урона ({spell.dtype}), без промаха."
        elif spell.kind == "save" and tcell:
            area = spells.cone_cells(cs.grid, cs.combatants[caster].pos, tcell, 3)
            victims = {cs.at(c) for c in area if cs.at(c)}
            for tid in victims:
                dmg = self.dice.roll_seeded("damage", spell.damage, roller=caster)
                self._apply_damage(caster, tid,
                                   dmg.total // 2 if self._save(tid, spell.save_ability, dc) else dmg.total)
            if spell.creates:
                surfaces.create(self, area, spell.creates)
            out += f" — конус поражает {len(victims)} целей."
        elif spell.kind == "utility" and spell.creates and tcell:
            surfaces.create(self, spells.square_cells(cs.grid, tcell, 1), spell.creates)
            out += f" — создаёт «{spell.creates}»."
        elif spell.kind == "heal" and target:
            heal = self.dice.roll_seeded("heal", spell.damage, roller=caster,
                                         modifier=ability_modifier(st.ability(st.spell_ability)) if st else 0)
            self.world.commit("heal", caster, target=target, payload={"amount": heal.total})
            out += f" — лечит {self._name(target)} на {heal.total}."
        cs.log.append(out)
        return self._ok(out)

    # ==================================================== Ход монстра =====
    def auto_turn(self) -> dict:
        cs = self.state
        cur = cs.current()
        if not self._can_act(cur):
            self.advance_turn()
            return self._ok(f"{self._name(cur)} пропускает ход.")
        surfaces.on_turn_start(self, cur)
        if not self.world.is_alive(cur):
            self.advance_turn()
            return self._ok(f"{self._name(cur)} гибнет от поверхности.")
        # мораль → бегство прочь от врагов
        if tactician.morale_check(self.world, self.dice, cs, cur) == "flee":
            cs.combatants[cur].disengaging = True
            self._flee(cur)
            cs.combatants[cur].fled = True
            self.advance_turn()
            return self._ok(f"{self._name(cur)} в ужасе бежит с поля боя!", fled=True)
        target = self._choose_target(cur)
        # опц. модель-тактик (роль tactician) уточняет намерение/цель; иначе эвристика
        if self.model is not None:
            mtac = self._model_tactic(cur)
            if mtac and mtac.get("intent") == "retreat":
                cs.combatants[cur].disengaging = True
                self._flee(cur)
                cs.combatants[cur].fled = True
                self.advance_turn()
                return self._ok(f"{self._name(cur)} тактически отступает!", fled=True)
            if mtac:
                mt = mtac.get("target")
                if (mt in cs.combatants and self.world.is_alive(mt)
                        and cs.combatants[mt].side != cs.combatants[cur].side):
                    target = mt
        if not target:
            self.advance_turn()
            return self._ok(f"{self._name(cur)} выжидает.")
        spell_key = self._monster_spell(cur)
        if spell_key and cs.grid.has_los(cs.combatants[cur].pos, cs.combatants[target].pos):
            line = self.cast(cur, spell_key, target=target)["outcome"]
        else:
            if not self.in_attack_range(cur, target):
                self._move_toward(cur, target)
            if self.in_attack_range(cur, target) and cs.turn_budget.action:
                cs.turn_budget.action = False
                line = self._perform_attack(cur, target)
            else:
                line = f"{self._name(cur)} занимает позицию."
        self.advance_turn()
        return self._ok(line)

    def _model_tactic(self, eid: str) -> dict | None:
        from ..inference import agents
        return agents.choose_tactic(self.model, self._tactic_digest(eid), eid)

    def _tactic_digest(self, eid: str) -> str:
        cs = self.state
        me = cs.combatants[eid]
        foes = self.alive_allies() if me.side == "enemy" else self.alive_enemies()
        st = self.world.get_stats(eid)
        fd = ", ".join(f"{f}@{cs.combatants[f].pos}" for f in foes)
        return (f"actor={eid}@{me.pos} side={me.side} hp={st.hp if st else '?'}; "
                f"enemies=[{fd}]; movement={cs.turn_budget.movement}, "
                f"action={cs.turn_budget.action}")

    def _move_toward(self, mover: str, target: str) -> None:
        cs = self.state
        tp = cs.combatants[target].pos
        reach = cs.grid.reachable(cs.combatants[mover].pos, cs.turn_budget.movement, cs.occupied(mover))
        if not reach:
            return
        best = min(reach, key=lambda cell: cs.grid.distance_squares(cell, tp))
        if self._walk_path(mover, [best]):
            return
        cs.turn_budget.movement -= reach[best]

    def _flee(self, mover: str) -> None:
        cs = self.state
        foes = [cs.combatants[e].pos for e in self.alive_allies()]
        reach = cs.grid.reachable(cs.combatants[mover].pos,
                                  cs.turn_budget.movement + self._speed(mover), cs.occupied(mover))
        if reach and foes:
            cs.combatants[mover].pos = max(
                reach, key=lambda cell: min(cs.grid.distance_squares(cell, f) for f in foes))

    # ==================================================== AoO =============
    def _provoke_aoo(self, mover: str, from_cell: tuple, to_cell: tuple) -> None:
        cs = self.state
        if cs.combatants[mover].disengaging:
            return
        for fid, foe in cs.combatants.items():
            if (foe.side == cs.combatants[mover].side or foe.fled or foe.reactions_used
                    or not self.world.is_alive(fid)):
                continue
            if cs.grid.adjacent(foe.pos, from_cell) and not cs.grid.adjacent(foe.pos, to_cell):
                foe.reactions_used += 1                   # AoO тратит реакцию, не action
                cs.log.append("AoO: " + self._perform_attack(fid, mover))
                if not self.world.is_alive(mover):
                    return

    # ==================================================== урон/смерть =====
    def _apply_damage(self, attacker: str, target: str, amount: int, roll=None) -> None:
        self.world.commit("damage", attacker, target=target, payload={"amount": amount}, roll=roll)
        c = self.state.combatants.get(target)
        if c and c.concentration and not self._save(target, "con", max(10, amount // 2)):
            c.concentration = None
        if not self.world.is_alive(target):
            self._on_zero_hp(target)
        if self.cognition and ids.is_npc(target):
            self.cognition.observe_and_appraise(target, attacker, "attack", "hostile",
                                                f"{self._name(attacker)} ударил меня в бою")

    def _on_zero_hp(self, eid: str) -> None:
        if ids.is_pc(eid):
            self.world.conditions.setdefault(eid, []).append(Condition("unconscious", "until_stable"))
            self.state.log.append(f"{self._name(eid)} падает без сознания!")
        else:
            self.state.log.append(f"{self._name(eid)} повержен.")
            self._spawn_corpse(eid)
            self._award_xp(eid)
            self._faction_fallout(eid)

    def _award_xp(self, eid: str) -> None:
        """Опыт за побеждённого врага — игроку (вся партия делит по упрощению)."""
        from ..rules.progression import MONSTER_XP
        from ..world.components import Persona
        pc = self.world.player_id
        if not pc:
            return
        p = self.world.ecs.get(eid, Persona)
        xp = MONSTER_XP.get(p.stat_block_ref if p else None, 25)
        self.world.commit("gain_xp", pc, target=eid, payload={"xp": xp})

    def _faction_fallout(self, eid: str) -> None:
        """Убийство члена фракции роняет репутацию с ней и поднимает у её врагов."""
        from ..world.components import Faction, Persona
        pc = self.world.player_id
        persona = self.world.ecs.get(eid, Persona)
        fid = persona.faction if persona else None
        if not pc or not fid:
            return
        self.world.commit("faction_rep", pc, payload={"faction": fid, "delta": -0.1})
        fac = self.world.ecs.get(fid, Faction)
        for ofid, val in (fac.relations.items() if fac else []):
            if val < 0:                                   # враги убитой фракции — одобряют
                self.world.commit("faction_rep", pc, payload={"faction": ofid, "delta": 0.05})

    def _spawn_corpse(self, eid: str) -> None:
        from ..gen.item_gen import generate_individual_treasure
        from ..inventory.container import Container
        cid = f"corpse:{ids.name_of(eid)}"
        if cid in self.world.containers:
            return
        items = [iid for iid, inst in self.world.items.items() if inst.owner_ref == eid]
        self.world.containers[cid] = Container(container_id=cid, owner_ref=None,
                                               kind="corpse", items=list(items))
        for iid in items:
            inst = self.world.items[iid]
            inst.owner_ref, inst.location_ref, inst.equipped_slot = None, cid, None
        if not items:
            persona = self.world.ecs.get(eid, Persona)
            sb = get_stat_block(persona.stat_block_ref) if persona else None
            generate_individual_treasure(self.world, sb.cr if sb else 0.0,
                                         self._party_level(), self.world.seed, cid)

    # ==================================================== ход/раунд =======
    def advance_turn(self) -> None:
        cs = self.state
        self.pending = None
        for _ in range(len(cs.initiative_order)):
            cs.turn_index += 1
            if cs.turn_index >= len(cs.initiative_order):
                cs.turn_index = 0
                cs.round += 1
                self._tick_durations()
                surfaces.tick(cs)
            cb = cs.combatants.get(cs.current())
            if cb and not cb.fled and self.world.is_alive(cs.current()):
                break
        cur = cs.current()
        cb = cs.combatants.get(cur)
        if cb:
            cb.reactions_used = 0                         # реакция обновляется в начале хода
            cb.dodging = cb.disengaging = False
        cs.turn_budget = TurnBudget.fresh(self._speed(cur))
        if self.check_end():
            return
        if cb and not ids.is_pc(cur):
            return
        surfaces.on_turn_start(self, cur)

    def end_turn(self) -> dict:
        self.advance_turn()
        return self._ok("Ход завершён.")

    def _tick_durations(self) -> None:
        for conds in self.world.conditions.values():
            for cond in list(conds):
                if cond.duration_kind == "rounds":
                    cond.rounds_left -= 1
                    if cond.rounds_left <= 0:
                        conds.remove(cond)

    def check_end(self) -> bool:
        cs = self.state
        if not self.alive_enemies():
            cs.mode, cs.outcome = "ended", "victory"
            cs.log.append("Победа!")
            return True
        if not self.alive_allies():
            cs.mode = "ended"
            party_fled = any(c.fled for c in cs.combatants.values() if c.side == "party")
            cs.outcome = "flee" if party_fled else "tpk"
            cs.log.append("Поражение партии.")
            return True
        return False

    # ==================================================== helpers =========
    def _can_act(self, eid: str) -> bool:
        c = self.state.combatants.get(eid)
        return bool(c and not c.fled and self.world.is_alive(eid)
                    and not is_incapacitated(self.world.conditions.get(eid, [])))

    def _has_condition(self, eid: str, name: str) -> bool:
        return any(c.name == name for c in self.world.conditions.get(eid, []))

    def _name(self, eid: str) -> str:
        p = self.world.ecs.get(eid, Persona)
        return (p.epithet or p.name) if p else ids.name_of(eid)

    def _speed(self, eid: str | None) -> int:
        st = self.world.ecs.get(eid, Stats5e) if eid else None
        return st.speed if st else 30

    def _save(self, eid: str, ability: str, dc: int) -> bool:
        res = self.dice.roll_seeded("save", "1d20", roller=eid,
                                    modifier=save_modifier(self.world, eid, ability), dc=dc)
        return res.total >= dc

    def _set_condition(self, eid: str, name: str) -> None:
        conds = self.world.conditions.setdefault(eid, [])
        if not any(c.name == name for c in conds):
            conds.append(Condition(name, "rounds", rounds_left=1))

    def _is_ranged(self, eid: str) -> bool:
        w = WEAPONS.get(equipped_weapon_key(self.world, eid))
        return bool(w and "ranged" in w.properties)

    def _enemy_adjacent(self, eid: str) -> bool:
        cs = self.state
        p = cs.combatants[eid].pos
        foes = self.alive_allies() if cs.combatants[eid].side == "enemy" else self.alive_enemies()
        return any(cs.grid.adjacent(p, cs.combatants[f].pos) for f in foes)

    def _choose_target(self, eid: str) -> str | None:
        cs = self.state
        foes = self.alive_allies() if cs.combatants[eid].side == "enemy" else self.alive_enemies()
        if not foes:
            return None
        p = cs.combatants[eid].pos
        return min(foes, key=lambda f: (cs.grid.distance_squares(p, cs.combatants[f].pos),
                                        self.world.get_stats(f).hp if self.world.get_stats(f) else 0))

    def _monster_spell(self, eid: str) -> str | None:
        st = self.world.ecs.get(eid, Stats5e)
        if st and st.spell_slots and sum(st.spell_slots.values()) > 0:
            return "magic_missile"
        return None

    def _free_cell(self, used: set) -> tuple:
        g = self.state.grid
        for y in range(g.rows):
            for x in range(g.cols):
                if g.is_passable(x, y) and (x, y) not in used:
                    return (x, y)
        return (0, 0)

    def _party_level(self) -> int:
        st = self.world.ecs.get(self.world.player_id, Stats5e) if self.world.player_id else None
        return st.level if st else 1
