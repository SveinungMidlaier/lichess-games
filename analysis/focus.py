#!/usr/bin/env python3
"""Rangerer fokusområder etter hvor mye de koster deg MER enn motstanderne dine.

Kostnad = fall i vinnersjanse / 100 = forventede poeng tapt (1 = en hel seier).
For hver kategori: dine poeng tapt per 50 partier, motstandernes i de samme partiene,
og differansen ("overskudd"). Positiv differanse = her taper du mer enn folk på ditt nivå.

Måling i blokker på 50 partier: viser hvor mye tallet svinger av ren tilfeldighet,
så du vet hvor stort fall som trengs før en forbedring er reell.

Leser analysis/out/moments_full.json (moments.py). Skriver analysis/out/focus.json.
"""
import json
import pathlib
import statistics as st
import sys
from collections import defaultdict

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from common import OUT, load_games  # noqa: E402

TC = "180+0"
RECENT_DAYS = 365   # "nå" = blitzpartiene de siste 12 månedene
EARLIER = 1500      # sammenligning: like mange partier rett før det
BLOCK = 50

MATE = {"mate", "mateIn1", "mateIn2", "mateIn3", "mateIn4", "mateIn5", "backRankMate", "smotheredMate",
        "anastasiaMate", "arabianMate", "hookMate", "bodenMate", "doubleBishopMate", "dovetailMate"}

# id, navn, beskrivelse, predikat(m, prev) der prev er motstanderens bukk rett før (eller None),
# Lichess-oppgavetema for trening.
CATS = [
    ("hanging", "Hanging pieces",
     "Leaving a piece or pawn en prise, so the opponent simply takes it.",
     lambda m, p: "hangingPiece" in m["tags"], "hangingPiece"),
    ("fork", "Allowing forks",
     "Moves that let one enemy piece attack two of yours.",
     lambda m, p: "fork" in m["tags"], "fork"),
    ("pin_skewer", "Pins and skewers",
     "Moves that walk into a pin or a skewer.",
     lambda m, p: "pin" in m["tags"] or "skewer" in m["tags"], "pin"),
    ("discovered", "Discovered attacks",
     "Missing that moving one enemy piece unmasks another (incl. double check).",
     lambda m, p: "discoveredAttack" in m["tags"] or "doubleCheck" in m["tags"], "discoveredAttack"),
    ("king_safety", "Mating attacks against you",
     "Blunders that allow a forced mate.",
     lambda m, p: bool(MATE & set(m["tags"])), "mateIn2"),
    ("combination", "Deflection, attraction and sacrifices",
     "Allowing combinations that need a sacrifice or remove a defender.",
     lambda m, p: bool({"deflection", "attraction", "overloading", "sacrifice", "capturingDefender", "interference",
                        "clearance"} & set(m["tags"])), "deflection"),
    ("pawns", "Passed pawns and promotion",
     "Underestimating advanced pawns and promotion threats.",
     lambda m, p: bool({"advancedPawn", "promotion", "underPromotion"} & set(m["tags"])), "advancedPawn"),
    ("missed", "Missed punishments",
     "The opponent just blundered and your reply let the chance go.",
     lambda m, p: p is not None, "hangingPiece"),
    ("converting", "Converting better positions",
     "Blunders while you were clearly better (65-90% winning chance).",
     lambda m, p: 65 <= m["wp_before"] < 90, None),
    ("defending", "Defending worse positions",
     "Blunders while already worse (10-35%), which turn a fight into a loss.",
     lambda m, p: 10 <= m["wp_before"] <= 35, "defensiveMove"),
    ("endgame", "Endgame technique",
     "Blunders after the endgame starts (six or fewer pieces).",
     lambda m, p: m["phase"] == "endgame", "endgame"),
    ("opening", "Opening phase",
     "Blunders in moves 1-12.",
     lambda m, p: m["phase"] == "opening", "opening"),
    ("long_think", "Calculation on long thinks",
     "Blunders on moves where you spent 8 seconds or more.",
     lambda m, p: (m.get("spent") or 0) >= 8, None),
    ("scramble", "Time scrambles",
     "Blunders with under 10 seconds left.",
     lambda m, p: m.get("clock") is not None and m["clock"] < 10, None),
]


