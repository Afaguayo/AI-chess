"""Chess rules: board, legal moves, check, checkmate, draws, FEN and SAN.

The board is a 10x12 "mailbox": 120 cells, where the 8x8 board sits in the
middle and the border cells are marked off-board. That makes move generation
simple, because stepping off the edge always lands on an 'x' cell.

    index 21 = a8 ... 28 = h8
    index 91 = a1 ... 98 = h1

Pieces are letters: uppercase for White (PNBRQK), lowercase for Black,
'.' for an empty square and 'x' for off-board.

A move is a tuple (from_square, to_square, promotion), where promotion is ''
or the piece letter a pawn becomes ('Q', 'R', 'B', 'N', always uppercase).
"""
import random

WHITE, BLACK = "w", "b"
EMPTY, OFF = ".", "x"

N, S, E, W = -10, 10, 1, -1
KNIGHT_STEPS = (-21, -19, -12, -8, 8, 12, 19, 21)
BISHOP_DIRS = (N + E, N + W, S + E, S + W)
ROOK_DIRS = (N, S, E, W)
KING_DIRS = BISHOP_DIRS + ROOK_DIRS

START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
FILES = "abcdefgh"

# Castling rights lost when a piece moves from, or is captured on, a square.
RIGHTS_TOUCHED = {95: "KQ", 98: "K", 91: "Q", 25: "kq", 28: "k", 21: "q"}


def square(name):
    """'e4' -> mailbox index."""
    file = FILES.index(name[0])
    rank = int(name[1])
    return 21 + file + (8 - rank) * 10


def square_name(index):
    """mailbox index -> 'e4'."""
    row, col = divmod(index - 21, 10)
    return FILES[col] + str(8 - row)


def color_of(piece):
    if piece in (EMPTY, OFF):
        return None
    return WHITE if piece.isupper() else BLACK


def other(color):
    return BLACK if color == WHITE else WHITE


BOARD_SQUARES = [21 + col + row * 10 for row in range(8) for col in range(8)]

# Zobrist hashing: a random number per (piece, square), per castling state,
# per en-passant file and for the side to move. XOR-ing them gives a
# position key that can be updated move by move; used for repetition and by
# the AI's transposition table.
_rng = random.Random(2024)
ZOBRIST_PIECE = {p: {sq: _rng.getrandbits(64) for sq in BOARD_SQUARES} for p in "PNBRQKpnbrqk"}
ZOBRIST_CASTLE = {c: _rng.getrandbits(64) for c in "KQkq"}
ZOBRIST_EP = {f: _rng.getrandbits(64) for f in range(8)}
ZOBRIST_BLACK = _rng.getrandbits(64)


class IllegalMove(ValueError):
    pass


