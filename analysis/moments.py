#!/usr/bin/env python3
"""Finner alle bukker (fall i vinnersjanse >= 15) for begge spillere i blitzpartier,
og beriker dem med åpen kildekode-verktøy:

  * Stockfish: straffelinjen etter bukken (PV), så taktikken kan klassifiseres.
  * lichess-puzzler sin tagger (cook.py, AGPL): samme temaer som Lichess-oppgaver
    (fork, pin, hangingPiece, mateIn2, backRankMate, ...).
  * Maia-1900 via Lc0: hva en typisk 1900-spiller ville spilt i samme stilling (bare dine trekk),
    og om det trekket hadde unngått bukken.

Gjenopptakbar: analysis/out/moments.ndjson (én linje per bukk, nøkkel "id-ply").

Bruk: python analysis/moments.py [--last N] [--workers 28]
Miljø: STOCKFISH, LC0, MAIA_WEIGHTS, PUZZLER_TAGGER (mappe med cook.py)
"""
import argparse
import json
import multiprocessing as mp
import os
import pathlib
import sys
import time

import chess
import chess.engine
import chess.pgn

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from common import OUT, load_games, win_pct  # noqa: E402

HOME = pathlib.Path.home()
SF = os.environ.get("STOCKFISH", str(HOME / "tools/stockfish/stockfish/stockfish-windows-x86-64-universal.exe"))
LC0 = os.environ.get("LC0", str(HOME / "tools/lc0/lc0.exe"))
MAIA = os.environ.get("MAIA_WEIGHTS", str(HOME / "tools/lc0/maia-1900.pb.gz"))
TAGGER = os.environ.get("PUZZLER_TAGGER", str(HOME / "tools/lichess-puzzler/tagger"))
MOMENTS = OUT / "moments.ndjson"
TC = "180+0"
PV_NODES = 400_000
CHECK_NODES = 60_000


def phase(board, move_no):
    pieces = sum(len(board.pieces(pt, c)) for pt in (chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN)
                 for c in (chess.WHITE, chess.BLACK))
    if pieces <= 6:
        return "endgame"
    return "opening" if move_no <= 12 else "middlegame"


