"""Раннер eval-сцен. python -m aidnd.eval [--json] [--offline] [scene_name]"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict

from ..inference import ModelManager
from .scenes import run_all, run_scene


def _print_transcript(t) -> None:
    print("\n" + "=" * 70)
    print(f"СЦЕНА: {t.scene} — {t.description}")
    print("=" * 70)
    for s in t.steps:
        tag = "🤖 МОДЕЛЬ" if s.source == "model" else (
            "⚙️  ДЕТЕРМ." if s.source == "deterministic" else "↩️  ФОЛЛБЭК")
        print(f"\n  [{s.role}] ({tag})")
        print(f"   контекст: {s.context}")
        out = s.output
        if isinstance(out, dict):
            for k, v in out.items():
                print(f"   {k}: {v}")
        else:
            print(f"   вывод: {out}")
    if t.mechanics:
        print(f"\n  механика: {t.mechanics}")
    print("\n  АВТОПРОВЕРКИ (объективная часть рубрики):")
    for c in t.checks:
        print("   " + str(c))
    if t.judge_questions:
        print("\n  ВОПРОСЫ СУДЬЕ (субъективная believability):")
        for q in t.judge_questions:
            print(f"   • {q}")


def main() -> None:
    args = sys.argv[1:]
    as_json = "--json" in args
    use_model = "--offline" not in args
    names = [a for a in args if not a.startswith("--")]

    online = ModelManager().available() if use_model else False
    if not as_json:
        mode = "ONLINE (выходы модели)" if online else "OFFLINE (детерминированные фоллбэки)"
        print(f"AI-DnD eval — режим: {mode}")

    if names == ["conversations"]:
        from .conversations import run_all as run_convs
        transcripts = run_convs(use_model=use_model)
    elif names:
        transcripts = [run_scene(n, use_model=use_model) for n in names]
    else:
        transcripts = run_all(use_model=use_model)

    if as_json:
        print(json.dumps([_t_to_dict(t) for t in transcripts], ensure_ascii=False,
                         indent=2, default=str))
        return

    total = passed = 0
    for t in transcripts:
        _print_transcript(t)
        total += len(t.checks)
        passed += sum(1 for c in t.checks if c.passed)
    print("\n" + "=" * 70)
    print(f"ИТОГ автопроверок: {passed}/{total} PASS по {len(transcripts)} сценам.")
    print("Субъективная believability — на усмотрение судьи поверх транскрипта.")


def _t_to_dict(t) -> dict:
    return {"scene": t.scene, "description": t.description,
            "steps": [asdict(s) for s in t.steps],
            "checks": [asdict(c) for c in t.checks],
            "mechanics": t.mechanics, "judge_questions": t.judge_questions,
            "auto_passed": t.auto_passed}


if __name__ == "__main__":
    main()
