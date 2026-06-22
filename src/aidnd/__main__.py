"""CLI-точка входа: текстовая игра в терминале.

Запуск:  python -m aidnd            (играть)
         python -m aidnd serve      (веб-сервер, L9)
         python -m aidnd doctor      (проверка окружения и сервера модели)
         python -m aidnd debug       (консольный авто-прогон квеста; требует онлайн-модель)
         python -m aidnd debug --offline  (то же на детерминированных фоллбэках)
"""

from __future__ import annotations

import sys

from . import config
from .bootstrap import new_session
from .rules.dice import roll_expr


def _auto_roll(rr: dict, salt: int) -> list[int]:
    """server-animated: сервер кидает, клиент «анимирует» к результату (док 07 §8).

    Сид стабилен между процессами (blake2b, не builtin hash) — воспроизводимо."""
    from .gen.seeds import subseed
    seed = subseed(0, rr["request_id"], salt) & 0x7FFFFFFF
    return roll_expr(rr["request_id"], rr["dice"], seed, source="server_ui").raw


def _resolve_rolls(session, result: dict, salt: int) -> dict:
    """Докручивает приостановленные броски авто-режимом."""
    while result.get("kind") == "roll_request":
        rr = result["roll_request"]
        faces = _auto_roll(rr, salt)
        dc = f" против DC {rr['dc']}" if rr.get("dc") is not None else ""
        print(f"  🎲 {rr['dice']} (мод {rr['modifier']:+d}){dc} → выпало {faces}")
        salt += 1
        result = session.submit_roll(faces)
    return result


def _print_result(r: dict) -> None:
    if r.get("text"):
        print("\n" + r["text"])
    if r.get("hint"):
        print(f"  ({r['hint']})")
    cv = r.get("combat")
    if cv:
        _print_combat(cv)


def _print_combat(cv: dict) -> None:
    print("\n  ⚔️  Раунд", cv["round"])
    for c in cv["combatants"]:
        mark = "→" if c["current"] else " "
        dead = " ✝" if c["hp"] <= 0 else (" 🏃" if c["fled"] else "")
        print(f"   {mark} {c['name']:<22} HP {c['hp']:>3}/{c['max_hp']:<3} AC {c['ac']}{dead}")


def _combat_loop(session, salt: int) -> int:
    """Интерактивный бой в терминале."""
    while session.combat and session.combat.state.mode == "active":
        session.combat_view()
        if session.combat.is_pc_turn():
            enemies = session.combat.alive_enemies()
            print("\n  Враги:", ", ".join(f"[{i+1}] {session._display(e)}"
                                          for i, e in enumerate(enemies)))
            choice = input("  Бой> цель (1..n) или 'all': ").strip()
            idx = 0
            if choice.isdigit():
                idx = max(0, min(len(enemies) - 1, int(choice) - 1))
            out = session.combat_attack(enemies[idx])
            out = _resolve_rolls(session, out, salt)
            salt += 3
            _print_result(out)
        else:
            break
    return salt


def play() -> None:
    print("=" * 64)
    print(" AI-DnD Engine — вертикальный срез LMoP (Phandalin + Cragmaw)")
    print(" Команды: свободный текст. Спец: /look /inv /quests /stats /help /quit")
    print("=" * 64)
    session = new_session(seed=config.WORLD_SEED, roster_size=12, use_model=True)
    online = bool(session.model and session.model.available())
    print(f"\n[сервер модели: {'ONLINE' if online else 'OFFLINE — детерминированные фоллбэки'}]")
    _print_result(session.look())
    salt = 1
    while True:
        try:
            raw = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nДо встречи в Фэндалине.")
            return
        if not raw:
            continue
        if raw in ("/quit", "/exit", "выход"):
            print("До встречи в Фэндалине.")
            return
        if raw == "/look":
            _print_result(session.look()); continue
        if raw == "/inv":
            _print_result(session.handle("инвентарь")); continue
        if raw in ("/stats",):
            v = session.view()["player"]
            print(f"\n{v['name']}: HP {v['hp']}/{v['max_hp']} AC {v['ac']} ур.{v['level']}")
            continue
        if raw == "/quests":
            for q in session.view()["quests"]:
                print(f"  • [{q['state']}] {q['title']}")
            continue
        if raw in ("/map", "/where", "/локации"):
            print("\n" + session.map_text())
            continue
        if raw in ("/journal", "/j", "/журнал", "/log"):
            print("\n" + session.journal_text())
            continue
        if raw == "/help":
            print("  свободный текст: иди в.., поговорить с.., осмотреть, обыскать,\n"
                  "  убедить.., атаковать.., купить, инвентарь, ждать\n"
                  "  в диалоге просто пиши реплику/вопрос собеседнику\n"
                  "  спец: /journal (журнал) /map (связность) /inv /quests /stats /look /quit")
            continue
        result = session.handle(raw)
        result = _resolve_rolls(session, result, salt)
        salt += 5
        _print_result(result)
        if result.get("kind") == "combat_start" or (session.combat and session.combat.state.mode == "active"):
            salt = _combat_loop(session, salt)


def doctor() -> None:
    from .inference import ModelManager
    print("AI-DnD doctor")
    print("  OLLAMA_HOST :", config.OLLAMA_HOST)
    print("  BASE_MODEL  :", config.BASE_MODEL, "(нарратив, когниция, бой…)")
    print("  INTENT_MODEL:", config.INTENT_MODEL, "(лёгкий классификатор интента)")
    m = ModelManager()
    ok = m.available()
    print("  сервер доступен:", ok)
    if ok:
        models = m.client.list_models()
        print("  модели на сервере:", models)
        for label, name in (("base", config.BASE_MODEL), ("intent", config.INTENT_MODEL)):
            present = any(name.split(":")[0] in mm for mm in models) or name in models
            print(f"   - {label} «{name}»:", "OK" if present else "НЕ НАЙДЕНА → ollama pull " + name)
    else:
        print("  (нет туннеля — движок работает на детерминированных фоллбэках)")


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "play"
    if cmd == "serve":
        from .server.app import run
        run()
    elif cmd == "doctor":
        doctor()
    elif cmd == "debug":
        from .runtime.debug_play import run as run_debug
        offline = "--offline" in sys.argv[2:]
        sys.exit(run_debug(offline=offline))
    else:
        play()


if __name__ == "__main__":
    main()
