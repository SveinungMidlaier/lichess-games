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
PHASE = {"1": "Åpning (trekk 1-12)", "2": "Midtspill", "3": "Sluttspill"}
CLOCK = {"a": "Under 5 s", "b": "5-10 s", "c": "10-27 s", "d": "27-63 s", "e": "63-117 s", "f": "Over 117 s"}
SPENT = {"a": "Under 1 s", "b": "1-2 s", "c": "2-4 s", "d": "4-8 s", "e": "8 s eller mer"}
EVAL = {"a": "Tapt (<15 %)", "b": "Dårligere (15-35 %)", "c": "Likt (35-65 %)", "d": "Bedre (65-85 %)",
        "e": "Vinnende (>85 %)"}
LENGTH = {"a": "20 trekk eller færre", "b": "21-40 trekk", "c": "41-60 trekk", "d": "Over 60 trekk"}
GAP = {"a": "150+ sterkere", "b": "50-150 sterkere", "c": "Innenfor 50", "d": "50-150 svakere", "e": "150+ svakere"}
CLOCKDIFF = {"a": "20 %+ mindre tid", "b": "5-20 % mindre", "c": "Omtrent likt", "d": "5-20 % mer", "e": "20 %+ mer tid"}
BTYPE = {
    "posisjonell/stille trekk": "Stille trekk som ødela stillingen",
    "overså gevinst av materiell": "Overså gevinst av materiell",
    "hengte offiser/dronning": "Hengte offiser eller dronning",
    "hengte bonde/byttet feil": "Hengte bonde eller byttet feil",
    "overså sjakk/taktikk med sjakk": "Overså taktikk med sjakk",
    "overså motstanderens sjakk/kongeangrep": "Overså motstanderens sjakk eller kongeangrep",
}
THEME = {
    "hangingPiece": "Hengt brikke", "fork": "Gaffel", "pin": "Binding", "skewer": "Spidd",
    "discoveredAttack": "Avdekket angrep", "doubleCheck": "Dobbeltsjakk", "mateIn1": "Matt i 1",
    "mateIn2": "Matt i 2", "mateIn3": "Matt i 3", "mateIn4": "Matt i 4", "mateIn5": "Matt i 5+",
    "mate": "Matt", "backRankMate": "Baklinjematt", "smotheredMate": "Kvelningsmatt", "deflection": "Avledning",
    "attraction": "Tiltrekning", "overloading": "Overbelastning", "sacrifice": "Offer",
    "capturingDefender": "Slå forsvareren", "interference": "Avskjæring", "clearance": "Rydding",
    "advancedPawn": "Fremskutt bonde", "promotion": "Forvandling", "trappedPiece": "Fanget brikke",
    "kingsideAttack": "Angrep på kongefløyen", "queensideAttack": "Angrep på dronningfløyen",
    "exposedKing": "Utsatt konge", "quietMove": "Stille trekk", "defensiveMove": "Forsvarstrekk",
    "intermezzo": "Mellomtrekk", "xRayAttack": "Røntgenangrep", "zugzwang": "Trekktvang",
    "attackingF2F7": "Angrep på f2/f7", "rookEndgame": "Tårnsluttspill", "pawnEndgame": "Bondesluttspill",
    "queenEndgame": "Dronningsluttspill", "bishopEndgame": "Løpersluttspill", "knightEndgame": "Springersluttspill",
    "queenRookEndgame": "Dronning- og tårnsluttspill", "castling": "Rokade", "enPassant": "En passant",
    "collinearMove": "Kollineært trekk", "coercion": "Tvang", "simplification": "Forenkling",
    "underPromotion": "Underforvandling", "middlegame": "Midtspill", "endgame": "Sluttspill", "opening": "Åpning",
    "anastasiaMate": "Anastasias matt", "arabianMate": "Arabisk matt", "hookMate": "Krokmatt",
    "bodenMate": "Bodens matt", "doubleBishopMate": "Løperparmatt", "dovetailMate": "Svalehalematt",
}
# Fokusområder (id fra focus.py) på norsk: navn, beskrivelse
CAT_NO = {
    "hanging": ("Hengte brikker", "Lar en brikke eller bonde stå udekket, så motstanderen bare tar den."),
    "fork": ("Tillater gafler", "Trekk som lar én av motstanderens brikker angripe to av dine."),
    "pin_skewer": ("Bindinger og spidd", "Trekk som går rett inn i en binding eller et spidd."),
    "discovered": ("Avdekkede angrep", "Overser at en brikke som flytter seg, avdekker en annen (også dobbeltsjakk)."),
    "king_safety": ("Mattangrep mot deg", "Bukker som tillater tvungen matt."),
    "combination": ("Avledning, tiltrekning og offer", "Tillater kombinasjoner med offer eller som fjerner en forsvarer."),
    "pawns": ("Fribønder og forvandling", "Undervurderer fremskutte bønder og forvandlingstrusler."),
    "missed": ("Uutnyttede gaver", "Motstanderen bukket nettopp, og svaret ditt slapp sjansen."),
    "converting": ("Vinne bedre stillinger", "Bukker når du sto klart bedre (65-90 % vinnersjanse)."),
    "defending": ("Forsvare dårligere stillinger", "Bukker når du allerede sto dårligere (10-35 %), som gjør kamp til tap."),
    "endgame": ("Sluttspillteknikk", "Bukker etter at sluttspillet har startet (seks eller færre offiserer)."),
    "opening": ("Åpningsfasen", "Bukker i trekk 1-12."),
    "long_think": ("Beregning ved lang tenking", "Bukker på trekk der du brukte 8 sekunder eller mer."),
    "scramble": ("Tidsnød", "Bukker med under 10 sekunder igjen."),
}
# Fokusplanen på norsk: navn, sjekk før hvert trekk
PLAN_NO = {
    "opening": ("Åpningen, trekk 9-12 (mest siciliansk med svart og mot London/Zukertort)",
                "Trekk 9-12: før hvert trekk, spør hva motstanderens siste trekk endret, og om kongen og løse "
                "brikker står trygt. Gå gjennom de 10 siste partiene i de svakeste variantene dine."),
    "fork": ("Tillater gafler",
             "Før hvert trekk: hvilke felt kan springerne, dronningen og bøndene hans nå, og treffer noen av dem "
             "to av brikkene mine?"),
    "hanging": ("Hengte brikker",
                "Bukksjekk før du slipper brikken: etter dette trekket, hvilke brikker står udekket eller er "
                "angrepet flere ganger enn de er dekket?"),
    "king_safety": ("Mattangrep mot deg",
                    "Hvert trekk: sjakker, slag og trusler mot kongen min. Tell forsvarerne rundt kongen før du "
                    "åpner stillingen."),
}