def collect(games, evals):
    """Alle bukker (begge sider) med kontekst."""
    out = []
    for g in games:
        ev = evals[g["id"]]
        cps = ev["cp"]
        me_white = g["color"] == "white"
        clocks = g.get("clocks") or []
        initial = g["clock"]["initial"]
        board = chess.Board()
        prev_blunder_ply = None
        for ply, san in enumerate(g["move_list"]):
            if ply + 1 >= len(cps):
                break
            try:
                move = board.parse_san(san)
            except ValueError:
                break
            white_moves = ply % 2 == 0
            sign = 1 if white_moves else -1
            wb, wa = win_pct(sign * cps[ply]), win_pct(sign * cps[ply + 1])
            drop = wb - wa
            if drop >= 15:
                mover_me = white_moves == me_white
                left = clocks[ply] / 100 if ply < len(clocks) else None
                prev = (clocks[ply - 2] / 100 if ply >= 2 else initial) if ply < len(clocks) else None
                out.append({
                    "key": f"{g['id']}-{ply}", "id": g["id"], "ply": ply, "who": "me" if mover_me else "opp",
                    "date": g["local"].strftime("%Y-%m-%d"), "created": g["createdAt"],
                    "drop": round(drop, 1), "wp_before": round(wb, 1), "wp_after": round(wa, 1),
                    "phase": phase(board, ply // 2 + 1), "move_no": ply // 2 + 1,
                    "clock": left, "spent": None if left is None or prev is None else round(max(0, prev - left), 1),
                    "after_opp_blunder": prev_blunder_ply == ply - 1,
                    "fen": board.fen(), "move": move.uci(), "san": san, "best": ev["best"][ply],
                    "cp_after_solver": -sign * cps[ply + 1],  # eval fra straffende sides perspektiv
                    "opening": (g.get("opening") or {}).get("name", "?"), "my_color": g["color"],
                })
                prev_blunder_ply = ply
            board.push(move)
    return out


# ---------- Maia (enkeltprosess) ----------
def maia_pass(moms, done):
    todo = [m for m in moms if m["who"] == "me" and "maia" not in done.get(m["key"], {})]
    if not todo or not (pathlib.Path(LC0).exists() and pathlib.Path(MAIA).exists()):
        return {}
    eng = chess.engine.SimpleEngine.popen_uci(LC0)
    eng.configure({"WeightsFile": MAIA, "Threads": 2})
    res, t0 = {}, time.time()
    for i, m in enumerate(todo):
        info = eng.analyse(chess.Board(m["fen"]), chess.engine.Limit(nodes=1))
        res[m["key"]] = info["pv"][0].uci() if info.get("pv") else None
        if (i + 1) % 2000 == 0:
            print(f"  maia {i + 1}/{len(todo)} ({(i + 1) / (time.time() - t0):.0f}/s)", flush=True)
    eng.quit()
    return res


# ---------- Stockfish-arbeidere ----------
_sf = None


def _init():
    global _sf
    _sf = chess.engine.SimpleEngine.popen_uci(SF)
    _sf.configure({"Threads": 1, "Hash": 64})


def _score(info, pov):
    return info["score"].pov(pov).score(mate_score=100000)


def sf_work(task):
    m, maia_move = task
    board = chess.Board(m["fen"])
    mover = board.turn
    board.push(chess.Move.from_uci(m["move"]))
    out = {"key": m["key"]}
    try:
        info = _sf.analyse(board, chess.engine.Limit(nodes=PV_NODES))
        pv = [mv.uci() for mv in info.get("pv", [])]
        mate = info["score"].pov(not mover).is_mate()
        n = min(len(pv), 9 if mate else 5)
        if n % 2 == 0:
            n -= 1
        out["pv"] = pv[:max(1, n)]
        out["solver_cp"] = 999999998 if mate else _score(info, not mover)
        if maia_move:
            out["maia"] = maia_move
            if maia_move == m["move"]:
                out["maia_drop"] = m["drop"]
            else:
                b2 = chess.Board(m["fen"])
                b2.push(chess.Move.from_uci(maia_move))
                i2 = _sf.analyse(b2, chess.engine.Limit(nodes=CHECK_NODES))
                cp = max(-1000, min(1000, _score(i2, mover)))
                out["maia_drop"] = round(max(0.0, m["wp_before"] - win_pct(cp)), 1)
    except Exception as e:  # noqa: BLE001
        out["error"] = str(e)[:200]
    return out


# ---------- lichess-puzzler-tagger ----------
def tag(m, pv, solver_cp):
    sys.path.insert(0, TAGGER)
    import cook  # noqa: E402
    from model import Puzzle  # noqa: E402
    board = chess.Board(m["fen"])
    node = chess.pgn.Game.from_board(board)
    for uci in [m["move"]] + pv:
        node = node.add_main_variation(chess.Move.from_uci(uci))
    try:
        return cook.cook(Puzzle(m["key"], node.game(), int(solver_cp)))
    except Exception:  # noqa: BLE001
        return ["?"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--last", type=int, default=0, help="bare de N siste blitzpartiene")
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 4))
    a = ap.parse_args()

    evals = {}
    for line in open(OUT / "evals.ndjson", encoding="utf-8"):
        r = json.loads(line)
        if "cp" in r:
            evals[r["id"]] = r
    games = [g for g in load_games() if g["tc"] == TC and g["rated"] and g["id"] in evals]
    if a.last:
        games = games[-a.last:]
    moms = collect(games, evals)
    done = {}
    if MOMENTS.exists():
        for line in open(MOMENTS, encoding="utf-8"):
            r = json.loads(line)
            done[r["key"]] = r
    print(f"{len(games)} partier, {len(moms)} bukker, {len(done)} ferdig fra før", flush=True)

    todo = [m for m in moms if m["key"] not in done]
    maia = maia_pass(todo, done)
    t0 = time.time()
    with mp.Pool(a.workers, initializer=_init) as pool, open(MOMENTS, "a", encoding="utf-8") as f:
        for i, r in enumerate(pool.imap_unordered(sf_work, [(m, maia.get(m["key"])) for m in todo], chunksize=8)):
            f.write(json.dumps(r) + "\n")
            if (i + 1) % 2000 == 0:
                f.flush()
                print(f"  stockfish {i + 1}/{len(todo)} ({(i + 1) / (time.time() - t0):.0f}/s)", flush=True)

    # Slå sammen og tagg
    extra = {}
    for line in open(MOMENTS, encoding="utf-8"):
        r = json.loads(line)
        extra[r["key"]] = r
    full = []
    for m in moms:
        e = extra.get(m["key"], {})
        if "pv" in e:
            m.update({k: e[k] for k in ("pv", "solver_cp", "maia", "maia_drop") if k in e})
            m["tags"] = tag(m, e["pv"], e["solver_cp"])
        full.append(m)
    (OUT / "moments_full.json").write_text(json.dumps(full), encoding="utf-8")
    print(f"Ferdig: {len(full)} bukker tagget -> moments_full.json", flush=True)


if __name__ == "__main__":
    main()
