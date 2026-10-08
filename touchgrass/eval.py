"""
NLU evaluation harness – workstream A.

Usage:  python -m touchgrass eval

Runs the 40 labelled fixture messages against one or more Gemma sizes,
prints accuracy + latency as a markdown table, and writes eval/results.md.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any

from touchgrass import config
from touchgrass.nlu import parse_availability, AvailabilityParse

logger = logging.getLogger(__name__)

FIXTURES_PATH = Path(__file__).parent.parent / "eval" / "fixtures.json"
RESULTS_PATH = Path(__file__).parent.parent / "eval" / "results.md"


def _check(parse: AvailabilityParse, expected: dict[str, Any]) -> dict[str, bool]:
    """Return per-field correctness."""
    results = {}

    # can_play
    results["can_play"] = parse.can_play == expected["can_play"]

    # language
    results["language"] = parse.language == expected.get("language", "en")

    # slots – at least one expected slot matched
    exp_slots = expected.get("slots", [])
    if not exp_slots:
        results["slots"] = len(parse.slots) == 0
    else:
        matched = False
        for es in exp_slots:
            for ps in parse.slots:
                wd_ok = es.get("weekday") is None or (
                    ps.weekday and ps.weekday == es["weekday"].lower()
                )
                if wd_ok:
                    matched = True
                    break
            if matched:
                break
        results["slots"] = matched

    # conditions (relaxed – just check intersection)
    exp_conds = set(expected.get("conditions", []))
    got_conds = set(parse.conditions)
    results["conditions"] = (not exp_conds) or bool(exp_conds & got_conds)

    return results


async def _eval_model(model: str, fixtures: list[dict]) -> dict[str, Any]:
    correct_total = 0
    field_totals: dict[str, int] = {"can_play": 0, "language": 0, "slots": 0, "conditions": 0}
    latencies: list[float] = []
    errors = 0

    for fix in fixtures:
        t0 = time.perf_counter()
        try:
            parse = await parse_availability(fix["message"], model=model)
            elapsed = time.perf_counter() - t0
            latencies.append(elapsed)
            checks = _check(parse, fix["expected"])
            if all(checks.values()):
                correct_total += 1
            for k, v in checks.items():
                if v:
                    field_totals[k] += 1
        except Exception as exc:
            elapsed = time.perf_counter() - t0
            latencies.append(elapsed)
            errors += 1
            logger.warning("Model %s failed on fixture %d: %s", model, fix["id"], exc)

    n = len(fixtures)
    avg_lat = sum(latencies) / len(latencies) if latencies else 0
    p95_lat = sorted(latencies)[int(0.95 * len(latencies)) - 1] if latencies else 0

    return {
        "model": model,
        "accuracy": correct_total / n,
        "can_play_acc": field_totals["can_play"] / n,
        "lang_acc": field_totals["language"] / n,
        "slots_acc": field_totals["slots"] / n,
        "conds_acc": field_totals["conditions"] / n,
        "avg_lat_s": avg_lat,
        "p95_lat_s": p95_lat,
        "errors": errors,
        "n": n,
    }


def _render_table(rows: list[dict[str, Any]]) -> str:
    header = (
        "| Model | Overall | can_play | language | slots | conditions | avg_lat | p95_lat | errors |"
    )
    sep = "|---|---|---|---|---|---|---|---|---|"
    lines = [header, sep]
    for r in rows:
        lines.append(
            f"| `{r['model']}` "
            f"| {r['accuracy']:.0%} "
            f"| {r['can_play_acc']:.0%} "
            f"| {r['lang_acc']:.0%} "
            f"| {r['slots_acc']:.0%} "
            f"| {r['conds_acc']:.0%} "
            f"| {r['avg_lat_s']:.1f}s "
            f"| {r['p95_lat_s']:.1f}s "
            f"| {r['errors']} |"
        )
    return "\n".join(lines)


async def run_eval(models: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO)

    if not FIXTURES_PATH.exists():
        print(f"Fixtures not found at {FIXTURES_PATH}")
        return

    with FIXTURES_PATH.open() as f:
        fixtures = json.load(f)

    print(f"Loaded {len(fixtures)} fixtures.")

    if models is None:
        # Try a few sizes; skip if not available
        candidates = [
            config.OLLAMA_MODEL,
            "gemma3:1b",
            "gemma3:4b",
        ]
        # Deduplicate while preserving order
        seen: set[str] = set()
        models = []
        for m in candidates:
            if m not in seen:
                models.append(m)
                seen.add(m)

    results = []
    for model in models:
        print(f"\n▶ Evaluating {model} on {len(fixtures)} fixtures…")
        try:
            row = await _eval_model(model, fixtures)
            results.append(row)
            print(f"  → Overall accuracy: {row['accuracy']:.0%}, avg latency: {row['avg_lat_s']:.1f}s")
        except Exception as exc:
            print(f"  → Skipped ({exc})")

    if not results:
        print("No models evaluated.")
        return

    table = _render_table(results)
    print("\n## NLU Eval Results\n")
    print(table)

    RESULTS_PATH.parent.mkdir(exist_ok=True)
    RESULTS_PATH.write_text(f"# NLU Evaluation Results\n\n{table}\n\n_Generated by `python -m touchgrass eval`_\n")
    print(f"\nResults saved to {RESULTS_PATH}")
