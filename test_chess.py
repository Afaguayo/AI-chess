"""Tests for the chess rules, the AI and the window.

    python3 -m unittest -v            # everything (GUI tests skip without pygame)
    SLOW=1 python3 -m unittest -v     # also the deeper perft counts
"""
import os
import random
import unittest

from ai import Searcher, best_move, evaluate
from chess_engine import BLACK, START_FEN, WHITE, Board, IllegalMove, square

SLOW = bool(os.environ.get("SLOW"))


def perft(board, depth):
    """Count the positions reachable in exactly `depth` moves."""
    if depth == 0:
        return 1
    total = 0
    me = board.turn
    for move in board.pseudo_moves():
        board.push(move)
        if not board.in_check(me):
            total += perft(board, depth - 1)
        board.pop()
    return total


class PerftTests(unittest.TestCase):
    """Published move counts for well-known positions. If move generation has
    any bug (castling, en passant, promotion, pins, checks) these numbers
    come out wrong."""

    CASES = [
        ("start", START_FEN, [20, 400, 8902, 197281]),
        ("kiwipete", "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1",
         [48, 2039, 97862]),
        ("endgame", "8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1", [14, 191, 2812, 43238]),
        ("promotions", "r3k2r/Pppp1ppp/1b3nbN/nP6/BBP1P3/q4N2/Pp1P2PP/R2Q1RK1 w kq - 0 1",
         [6, 264, 9467]),
        ("tricky", "rnbq1k1r/pp1Pbppp/2p5/8/2B5/8/PPP1NnPP/RNBQK2R w KQ - 1 8", [44, 1486, 62379]),
    ]

    def test_perft(self):
        for name, fen, counts in self.CASES:
            limit = len(counts) if SLOW else min(len(counts), 3)
            board = Board(fen)
            for depth in range(1, limit + 1):
                with self.subTest(position=name, depth=depth):
                    self.assertEqual(perft(board, depth), counts[depth - 1])
            self.assertEqual(board.fen(), Board(fen).fen(), "push/pop must restore the board")


class RuleTests(unittest.TestCase):
    def play(self, board, *moves):
        for text in moves:
            board.push(board.parse_move(text))

    def test_fen_round_trip(self):
        for fen in [START_FEN, PerftTests.CASES[1][1], "8/8/8/8/8/8/8/K6k b - - 12 40"]:
            self.assertEqual(Board(fen).fen(), fen)

    def test_bad_fen(self):
        for fen in ["", "8/8/8 w - -", "rnbqkbnr/pppppppp/9/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
                    "8/8/8/8/8/8/8/8 w - - 0 1"]:
            with self.assertRaises(ValueError):
                Board(fen)

    def test_castling_both_sides(self):
        board = Board("r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1")
        self.play(board, "O-O")
        self.assertEqual(board.board[square("g1")], "K")
        self.assertEqual(board.board[square("f1")], "R")
        self.play(board, "O-O-O")
        self.assertEqual(board.board[square("c8")], "k")
        self.assertEqual(board.board[square("d8")], "r")
        self.assertEqual(board.castling, "")

    def test_cannot_castle_through_check(self):
        board = Board("4k3/8/8/8/8/8/5r2/4K2R w K - 0 1")   # rook on f2 guards f1
        self.assertNotIn("O-O", [board.san(m) for m in board.legal_moves()])

    def test_rook_move_loses_castling_right(self):
        board = Board("r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1")
        self.play(board, "Rh2", "Ra7")
        self.assertEqual(board.castling, "Qk")

    def test_capturing_rook_removes_right(self):
        board = Board("r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1")
        self.play(board, "Rxa8+")
        self.assertEqual(board.castling, "Kk")

    def test_en_passant(self):
        board = Board()
        self.play(board, "e4", "a6", "e5", "d5")
        self.assertEqual(board.san(board.parse_move("exd6")), "exd6")
        self.play(board, "exd6")
        self.assertEqual(board.board[square("d5")], ".")
        self.assertEqual(board.board[square("d6")], "P")
        board.pop()
        self.assertEqual(board.board[square("d5")], "p")

    def test_en_passant_expires(self):
        board = Board()
        self.play(board, "e4", "a6", "e5", "d5", "a3", "a5")
        with self.assertRaises(IllegalMove):
            board.parse_move("exd6")

    def test_promotion_choices(self):
        board = Board("8/P7/8/8/8/8/8/k6K w - - 0 1")
        promos = sorted(m[2] for m in board.legal_moves() if m[0] == square("a7"))
        self.assertEqual(promos, ["B", "N", "Q", "R"])
        self.play(board, "a8=N")
        self.assertEqual(board.board[square("a8")], "N")
        board.pop()
        self.assertEqual(board.board[square("a7")], "P")

    def test_pinned_piece_cannot_move(self):
        board = Board("4k3/4r3/8/8/8/8/4N3/4K3 w - - 0 1")
        self.assertFalse([m for m in board.legal_moves() if m[0] == square("e2")])

    def test_checkmate(self):
        board = Board()
        self.play(board, "f3", "e5", "g4", "Qh4#")
        self.assertEqual(board.result(), ("0-1", "checkmate"))

    def test_stalemate(self):
        board = Board("7k/5Q2/6K1/8/8/8/8/8 b - - 0 1")
        self.assertEqual(board.result(), ("1/2-1/2", "stalemate"))

    def test_insufficient_material(self):
        for fen, drawn in [("8/8/8/4k3/8/8/8/4K3 w - - 0 1", True),
                           ("8/8/8/4k3/8/8/8/3NK3 w - - 0 1", True),
                           ("8/8/8/4k3/8/8/2B5/3BK3 w - - 0 1", True),   # both bishops on light squares
                           ("8/8/8/4k3/8/8/8/2BBK3 w - - 0 1", False),    # opposite colors
                           ("8/8/8/4k3/8/8/8/3RK3 w - - 0 1", False)]:
            with self.subTest(fen=fen):
                self.assertEqual(Board(fen).insufficient_material(), drawn)

    def test_threefold_repetition(self):
        board = Board()
        self.play(board, "Nf3", "Nf6", "Ng1", "Ng8", "Nf3", "Nf6", "Ng1", "Ng8")
        self.assertEqual(board.result(), ("1/2-1/2", "threefold repetition"))

    def test_fifty_move_rule(self):
        board = Board("8/8/8/4k3/8/8/8/R3K3 w - - 99 80")
        self.play(board, "Ra2")
        self.assertEqual(board.result(), ("1/2-1/2", "50-move rule"))

    def test_hash_matches_after_moves(self):
        board = Board()
        rng = random.Random(1)
        for _ in range(60):
            moves = board.legal_moves()
            if not moves:
                break
            board.push(rng.choice(moves))
            self.assertEqual(board.hash, Board(board.fen()).hash)


