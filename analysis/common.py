"""Felles innlasting av partier fra data/<år>.ndjson (kun standard sjakk, dedupliserert)."""
import glob
import json
import math
import pathlib
from datetime import datetime, timedelta, timezone

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT = ROOT / "analysis" / "out"
ME = "tafsle"


def oslo_time(ms: int) -> datetime:
    """UTC-ms -> norsk lokaltid (EU-sommertid: siste søndag i mars/oktober kl. 01 UTC)."""
    t = datetime.fromtimestamp(ms / 1000, timezone.utc)

    def last_sunday(year, month):
        d = datetime(year, month + 1, 1, 1, tzinfo=timezone.utc) - timedelta(days=1)
        return d - timedelta(days=(d.weekday() + 1) % 7)

    dst = last_sunday(t.year, 3) <= t < last_sunday(t.year, 10)
    return (t + timedelta(hours=2 if dst else 1)).replace(tzinfo=None)


def expected(my: int, opp: int) -> float:
    return 1 / (1 + 10 ** ((opp - my) / 400))


def load_games(standard_only: bool = True):
    """Returnerer liste med dicts, sortert etter tid, med ferdig utledede felt."""
    seen, games = set(), []
    for f in sorted(glob.glob(str(DATA / "*.ndjson"))):
        for line in open(f, encoding="utf-8"):
            g = json.loads(line)
            if g["id"] in seen:
                continue
            seen.add(g["id"])
            if standard_only and (g["variant"] != "standard" or "initialFen" in g):
                continue
            w, b = g["players"]["white"], g["players"]["black"]
            if w.get("user", {}).get("id") == ME:
                color, me, opp = "white", w, b
            elif b.get("user", {}).get("id") == ME:
                color, me, opp = "black", b, w
            else:
                continue
            if "rating" not in me or "rating" not in opp:
                continue  # f.eks. mot AI
            winner = g.get("winner")
            score = 0.5 if winner is None else (1.0 if winner == color else 0.0)
            clock = g.get("clock") or {}
            g.update(
                color=color,
                my_rating=me["rating"],
                opp_rating=opp["rating"],
                rating_diff=me.get("ratingDiff", 0),
                opp_name=opp.get("user", {}).get("name", "?"),
                score=score,
                exp=expected(me["rating"], opp["rating"]),
                tc=f"{clock.get('initial', 0)}+{clock.get('increment', 0)}",
                local=oslo_time(g["createdAt"]),
                move_list=g["moves"].split() if g.get("moves") else [],
            )
            games.append(g)
    games.sort(key=lambda g: g["createdAt"])
    return games


def win_pct(cp: float) -> float:
    """Lichess sin vinnersjanse-formel (0-100) fra centipawns."""
    return 50 + 50 * (2 / (1 + math.exp(-0.00368208 * cp)) - 1)
