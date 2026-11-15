#!/usr/bin/env python3
"""Statistisk analyse uten motor: resultater, åpninger, tidsbruk, tilt, tidspunkt.

Alle "score"-tall er i % (seier=1, remis=0.5). "vs forventet" = faktisk score minus
Elo-forventet score gitt ratingforskjell, i prosentpoeng. Positivt = bedre enn ratingen tilsier.
Skriver analysis/out/stats.json og en tekstoppsummering til stdout.
"""
import json
import pathlib
import statistics as st
import sys
from collections import defaultdict

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from common import OUT, load_games  # noqa: E402

MAIN_TC = {"180+0": "blitz 3+0", "60+0": "bullet 1+0"}
SESSION_GAP_MIN = 30


def agg(gs):
    n = len(gs)
    if not n:
        return None
    s = sum(g["score"] for g in gs)
    e = sum(g["exp"] for g in gs)
    return {
        "n": n,
        "score": round(100 * s / n, 1),
        "vs_exp": round(100 * (s - e) / n, 1),
        "w": sum(g["score"] == 1 for g in gs),
        "d": sum(g["score"] == 0.5 for g in gs),
        "l": sum(g["score"] == 0 for g in gs),
    }


def group(gs, key, min_n=1):
    d = defaultdict(list)
    for g in gs:
        k = key(g)
        if k is not None:
            d[k].append(g)
    return {k: agg(v) for k, v in d.items() if len(v) >= min_n}


def family(g):
    o = g.get("opening")
    return o["name"].split(":")[0].strip() if o else None


def variation(g):
    o = g.get("opening")
    return o["name"].split(",")[0].strip() if o else None


def clock_at(g, my_move_no):
    """Min gjenværende tid (sek) etter mitt trekk nr. my_move_no (1-basert)."""
    c = g.get("clocks")
    if not c:
        return None
    idx = 2 * (my_move_no - 1) + (0 if g["color"] == "white" else 1)
    return c[idx] / 100 if idx < len(c) else None


def opp_clock_at(g, my_move_no):
    c = g.get("clocks")
    if not c:
        return None
    idx = 2 * (my_move_no - 1) + (1 if g["color"] == "white" else 0)
    return c[idx] / 100 if idx < len(c) else None


def time_stats(gs):
    out = {}
    initial = gs[0]["clock"]["initial"]
    for mv in (10, 20, 30, 40):
        mine = [x for x in (clock_at(g, mv) for g in gs) if x is not None]
        opp = [x for x in (opp_clock_at(g, mv) for g in gs) if x is not None]
        if len(mine) > 50:
            out[f"move{mv}"] = {
                "my_pct_left": round(100 * st.median(mine) / initial, 1),
                "opp_pct_left": round(100 * st.median(opp) / initial, 1),
                "n": len(mine),
            }
    losses = [g for g in gs if g["score"] == 0]
    wins = [g for g in gs if g["score"] == 1]
    out["loss_terminations"] = dict(_count(g["status"] for g in losses))
    out["win_terminations"] = dict(_count(g["status"] for g in wins))
    out["timeout_loss_pct_of_losses"] = round(100 * out["loss_terminations"].get("outoftime", 0) / max(1, len(losses)), 1)
    out["timeout_win_pct_of_wins"] = round(100 * out["win_terminations"].get("outoftime", 0) / max(1, len(wins)), 1)

    # Tidsforsprang/-underskudd ved trekk 20 og resultat
    def bucket(g):
        m, o = clock_at(g, 20), opp_clock_at(g, 20)
        if m is None or o is None:
            return None
        diff = (m - o) / initial * 100
        if diff < -20:
            return "a: >20% mindre tid"
        if diff < -5:
            return "b: 5-20% mindre"
        if diff <= 5:
            return "c: omtrent likt"
        if diff <= 20:
            return "d: 5-20% mer"
        return "e: >20% mer tid"
    out["by_clock_diff_move20"] = dict(sorted(group(gs, bucket).items()))
    return out


def _count(it):
    d = defaultdict(int)
    for x in it:
        d[x] += 1
    return sorted(d.items(), key=lambda kv: -kv[1])


def sessions(gs):
    """Del i økter (pause > 30 min) og se på score etter posisjon i økt og etter tap/seier."""
    for i, g in enumerate(gs):
        prev = gs[i - 1] if i else None
        new = prev is None or (g["createdAt"] - prev["lastMoveAt"]) > SESSION_GAP_MIN * 60_000
        g["sess_idx"] = 1 if new else prev["sess_idx"] + 1
        if new:
            g["streak"] = 0
        else:
            ps = prev["streak"]
            if prev["score"] == 0:
                g["streak"] = ps - 1 if ps < 0 else -1
            elif prev["score"] == 1:
                g["streak"] = ps + 1 if ps > 0 else 1
            else:
                g["streak"] = 0
    idx = group(gs, lambda g: min(g["sess_idx"], 31))
    by_idx = {}
    for lo, hi, lab in [(1, 1, "1"), (2, 5, "2-5"), (6, 10, "6-10"), (11, 20, "11-20"), (21, 31, "21+")]:
        sub = [g for g in gs if lo <= min(g["sess_idx"], 31) <= hi]
        by_idx[lab] = agg(sub)

    def sk(g):
        s = g["streak"]
        if g["sess_idx"] == 1:
            return "0: første i økt"
        if s <= -3:
            return "1: etter 3+ tap på rad"
        if s == -2:
            return "2: etter 2 tap på rad"
        if s == -1:
            return "3: etter 1 tap"
        if s == 0:
            return "4: etter remis"
        if s == 1:
            return "5: etter 1 seier"
        return "6: etter 2+ seire"
    # Hvor lange økter, og hvordan slutter de
    sess_lens, ends = [], defaultdict(int)
    for i, g in enumerate(gs):
        last = i == len(gs) - 1 or gs[i + 1]["sess_idx"] == 1
        if last:
            sess_lens.append(g["sess_idx"])
            ends["tap" if g["score"] == 0 else "seier" if g["score"] == 1 else "remis"] += 1
    return {
        "by_index_in_session": by_idx,
        "by_streak": dict(sorted(group(gs, sk).items())),
        "n_sessions": len(sess_lens),
        "median_session_len": st.median(sess_lens),
        "pct_sessions_20plus": round(100 * sum(x >= 20 for x in sess_lens) / len(sess_lens), 1),
        "session_ends_with": dict(ends),
    }


