#!/usr/bin/env python3
"""Følger fokusplanen i blokker på 50 blitzpartier og skriver focus/PROGRESS.md + focus/progress.json.

focus/plan.json:
  {"start": "YYYY-MM-DD", "block_size": 50,
   "queue": [{"id": "<kategori fra focus.py>", "name": ..., "baseline_blunders_per50": x,
              "baseline_sd": y, "baseline_points_per50": z, "lichess_theme": ...}, ...]}

Blokk i = partiene 50*i+1 .. 50*(i+1) spilt (blitz 3+0, rated) etter startdatoen.
Etter siste fokus i køen starter man på nytt fra første (repetisjon).
Krever at engine.py og moments.py har kjørt for de nye partiene.
"""
import json
import pathlib
import sys
from collections import defaultdict
from datetime import datetime

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from common import OUT, ROOT, load_games  # noqa: E402
from focus import CATS, TC  # noqa: E402

FOCUS_DIR = ROOT / "focus"


def sg(v):
    return "–" if v is None else f"{v:+}"


def main():
    plan = json.loads((FOCUS_DIR / "plan.json").read_text(encoding="utf-8"))
    size = plan.get("block_size", 50)
    start = datetime.strptime(plan["start"], "%Y-%m-%d %H:%M" if " " in plan["start"] else "%Y-%m-%d")
    games = [g for g in load_games() if g["tc"] == TC and g["rated"] and g["local"] >= start]

    moms = {}
    p = OUT / "moments_full.json"
    if p.exists():
        for m in json.loads(p.read_text(encoding="utf-8")):
            if "tags" in m:
                moms.setdefault(m["id"], []).append(m)
    ev_ids = set()
    if (OUT / "evals.ndjson").exists():
        for line in open(OUT / "evals.ndjson", encoding="utf-8"):
            r = json.loads(line)
            if "cp" in r:
                ev_ids.add(r["id"])

    preds = {c[0]: c[3] for c in CATS}
    blocks = []
    for bi in range(0, max(1, (len(games) + size - 1) // size)):
        chunk = games[bi * size:(bi + 1) * size]
        focus = plan["queue"][bi % len(plan["queue"])]
        analysed = [g for g in chunk if g["id"] in ev_ids]
        hits, pts, all_bl = 0, 0.0, 0
        for g in analysed:
            ms = sorted(moms.get(g["id"], []), key=lambda m: m["ply"])
            by_ply = {m["ply"]: m for m in ms}
            for m in ms:
                if m["who"] != "me":
                    continue
                all_bl += 1
                prev = by_ply.get(m["ply"] - 1) if m["after_opp_blunder"] else None
                if preds[focus["id"]](m, prev):
                    hits += 1
                    pts += m["drop"] / 100
        n = len(analysed)
        score = sum(g["score"] for g in chunk)
        exp = sum(g["exp"] for g in chunk)
        per50 = hits / n * size if n else None
        base, sd = focus["baseline_blunders_per50"], focus["baseline_sd"]
        if per50 is None or n < 10:
            verdict = "for få partier ennå"
        elif per50 <= base - 1.5 * sd:
            verdict = "klar forbedring"
        elif per50 <= base - 0.5 * sd:
            verdict = "trolig bedre"
        elif per50 >= base + 1.0 * sd:
            verdict = "dårligere enn vanlig"
        else:
            verdict = "innenfor normal variasjon"
        blocks.append({
            "block": bi + 1, "focus": focus["id"], "focus_name": focus["name"],
            "games": len(chunk), "analysed": n, "complete": len(chunk) == size,
            "from": chunk[0]["local"].strftime("%Y-%m-%d") if chunk else None,
            "to": chunk[-1]["local"].strftime("%Y-%m-%d") if chunk else None,
            "focus_blunders": hits, "focus_blunders_per50": None if per50 is None else round(per50, 1),
            "baseline_per50": base, "baseline_sd": sd,
            "points_lost_per50": round(pts / n * size, 2) if n else None,
            "all_blunders_per_game": round(all_bl / n, 2) if n else None,
            "score_pct": round(100 * score / len(chunk), 1) if chunk else None,
            "vs_expected": round(100 * (score - exp) / len(chunk), 1) if chunk else None,
            "rating_end": (chunk[-1]["my_rating"] + chunk[-1]["rating_diff"]) if chunk else None,
            "verdict": verdict,
        })

    FOCUS_DIR.mkdir(exist_ok=True)
    (FOCUS_DIR / "progress.json").write_text(json.dumps({"plan": plan, "blocks": blocks}, indent=1, ensure_ascii=False),
                                             encoding="utf-8")
    cur = blocks[-1]
    lines = [
        "# Fokusplan – fremdrift",
        "",
        f"Oppdatert {datetime.now():%Y-%m-%d %H:%M}. Blitz 3+0, rated, fra {plan['start']}. "
        f"Hver blokk = {size} partier med ett fokus.",
        "",
        f"## Nå: {cur['focus_name']} (blokk {cur['block']})",
        "",
        f"- Partier i blokken: **{cur['games']} / {size}** (motoranalysert: {cur['analysed']})",
        f"- Bukker i fokuskategorien: **{cur['focus_blunders_per50']}** per 50 partier "
        f"(utgangspunkt {cur['baseline_per50']} ± {cur['baseline_sd']})",
        f"- Vurdering: **{cur['verdict']}**",
        f"- Score {cur['score_pct']} % ({sg(cur['vs_expected'])} mot forventet), rating {cur['rating_end']}",
        "",
        "## Alle blokker",
        "",
        "| Blokk | Fokus | Partier | Fokusbukker/50 | Utgangspunkt | Vurdering | Score | Mot forventet | Rating |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for b in blocks:
        lines.append(f"| {b['block']} | {b['focus_name']} | {b['games']} | {b['focus_blunders_per50']} | "
                     f"{b['baseline_per50']} ± {b['baseline_sd']} | {b['verdict']} | {b['score_pct']} % | "
                     f"{sg(b['vs_expected'])} | {b['rating_end']} |")
    lines += ["", "Vurdering: «klar forbedring» = under utgangspunkt − 1,5 standardavvik for 50-partiersblokker; "
                  "«trolig bedre» = under − 0,5 sd. Tilfeldig variasjon mellom blokker er stor, så se på flere blokker."]
    (FOCUS_DIR / "PROGRESS.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