class NotationTests(unittest.TestCase):
    def test_san_disambiguation(self):
        board = Board("4k3/8/8/8/8/8/8/1N2KN2 w - - 0 1")
        self.assertEqual(board.san(board.parse_move("b1d2")), "Nbd2")
        board = Board("4k3/8/8/8/R7/8/8/R3K3 w - - 0 1")
        self.assertEqual(board.san(board.parse_move("a1a2")), "R1a2")

    def test_san_check_and_mate_marks(self):
        board = Board("6k1/5ppp/8/8/8/8/8/4R1K1 w - - 0 1")
        self.assertEqual(board.san(board.parse_move("e1e8")), "Re8#")
        board = Board("4k3/8/8/8/8/8/8/R3K3 w - - 0 1")
        self.assertEqual(board.san(board.parse_move("a1a8")), "Ra8+")

    def test_parse_accepts_uci_and_san(self):
        board = Board()
        self.assertEqual(board.parse_move("g1f3"), board.parse_move("Nf3"))
        self.assertEqual(board.parse_move("e2e4"), (square("e2"), square("e4"), ""))
        with self.assertRaises(IllegalMove):
            board.parse_move("e5")
        with self.assertRaises(IllegalMove):
            board.push_legal((square("e2"), square("e5"), ""))

    def test_parse_castling_with_zeros(self):
        board = Board("4k3/8/8/8/8/8/8/4K2R w K - 0 1")
        self.assertEqual(board.san(board.parse_move("0-0")), "O-O")


class AITests(unittest.TestCase):
    def search(self, fen, seconds=2.0):
        return Searcher(seconds, 8).search(Board(fen))

    def test_finds_mate_in_one(self):
        move, score, _ = self.search("6k1/5ppp/8/8/8/8/8/4R1K1 w - - 0 1")
        self.assertEqual(Board("6k1/5ppp/8/8/8/8/8/4R1K1 w - - 0 1").san(move), "Re8#")
        self.assertGreater(score, 90_000)

    def test_scholars_mate(self):
        fen = "r1bqkb1r/pppp1ppp/2n2n2/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR w KQkq - 4 4"
        move, _, _ = self.search(fen)
        self.assertEqual(Board(fen).san(move), "Qxf7#")

    def test_finds_mate_in_two(self):  # a sacrifice, then back-rank mate
        fen = "r5k1/5ppp/8/8/8/8/1Q6/1R4K1 w - - 0 1"   # Qb8! Rxb8 Rxb8#
        move, score, _ = self.search(fen)
        self.assertGreater(score, 90_000)

    def test_wins_free_queen(self):
        fen = "4k3/8/8/3q4/8/8/3R4/3K4 w - - 0 1"
        move, _, _ = self.search(fen, 1.0)
        self.assertEqual(Board(fen).san(move), "Rxd5")

    def test_does_not_hang_queen(self):
        # Black's queen is attacked by a pawn; every sensible reply moves it.
        fen = "rnb1kbnr/pppp1ppp/8/4q3/3P4/8/PPP1PPPP/RNBQKBNR b KQkq - 0 3"
        move, _, _ = self.search(fen, 1.0)
        self.assertEqual(move[0], square("e5"))

    def test_no_move_when_game_over(self):
        move, _, _ = self.search("rnb1kbnr/pppp1ppp/8/4p3/5PPq/8/PPPPP2P/RNBQKBNR w KQkq - 1 3")
        self.assertIsNone(move)

    def test_search_leaves_board_unchanged(self):
        board = Board(PerftTests.CASES[1][1])
        before = board.fen()
        Searcher(0.3, 3).search(board)
        self.assertEqual(board.fen(), before)

    def test_evaluate_is_symmetric(self):
        board = Board()
        self.assertEqual(evaluate(board), 0)
        board = Board("4k3/8/8/8/8/8/8/3QK3 w - - 0 1")
        self.assertGreater(evaluate(board), 800)
        board.turn = BLACK
        self.assertLess(evaluate(board), -800)

    def test_every_level_returns_a_legal_move(self):
        board = Board()
        for level in ("easy", "medium", "hard"):
            with self.subTest(level=level):
                self.assertIn(best_move(board, level, random.Random(0)), board.legal_moves())

    def test_ai_vs_ai_game_is_legal(self):
        board = Board()
        rng = random.Random(3)
        for _ in range(40):
            if board.result():
                break
            move = Searcher(0.05, 2, 60, rng).search(board)[0]
            board.push_legal(move)


