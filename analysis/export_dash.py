#!/usr/bin/env python3
"""Samler stats.json + weaknesses.json + blunders til én JSON-fil for rapportsiden.

Kun blitz 3+0 (hovedtidskontrollen din). Output: analysis/out/dash.json
  {"tables": {navn: [rader]}, "meta": [...]}
Kjøres etter stats.py og weaknesses.py.
"""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from common import OUT  # noqa: E402

TC = "180+0"
PHASE = {"1": "Opening (moves 1-12)", "2": "Middlegame", "3": "Endgame"}
CLOCK = {"a": "Under 5 s", "b": "5-10 s", "c": "10-27 s", "d": "27-63 s", "e": "63-117 s", "f": "Over 117 s"}
SPENT = {"a": "Under 1 s", "b": "1-2 s", "c": "2-4 s", "d": "4-8 s", "e": "8 s or more"}
EVAL = {"a": "Lost (<15%)", "b": "Worse (15-35%)", "c": "Equal (35-65%)", "d": "Better (65-85%)", "e": "Winning (>85%)"}
LENGTH = {"a": "20 moves or fewer", "b": "21-40 moves", "c": "41-60 moves", "d": "Over 60 moves"}
GAP = {"a": "150+ stronger", "b": "50-150 stronger", "c": "Within 50", "d": "50-150 weaker", "e": "150+ weaker"}
CLOCKDIFF = {"a": "20%+ less time", "b": "5-20% less", "c": "About equal", "d": "5-20% more", "e": "20%+ more time"}
BTYPE = {
    "posisjonell/stille trekk": "Quiet move that spoiled the position",
    "overså gevinst av materiell": "Missed a winning capture",
    "hengte offiser/dronning": "Hung a piece or the queen",
    "hengte bonde/byttet feil": "Hung a pawn or traded badly",
    "overså sjakk/taktikk med sjakk": "Missed a tactic with check",
    "overså motstanderens sjakk/kongeangrep": "Missed the opponent's check or king attack",
}
THEME = {
    "hangingPiece": "Hanging piece", "fork": "Fork", "pin": "Pin", "skewer": "Skewer",
    "discoveredAttack": "Discovered attack", "doubleCheck": "Double check", "mateIn1": "Mate in 1",
    "mateIn2": "Mate in 2", "mateIn3": "Mate in 3", "mateIn4": "Mate in 4", "mateIn5": "Mate in 5+",
    "backRankMate": "Back-rank mate", "smotheredMate": "Smothered mate", "deflection": "Deflection",
    "attraction": "Attraction", "overloading": "Overloading", "sacrifice": "Sacrifice",
    "capturingDefender": "Capturing the defender", "interference": "Interference", "clearance": "Clearance",
    "advancedPawn": "Advanced pawn", "promotion": "Promotion", "trappedPiece": "Trapped piece",
    "kingsideAttack": "Kingside attack", "queensideAttack": "Queenside attack", "exposedKing": "Exposed king",
    "quietMove": "Quiet move", "defensiveMove": "Defensive move", "intermezzo": "Intermezzo",
    "xRayAttack": "X-ray attack", "zugzwang": "Zugzwang", "attackingF2F7": "Attack on f2/f7",
    "rookEndgame": "Rook endgame", "pawnEndgame": "Pawn endgame", "queenEndgame": "Queen endgame",
    "bishopEndgame": "Bishop endgame", "knightEndgame": "Knight endgame", "queenRookEndgame": "Queen and rook endgame",
    "castling": "Castling", "enPassant": "En passant", "collinearMove": "Collinear move", "coercion": "Coercion",
    "simplification": "Simplification", "underPromotion": "Underpromotion",
}


def mapped(d, names, fields):
    rows = []
    for k, v in d.items():
        if not v:
            continue
        key = k.split(":")[0].strip() if ":" in k else k[0]
        rows.append({"order": key, "bucket": names.get(key, k), **{f: v[f] for f in fields}})
    return sorted(rows, key=lambda r: r["order"])


