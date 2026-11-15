#!/usr/bin/env python3
"""Motorbasert svakhetsanalyse. Leser analysis/out/evals.ndjson (fra engine.py).

Feilklassifisering som Lichess: fall i vinnersjanse (0-100-skala) for spilleren som trekker:
  unøyaktighet >= 5, feil >= 10, bukk (blunder) >= 15 prosentpoeng.
Skriver analysis/out/weaknesses.json.
"""
import json
import pathlib
import sys
from collections import defaultdict

import chess

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from common import OUT, load_games, win_pct  # noqa: E402

VAL = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3, chess.ROOK: 5, chess.QUEEN: 9, chess.KING: 0}
TCS = {"180+0": "blitz 3+0", "60+0": "bullet 1+0"}


def cls(drop):
    return "blunder" if drop >= 15 else "mistake" if drop >= 10 else "inacc" if drop >= 5 else "ok"


class Acc:
    """Teller trekk og feil i en kategori."""

    def __init__(self):
        self.n = self.blunder = self.mistake = self.inacc = 0
        self.loss = 0.0

    def add(self, drop):
        self.n += 1
        self.loss += drop
        c = cls(drop)
        if c != "ok":
            setattr(self, c, getattr(self, c) + 1)

    def out(self):
        if not self.n:
            return None
        return {"moves": self.n,
                "blunder_per100": round(100 * self.blunder / self.n, 2),
                "mistake_per100": round(100 * self.mistake / self.n, 2),
                "avg_winpct_loss": round(self.loss / self.n, 2)}


def phase(board, my_move_no):
    pieces = sum(len(board.pieces(pt, c)) for pt in (chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN)
                 for c in (chess.WHITE, chess.BLACK))
    if pieces <= 6:
        return "3 sluttspill"
    if my_move_no <= 12:
        return "1 åpning (trekk 1-12)"
    return "2 midtspill"


def clock_bucket(sec, initial):
    f = sec / initial
    if sec < 5:
        return "a: <5 s"
    if sec < 10:
        return "b: 5-10 s"
    if f < 0.15:
        return "c: 10 s-15%"
    if f < 0.35:
        return "d: 15-35%"
    if f < 0.65:
        return "e: 35-65%"
    return "f: >65%"


def spent_bucket(sec):
    return ("a: <1 s" if sec < 1 else "b: 1-2 s" if sec < 2 else "c: 2-4 s" if sec < 4
            else "d: 4-8 s" if sec < 8 else "e: 8+ s")


def eval_bucket(wp):
    return ("a: tapt (<15%)" if wp < 15 else "b: dårligere (15-35%)" if wp < 35 else
            "c: lik (35-65%)" if wp <= 65 else "d: bedre (65-85%)" if wp <= 85 else "e: vunnet (>85%)")


def blunder_type(board_before, my_move, best_uci, reply_uci):
    """Grov heuristikk for hva slags bukk det var."""
    tags = []
    board = board_before.copy()
    best = chess.Move.from_uci(best_uci) if best_uci else None
    if best and best != my_move:
        if board.gives_check(best):
            tags.append("overså sjakk/taktikk med sjakk")
        elif board.is_capture(best):
            tags.append("overså gevinst av materiell")
    board.push(my_move)
    if reply_uci:
        reply = chess.Move.from_uci(reply_uci)
        if reply in board.legal_moves:
            if board.is_capture(reply):
                victim = board.piece_at(reply.to_square)
                if victim and VAL[victim.piece_type] >= 3:
                    tags.append("hengte offiser/dronning")
                else:
                    tags.append("hengte bonde/byttet feil")
            if board.gives_check(reply):
                tags.append("overså motstanderens sjakk/kongeangrep")
    if not tags:
        tags.append("posisjonell/stille trekk")
    return tags[0]