def theme_list(s):
    return ", ".join(THEME.get(t.strip(), t.strip()) for t in s.split(",") if t.strip())


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
                rows.append({"key": f"{col}|{name}", "color": {"white": "Hvit", "black": "Svart"}[col], "opening": name,
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
            "name": CAT_NO.get(r["id"], (r["name"],))[0],
            "description": CAT_NO.get(r["id"], (None, r["description"]))[1],
            **{k: r[k] for k in ("id", "points_lost_per50", "opp_points_lost_per50",
                                 "excess_per50", "blunders_per50", "avoidable_pct", "excess_earlier",
                                 "block_sd_blunders")},
            "rank": i + 1,
            "train_url": f"https://lichess.org/training/{r['lichess_theme']}" if r["lichess_theme"] else None,
        } for i, r in enumerate(f["rank"])]
        top = [r["id"] for r in f["rank"][:4]]
        names = {r["id"]: r["name"] for r in f["rank"]}
        names = {k: CAT_NO.get(k, (v,))[0] for k, v in names.items()}
        T["focus_blocks"] = [{**b, "name": names[b["cat"]], "key": f"{b['cat']}-{b['block']}"}
                             for b in f["blocks"] if b["cat"] in top]
        T["themes"] = [{"theme": THEME.get(t["theme"], t["theme"]), **{k: t[k] for k in ("me", "opp", "excess")}}
                       for t in f["themes"] if t["me"] + t["opp"] >= 0.15][:16]
        T["focus_practice"] = [{**p, "name": names[p["cat"]], "themes": theme_list(p["themes"])}
                               for p in f["practice"]]

    pp = OUT.parent.parent / "focus" / "plan.json"
    if pp.exists():
        plan = json.loads(pp.read_text(encoding="utf-8"))
        size = plan.get("block_size", 50)
        T["plan"] = [{
            "block": i + 1, "games": f"Parti {i * size + 1}-{(i + 1) * size}", "id": q["id"],
            "name": PLAN_NO.get(q["id"], (q["name"],))[0], "check": PLAN_NO.get(q["id"], (None, q["check"]))[1], "train_url": q["train_url"],
            "baseline": q["baseline_blunders_per50"], "sd": q["baseline_sd"],
            "target": round(q["baseline_blunders_per50"] - 1.5 * q["baseline_sd"], 1),
            "excess": q["baseline_excess_per50"], "start": plan["start"],
        } for i, q in enumerate(plan["queue"])]

        prp = pp.parent / "progress.json"
        if prp.exists():
            blocks = json.loads(prp.read_text(encoding="utf-8"))["blocks"]
            T["progress"] = [{
                "block": b["block"], "name": PLAN_NO.get(b["focus"], (b["focus_name"],))[0],
                "start": b.get("start") or b["from"], "games": b["games"], "size": size, "analysed": b["analysed"], "complete": b["complete"],
                "from": b["from"], "to": b["to"], "focus_blunders": b["focus_blunders"],
                "per50": b["focus_blunders_per50"], "baseline": b["baseline_per50"], "sd": b["baseline_sd"],
                "target": round(b["baseline_per50"] - 1.5 * b["baseline_sd"], 1),
                "likely": round(b["baseline_per50"] - 0.5 * b["baseline_sd"], 1),
                "score": b["score_pct"], "vs_exp": b["vs_expected"], "rating": b["rating_end"],
                "verdict": b["verdict"], "current": i == len(blocks) - 1,
            } for i, b in enumerate(blocks)]

    here = pathlib.Path(__file__).resolve()
    meta = [
        {"label": "export_dash.py", "value": here.read_text(encoding="utf-8"), "type": "code", "lang": "python"},
        {"label": "Inndata", "value": "analysis/out/stats.json (stats.py), analysis/out/weaknesses.json og "
                                      "blunders_180_0.json (weaknesses.py, Stockfish 19 med 50k noder per stilling), "
                                      "focus.json (moments.py + focus.py: Stockfish 19 straffelinjer med 400k noder, "
                                      "temaer fra lichess-puzzler-taggeren, Maia-1900 via Lc0 0.32), "
                                      "focus/progress.json (track.py)"},
        {"label": "Kode", "value": "https://github.com/SveinungMidlaier/lichess-games/tree/main/analysis"},
    ]
    (OUT / "dash.json").write_text(json.dumps({"tables": T, "meta": meta}, ensure_ascii=False), encoding="utf-8")
    print({k: len(v) for k, v in T.items()})


if __name__ == "__main__":
    main()