def main():
    s = json.loads((OUT / "stats.json").read_text(encoding="utf-8"))[TC]
    w = json.loads((OUT / "weaknesses.json").read_text(encoding="utf-8")).get(TC, {})
    T = {}

    rating = s["rating"]
    T["summary"] = [{
        "games": s["overall"]["n"],
        "score": s["overall"]["score"],
        "rating_now": rating["current"],
        "rating_peak": rating["peak"],
        "peak_date": rating["peak_date"],
        "engine_games": w.get("games", 0),
        "my_blunders_per100": (w.get("me") or {}).get("blunder_per100"),
        "opp_blunders_per100": (w.get("opponents") or {}).get("blunder_per100"),
        "conversion_pct": (w.get("won_positions") or {}).get("conversion_pct"),
        "won_positions": (w.get("won_positions") or {}).get("won_positions"),
        "won_lost": (w.get("won_positions") or {}).get("lost"),
        "punish_pct": (w.get("punishing_opp_blunders") or {}).get("punish_pct"),
        "timeout_loss_pct": s["time"]["timeout_loss_pct_of_losses"],
    }]
    T["rating"] = [{"month": m, "rating": r} for m, r in rating["monthly_end"].items() if m >= "2020-01"]
    T["length"] = mapped(s["by_length"], LENGTH, ("n", "score", "vs_exp"))
    T["gap"] = [r for r in mapped(s["by_rating_gap"], GAP, ("n", "score", "vs_exp")) if r["n"] >= 100]
    T["clockdiff"] = mapped(s["time"]["by_clock_diff_move20"], CLOCKDIFF, ("n", "score", "vs_exp"))
    T["hours"] = [{"order": k, "bucket": k.replace("-", ":00-") + ":00", **{f: v[f] for f in ("n", "score", "vs_exp")}}
                  for k, v in s["by_hour"].items() if v["n"] >= 100]

    ev12 = {(o["color"], o["opening"]): o["avg_winpct_after_move12"]
            for o in w.get("openings_by_eval_move12_worst", []) + w.get("openings_by_eval_move12_best", [])}
    rows = []
    for col in ("white", "black"):
        for name, v in s["openings"][col]["variations"].items():
            if v["n"] >= 50:
                rows.append({"key": f"{col}|{name}", "color": col.capitalize(), "opening": name,
                             "n": v["n"], "score": v["score"], "vs_exp": v["vs_exp"],
                             "winpct_move12": ev12.get((col, name))})
    T["openings"] = sorted(rows, key=lambda r: r["vs_exp"])

    if w:
        me, op = w["by_phase"], w["by_phase_opponents"]
        T["phase"] = [{"order": k[0], "phase": PHASE[k[0]], "you": me[k]["blunder_per100"],
                       "opponents": op[k]["blunder_per100"], "moves": me[k]["moves"]} for k in sorted(me)]
        T["clock_left"] = mapped(w["by_clock_left"], CLOCK, ("moves", "blunder_per100", "mistake_per100"))
        T["spent"] = mapped(w["by_time_spent"], SPENT, ("moves", "blunder_per100", "mistake_per100"))
        T["eval_before"] = mapped(w["by_eval_before"], EVAL, ("moves", "blunder_per100", "mistake_per100"))
        tot = sum(w["blunder_types"].values()) or 1
        T["btypes"] = [{"type": BTYPE.get(k, k), "count": v, "share": round(100 * v / tot, 1)}
                       for k, v in w["blunder_types"].items()]
        T["endgame"] = [{"order": k[0], "bucket": EVAL[k[0]], "n": v["n"], "score": v["score"]}
                        for k, v in w["endgame_entry_score"].items()]
        ex = json.loads((OUT / "blunders_180_0.json").read_text(encoding="utf-8"))
        ex = [e for e in ex if e["drop"] >= 30 and e["wp_before"] >= 40]
        ex.sort(key=lambda e: (e["date"], e["ply"]), reverse=True)
        T["practice"] = [{
            "key": f"{e['id']}-{e['ply']}", "date": e["date"],
            "move_no": f"{e['ply'] // 2 + 1}{'.' if e['ply'] % 2 == 0 else '...'}",
            "played": e["move"], "best": e["best"], "type": BTYPE.get(e["type"], e["type"]),
            "winpct": f"{e['wp_before']}% → {e['wp_after']}%",
            "url": f"https://lichess.org/{e['id']}#{e['ply']}",
        } for e in ex[:25]]

    fp = OUT / "focus.json"
    if fp.exists():
        f = json.loads(fp.read_text(encoding="utf-8"))
        T["summary"][0].update({"focus_games": f["window"]["games"], "focus_from": f["window"]["from"],
                                "focus_to": f["window"]["to"]})
        T["focus_rank"] = [{
            **{k: r[k] for k in ("id", "name", "description", "points_lost_per50", "opp_points_lost_per50",
                                 "excess_per50", "blunders_per50", "avoidable_pct", "excess_earlier",
                                 "block_sd_blunders")},
            "rank": i + 1,
            "train_url": f"https://lichess.org/training/{r['lichess_theme']}" if r["lichess_theme"] else None,
        } for i, r in enumerate(f["rank"])]
        top = [r["id"] for r in f["rank"][:4]]
        names = {r["id"]: r["name"] for r in f["rank"]}
        T["focus_blocks"] = [{**b, "name": names[b["cat"]], "key": f"{b['cat']}-{b['block']}"}
                             for b in f["blocks"] if b["cat"] in top]
        T["themes"] = [{"theme": THEME.get(t["theme"], t["theme"]), **{k: t[k] for k in ("me", "opp", "excess")}}
                       for t in f["themes"] if t["me"] + t["opp"] >= 0.15][:16]
        T["focus_practice"] = [{**p, "name": names[p["cat"]]} for p in f["practice"]]

    pp = OUT.parent.parent / "focus" / "plan.json"
    if pp.exists():
        plan = json.loads(pp.read_text(encoding="utf-8"))
        size = plan.get("block_size", 50)
        T["plan"] = [{
            "block": i + 1, "games": f"Games {i * size + 1}-{(i + 1) * size}", "id": q["id"], "name": q["name"],
            "check": q["check"], "train_url": q["train_url"],
            "baseline": q["baseline_blunders_per50"], "sd": q["baseline_sd"],
            "target": round(q["baseline_blunders_per50"] - 1.5 * q["baseline_sd"], 1),
            "excess": q["baseline_excess_per50"], "start": plan["start"],
        } for i, q in enumerate(plan["queue"])]

    here = pathlib.Path(__file__).resolve()
    meta = [
        {"label": "export_dash.py", "value": here.read_text(encoding="utf-8"), "type": "code", "lang": "python"},
        {"label": "Input", "value": "analysis/out/stats.json (stats.py), analysis/out/weaknesses.json and "
                                    "blunders_180_0.json (weaknesses.py, Stockfish 19 at 50k nodes/position), "
                                    "focus.json (moments.py + focus.py: Stockfish 19 punishing lines at 400k nodes, "
                                    "lichess-puzzler tagger themes, Maia-1900 via Lc0 0.32)"},
        {"label": "Code", "value": "https://github.com/SveinungMidlaier/lichess-games/tree/main/analysis"},
    ]
    (OUT / "dash.json").write_text(json.dumps({"tables": T, "meta": meta}, ensure_ascii=False), encoding="utf-8")
    print({k: len(v) for k, v in T.items()})


if __name__ == "__main__":
    main()
