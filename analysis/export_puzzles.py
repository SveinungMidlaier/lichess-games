#!/usr/bin/env python3
"""Lager personlige oppgaver fra egne bukker (blitz 3+0, rated) til oppgavesiden.

Én oppgave = stillingen før en av dine bukker. Oppgaven er å finne et godt trekk.
Stockfish (multipv) avgjør hvilke trekk som godtas: alle innenfor ACCEPT win% av beste.

Output: analysis/out/puzzles.json
Bruk: python analysis/export_puzzles.py [--days 365] [--min-drop 20] [--workers 28]
Krever at moments.py har kjørt (moments_full.json).
"""
import argparse
import json
import multiprocessing as mp
import pathlib
import sys
from datetime import timedelta

import chess
import chess.engine

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from common import OUT, load_games, win_pct  # noqa: E402
from engine import SF  # noqa: E402

ACCEPT = 6.0      # win%-poeng under beste trekk som fortsatt godtas
NODES = 400_000   # alle lovlige trekk analyseres (multipv = antall trekk)

CAT_ORDER = [
    ("mate", "Matt", lambda t: any(x.startswith("mate") or x.endswith("Mate") for x in t)),
    ("fork", "Gaffel", lambda t: "fork" in t),
    ("hanging", "Hengt brikke", lambda t: "hangingPiece" in t or "trappedPiece" in t),
    ("pin", "Binding / spidd", lambda t: "pin" in t or "skewer" in t or "xRayAttack" in t),
    ("discovered", "Avdekket angrep", lambda t: "discoveredAttack" in t or "doubleCheck" in t),
    ("other", "Annen taktikk", lambda t: True),
]

_eng = None


def _init():
    global _eng
    _eng = chess.engine.SimpleEngine.popen_uci(SF)
    _eng.configure({"Threads": 1, "Hash": 64})


def accepted(task):
    key, fen = task
    board = chess.Board(fen)
    pov = board.turn
    n = board.legal_moves.count()
    infos = _eng.analyse(board, chess.engine.Limit(nodes=NODES), multipv=max(1, n))
    scored = []
    for inf in infos:
        if not inf.get("pv"):
            continue
        cp = inf["score"].pov(pov).score(mate_score=1000)
        scored.append((inf["pv"][0].uci(), win_pct(max(-1000, min(1000, cp)))))
    if not scored:
        return key, [], None, {}
    top = max(w for _, w in scored)
    ok = [m for m, w in scored if w >= top - ACCEPT]
    ev = {}
    for m, w in scored:                      # vinnersjanse etter hvert trekk (promotering: beste variant)
        ev[m[:4]] = max(ev.get(m[:4], -1), round(w))
    return key, ok, round(top, 1), ev


def san_line(board, ucis):
    b = board.copy()
    out = []
    for u in ucis:
        mv = chess.Move.from_uci(u)
        if mv not in b.legal_moves:
            break
        out.append(b.san(mv))
        b.push(mv)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=365)
    ap.add_argument("--min-drop", type=float, default=20)
    ap.add_argument("--workers", type=int, default=28)
    a = ap.parse_args()

    games = {g["id"]: g for g in load_games() if g["tc"] == "180+0" and g["rated"]}
    last = max(g["local"] for g in games.values())
    since = last - timedelta(days=a.days)
    moms = json.loads((OUT / "moments_full.json").read_text(encoding="utf-8"))
    sel = []
    for m in moms:
        g = games.get(m["id"])
        if (m["who"] != "me" or not g or g["local"] < since or "tags" not in m or not m.get("best")
                or m["drop"] < a.min_drop or m["wp_before"] < 30):
            continue
        sel.append((m, g))
    print(f"{len(sel)} oppgaver, analyserer godkjente trekk ...", flush=True)

    with mp.Pool(a.workers, initializer=_init) as pool:
        acc = dict((k, (ok, top, ev)) for k, ok, top, ev in
                   pool.imap_unordered(accepted, [(m["key"], m["fen"]) for m, _ in sel], chunksize=4))

    out = []
    for m, g in sel:
        ok, top, ev = acc.get(m["key"], ([], None, {}))
        if m["best"] not in ok:
            ok = [m["best"]] + ok
        if m["move"] in ok:          # dypere analyse sier at trekket ditt var greit: ikke en oppgave
            continue
        board = chess.Board(m["fen"])
        ply = m["ply"]
        prev = None
        if ply > 0:
            b0 = chess.Board()
            for san in g["move_list"][:ply - 1]:
                b0.push_san(san)
            prev = b0.parse_san(g["move_list"][ply - 1]).uci()
        tags = set(m["tags"])
        cat_id, cat_name = next((i, n) for i, n, f in CAT_ORDER if f(tags))
        after = board.copy()
        after.push(chess.Move.from_uci(m["move"]))
        maia = m.get("maia")
        out.append({
            "k": m["key"], "id": m["id"], "ply": ply, "date": m["date"], "fen": m["fen"],
            "color": m["my_color"], "prev": prev, "ok": ok,
            "best_san": board.san(chess.Move.from_uci(m["best"])),
            "best_line": san_line(board, [m["best"]]),
            "played": m["move"], "played_san": m["san"],
            "punish": san_line(after, m.get("pv", [])),
            "drop": m["drop"], "ev": ev, "wp_before": m["wp_before"], "wp_after": m["wp_after"],
            "clock": m.get("clock"), "spent": m.get("spent"), "move_no": m["move_no"], "phase": m["phase"],
            "opening": m.get("opening") or "", "cat": cat_id, "cat_name": cat_name,
            "maia_ok": maia is not None and m.get("maia_drop", 99) < 10,
            "maia_san": board.san(chess.Move.from_uci(maia)) if maia else None,
            "url": f"https://lichess.org/{m['id']}#{ply}",
        })
    out.sort(key=lambda p: (p["date"], p["ply"]), reverse=True)
    (OUT / "puzzles.json").write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    from collections import Counter
    print(len(out), "oppgaver ->", OUT / "puzzles.json")
    print(Counter(p["cat_name"] for p in out), "Maia-unngåelige:", sum(p["maia_ok"] for p in out))


if __name__ == "__main__":
    main()
