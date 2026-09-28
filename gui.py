"""Pygame window: play chess against the AI.

Mouse: click a piece then a square, or drag it.
Keys:  N new game   U undo   F flip board   1/2/3 easy/medium/hard   Esc quit
"""
import os
import threading

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
import pygame  # noqa: E402

from ai import LEVELS, Searcher  # noqa: E402
from chess_engine import BLACK, FILES, WHITE, Board, color_of  # noqa: E402

SQ = 80
BOARD_PX = SQ * 8
PANEL = 280
WIDTH, HEIGHT = BOARD_PX + PANEL, BOARD_PX

LIGHT = (238, 238, 210)
DARK = (118, 150, 86)
LAST_MOVE = (246, 246, 105, 150)
SELECTED = (57, 255, 20, 110)
CHECK = (235, 60, 60, 170)
HINT = (20, 20, 20, 60)
PANEL_BG = (13, 17, 23)
PANEL_LINE = (48, 54, 61)
TEXT = (230, 237, 243)
MUTED = (139, 148, 158)
NEON = (57, 255, 20)
PINK = (255, 43, 214)

# Chess glyphs: filled shapes and outlines. White pieces are drawn as a white
# filled shape with the outline on top; black pieces as the filled shape.
SOLID = {"K": "♚", "Q": "♛", "R": "♜", "B": "♝", "N": "♞", "P": "♟"}
OUTLINE = {"K": "♔", "Q": "♕", "R": "♖", "B": "♗", "N": "♘", "P": "♙"}
GLYPH_FONTS = ["applesymbols", "segoeuisymbol", "dejavusans", "notosanssymbols2",
               "freeserif", "symbola", "arialunicodems"]


def find_glyph_font(size):
    """A system font that has the chess symbols, or None."""
    for name in GLYPH_FONTS:
        path = pygame.font.match_font(name)
        if not path:
            continue
        font = pygame.font.Font(path, size)
        if all(m is not None for m in font.metrics("".join(SOLID.values()) + "".join(OUTLINE.values()))):
            return font
    return None


