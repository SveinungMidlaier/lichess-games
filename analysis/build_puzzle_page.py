#!/usr/bin/env python3
"""Bygger oppgavesiden: analysis/puzzle_page.html + out/puzzles.json + brikker -> out/puzzles.html.

Bruk: python analysis/build_puzzle_page.py [utfil]
Brikkene er cburnett-settet som følger med python-chess (chess.svg).
"""
import base64
import json
import pathlib
import sys

import chess.svg

HERE = pathlib.Path(__file__).resolve().parent
OUT = HERE / "out"


def main():
    dest = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else OUT / "puzzles.html"
    pieces = {}
    for sym, svg in chess.svg.PIECES.items():
        full = ('<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
                f'viewBox="0 0 45 45">{svg}</svg>')
        pieces[sym] = "data:image/svg+xml;base64," + base64.b64encode(full.encode()).decode()
    puzzles = (OUT / "puzzles.json").read_text(encoding="utf-8")

    def safe(s):
        return s.replace("</", "<\\/")

    page = (HERE / "puzzle_page.html").read_text(encoding="utf-8")
    page = page.replace("__PUZZLES__", safe(puzzles)).replace("__PIECES__", safe(json.dumps(pieces)))
    dest.write_text(page, encoding="utf-8")
    print(dest, f"{len(page) / 1e6:.2f} MB")


if __name__ == "__main__":
    main()