try:
    import pygame  # noqa: F401
    HAVE_PYGAME = True
except ImportError:
    HAVE_PYGAME = False


@unittest.skipUnless(HAVE_PYGAME, "pygame not installed")
class GuiTests(unittest.TestCase):
    """Drive the window through its event handlers with no screen attached."""

    @classmethod
    def setUpClass(cls):
        os.environ["SDL_VIDEODRIVER"] = "dummy"
        import gui
        cls.gui = gui

    def setUp(self):
        self.app = self.gui.ChessApp(WHITE, "easy")

    def tearDown(self):
        self.app.cancel_ai()

    def center(self, name):
        return self.app.square_rect(square(name)).center

    def wait_for_ai(self):
        while self.app.ai_thread:
            self.app.ai_thread.join()
            self.app.poll_ai()

    def test_click_to_move_then_ai_replies(self):
        self.app.on_mouse_down(self.center("e2"))
        self.app.on_mouse_up(self.center("e2"))
        self.app.on_mouse_down(self.center("e4"))
        self.assertEqual(self.app.san_moves, ["e4"])
        self.wait_for_ai()
        self.assertEqual(len(self.app.san_moves), 2)
        self.assertEqual(self.app.board.turn, WHITE)

    def test_drag_to_move(self):
        self.app.on_mouse_down(self.center("g1"))
        self.app.on_mouse_up(self.center("f3"))
        self.assertEqual(self.app.san_moves[0], "Nf3")

    def test_illegal_click_does_nothing(self):
        self.app.on_mouse_down(self.center("e2"))
        self.app.on_mouse_down(self.center("e5"))
        self.assertEqual(self.app.san_moves, [])

    def test_cannot_move_opponent_pieces(self):
        self.app.on_mouse_down(self.center("e7"))
        self.assertIsNone(self.app.selected)

    def test_undo_takes_back_both_moves(self):
        self.app.play(self.app.board.parse_move("e4"))
        self.wait_for_ai()
        self.app.undo()
        self.assertEqual(self.app.board.fen(), START_FEN)
        self.assertEqual(self.app.san_moves, [])

    def test_playing_black_makes_ai_move_first(self):
        app = self.gui.ChessApp(BLACK, "easy")
        self.assertTrue(app.flipped)
        while app.ai_thread:
            app.ai_thread.join()
            app.poll_ai()
        self.assertEqual(len(app.san_moves), 1)
        self.assertEqual(app.board.turn, BLACK)

    def test_promotion_picker(self):
        self.app.board = Board("4k3/1P6/8/8/8/8/8/4K3 w - - 0 1")
        self.app.on_mouse_down(self.center("b7"))
        self.app.on_mouse_down(self.center("b8"))
        self.assertEqual(self.app.promotion, (square("b7"), square("b8")))
        knight_rect = dict(self.app.promotion_rects())["N"]
        self.app.on_mouse_down(knight_rect.center)
        self.assertEqual(self.app.board.board[square("b8")], "N")

    def test_game_over_is_detected_and_drawn(self):
        self.app.board = Board("6k1/5ppp/8/8/8/8/8/4R1K1 w - - 0 1")
        self.app.play(self.app.board.parse_move("Re8#"))
        self.assertEqual(self.app.result, ("1-0", "checkmate"))
        self.assertEqual(self.app.status_text()[0], "You win by checkmate!")
        self.app.draw()                       # must not crash

    def test_buttons(self):
        by_text = {b.text: b for b in self.app.buttons}
        by_text["Hard"].action()
        self.assertEqual(self.app.level, "hard")
        by_text["Flip (F)"].action()
        self.assertTrue(self.app.flipped)
        by_text["New: Black"].action()
        self.assertEqual(self.app.human, BLACK)


if __name__ == "__main__":
    unittest.main()