def main():
    evals = {}
    path = OUT / "evals.ndjson"
    for line in open(path, encoding="utf-8"):
        r = json.loads(line)
        if "cp" in r:
            evals[r["id"]] = r
    games = [g for g in load_games() if g["id"] in evals and g["tc"] in TCS and g["rated"]]
    print(f"{len(games)} analyserte partier", file=sys.stderr)

    R = {}
    for tc, label in TCS.items():
        gs = [g for g in games if g["tc"] == tc]
        if not gs:
            continue
        initial = gs[0]["clock"]["initial"]
        me_all, opp_all = Acc(), Acc()
        by_phase, by_phase_opp = defaultdict(Acc), defaultdict(Acc)
        by_clock, by_spent, by_eval = defaultdict(Acc), defaultdict(Acc), defaultdict(Acc)
        by_year = defaultdict(Acc)
        btype = defaultdict(int)
        btype_phase = defaultdict(lambda: defaultdict(int))
        thrown = {"won_positions": 0, "converted": 0, "drawn": 0, "lost": 0, "lost_how": defaultdict(int)}
        saved = {"lost_positions": 0, "saved_draw": 0, "won": 0}
        punish = {"opp_blunders": 0, "punished": 0, "missed": 0}
        open_eval = defaultdict(list)   # åpning -> min vinnersjanse etter trekk 12
        endgame_entry = defaultdict(lambda: [0, 0.0])  # eval-bucket ved overgang til sluttspill -> [n, score]
        examples = []

        for g in gs:
            ev = evals[g["id"]]
            cps, best = ev["cp"], ev["best"]
            sign = 1 if g["color"] == "white" else -1
            mine_first = 0 if g["color"] == "white" else 1
            clocks = g.get("clocks") or []
            board = chess.Board()
            max_wp, min_wp = 50, 50
            in_endgame = False
            opp_blundered_at = None
            for ply, san in enumerate(g["move_list"]):
                if ply + 1 >= len(cps):
                    break
                mover_is_me = (ply % 2) == mine_first
                wp_before = win_pct(sign * cps[ply])
                wp_after = win_pct(sign * cps[ply + 1])
                try:
                    move = board.parse_san(san)
                except ValueError:
                    break
                my_move_no = ply // 2 + 1
                ph = phase(board, my_move_no)
                if not in_endgame and ph.startswith("3"):
                    in_endgame = True
                    endgame_entry[eval_bucket(wp_before)][0] += 1
                    endgame_entry[eval_bucket(wp_before)][1] += g["score"]
                if mover_is_me:
                    drop = max(0.0, wp_before - wp_after)
                    me_all.add(drop)
                    by_phase[ph].add(drop)
                    by_eval[eval_bucket(wp_before)].add(drop)
                    by_year[g["local"].year].add(drop)
                    if ply < len(clocks):
                        left = clocks[ply] / 100
                        prev = clocks[ply - 2] / 100 if ply >= 2 else initial
                        by_clock[clock_bucket(left, initial)].add(drop)
                        if ply >= 2:
                            by_spent[spent_bucket(max(0.0, prev - left))].add(drop)
                    if drop >= 15:
                        reply = best[ply + 1] if ply + 1 < len(best) else None
                        t = blunder_type(board, move, best[ply], reply)
                        btype[t] += 1
                        btype_phase[ph][t] += 1
                        try:
                            best_san = board.san(chess.Move.from_uci(best[ply])) if best[ply] else None
                        except ValueError:
                            best_san = best[ply]
                        examples.append({"id": g["id"], "ply": ply, "move": san, "best": best_san,
                                         "drop": round(drop, 1), "type": t, "phase": ph,
                                         "wp_before": round(wp_before), "wp_after": round(wp_after),
                                         "opening": (g.get("opening") or {}).get("name", "?"),
                                         "fen": board.fen(), "date": g["local"].strftime("%Y-%m-%d"),
                                         "result": g["score"]})
                    if opp_blundered_at == ply - 1:
                        punish["opp_blunders"] += 1
                        if drop < 10:
                            punish["punished"] += 1
                        else:
                            punish["missed"] += 1
                    max_wp, min_wp = max(max_wp, wp_after), min(min_wp, wp_after)
                else:
                    drop = max(0.0, (100 - wp_before) - (100 - wp_after))
                    opp_all.add(drop)
                    by_phase_opp[ph].add(drop)
                    if drop >= 15 and wp_after >= 60:
                        opp_blundered_at = ply
                if mover_is_me and my_move_no == 12:
                    open_eval[(g["color"], (g.get("opening") or {}).get("name", "?").split(",")[0])].append(wp_after)
                board.push(move)

            if max_wp >= 90:
                thrown["won_positions"] += 1
                if g["score"] == 1:
                    thrown["converted"] += 1
                elif g["score"] == 0.5:
                    thrown["drawn"] += 1
                else:
                    thrown["lost"] += 1
                    thrown["lost_how"][g["status"]] += 1
            if min_wp <= 10:
                saved["lost_positions"] += 1
                if g["score"] == 0.5:
                    saved["saved_draw"] += 1
                elif g["score"] == 1:
                    saved["won"] += 1

        def dd(d):
            return {k: v.out() for k, v in sorted(d.items())}

        openings = []
        for (col, name), wps in open_eval.items():
            if len(wps) >= 25:
                openings.append({"color": col, "opening": name, "n": len(wps),
                                 "avg_winpct_after_move12": round(sum(wps) / len(wps), 1)})
        openings.sort(key=lambda o: o["avg_winpct_after_move12"])
        tw = thrown["won_positions"] or 1
        R[tc] = {
            "label": label,
            "games": len(gs),
            "me": me_all.out(),
            "opponents": opp_all.out(),
            "by_phase": dd(by_phase),
            "by_phase_opponents": dd(by_phase_opp),
            "by_clock_left": dd(by_clock),
            "by_time_spent": dd(by_spent),
            "by_eval_before": dd(by_eval),
            "by_year": dd(by_year),
            "blunder_types": dict(sorted(btype.items(), key=lambda kv: -kv[1])),
            "blunder_types_by_phase": {k: dict(v) for k, v in sorted(btype_phase.items())},
            "won_positions": {**thrown, "lost_how": dict(thrown["lost_how"]),
                              "conversion_pct": round(100 * thrown["converted"] / tw, 1)},
            "lost_positions": saved,
            "punishing_opp_blunders": {**punish, "punish_pct": round(100 * punish["punished"] / max(1, punish["opp_blunders"]), 1)},
            "endgame_entry_score": {k: {"n": v[0], "score": round(100 * v[1] / v[0], 1)} for k, v in sorted(endgame_entry.items())},
            "openings_by_eval_move12_worst": openings[:15],
            "openings_by_eval_move12_best": openings[-10:][::-1],
        }
        (OUT / f"blunders_{tc.replace('+', '_')}.json").write_text(json.dumps(examples), encoding="utf-8")

    (OUT / "weaknesses.json").write_text(json.dumps(R, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(R, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
