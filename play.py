#!/usr/bin/env python3
"""Play chess against the AI.

    python3 play.py                         # window (needs pygame)
    python3 play.py --color black --level hard
    python3 play.py --text                  # in the terminal, no pygame needed
"""
import argparse
import sys

from ai import LEVELS, Searcher
from chess_engine import BLACK, WHITE, Board, IllegalMove

GLYPHS = dict(zip("KQRBNPkqrbnp", "♔♕♖♗♘♙♚♛♜♝♞♟"))


def render(board, flipped):
    rows = range(8) if not flipped else range(7, -1, -1)
    cols = list(range(8)) if not flipped else list(range(7, -1, -1))
    lines = []
    for row in rows:
        cells = []
        for col in cols:
            p = board.board[21 + row * 10 + col]
            cells.append(GLYPHS.get(p, "·"))
        lines.append(f"{8 - row} " + " ".join(cells))
    files = "abcdefgh" if not flipped else "hgfedcba"
    lines.append("  " + " ".join(files))
    return "\n".join(lines)


def play_text(human, level):
    board = Board()
    print(f"You are {'White' if human == WHITE else 'Black'} at {level} level.")
    print("Type moves like e4, Nf3, O-O, exd5, e8=Q or e2e4. Commands: undo, quit.\n")
    while True:
        print(render(board, human == BLACK))
        result = board.result()
        if result:
            print(f"\nGame over: {result[0]} ({result[1]})")
            return
        if board.turn == human:
            if board.in_check():
                print("Check!")
            try:
                text = input("\nyour move> ").strip()
            except EOFError:
                return
            if text in ("quit", "exit", "q"):
                return
            if text == "undo":
                for _ in range(2):
                    if board.moves:
                        board.pop()
                continue
            try:
                board.push(board.parse_move(text))
            except IllegalMove as exc:
                print(exc)
        else:
            print("\nAI thinking...")
            seconds, depth, noise = LEVELS[level]
            move, _, _ = Searcher(seconds, depth, noise).search(board)
            print(f"AI plays {board.san(move)}\n")
            board.push(move)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Play chess against the AI.")
    parser.add_argument("--color", choices=["white", "black"], default="white",
                        help="the side you play (default: white)")
    parser.add_argument("--level", choices=list(LEVELS), default="medium",
                        help="AI strength (default: medium)")
    parser.add_argument("--text", action="store_true", help="play in the terminal")
    args = parser.parse_args(argv)
    human = WHITE if args.color == "white" else BLACK

    if not args.text:
        try:
            from gui import ChessApp
        except ImportError:
            print("pygame isn't installed, so playing in the terminal instead.\n"
                  "For the window: pip install -r requirements.txt\n", file=sys.stderr)
        else:
            ChessApp(human, args.level).run()
            return
    play_text(human, args.level)


if __name__ == "__main__":
    main()
