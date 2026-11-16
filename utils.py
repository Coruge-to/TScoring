import math
import datetime
from collections import deque
import os
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFontMetrics, QPainterPath, QPen, QTransform
from config import *

# ★ ネットワークファイル用のログ関数
# Phase SI-A: the Desktop debug log has ONE switch. Normal mode (python main.py) keeps writing as it always did; managed mode switches it off when it
# starts (main.run_managed) unless the environment variable TS_SCORING_DESKTOP_LOG=1 asks for it: the log lines can carry station names.
DESKTOP_LOG_ENV = "TS_SCORING_DESKTOP_LOG"
_desktop_log_enabled = True


def set_desktop_log_enabled(flag):
    global _desktop_log_enabled
    _desktop_log_enabled = bool(flag)


def desktop_log_enabled():
    return _desktop_log_enabled


def desktop_log_requested(environ=None):
    """Is the Desktop log explicitly asked for (managed mode)? Only the exact value '1'."""
    return (os.environ if environ is None else environ).get(DESKTOP_LOG_ENV, "") == "1"


def write_desktop_log(msg):
    if not _desktop_log_enabled:
        return
    desktop = os.path.join(os.path.expanduser("~"), "Desktop")
    log_file = os.path.join(desktop, "debug.log")
    try:
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.datetime.now().strftime('%H:%M:%S.%f')[:-3]}] {msg}\n")
    except:
        pass

def get_outline_color(t_color):
    return COLOR_OUTLINE_BLACK if t_color == COLOR_WHITE else COLOR_OUTLINE_WHITE

# 【軽量版】8方向ずらし描画（F6メニューや、X線ゴーグルなど文字が細かい画面用）
def draw_text_with_outline(painter, text, font, text_color, outline_color, x, y, align="left", passes=8):
    fm = QFontMetrics(font)
    text_str = str(text)
    if align == "right":
        x -= fm.horizontalAdvance(text_str)
    elif align == "center":
        x -= fm.horizontalAdvance(text_str) / 2

    painter.setFont(font)
    
    if isinstance(outline_color, tuple):
        painter.setPen(QColor(*outline_color))
    else:
        painter.setPen(outline_color)
        
    offset = OUTLINE_WIDTH / 2.0
    offsets = [(-offset, -offset), (0, -offset), (offset, -offset), 
               (-offset, 0),                     (offset, 0), 
               (-offset, offset),  (0, offset),  (offset, offset)]
               
    for dx, dy in offsets:
        painter.drawText(int(x + dx), int(y + dy), text_str)

    if isinstance(text_color, tuple):
        painter.setPen(QColor(*text_color))
    else:
        painter.setPen(text_color)
    painter.drawText(int(x), int(y), text_str)

# ★【高品質版】パス・ストローク描画（HUDのデカ文字用・Wordと同じ美しい縁取り）
_GLYPH_TUNE_CACHE = {}


def glyph_tune_of(font):
    """Case C2 (HUD UI, Owner 2026-11-16): the two glyphs of the HUD font that look off inside the monospaced cell, measured from the font itself (the real Windows platform differs from offscreen):
    the decimal point sits left of the cell centre of the digits (dot_dx: shift to the right that puts its ink centre on the ink centre of the digit 0), and the slash is taller than k / h (slash_scale and
    slash_dy: shrink about the glyph origin so its height equals the height of k, bottom on the bottom of k)."""
    key = (font.family(), font.pointSizeF(), font.pixelSize(), font.weight(), int(font.hintingPreference().value))
    tune = _GLYPH_TUNE_CACHE.get(key)
    if tune is None:
        fm = QFontMetrics(font)
        zero, dot, k, slash = fm.tightBoundingRect("0"), fm.tightBoundingRect("."), fm.tightBoundingRect("k"), fm.tightBoundingRect("/")
        dot_dx = (zero.x() + zero.width() / 2.0) - (dot.x() + dot.width() / 2.0)
        slash_h, k_h = float(slash.height()), float(k.height())
        scale = k_h / slash_h if slash_h > 0 and k_h > 0 else 1.0
        scale = min(1.0, scale)
        slash_cx = slash.x() + slash.width() / 2.0
        tune = {"dot_dx": dot_dx, "slash_scale": scale, "slash_tx": slash_cx - scale * slash_cx, "slash_ty": (k.y() + k.height()) - scale * (slash.y() + slash.height())}
        _GLYPH_TUNE_CACHE[key] = tune
    return tune


