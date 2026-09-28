"""The computer player: negamax search with alpha-beta pruning.

How it picks a move:
1. Iterative deepening: search 1 move deep, then 2, then 3... until the time
   budget runs out, keeping the best move from the last finished depth.
2. Alpha-beta pruning skips lines that can't change the result. It works best
   when good moves are tried first, so moves are ordered: the best move from
   the previous search (transposition table), then captures of valuable
   pieces by cheap ones (MVV-LVA), then the rest.
3. At the end of each line, a quiescence search keeps playing out captures,
   so the AI doesn't stop right before losing its queen.
4. Positions are scored by material plus piece-square tables, which reward
   centralized knights, advanced pawns, a sheltered king and so on.
"""
import random
import time

from chess_engine import BLACK, BOARD_SQUARES, EMPTY, WHITE

VALUES = {"P": 100, "N": 320, "B": 330, "R": 500, "Q": 900, "K": 0}
MATE = 100_000

# Piece-square tables from White's point of view, a8 first (row 0) to h1.
# Values from Tomasz Michniewski's "Simplified Evaluation Function".
PST = {
    "P": [0, 0, 0, 0, 0, 0, 0, 0,
          50, 50, 50, 50, 50, 50, 50, 50,
          10, 10, 20, 30, 30, 20, 10, 10,
          5, 5, 10, 25, 25, 10, 5, 5,
          0, 0, 0, 20, 20, 0, 0, 0,
          5, -5, -10, 0, 0, -10, -5, 5,
          5, 10, 10, -20, -20, 10, 10, 5,
          0, 0, 0, 0, 0, 0, 0, 0],
    "N": [-50, -40, -30, -30, -30, -30, -40, -50,
          -40, -20, 0, 0, 0, 0, -20, -40,
          -30, 0, 10, 15, 15, 10, 0, -30,
          -30, 5, 15, 20, 20, 15, 5, -30,
          -30, 0, 15, 20, 20, 15, 0, -30,
          -30, 5, 10, 15, 15, 10, 5, -30,
          -40, -20, 0, 5, 5, 0, -20, -40,
          -50, -40, -30, -30, -30, -30, -40, -50],
    "B": [-20, -10, -10, -10, -10, -10, -10, -20,
          -10, 0, 0, 0, 0, 0, 0, -10,
          -10, 0, 5, 10, 10, 5, 0, -10,
          -10, 5, 5, 10, 10, 5, 5, -10,
          -10, 0, 10, 10, 10, 10, 0, -10,
          -10, 10, 10, 10, 10, 10, 10, -10,
          -10, 5, 0, 0, 0, 0, 5, -10,
          -20, -10, -10, -10, -10, -10, -10, -20],
    "R": [0, 0, 0, 0, 0, 0, 0, 0,
          5, 10, 10, 10, 10, 10, 10, 5,
          -5, 0, 0, 0, 0, 0, 0, -5,
          -5, 0, 0, 0, 0, 0, 0, -5,
          -5, 0, 0, 0, 0, 0, 0, -5,
          -5, 0, 0, 0, 0, 0, 0, -5,
          -5, 0, 0, 0, 0, 0, 0, -5,
          0, 0, 0, 5, 5, 0, 0, 0],
    "Q": [-20, -10, -10, -5, -5, -10, -10, -20,
          -10, 0, 0, 0, 0, 0, 0, -10,
          -10, 0, 5, 5, 5, 5, 0, -10,
          -5, 0, 5, 5, 5, 5, 0, -5,
          0, 0, 5, 5, 5, 5, 0, -5,
          -10, 5, 5, 5, 5, 5, 0, -10,
          -10, 0, 5, 0, 0, 0, 0, -10,
          -20, -10, -10, -5, -5, -10, -10, -20],
    "K": [-30, -40, -40, -50, -50, -40, -40, -30,
          -30, -40, -40, -50, -50, -40, -40, -30,
          -30, -40, -40, -50, -50, -40, -40, -30,
          -30, -40, -40, -50, -50, -40, -40, -30,
          -20, -30, -30, -40, -40, -30, -30, -20,
          -10, -20, -20, -20, -20, -20, -20, -10,
          20, 20, 0, 0, 0, 0, 20, 20,
          20, 30, 10, 0, 0, 10, 30, 20],
    # In the endgame the king should walk to the center instead of hiding.
    "K_END": [-50, -40, -30, -20, -20, -30, -40, -50,
              -30, -20, -10, 0, 0, -10, -20, -30,
              -30, -10, 20, 30, 30, 20, -10, -30,
              -30, -10, 30, 40, 40, 30, -10, -30,
              -30, -10, 30, 40, 40, 30, -10, -30,
              -30, -10, 20, 30, 30, 20, -10, -30,
              -30, -30, 0, 0, 0, 0, -30, -30,
              -50, -30, -30, -30, -30, -30, -30, -50],
}

# Precompute: SCORE[piece][square] = value + table bonus, positive for White.
SCORE = {}
for kind, table in PST.items():
    for color_piece, sign in ((kind[0], 1), (kind[0].lower(), -1)):
        key = color_piece + ("_END" if kind == "K_END" else "")
        SCORE[key] = {}
        for i, sq in enumerate(BOARD_SQUARES):
            row, col = divmod(i, 8)
            index = i if sign == 1 else (7 - row) * 8 + col   # mirror for Black
            SCORE[key][sq] = sign * (VALUES[kind[0]] + table[index])

LEVELS = {
    # name: (seconds to think, max depth, random noise in centipawns)
    "easy": (0.3, 1, 120),
    "medium": (1.0, 4, 15),
    "hard": (3.0, 8, 0),
}