def to_san(fen, uci):
    import chess
    try:
        b = chess.Board(fen)
        return b.san(chess.Move.from_uci(uci))
    except Exception:  # noqa: BLE001
        return uci


def main():
    games = [g for g in load_games() if g["tc"] == TC and g["rated"]]
    moms = json.loads((OUT / "moments_full.json").read_text(encoding="utf-8"))
    moms = [m for m in moms if "tags" in m]
    analysed = sorted({m["id"] for m in moms} | set(), key=lambda x: x)
    by_game = defaultdict(list)
    for m in moms:
        by_game[m["id"]].append(m)
    # Partier med motoranalyse (også de uten bukker) i kronologisk rekkefølge
    ev_ids = set()
    for line in open(OUT / "evals.ndjson", encoding="utf-8"):
        r = json.loads(line)
        if "cp" in r:
            ev_ids.add(r["id"])
    gs = [g for g in games if g["id"] in ev_ids]
    from datetime import timedelta
    cutoff = gs[-1]["local"] - timedelta(days=RECENT_DAYS)
    recent = [g for g in gs if g["local"] >= cutoff]
    earlier = [g for g in gs if g["local"] < cutoff][-EARLIER:]
    print(f"{len(gs)} analyserte blitzpartier, {len(moms)} bukker; 'nå' = siste {len(recent)} partier "
          f"({recent[0]['local']:%Y-%m-%d} til {recent[-1]['local']:%Y-%m-%d})", file=sys.stderr)

    def cat_hits(g):
        """-> {cat: [me_cost, opp_cost, me_n, opp_n, me_avoidable_n, me_maia_n]} for ett parti."""
        out = defaultdict(lambda: [0.0, 0.0, 0, 0, 0, 0])
        ms = sorted(by_game.get(g["id"], []), key=lambda m: m["ply"])
        prev_by_ply = {m["ply"]: m for m in ms}
        for m in ms:
            p = prev_by_ply.get(m["ply"] - 1) if m["after_opp_blunder"] else None
            for cid, _, _, pred, _ in CATS:
                try:
                    hit = pred(m, p)
                except Exception:  # noqa: BLE001
                    hit = False
                if not hit:
                    continue
                o = out[cid]
                if m["who"] == "me":
                    o[0] += m["drop"] / 100
                    o[2] += 1
                    if "maia_drop" in m:
                        o[5] += 1
                        o[4] += m["maia_drop"] < 10
                else:
                    o[1] += m["drop"] / 100
                    o[3] += 1
        return out

    per_game = {g["id"]: cat_hits(g) for g in gs}

    def summarise(sub):
        n = len(sub)
        res = {}
        for cid, name, desc, _, theme in CATS:
            me = sum(per_game[g["id"]][cid][0] for g in sub if cid in per_game[g["id"]])
            op = sum(per_game[g["id"]][cid][1] for g in sub if cid in per_game[g["id"]])
            me_n = sum(per_game[g["id"]][cid][2] for g in sub if cid in per_game[g["id"]])
            av = sum(per_game[g["id"]][cid][4] for g in sub if cid in per_game[g["id"]])
            mn = sum(per_game[g["id"]][cid][5] for g in sub if cid in per_game[g["id"]])
            res[cid] = {"me": me / n * BLOCK, "opp": op / n * BLOCK, "excess": (me - op) / n * BLOCK,
                        "me_count": me_n / n * BLOCK, "avoidable_pct": 100 * av / mn if mn else None}
        return res

    now = summarise(recent)
    prev = summarise(earlier) if len(earlier) >= 300 else None

    # Blokker à 50 partier: variasjon i "dine poeng tapt" og "antall bukker" per kategori
    blocks = [recent[i:i + BLOCK] for i in range(0, len(recent) - BLOCK + 1, BLOCK)]
    block_rows = []
    noise = {}
    for cid, *_ in CATS:
        vals, counts = [], []
        for bi, b in enumerate(blocks):
            s = summarise(b)[cid]
            vals.append(s["me"])
            counts.append(s["me_count"])
            block_rows.append({"block": bi + 1, "start": b[0]["local"].strftime("%Y-%m-%d"), "cat": cid,
                               "points_lost": round(s["me"], 2), "blunders": round(s["me_count"], 1)})
        noise[cid] = {"sd_points": st.pstdev(vals) if len(vals) > 1 else None,
                      "sd_blunders": st.pstdev(counts) if len(counts) > 1 else None,
                      "mean_blunders": st.mean(counts) if counts else None}

    rank = []
    for cid, name, desc, _, theme in CATS:
        r = now[cid]
        rank.append({
            "id": cid, "name": name, "description": desc, "lichess_theme": theme,
            "points_lost_per50": round(r["me"], 2), "opp_points_lost_per50": round(r["opp"], 2),
            "excess_per50": round(r["excess"], 2),
            "blunders_per50": round(r["me_count"], 1),
            "avoidable_pct": None if r["avoidable_pct"] is None else round(r["avoidable_pct"], 0),
            "excess_earlier": None if not prev else round(prev[cid]["excess"], 2),
            "block_sd_blunders": None if noise[cid]["sd_blunders"] is None else round(noise[cid]["sd_blunders"], 1),
        })
    rank.sort(key=lambda r: -r["excess_per50"])

    # Temaer (lichess-puzzler-tagger) – hva du tillater vs motstanderne, siste 12 måneder
    rid = {g["id"] for g in recent}
    theme_me, theme_op = defaultdict(float), defaultdict(float)
    for m in moms:
        if m["id"] not in rid:
            continue
        for t in m["tags"]:
            if t in ("advantage", "crushing", "equality", "short", "long", "veryLong", "oneMove", "mate"):
                continue
            (theme_me if m["who"] == "me" else theme_op)[t] += m["drop"] / 100
    n = len(recent)
    themes = sorted(({"theme": t, "me": round(theme_me[t] / n * BLOCK, 2), "opp": round(theme_op[t] / n * BLOCK, 2),
                      "excess": round((theme_me[t] - theme_op[t]) / n * BLOCK, 2)}
                     for t in set(theme_me) | set(theme_op)), key=lambda r: -r["excess"])

    # Øvingsstillinger per kategori: nyeste avoidable bukker (Maia-1900 hadde unngått dem)
    practice = []
    for r in rank[:6]:
        cid = r["id"]
        pred = next(c[3] for c in CATS if c[0] == cid)
        cands = []
        for m in moms:
            if m["who"] != "me" or m["id"] not in rid or m["drop"] < 20:
                continue
            ms = by_game[m["id"]]
            p = next((x for x in ms if x["ply"] == m["ply"] - 1), None) if m["after_opp_blunder"] else None
            if pred(m, p):
                cands.append(m)
        cands.sort(key=lambda m: (m.get("maia_drop", 99) < 10, m["created"]), reverse=True)
        for m in cands[:12]:
            practice.append({"cat": cid, "key": m["key"], "date": m["date"], "move_no": m["move_no"],
                             "played": m["san"], "best": to_san(m["fen"], m["best"]), "drop": m["drop"],
                             "maia_avoids": m.get("maia_drop") is not None and m["maia_drop"] < 10,
                             "themes": ", ".join(t for t in m["tags"] if t not in ("advantage", "crushing", "equality", "short", "long", "veryLong", "oneMove")),
                             "url": f"https://lichess.org/{m['id']}#{m['ply']}"})

    out = {"window": {"games": len(recent), "from": recent[0]["local"].strftime("%Y-%m-%d"),
                      "to": recent[-1]["local"].strftime("%Y-%m-%d"), "analysed_total": len(gs),
                      "earlier_games": len(earlier),
                      "earlier_from": earlier[0]["local"].strftime("%Y-%m-%d") if earlier else None},
           "rank": rank, "themes": themes, "blocks": block_rows, "practice": practice}
    (OUT / "focus.json").write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    for r in rank:
        print(f"{r['excess_per50']:+6.2f}  meg {r['points_lost_per50']:5.2f}  mot {r['opp_points_lost_per50']:5.2f}  "
              f"bukker/50 {r['blunders_per50']:5.1f} ±{r['block_sd_blunders']}  unngåelig {r['avoidable_pct']}%  "
              f"(før {r['excess_earlier']})  {r['name']}")
    print("Temaer:", [(t["theme"], t["excess"]) for t in themes[:12]])


if __name__ == "__main__":
    main()