def tuned_text_path(font, fm, text_str, x, y):
    """The path of text_str at (x, y) with the decimal point centred in its cell and the slash scaled to the height of k (glyph_tune_of). The cell of every character is its own advance (the HUD font is monospaced)."""
    tune = glyph_tune_of(font)
    path = QPainterPath()
    run_start = 0
    for i, ch in enumerate(text_str):
        if ch not in "./":
            continue
        if i > run_start:
            path.addText(x + fm.horizontalAdvance(text_str[:run_start]), y, font, text_str[run_start:i])
        cell_x = x + fm.horizontalAdvance(text_str[:i])
        if ch == ".":
            path.addText(cell_x + tune["dot_dx"], y, font, ".")
        else:
            glyph = QPainterPath()
            glyph.addText(0, 0, font, "/")
            path.addPath(QTransform(tune["slash_scale"], 0, 0, tune["slash_scale"], cell_x + tune["slash_tx"], y + tune["slash_ty"]).map(glyph))
        run_start = i + 1
    if run_start < len(text_str):
        path.addText(x + fm.horizontalAdvance(text_str[:run_start]), y, font, text_str[run_start:])
    return path


# Case C3-d (Owner 2026-11-16): the kerning of the brake text of the handle row also works INSIDE a text. main.KERNING_OFFSETS (the glyphs with a blank on their RIGHT side) used to cut the blank only at the END of a text;
# now the degree sign and the full-width closing bracket are cut wherever they stand, and the full-width opening bracket (the blank on its LEFT side, the mirror of the closing one) is cut by the same amount.
KERN_LEFT_OFFSETS = {"（": 28, "(": 3}     # "(" half-width opening parenthesis: blank 7 px on its left, 3 px are cut (Owner 2026-11-16)
KERN_MID_CHARS = ("°", "）", ")")


def kerned_text_layout(text, fm, right_offsets):
    """(x of every character from the left end of the text, width of the text) when the text needs the inner kerning, else None (the caller keeps the old end-of-text rule: kerned_text_width / get_text_offset).
    A glyph moves left by its own left cut; the next glyph starts after the advance minus both cuts; a right cut (right_offsets) counts at the end of the text and, for KERN_MID_CHARS, anywhere."""
    s = str(text)
    if not (any(c in KERN_MID_CHARS for c in s[:-1]) or any(c in KERN_LEFT_OFFSETS for c in s)):
        return None
    positions, x, last = [], 0, len(s) - 1
    for i, ch in enumerate(s):
        left_cut = KERN_LEFT_OFFSETS.get(ch, 0)
        right_cut = right_offsets.get(ch, 0) if (i == last or ch in KERN_MID_CHARS) else 0
        positions.append(x - left_cut)
        x += fm.horizontalAdvance(ch) - left_cut - right_cut
    return positions, x


def kerned_text_width(text, fm, right_offsets):
    """The width of a brake text of the handle row: the kerned layout when it applies, else the advance minus the end-of-text cut (the rule before this change)."""
    layout = kerned_text_layout(text, fm, right_offsets)
    if layout is not None:
        return layout[1]
    width = fm.horizontalAdvance(text)
    for suffix, offset in right_offsets.items():
        if str(text).endswith(suffix):
            return width - offset
    return width


def draw_text_with_stroke(painter, text, font, text_color, outline_color, x, y, align="left", stroke_width=OUTLINE_WIDTH, tune_glyphs=False, kern_positions=None):
    path = QPainterPath()
    fm = QFontMetrics(font)
    text_str = str(text)
    
    if align == "right":
        x -= fm.horizontalAdvance(text_str)
    elif align == "center":
        x -= fm.horizontalAdvance(text_str) / 2
        
    if kern_positions is not None:
        for ch, offset_x in zip(text_str, kern_positions):
            path.addText(x + offset_x, y, font, ch)
    elif tune_glyphs:
        path = tuned_text_path(font, fm, text_str, x, y)
    else:
        path.addText(x, y, font, text_str)

    if isinstance(outline_color, tuple):
        pen_color = QColor(*outline_color)
    else:
        pen_color = outline_color
        
    pen = QPen(pen_color, stroke_width)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.drawPath(path)
    
    painter.setPen(Qt.PenStyle.NoPen)
    if isinstance(text_color, tuple):
        brush_color = QColor(*text_color)
    else:
        brush_color = text_color
    painter.setBrush(brush_color)
    painter.drawPath(path)