def openings(gs, min_n):
    res = {}
    for col in ("white", "black"):
        sub = [g for g in gs if g["color"] == col]
        fam = group(sub, family, min_n)
        var = group(sub, variation, min_n)
        res[col] = {
            "families": dict(sorted(fam.items(), key=lambda kv: -kv[1]["n"])),
            "variations": dict(sorted(var.items(), key=lambda kv: -kv[1]["n"])),
        }
    # Første trekk
    res["first_move_white"] = group([g for g in gs if g["color"] == "white"], lambda g: g["move_list"][0] if g["move_list"] else None, min_n)
    res["reply_to_e4"] = group([g for g in gs if g["color"] == "black" and g["move_list"][:1] == ["e4"]],
                               lambda g: g["move_list"][1] if len(g["move_list"]) > 1 else None, min_n)
    res["reply_to_d4"] = group([g for g in gs if g["color"] == "black" and g["move_list"][:1] == ["d4"]],
                               lambda g: g["move_list"][1] if len(g["move_list"]) > 1 else None, min_n)
    # Korte tap (<= 25 trekk, ikke på tid) per åpning: feller/åpningskatastrofer
    short = [g for g in gs if g["score"] == 0 and len(g["move_list"]) <= 50 and g["status"] != "outoftime"]
    res["short_losses_by_family"] = dict(_count(f"{g['color']}: {variation(g)}" for g in short)[:15])
    res["n_short_losses"] = len(short)
    return res


def rating_history(gs):
    by_month = {}
    for g in gs:
        by_month[g["local"].strftime("%Y-%m")] = g["my_rating"] + g["rating_diff"]
    peak = max(gs, key=lambda g: g["my_rating"] + g["rating_diff"])
    return {
        "monthly_end": by_month,
        "peak": peak["my_rating"] + peak["rating_diff"],
        "peak_date": peak["local"].strftime("%Y-%m-%d"),
        "current": gs[-1]["my_rating"] + gs[-1]["rating_diff"],
    }


def analyse_tc(gs, label):
    min_n = 40 if len(gs) > 3000 else 20
    hour_bucket = lambda g: f"{(g['local'].hour // 3) * 3:02d}-{(g['local'].hour // 3) * 3 + 3:02d}"
    rd = lambda g: (
        "a: motstander 150+ høyere" if g["opp_rating"] - g["my_rating"] >= 150 else
        "b: 50-150 høyere" if g["opp_rating"] - g["my_rating"] >= 50 else
        "c: ±50" if abs(g["opp_rating"] - g["my_rating"]) < 50 else
        "d: 50-150 lavere" if g["my_rating"] - g["opp_rating"] < 150 else
        "e: 150+ lavere")
    length = lambda g: (
        "a: <=20 trekk" if len(g["move_list"]) <= 40 else
        "b: 21-40" if len(g["move_list"]) <= 80 else
        "c: 41-60" if len(g["move_list"]) <= 120 else "d: 60+")
    recent = [g for g in gs if g["local"].year >= gs[-1]["local"].year - 1]
    return {
        "label": label,
        "overall": agg(gs),
        "recent_2y": agg(recent),
        "by_color": group(gs, lambda g: g["color"]),
        "by_year": dict(sorted(group(gs, lambda g: g["local"].year).items())),
        "rating": rating_history(gs),
        "by_hour": dict(sorted(group(gs, hour_bucket).items())),
        "by_weekday": dict(sorted(group(gs, lambda g: g["local"].strftime("%u %a")).items())),
        "by_rating_gap": dict(sorted(group(gs, rd).items())),
        "by_length": dict(sorted(group(gs, length).items())),
        "time": time_stats(gs),
        "sessions": sessions(gs),
        "openings": openings(gs, min_n),
        "openings_recent": openings(recent, max(15, min_n // 3)),
    }


def main():
    games = load_games()
    OUT.mkdir(parents=True, exist_ok=True)
    result = {"n_standard": len(games)}
    for tc, label in MAIN_TC.items():
        gs = [g for g in games if g["tc"] == tc and g["rated"]]
        result[tc] = analyse_tc(gs, label)
    (OUT / "stats.json").write_text(json.dumps(result, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    print(json.dumps(result, indent=1, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
