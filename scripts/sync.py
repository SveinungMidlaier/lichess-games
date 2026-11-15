#!/usr/bin/env python3
"""Henter nye Lichess-partier for en bruker og legger dem til i data/<år>.ndjson.

Første kjøring henter hele historikken. Deretter bare partier etter siste lagrede.
Valgfri env LICHESS_TOKEN (ingen scopes trengs) gir raskere eksport.
"""
import json
import os
import pathlib
import sys
import time
import urllib.request
from datetime import datetime, timezone

USER = os.environ.get("LICHESS_USER", "Tafsle")
TOKEN = os.environ.get("LICHESS_TOKEN", "").strip()
ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
STATE = DATA / "state.json"


def load_since() -> int:
    if STATE.exists():
        return int(json.loads(STATE.read_text())["last_created_at"]) + 1
    return 0


def main() -> int:
    DATA.mkdir(exist_ok=True)
    since = load_since()
    params = (
        f"since={since}&sort=dateAsc&opening=true&clocks=true&evals=true"
        "&accuracy=true&pgnInJson=true&moves=true"
    )
    url = f"https://lichess.org/api/games/user/{USER}?{params}"
    headers = {"Accept": "application/x-ndjson", "User-Agent": f"lichess-sync/{USER}"}
    if TOKEN:
        headers["Authorization"] = f"Bearer {TOKEN}"

    req = urllib.request.Request(url, headers=headers)
    count, last = 0, since - 1 if since else 0
    handles = {}
    try:
        with urllib.request.urlopen(req, timeout=600) as resp:
            for raw in resp:
                line = raw.decode("utf-8").strip()
                if not line:
                    continue
                g = json.loads(line)
                year = datetime.fromtimestamp(g["createdAt"] / 1000, timezone.utc).year
                if year not in handles:
                    handles[year] = open(DATA / f"{year}.ndjson", "a", encoding="utf-8")
                handles[year].write(line + "\n")
                last = max(last, g["createdAt"])
                count += 1
                if count % 1000 == 0:
                    print(f"{count} partier ...", flush=True)
    finally:
        for h in handles.values():
            h.close()

    if count:
        STATE.write_text(json.dumps({
            "user": USER,
            "last_created_at": last,
            "last_sync": int(time.time() * 1000),
        }, indent=2) + "\n")
    print(f"Ferdig: {count} nye partier for {USER}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
