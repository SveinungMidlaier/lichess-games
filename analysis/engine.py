#!/usr/bin/env python3
"""Stockfish-analyse av alle standardpartier. Gjenopptakbar.

Skriver analysis/out/evals.ndjson med én linje per parti:
  {"id", "cp": [eval etter ply 0..n, hvit perspektiv, ±1000 for matt], "best": [beste trekk (uci) i hver stilling]}

Bruk: python analysis/engine.py [--nodes 100000] [--workers 30] [--limit N] [--newest-first]
Krever: pip install chess, og Stockfish (env STOCKFISH eller ~/tools/stockfish/...).
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

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from common import OUT, load_games  # noqa: E402

DEFAULT_SF = pathlib.Path.home() / "tools/stockfish/stockfish/stockfish-windows-x86-64-universal.exe"
SF = os.environ.get("STOCKFISH", str(DEFAULT_SF))
EVALS = OUT / "evals.ndjson"

_engine = None
_nodes = 100_000


def _init(nodes):
    global _engine, _nodes
    _nodes = nodes
    _engine = chess.engine.SimpleEngine.popen_uci(SF)
    _engine.configure({"Threads": 1, "Hash": 32})


def _score(info):
    s = info["score"].white()
    return max(-1000, min(1000, s.score(mate_score=1000)))


def analyse(task):
    gid, moves = task
    board = chess.Board()
    cps, best = [], []
    try:
        _engine.protocol.send_line("ucinewgame")  # unngå hash-lekkasje mellom partier
        for i in range(len(moves) + 1):
            if board.is_game_over():
                if board.is_checkmate():
                    cps.append(-1000 if board.turn == chess.WHITE else 1000)
                else:
                    cps.append(0)
                best.append(None)
            else:
                info = _engine.analyse(board, chess.engine.Limit(nodes=_nodes))
                cps.append(_score(info))
                pv = info.get("pv")
                best.append(pv[0].uci() if pv else None)
            if i < len(moves):
                board.push_san(moves[i])
    except Exception as e:  # ulovlig trekk e.l.
        return {"id": gid, "error": str(e)[:200]}
    return {"id": gid, "cp": cps, "best": best}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--nodes", type=int, default=100_000)
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 2))
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--newest-first", action="store_true")
    a = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    done = set()
    if EVALS.exists():
        for line in open(EVALS, encoding="utf-8"):
            try:
                r = json.loads(line)
                if "cp" in r:  # feilede partier (f.eks. avbrutt kjøring) prøves på nytt
                    done.add(r["id"])
            except Exception:
                pass
    games = [g for g in load_games() if g["id"] not in done and len(g["move_list"]) >= 2]
    if a.newest_first:
        games.reverse()
    if a.limit:
        games = games[: a.limit]
    total_pos = sum(len(g["move_list"]) + 1 for g in games)
    print(f"{len(done)} ferdig fra før, {len(games)} partier / {total_pos} stillinger igjen, "
          f"{a.workers} prosesser, {a.nodes} noder/stilling", flush=True)

    tasks = [(g["id"], g["move_list"]) for g in games]
    t0, n, pos = time.time(), 0, 0
    with mp.Pool(a.workers, initializer=_init, initargs=(a.nodes,)) as pool, \
            open(EVALS, "a", encoding="utf-8") as out:
        for res in pool.imap_unordered(analyse, tasks, chunksize=4):
            out.write(json.dumps(res, separators=(",", ":")) + "\n")
            n += 1
            pos += len(res.get("cp", []))
            if n % 200 == 0 or n == len(tasks):
                out.flush()
                el = time.time() - t0
                rate = pos / el
                eta = (total_pos - pos) / rate / 60 if rate else 0
                print(f"{n}/{len(tasks)} partier, {rate:.0f} stillinger/s, ca. {eta:.0f} min igjen", flush=True)


if __name__ == "__main__":
    main()