class PieceArt:
    """Pre-rendered piece images, one per piece letter."""

    def __init__(self):
        self.images = {}
        font = find_glyph_font(int(SQ * 0.82))
        label = pygame.font.SysFont("arial", int(SQ * 0.42), bold=True)
        for kind in "KQRBNP":
            for piece in (kind, kind.lower()):
                surface = pygame.Surface((SQ, SQ), pygame.SRCALPHA)
                white = piece.isupper()
                if font:
                    fill = (250, 250, 250) if white else (25, 25, 25)
                    for glyph, color in ((SOLID[kind], fill),
                                         (OUTLINE[kind] if white else SOLID[kind],
                                          (30, 30, 30) if white else (25, 25, 25))):
                        text = font.render(glyph, True, color)
                        surface.blit(text, text.get_rect(center=(SQ // 2, SQ // 2 + 2)))
                else:   # no symbol font: draw a token with the piece letter
                    fill, ink = ((245, 245, 245), (30, 30, 30)) if white else ((30, 30, 30), (245, 245, 245))
                    pygame.draw.circle(surface, fill, (SQ // 2, SQ // 2), SQ * 0.36)
                    pygame.draw.circle(surface, ink, (SQ // 2, SQ // 2), SQ * 0.36, 3)
                    text = label.render(kind, True, ink)
                    surface.blit(text, text.get_rect(center=(SQ // 2, SQ // 2)))
                self.images[piece] = surface


class Button:
    def __init__(self, rect, text, action, active=lambda: False):
        self.rect = pygame.Rect(rect)
        self.text = text
        self.action = action
        self.active = active

    def draw(self, screen, font, hover):
        on = self.active()
        bg = NEON if on else (33, 38, 45) if not hover else (48, 54, 61)
        pygame.draw.rect(screen, bg, self.rect, border_radius=6)
        pygame.draw.rect(screen, NEON if (hover or on) else PANEL_LINE, self.rect, 1, border_radius=6)
        label = font.render(self.text, True, PANEL_BG if on else TEXT)
        screen.blit(label, label.get_rect(center=self.rect.center))


class ChessApp:
    def __init__(self, human=WHITE, level="medium", screen=None):
        pygame.init()
        pygame.display.set_caption("AI Chess")
        self.screen = screen or pygame.display.set_mode((WIDTH, HEIGHT))
        self.clock = pygame.time.Clock()
        self.font = pygame.font.SysFont("menlo,consolas,dejavusansmono,couriernew", 16)
        self.small = pygame.font.SysFont("menlo,consolas,dejavusansmono,couriernew", 13)
        self.title = pygame.font.SysFont("menlo,consolas,dejavusansmono,couriernew", 26, bold=True)
        self.art = PieceArt()
        self.level = level
        self.buttons = self._make_buttons()
        self.new_game(human)

    # ------------------------------------------------------------ state

    def new_game(self, human=None):
        self.cancel_ai()
        self.human = human or getattr(self, "human", WHITE)
        self.flipped = self.human == BLACK
        self.board = Board()
        self.san_moves = []
        self.selected = None
        self.dragging = False
        self.promotion = None       # (from, to) waiting for a piece choice
        self.result = None
        self.ai_thread = None
        self.ai_move = None
        self.maybe_start_ai()

    def _make_buttons(self):
        x, w = BOARD_PX + 20, PANEL - 40
        half = (w - 10) // 2
        third = (w - 20) // 3
        buttons = [
            Button((x, 78, half, 34), "New: White", lambda: self.new_game(WHITE)),
            Button((x + half + 10, 78, half, 34), "New: Black", lambda: self.new_game(BLACK)),
        ]
        for i, name in enumerate(LEVELS):
            buttons.append(Button((x + i * (third + 10), 146, third, 30), name.title(),
                                  lambda n=name: self.set_level(n),
                                  lambda n=name: self.level == n))
        buttons += [
            Button((x, 190, half, 30), "Undo (U)", self.undo),
            Button((x + half + 10, 190, half, 30), "Flip (F)", self.flip),
        ]
        return buttons

    def set_level(self, name):
        self.level = name

    def flip(self):
        self.flipped = not self.flipped

    def undo(self):
        self.cancel_ai()
        self.promotion = None
        self.selected = None
        # Take back the AI's reply and the player's move.
        while self.board.moves:
            self.board.pop()
            self.san_moves.pop()
            if self.board.turn == self.human:
                break
        self.result = None
        self.maybe_start_ai()

    # --------------------------------------------------------------- AI

    def cancel_ai(self):
        if getattr(self, "ai_thread", None) and self.ai_thread.is_alive():
            self.searcher.stop = True
            self.ai_thread.join()
        self.ai_thread = None
        self.ai_move = None

    def maybe_start_ai(self):
        if self.result or self.board.turn == self.human or self.ai_thread:
            return
        seconds, depth, noise = LEVELS[self.level]
        self.searcher = Searcher(seconds, depth, noise)
        snapshot = self.board.copy()

        def think():
            move, _, _ = self.searcher.search(snapshot)
            self.ai_move = move

        self.ai_thread = threading.Thread(target=think, daemon=True)
        self.ai_thread.start()

    def poll_ai(self):
        if self.ai_thread and not self.ai_thread.is_alive():
            move = self.ai_move
            self.ai_thread = None
            self.ai_move = None
            if move:
                self.play(move)

    # ------------------------------------------------------------- moves

    def play(self, move):
        self.san_moves.append(self.board.san(move))
        self.board.push(move)
        self.selected = None
        self.result = self.board.result()
        self.maybe_start_ai()

    def legal_from(self, sq):
        return [m for m in self.board.legal_moves() if m[0] == sq]

    def try_move(self, frm, to):
        moves = [m for m in self.legal_from(frm) if m[1] == to]
        if not moves:
            return False
        if len(moves) > 1:            # several promotion choices
            self.promotion = (frm, to)
        else:
            self.play(moves[0])
        return True

    # ------------------------------------------------------ coordinates

    def square_at(self, pos):
        x, y = pos
        if not (0 <= x < BOARD_PX and 0 <= y < BOARD_PX):
            return None
        col, row = x // SQ, y // SQ
        if self.flipped:
            col, row = 7 - col, 7 - row
        return 21 + row * 10 + col

    def square_rect(self, sq):
        row, col = divmod(sq - 21, 10)
        if self.flipped:
            row, col = 7 - row, 7 - col
        return pygame.Rect(col * SQ, row * SQ, SQ, SQ)

    def promotion_rects(self):
        frm, to = self.promotion
        rect = self.square_rect(to)
        step = SQ if rect.y == 0 else -SQ
        return [(p, rect.move(0, i * step)) for i, p in enumerate("QRBN")]

    # ------------------------------------------------------------ events

    def human_turn(self):
        return self.board.turn == self.human and not self.result and not self.ai_thread

    def on_mouse_down(self, pos):
        for button in self.buttons:
            if button.rect.collidepoint(pos):
                button.action()
                return
        if self.promotion:
            for piece, rect in self.promotion_rects():
                if rect.collidepoint(pos):
                    frm, to = self.promotion
                    self.promotion = None
                    self.play((frm, to, piece))
                    return
            self.promotion = None
            return
        if not self.human_turn():
            return
        sq = self.square_at(pos)
        if sq is None:
            return
        if self.selected and self.try_move(self.selected, sq):
            return
        if color_of(self.board.board[sq]) == self.human:
            self.selected = sq
            self.dragging = True
        else:
            self.selected = None

    def on_mouse_up(self, pos):
        if not self.dragging:
            return
        self.dragging = False
        sq = self.square_at(pos)
        if self.selected and sq and sq != self.selected:
            if not self.try_move(self.selected, sq):
                self.selected = None

    def on_key(self, key):
        actions = {pygame.K_n: lambda: self.new_game(), pygame.K_u: self.undo, pygame.K_f: self.flip,
                   pygame.K_1: lambda: self.set_level("easy"),
                   pygame.K_2: lambda: self.set_level("medium"),
                   pygame.K_3: lambda: self.set_level("hard")}
        if key in actions:
            actions[key]()

    # ----------------------------------------------------------- drawing

    def tint(self, rect, rgba):
        layer = pygame.Surface(rect.size, pygame.SRCALPHA)
        layer.fill(rgba)
        self.screen.blit(layer, rect)

    def draw_board(self):
        for row in range(8):
            for col in range(8):
                color = LIGHT if (row + col) % 2 == 0 else DARK
                pygame.draw.rect(self.screen, color, (col * SQ, row * SQ, SQ, SQ))
        # File letters along the bottom row, rank numbers down the left column,
        # each drawn in the color of the opposite square so it stays readable.
        for i in range(8):
            file_letter = FILES[7 - i] if self.flipped else FILES[i]
            color = DARK if (7 + i) % 2 == 0 else LIGHT
            self.screen.blit(self.small.render(file_letter, True, color),
                             (i * SQ + SQ - 11, BOARD_PX - 17))
            rank = str(i + 1) if self.flipped else str(8 - i)
            color = DARK if i % 2 == 0 else LIGHT
            self.screen.blit(self.small.render(rank, True, color), (4, i * SQ + 3))
        if self.board.moves:
            frm, to, _ = self.board.moves[-1]
            self.tint(self.square_rect(frm), LAST_MOVE)
            self.tint(self.square_rect(to), LAST_MOVE)
        if self.board.in_check():
            rect = self.square_rect(self.board.kings[self.board.turn])
            glow = pygame.Surface((SQ, SQ), pygame.SRCALPHA)
            for radius, alpha in ((SQ // 2, 90), (SQ // 3, 170)):
                pygame.draw.circle(glow, CHECK[:3] + (alpha,), (SQ // 2, SQ // 2), radius)
            self.screen.blit(glow, rect)
        if self.selected:
            self.tint(self.square_rect(self.selected), SELECTED)
            for move in self.legal_from(self.selected):
                rect = self.square_rect(move[1])
                dot = pygame.Surface((SQ, SQ), pygame.SRCALPHA)
                if self.board.board[move[1]] == ".":
                    pygame.draw.circle(dot, HINT, (SQ // 2, SQ // 2), SQ // 7)
                else:
                    pygame.draw.circle(dot, HINT, (SQ // 2, SQ // 2), SQ // 2 - 2, 6)
                self.screen.blit(dot, rect)

    def draw_pieces(self):
        mouse = pygame.mouse.get_pos()
        for sq in range(21, 99):
            piece = self.board.board[sq]
            if piece in ".x":
                continue
            if self.dragging and sq == self.selected:
                continue
            self.screen.blit(self.art.images[piece], self.square_rect(sq))
        if self.dragging and self.selected:
            image = self.art.images[self.board.board[self.selected]]
            self.screen.blit(image, image.get_rect(center=mouse))

    def draw_promotion(self):
        if not self.promotion:
            return
        self.tint(pygame.Rect(0, 0, BOARD_PX, BOARD_PX), (0, 0, 0, 120))
        for piece, rect in self.promotion_rects():
            pygame.draw.rect(self.screen, (245, 245, 245), rect)
            pygame.draw.rect(self.screen, NEON, rect, 3)
            art = piece if self.human == WHITE else piece.lower()
            self.screen.blit(self.art.images[art], rect)

    def status_text(self):
        if self.result:
            score, reason = self.result
            if score == "1/2-1/2":
                return f"Draw by {reason}", MUTED
            winner = WHITE if score == "1-0" else BLACK
            if winner == self.human:
                return f"You win by {reason}!", NEON
            return f"AI wins by {reason}", PINK
        if self.ai_thread:
            dots = "." * (pygame.time.get_ticks() // 400 % 4)
            return f"AI thinking{dots}", PINK
        check = " (check!)" if self.board.in_check() else ""
        return "Your move" + check, NEON

    def draw_panel(self):
        x = BOARD_PX
        pygame.draw.rect(self.screen, PANEL_BG, (x, 0, PANEL, HEIGHT))
        pygame.draw.line(self.screen, PANEL_LINE, (x, 0), (x, HEIGHT))
        self.screen.blit(self.title.render("AI CHESS", True, NEON), (x + 20, 20))
        self.screen.blit(self.small.render("> player 1 vs cpu", True, MUTED), (x + 22, 52))
        self.screen.blit(self.small.render("DIFFICULTY", True, MUTED), (x + 20, 126))
        mouse = pygame.mouse.get_pos()
        for button in self.buttons:
            button.draw(self.screen, self.small, button.rect.collidepoint(mouse))

        text, color = self.status_text()
        pygame.draw.rect(self.screen, (22, 27, 34), (x + 20, 236, PANEL - 40, 40), border_radius=6)
        self.screen.blit(self.font.render(text, True, color), (x + 32, 247))

        self.screen.blit(self.small.render("MOVES", True, MUTED), (x + 20, 292))
        lines = []
        for i in range(0, len(self.san_moves), 2):
            pair = self.san_moves[i:i + 2]
            lines.append(f"{i // 2 + 1:>3}. {pair[0]:<8}{pair[1] if len(pair) > 1 else ''}")
        visible = lines[-15:]
        for i, line in enumerate(visible):
            self.screen.blit(self.small.render(line, True, TEXT), (x + 20, 314 + i * 20))
        help_text = "N new · U undo · F flip"
        self.screen.blit(self.small.render(help_text, True, MUTED), (x + 20, HEIGHT - 26))

    def draw_game_over(self):
        if not self.result:
            return
        text, color = self.status_text()
        box = pygame.Rect(0, 0, 420, 120)
        box.center = (BOARD_PX // 2, BOARD_PX // 2)
        layer = pygame.Surface(box.size, pygame.SRCALPHA)
        pygame.draw.rect(layer, (13, 17, 23, 230), layer.get_rect(), border_radius=8)
        self.screen.blit(layer, box)
        pygame.draw.rect(self.screen, color, box, 2, border_radius=8)
        title = self.title.render(text, True, color)
        self.screen.blit(title, title.get_rect(center=(box.centerx, box.centery - 16)))
        hint = self.small.render("Press N for a new game", True, TEXT)
        self.screen.blit(hint, hint.get_rect(center=(box.centerx, box.centery + 26)))

    def draw(self):
        self.draw_board()
        self.draw_pieces()
        self.draw_promotion()
        self.draw_game_over()
        self.draw_panel()

    # -------------------------------------------------------------- loop

    def run(self):
        running = True
        while running:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        running = False
                    else:
                        self.on_key(event.key)
                elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    self.on_mouse_down(event.pos)
                elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                    self.on_mouse_up(event.pos)
            self.poll_ai()
            self.draw()
            pygame.display.flip()
            self.clock.tick(60)
        self.cancel_ai()
        pygame.quit()