class Timeout(Exception):
    pass


def evaluate(board):
    """Score from the side to move's point of view, in centipawns."""
    b = board.board
    queens = 0
    minors = 0
    total = 0
    for sq in BOARD_SQUARES:
        p = b[sq]
        if p == EMPTY:
            continue
        if p in "Qq":
            queens += 1
        elif p in "RNBrnb":
            minors += 1
        if p not in "Kk":
            total += SCORE[p][sq]
    endgame = queens == 0 or (queens <= 2 and minors <= 2)
    suffix = "_END" if endgame else ""
    total += SCORE["K" + suffix][board.kings[WHITE]] + SCORE["k" + suffix][board.kings[BLACK]]
    return total if board.turn == WHITE else -total


class Searcher:
    def __init__(self, seconds=1.0, max_depth=64, noise=0, rng=None):
        self.seconds = seconds
        self.max_depth = max_depth
        self.noise = noise
        self.rng = rng or random.Random()
        self.table = {}          # position hash -> (depth, score, flag, best move)
        self.nodes = 0
        self.deadline = 0.0
        self.stop = False        # set from another thread to abort early

    def order(self, board, moves, best=None):
        b = board.board

        def key(move):
            if move == best:
                return -10_000
            frm, to, promo = move
            score = 0
            victim = b[to]
            if victim != EMPTY:
                score -= 10 * VALUES[victim.upper()] - VALUES[b[frm].upper()]
            if promo:
                score -= VALUES[promo]
            return score
        return sorted(moves, key=key)

    def check_time(self):
        self.nodes += 1
        if self.nodes & 1023 == 0 and (time.time() > self.deadline or self.stop):
            raise Timeout

    def quiesce(self, board, alpha, beta, ply):
        self.check_time()
        stand = evaluate(board)
        if stand >= beta:
            return beta
        alpha = max(alpha, stand)
        me = board.turn
        for move in self.order(board, board.pseudo_moves(captures_only=True)):
            board.push(move)
            if board.in_check(me):
                board.pop()
                continue
            score = -self.quiesce(board, -beta, -alpha, ply + 1)
            board.pop()
            if score >= beta:
                return beta
            alpha = max(alpha, score)
        return alpha

    def negamax(self, board, depth, alpha, beta, ply):
        self.check_time()
        # Draw by 50-move rule or repetition. A repeat can only happen since the
        # last capture or pawn move, so only those positions are checked.
        if ply and (board.halfmove >= 100
                    or board.hash in board.hashes[-board.halfmove - 1:-1]):
            return 0
        in_check = board.in_check()
        if in_check:
            depth += 1                                 # look deeper when in check
        if depth <= 0:
            return self.quiesce(board, alpha, beta, ply)

        entry = self.table.get(board.hash)
        best_move = None
        if entry:
            e_depth, e_score, e_flag, best_move = entry
            if ply and e_depth >= depth:
                if e_flag == 0:
                    return e_score
                if e_flag == 1 and e_score >= beta:
                    return e_score
                if e_flag == -1 and e_score <= alpha:
                    return e_score

        original_alpha = alpha
        me = board.turn
        best_score = -MATE - 1
        legal = 0
        for move in self.order(board, board.pseudo_moves(), best_move):
            board.push(move)
            if board.in_check(me):
                board.pop()
                continue
            legal += 1
            score = -self.negamax(board, depth - 1, -beta, -alpha, ply + 1)
            board.pop()
            if score > best_score:
                best_score, best_move = score, move
            alpha = max(alpha, score)
            if alpha >= beta:
                break
        if legal == 0:
            return -MATE + ply if in_check else 0      # checkmate or stalemate

        flag = 1 if best_score >= beta else -1 if best_score <= original_alpha else 0
        self.table[board.hash] = (depth, best_score, flag, best_move)
        return best_score

    def root(self, board, depth):
        """Score every root move at this depth; return [(score, move)] best first."""
        me = board.turn
        scored = []
        best = self.table.get(board.hash, (0, 0, 0, None))[3]
        alpha = -MATE - 1
        for move in self.order(board, board.pseudo_moves(), best):
            board.push(move)
            if board.in_check(me):
                board.pop()
                continue
            # With noise, every root move needs an exact score, so no pruning.
            beta = MATE + 1 if self.noise else -alpha
            score = -self.negamax(board, depth - 1, -MATE - 1, beta, 1)
            board.pop()
            scored.append((score, move))
            if not self.noise:
                alpha = max(alpha, score)
        scored.sort(key=lambda sm: -sm[0])
        if scored:
            self.table[board.hash] = (depth, scored[0][0], 0, scored[0][1])
        return scored

    def search(self, board):
        """Return (best move, score, depth reached). board is left unchanged."""
        board = board.copy()
        self.deadline = time.time() + self.seconds
        self.nodes = 0
        legal = board.legal_moves()
        if not legal:
            return None, 0, 0
        if len(legal) == 1:
            return legal[0], 0, 0
        results, depth_done = [(0, legal[0])], 0
        for depth in range(1, self.max_depth + 1):
            try:
                results = self.root(board, depth)
                depth_done = depth
            except Timeout:
                break
            if abs(results[0][0]) > MATE - 100:    # found a forced mate
                break
        score, move = results[0]
        if self.noise:
            # Weaker levels: pick among moves close to the best, at random.
            close = [m for s, m in results if s >= score - self.noise]
            move = self.rng.choice(close)
        return move, score, depth_done


def best_move(board, level="medium", rng=None):
    seconds, depth, noise = LEVELS[level]
    move, _, _ = Searcher(seconds, depth, noise, rng).search(board)
    return move