# ==========================================================
# ★ scoring_logic.py で使われる計算用関数（迷子になっていたものを統合）
# ==========================================================
def calculate_warning_distance(current_speed, next_limit):
    if next_limit < current_speed:
        speed_diff = current_speed - next_limit
        a_kmh = 3.5 if speed_diff >= 40.0 else 2.5
        v0 = current_speed / 3.6
        v1 = next_limit / 3.6
        a = a_kmh / 3.6 
        decel_dist = (v0**2 - v1**2) / (2 * a)
        margin_dist = v0 * 5.0 
        return decel_dist, decel_dist + margin_dist
    return 0.0, 0.0

def calculate_apex_speed(v_start_kmh, v_target_kmh, dist_m, lower_limit_kmh):
    v0 = v_start_kmh / 3.6
    v1 = lower_limit_kmh / 3.6
    a1 = 1.5 / 3.6 
    speed_diff = v_target_kmh - lower_limit_kmh 
    a_kmh = 3.5 if speed_diff >= 40.0 else 2.5
    a2 = a_kmh / 3.6 
    A = (a1 + a2) / (2 * a1 * a2)
    B = 5.0
    C = -(dist_m + (v0**2)/(2*a1) + (v1**2)/(2*a2))
    D = B**2 - 4*A*C
    if D < 0: return v_start_kmh 
    v_apex = (-B + math.sqrt(D)) / (2 * A)
    v_apex_kmh = v_apex * 3.6
    return max(v_start_kmh, min(v_apex_kmh, v_target_kmh))

# ==========================================================
# 数値入力用のキーイベント分類（β版は日本語キーボード配列が対象）
# ==========================================================
NUMERIC_DIGIT_NAMES = "0123456789"
NUMERIC_NAVIGATION_NAMES = ("up", "down", "left", "right")

def classify_numeric_key_event(event, ctrl_alt_pressed=False):
    """
    keyboardのKeyboardEventを、数値入力用に分類する。

    戻り値:
      ("digit", "0"〜"9", "main" | "keypad") … 数字として受理する
      ("nav", "up" | "down" | "left" | "right", "main" | "keypad") … 数字にしない
      None … 数値入力と無関係

    event.nameはOSがNumLockとShiftの状態を反映して解決した名前で、
      通常数字      : "0"〜"9"（is_keypad=False）
      テンキー数字  : NumLock ONなら"0"〜"9"（is_keypad=True）
      テンキー      : NumLock OFFならナビゲーション名（is_keypad=True）
      方向キー      : "up"等（is_keypad=False）
      Shift+数字    : 記号
    となる。NumLockの状態は自前で読まない。
    """
    if getattr(event, 'event_type', None) != 'down':
        return None

    name = getattr(event, 'name', None)
    if not name:
        return None

    source = 'keypad' if getattr(event, 'is_keypad', False) else 'main'

    if len(name) == 1 and name in NUMERIC_DIGIT_NAMES:
        if ctrl_alt_pressed:
            return None
        return ("digit", name, source)

    if name in NUMERIC_NAVIGATION_NAMES:
        return ("nav", name, source)

    return None


class NumericKeyInputRouter:
    """
    数値入力用のキーイベントを集めるルーター。

    keyboard.hook(router.on_event, suppress=True)で登録して使う。
    on_eventはkeyboardのフックスレッドから呼ばれるため、Qtには触れず、
    分類結果をdequeへ積むだけにする。Qt側のタイマーがdrain()で取り出す。
    on_eventは常にTrueを返し、キーの抑止は既存のキーフックに任せる。
    """

    def __init__(self, max_events=64, allow_repeat=False):
        self.events = deque(maxlen=max_events)
        self.allow_repeat = allow_repeat
        self._held_scan_codes = set()
        self._ctrl_alt_scan_codes = set()

    def reset(self):
        self.events.clear()
        self._held_scan_codes.clear()
        self._ctrl_alt_scan_codes.clear()

    def on_event(self, event):
        try:
            name = getattr(event, 'name', None) or ""
            scan_code = event.scan_code
            event_type = event.event_type

            if "ctrl" in name or "alt" in name:
                if event_type == 'down':
                    self._ctrl_alt_scan_codes.add(scan_code)
                else:
                    self._ctrl_alt_scan_codes.discard(scan_code)

            if event_type == 'up':
                self._held_scan_codes.discard(scan_code)
                return True

            is_repeat = scan_code in self._held_scan_codes
            self._held_scan_codes.add(scan_code)
            if is_repeat and not self.allow_repeat:
                return True

            classified = classify_numeric_key_event(
                event,
                ctrl_alt_pressed=bool(self._ctrl_alt_scan_codes),
            )
            if classified is not None:
                self.events.append(classified)
        except Exception:
            pass
        return True

    def drain(self):
        drained = []
        while True:
            try:
                drained.append(self.events.popleft())
            except IndexError:
                break
        return drained