class Board:
    def __init__(self, fen=START_FEN):
        self.set_fen(fen)

    # ------------------------------------------------------------ FEN

    def set_fen(self, fen):
        parts = fen.split()
        if len(parts) < 4:
            raise ValueError(f"bad FEN: {fen!r}")
        rows = parts[0].split("/")
        if len(rows) != 8:
            raise ValueError(f"bad FEN board: {parts[0]!r}")
        self.board = [OFF] * 120
        for row, text in enumerate(rows):
            col = 0
            for ch in text:
                if ch.isdigit():
                    for _ in range(int(ch)):
                        self.board[21 + row * 10 + col] = EMPTY
                        col += 1
                elif ch in "PNBRQKpnbrqk":
                    self.board[21 + row * 10 + col] = ch
                    col += 1
                else:
                    raise ValueError(f"bad FEN piece: {ch!r}")
            if col != 8:
                raise ValueError(f"bad FEN row: {text!r}")
        self.turn = parts[1]
        self.castling = "" if parts[2] == "-" else parts[2]
        self.ep = None if parts[3] == "-" else square(parts[3])
        self.halfmove = int(parts[4]) if len(parts) > 4 else 0
        self.fullmove = int(parts[5]) if len(parts) > 5 else 1
        self.kings = {color_of(p): sq for sq in BOARD_SQUARES
                      for p in [self.board[sq]] if p in "Kk"}
        if len(self.kings) != 2:
            raise ValueError("FEN needs exactly one king per side")
        self.history = []      # undo records, one per move made
        self.moves = []        # moves made, in order
        self.hash = self._full_hash()
        self.hashes = [self.hash]

    def fen(self):
        rows = []
        for row in range(8):
            text, empty = "", 0
            for col in range(8):
                p = self.board[21 + row * 10 + col]
                if p == EMPTY:
                    empty += 1
                else:
                    text += (str(empty) if empty else "") + p
                    empty = 0
            rows.append(text + (str(empty) if empty else ""))
        ep = square_name(self.ep) if self.ep else "-"
        return (f"{'/'.join(rows)} {self.turn} {self.castling or '-'} {ep} "
                f"{self.halfmove} {self.fullmove}")

    def copy(self):
        clone = Board.__new__(Board)
        clone.board = self.board[:]
        clone.turn, clone.castling, clone.ep = self.turn, self.castling, self.ep
        clone.halfmove, clone.fullmove = self.halfmove, self.fullmove
        clone.kings = dict(self.kings)
        clone.history = list(self.history)
        clone.moves = list(self.moves)
        clone.hash, clone.hashes = self.hash, list(self.hashes)
        return clone

    def _full_hash(self):
        h = 0
        for sq in BOARD_SQUARES:
            p = self.board[sq]
            if p != EMPTY:
                h ^= ZOBRIST_PIECE[p][sq]
        for c in self.castling:
            h ^= ZOBRIST_CASTLE[c]
        if self.ep:
            h ^= ZOBRIST_EP[(self.ep - 21) % 10]
        if self.turn == BLACK:
            h ^= ZOBRIST_BLACK
        return h

    # ---------------------------------------------------------- attacks

    def is_attacked(self, sq, by):
        """True if color `by` attacks square sq."""
        b = self.board
        if by == WHITE:
            pawn, knight, bishop, rook, queen, king = "PNBRQK"
            if b[sq + 9] == pawn or b[sq + 11] == pawn:
                return True
        else:
            pawn, knight, bishop, rook, queen, king = "pnbrqk"
            if b[sq - 9] == pawn or b[sq - 11] == pawn:
                return True
        for step in KNIGHT_STEPS:
            if b[sq + step] == knight:
                return True
        for step in KING_DIRS:
            if b[sq + step] == king:
                return True
        for step in BISHOP_DIRS:
            t = sq + step
            while b[t] == EMPTY:
                t += step
            if b[t] == bishop or b[t] == queen:
                return True
        for step in ROOK_DIRS:
            t = sq + step
            while b[t] == EMPTY:
                t += step
            if b[t] == rook or b[t] == queen:
                return True
        return False

    def in_check(self, color=None):
        color = color or self.turn
        return self.is_attacked(self.kings[color], other(color))

    # ------------------------------------------------------ move generation

    def pseudo_moves(self, captures_only=False):
        """Moves that follow piece rules but may leave the king in check."""
        b, me = self.board, self.turn
        moves = []
        add = moves.append
        enemy = str.islower if me == WHITE else str.isupper
        for sq in BOARD_SQUARES:
            p = b[sq]
            if p == EMPTY or color_of(p) != me:
                continue
            kind = p.upper()
            if kind == "P":
                self._pawn_moves(sq, captures_only, add)
            elif kind == "N" or kind == "K":
                for step in (KNIGHT_STEPS if kind == "N" else KING_DIRS):
                    t = sq + step
                    target = b[t]
                    if target == EMPTY:
                        if not captures_only:
                            add((sq, t, ""))
                    elif target != OFF and enemy(target):
                        add((sq, t, ""))
            else:
                dirs = BISHOP_DIRS if kind == "B" else ROOK_DIRS if kind == "R" else KING_DIRS
                for step in dirs:
                    t = sq + step
                    while b[t] == EMPTY:
                        if not captures_only:
                            add((sq, t, ""))
                        t += step
                    if b[t] != OFF and enemy(b[t]):
                        add((sq, t, ""))
        if not captures_only:
            self._castle_moves(add)
        return moves

    def _pawn_moves(self, sq, captures_only, add):
        b = self.board
        if self.turn == WHITE:
            fwd, start_row, last_row, enemy = N, 6, 0, str.islower
        else:
            fwd, start_row, last_row, enemy = S, 1, 7, str.isupper
        row = (sq - 21) // 10

        def push(to):
            if (to - 21) // 10 == last_row:
                for promo in "QRBN":
                    add((sq, to, promo))
            else:
                add((sq, to, ""))

        one = sq + fwd
        if b[one] == EMPTY:
            last = (one - 21) // 10 == last_row
            if not captures_only or last:   # promotions count as "noisy"
                push(one)
            if not captures_only and row == start_row and b[one + fwd] == EMPTY:
                add((sq, one + fwd, ""))
        for side in (E, W):
            t = one + side
            if b[t] not in (EMPTY, OFF) and enemy(b[t]):
                push(t)
            elif t == self.ep:
                add((sq, t, ""))

    def _castle_moves(self, add):
        b, rights = self.board, self.castling
        if self.turn == WHITE:
            king, rook, home, k_side, q_side = "K", "R", 95, "K", "Q"
        else:
            king, rook, home, k_side, q_side = "k", "r", 25, "k", "q"
        if b[home] != king:
            return
        them = other(self.turn)
        if k_side in rights and b[home + 1] == b[home + 2] == EMPTY and b[home + 3] == rook:
            if not any(self.is_attacked(home + i, them) for i in (0, 1, 2)):
                add((home, home + 2, ""))
        if (q_side in rights and b[home - 1] == b[home - 2] == b[home - 3] == EMPTY
                and b[home - 4] == rook):
            if not any(self.is_attacked(home - i, them) for i in (0, 1, 2)):
                add((home, home - 2, ""))

    def legal_moves(self):
        legal = []
        me = self.turn
        for move in self.pseudo_moves():
            self.push(move)
            if not self.in_check(me):
                legal.append(move)
            self.pop()
        return legal

    # ------------------------------------------------------ make / unmake

    def push(self, move):
        """Make a move (assumed pseudo-legal). Undo with pop()."""
        frm, to, promo = move
        b = self.board
        piece = b[frm]
        captured = b[to]
        record = (move, captured, self.castling, self.ep, self.halfmove, self.hash, None)
        h = self.hash ^ ZOBRIST_PIECE[piece][frm]

        if captured != EMPTY:
            h ^= ZOBRIST_PIECE[captured][to]

        kind = piece.upper()
        # En passant: the captured pawn is beside the target, not on it.
        if kind == "P" and to == self.ep:
            behind = to + (S if piece == "P" else N)
            captured = b[behind]
            h ^= ZOBRIST_PIECE[captured][behind]
            b[behind] = EMPTY
            record = record[:1] + (EMPTY,) + record[2:6] + (behind,)
        # Castling: move the rook too.
        if kind == "K" and abs(to - frm) == 2:
            rook_from, rook_to = (frm + 3, frm + 1) if to > frm else (frm - 4, frm - 1)
            rook = b[rook_from]
            b[rook_to], b[rook_from] = rook, EMPTY
            h ^= ZOBRIST_PIECE[rook][rook_from] ^ ZOBRIST_PIECE[rook][rook_to]
        if kind == "K":
            self.kings[color_of(piece)] = to

        placed = (promo if piece.isupper() else promo.lower()) if promo else piece
        b[to], b[frm] = placed, EMPTY
        h ^= ZOBRIST_PIECE[placed][to]

        for c in self.castling:
            h ^= ZOBRIST_CASTLE[c]
        lost = RIGHTS_TOUCHED.get(frm, "") + RIGHTS_TOUCHED.get(to, "")
        if lost:
            self.castling = "".join(c for c in self.castling if c not in lost)
        for c in self.castling:
            h ^= ZOBRIST_CASTLE[c]

        if self.ep:
            h ^= ZOBRIST_EP[(self.ep - 21) % 10]
        self.ep = (frm + to) // 2 if kind == "P" and abs(to - frm) == 20 else None
        if self.ep:
            h ^= ZOBRIST_EP[(self.ep - 21) % 10]

        self.halfmove = 0 if kind == "P" or captured != EMPTY else self.halfmove + 1
        if self.turn == BLACK:
            self.fullmove += 1
        self.turn = other(self.turn)
        h ^= ZOBRIST_BLACK

        self.hash = h
        self.history.append(record)
        self.moves.append(move)
        self.hashes.append(h)

    def pop(self):
        """Undo the last move."""
        move, captured, castling, ep, halfmove, h, ep_square = self.history.pop()
        self.moves.pop()
        self.hashes.pop()
        frm, to, promo = move
        b = self.board
        self.turn = other(self.turn)
        if self.turn == BLACK:
            self.fullmove -= 1
        piece = b[to]
        if promo:
            piece = "P" if piece.isupper() else "p"
        b[frm], b[to] = piece, captured
        if ep_square:
            b[ep_square] = "p" if piece == "P" else "P"
        if piece in "Kk":
            self.kings[color_of(piece)] = frm
            if abs(to - frm) == 2:
                rook_from, rook_to = (frm + 3, frm + 1) if to > frm else (frm - 4, frm - 1)
                b[rook_from], b[rook_to] = b[rook_to], EMPTY
        self.castling, self.ep, self.halfmove, self.hash = castling, ep, halfmove, h
        return move

    def push_legal(self, move):
        if move not in self.legal_moves():
            raise IllegalMove(f"illegal move: {self.uci(move)}")
        self.push(move)

    # ----------------------------------------------------------- game end

    def repetitions(self):
        """How many times the current position has occurred."""
        return self.hashes.count(self.hash)

    def insufficient_material(self):
        pieces = [(p, sq) for sq in BOARD_SQUARES for p in [self.board[sq]]
                  if p not in (EMPTY, "K", "k")]
        if not pieces:
            return True
        if len(pieces) == 1 and pieces[0][0] in "NBnb":
            return True
        if all(p in "Bb" for p, _ in pieces):   # only bishops, all on one color
            colors = {((sq - 21) // 10 + (sq - 21) % 10) % 2 for _, sq in pieces}
            return len(colors) == 1
        return False

    def result(self):
        """None while the game is on, else (score, reason).

        score is '1-0', '0-1' or '1/2-1/2'.
        """
        if not self.legal_moves():
            if self.in_check():
                return ("0-1" if self.turn == WHITE else "1-0"), "checkmate"
            return "1/2-1/2", "stalemate"
        if self.halfmove >= 100:
            return "1/2-1/2", "50-move rule"
        if self.repetitions() >= 3:
            return "1/2-1/2", "threefold repetition"
        if self.insufficient_material():
            return "1/2-1/2", "insufficient material"
        return None

    # ---------------------------------------------------------- notation

    @staticmethod
    def uci(move):
        frm, to, promo = move
        return square_name(frm) + square_name(to) + promo.lower()

    def san(self, move):
        """Standard algebraic notation for a legal move, e.g. Nbd7, exd6+, O-O."""
        frm, to, promo = move
        piece = self.board[frm].upper()
        if piece == "K" and abs(to - frm) == 2:
            text = "O-O" if to > frm else "O-O-O"
        else:
            capture = self.board[to] != EMPTY or (piece == "P" and to == self.ep)
            if piece == "P":
                text = (square_name(frm)[0] + "x" if capture else "") + square_name(to)
                if promo:
                    text += "=" + promo
            else:
                rivals = [m[0] for m in self.legal_moves()
                          if m[1] == to and m[0] != frm and self.board[m[0]].upper() == piece]
                hint = ""
                if rivals:
                    same_file = any(r % 10 == frm % 10 for r in rivals)
                    same_rank = any(r // 10 == frm // 10 for r in rivals)
                    name = square_name(frm)
                    if not same_file:
                        hint = name[0]
                    elif not same_rank:
                        hint = name[1]
                    else:
                        hint = name
                text = piece + hint + ("x" if capture else "") + square_name(to)
        self.push(move)
        if self.in_check():
            text += "#" if not self.legal_moves() else "+"
        self.pop()
        return text

    def parse_move(self, text):
        """Accept SAN ('Nf3', 'exd5', 'O-O', 'e8=Q') or UCI ('g1f3', 'e7e8q')."""
        text = text.strip()
        legal = self.legal_moves()
        clean = text.replace("0", "O").rstrip("+#!?")
        for move in legal:
            if self.uci(move) == text.lower():
                return move
        for move in legal:
            if self.san(move).rstrip("+#") == clean:
                return move
        # forgive a missing '=' in promotions: e8Q
        for move in legal:
            if self.san(move).rstrip("+#").replace("=", "") == clean.replace("=", ""):
                return move
        raise IllegalMove(f"not a legal move here: {text!r}")

    def __str__(self):
        rows = []
        for row in range(8):
            cells = [self.board[21 + row * 10 + col] for col in range(8)]
            rows.append(f"{8 - row} " + " ".join(cells))
        rows.append("  a b c d e f g h")
        return "\n".join(rows)
