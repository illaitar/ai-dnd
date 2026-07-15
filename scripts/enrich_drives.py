"""Pass B of NPC entity enrichment — LLM batch: distills persona wants/fears/secret into
structured `mech.drives` (docs/superpowers/specs/2026-07-15-npc-entity-enrichment-design.md
§3.6, §4.1). Mirrors peoplegen.py: character_writer role, ThreadPoolExecutor concurrency,
--resume. Adults only (dependents carry no agenda, skipped by eligible_rows).

No offline fallback: unparseable output / no model → that row is SKIPPED (logged), never a stub
drive. Re-run with --resume to pick up skipped/unprocessed rows.

Run:  .venv/bin/python scripts/enrich_drives.py [--db data/worlds.db] [--limit N] [--resume]
                                                 [--concurrency 8] [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))


def _setenv() -> None:
    """Подтянуть ключи из .secrets в окружение ДО импорта aidnd.config (он читает env на импорте)."""
    def load(fname, var):
        if os.environ.get(var):
            return
        p = os.path.join(ROOT, ".secrets", fname)
        if os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                os.environ[var] = f.read().strip()
    load("deepseek.key", "DEEPSEEK_API_KEY")
    if os.environ.get("DEEPSEEK_API_KEY"):
        os.environ.setdefault("AIDND_PROFILE", "deepseek")


_setenv()

from aidnd.inference import LLMBadOutput, LLMUnavailable, ModelManager  # noqa: E402
from aidnd.worldgen import WorldStore  # noqa: E402
from aidnd.worldgen.enrich_drives import (  # noqa: E402
    LLMDrives,
    build_ctx,
    eligible_rows,
    write_drives,
)


def main() -> None:
    ap = argparse.ArgumentParser(description="Pass B — LLM-batch NPC drives (mech.drives).")
    ap.add_argument("--db", default=os.path.join(ROOT, "data", "worlds.db"),
                    help="path to worlds.db (default: data/worlds.db)")
    ap.add_argument("--limit", type=int, default=None,
                    help="process at most N eligible rows (test slice)")
    ap.add_argument("--resume", action="store_true",
                    help="skip rows that already carry mech.drives")
    ap.add_argument("--concurrency", type=int, default=8)
    ap.add_argument("--dry-run", action="store_true",
                    help="call the LLM for 3 rows, print parsed drives, write nothing")
    args = ap.parse_args()

    store = WorldStore(args.db)
    mgr = ModelManager()
    if not mgr.available():          # bank NPCs are prod data — no offline fallback
        sys.exit("LLM недоступен (профиль/ключ) — драйвы без модели не генерим")
    enr = LLMDrives(mgr)

    rows = eligible_rows(store, resume=args.resume)
    if args.dry_run:
        rows = rows[:3]
    elif args.limit is not None:
        rows = rows[:args.limit]
    print(f"LLM: {os.environ.get('AIDND_PROFILE', 'local')} · к обработке: {len(rows)} строк "
          f"(адулты, resume={args.resume}) · банк сейчас: {store.people_count()}")

    def work(row):
        return row, enr.derive(build_ctx(row))

    n = 0
    failed = 0
    with ThreadPoolExecutor(max_workers=max(1, args.concurrency)) as ex:
        futs = {ex.submit(work, row): row for row in rows}
        for fut in as_completed(futs):
            row = futs[fut]
            try:
                row, drives = fut.result()
            except (LLMBadOutput, LLMUnavailable) as exc:
                failed += 1
                print(f"  [skip] {row['id']} {row['name']}: {exc}")
                continue
            if args.dry_run:
                print(f"\n=== {row['id']} ({row['role']}) {row['name']} ===")
                print(json.dumps(drives, ensure_ascii=False, indent=2))
            else:
                write_drives(store, row, drives)
            n += 1
            print(f"  [{n}/{len(rows)}] {row['id']} {row['name']:22} drives:{len(drives)}")

    if args.dry_run:
        print(f"\n[dry-run] разобрано {n} из {len(rows)} (ничего не записано)")
    else:
        print(f"\nготово: записано {n}, пропущено (bad output) {failed} из {len(rows)}")


if __name__ == "__main__":
    main()
