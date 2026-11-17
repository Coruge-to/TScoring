"""Speed limit advance probe (observation only).

What it is for (Owner 2026-11-17): the red / blue blink warnings of the HUD speed-limit row ("制限速度予告", scoring_logic.update_physics_and_scoring) are judged from the position, the speed and the limits
ahead. To talk about "this part feels wrong" with numbers, this module writes a time series of everything the judgement uses and decides (one CSV row about 20 times a second and at every change of
the shown state), while the Owner drives.

It is OFF unless the flag file exists: %USERPROFILE%\\Documents\\bve_score\\limit-probe\\ON (create it to start a recording, delete it to stop; looked at every 2 s). While it is off the cost of a
call is one clock read. It only READS the Overlay and the arguments; it never changes the judgement, the HUD or any attribute, and nothing it does can raise into the caller. The CSV is written
next to the flag: limit-<yyyymmdd-HHMMSS>-P<pid>.csv (one file per process and recording).
"""
import os
import time

CHECK_EVERY_S = 2.0
MIN_ROW_INTERVAL_S = 0.05
FLUSH_EVERY_S = 1.0
FLAG_NAME = "ON"

COLUMNS = (
    "wall_s", "bve_time_s", "loc_m", "speed_kmh", "brk_notch", "bc_kpa",
    "eff_limit", "limit_type", "head_limit", "tail_limit", "sig_limit", "fwd_sig_loc", "fwd_sig_limit", "clear_dist_m", "train_len_m", "waiting_tail", "target_val", "target_loc",
    "disp_limit", "color", "blink_active", "blink_phase", "blink_cycle_s",
    "red_val", "red_loc", "red_dist_m", "red_decel_m", "red_warn_m", "red_urgency_m", "red_calc_v", "red_type",
    "blue_val", "blue_dist_m", "blue_type", "blue_suppressed",
    "n_reds", "reds", "future3", "flash_key", "flash_count", "strictest_val",
)


def _probe_dir():
    base = os.environ.get("USERPROFILE") or os.path.expanduser("~")
    return os.path.join(base, "Documents", "bve_score", "limit-probe")


class _Probe(object):
    def __init__(self):
        self.directory = None                 # None = the default (resolved at use, so a test can set the environment)
        self.clock = time.monotonic
        self.next_check = 0.0
        self.file = None
        self.path = None
        self.last_row = -1e9
        self.last_flush = 0.0
        self.last_sig = None
        self.rows = 0

    def dir(self):
        return self.directory or _probe_dir()

    def flag_present(self):
        try:
            return os.path.exists(os.path.join(self.dir(), FLAG_NAME))
        except Exception:
            return False

    def active(self, now):
        if now >= self.next_check:
            self.next_check = now + CHECK_EVERY_S
            present = self.flag_present()
            if present and self.file is None:
                self.open()
            elif not present and self.file is not None:
                self.close()
        return self.file is not None

    def open(self):
        d = self.dir()
        os.makedirs(d, exist_ok=True)
        self.path = os.path.join(d, "limit-%s-P%d.csv" % (time.strftime("%Y%m%d-%H%M%S"), os.getpid()))
        self.file = open(self.path, "w", encoding="utf-8", newline="")
        self.file.write(",".join(COLUMNS) + "\n")
        self.last_row = -1e9
        self.last_sig = None
        self.rows = 0

    def close(self):
        f, self.file = self.file, None
        if f is not None:
            try:
                f.flush()
                f.close()
            except Exception:
                pass

    def write(self, now, sig, row):
        if sig == self.last_sig and now - self.last_row < MIN_ROW_INTERVAL_S:
            return
        self.last_sig = sig
        self.last_row = now
        self.file.write(",".join(row) + "\n")
        self.rows += 1
        if now - self.last_flush >= FLUSH_EVERY_S:
            self.last_flush = now
            self.file.flush()


_probe = _Probe()


def _f(v, digits=2):
    try:
        return ("%." + str(digits) + "f") % float(v)
    except Exception:
        return ""


def _color_name(c):
    try:
        import config
        if c == config.COLOR_B_EMG:
            return "RED"
        if c == config.COLOR_P:
            return "BLUE"
        if c == config.COLOR_WHITE:
            return "WHITE"
    except Exception:
        pass
    return str(c).replace(",", " ")


def note(o, current_time, dt, is_waiting_tail, target_val, target_loc, future_targets, active_reds, active_red, active_blue, blink_cycle, blue_suppressed=False):
    """Called once per update step right after the speed limit judgement. Never raises, never changes anything."""
    try:
        p = _probe
        now = p.clock()
        if not p.active(now):
            return
        red = active_red or {}
        blue = active_blue or {}
        key = getattr(o, "current_flashing_key", None)
        counts = getattr(o, "limit_flash_counts", None) or {}
        disp = getattr(o, "disp_limit", "")
        color = _color_name(getattr(o, "limit_color", None))
        blink = bool(getattr(o, "blink_active", False))
        sig = (disp, color, blink, red.get("val"), red.get("loc"), blue.get("val"), getattr(o, "effective_limit", None), bool(is_waiting_tail), key, bool(blue_suppressed))
        reds = ";".join("%s@%s:%s/%s" % (r.get("val"), _f(r.get("loc"), 0), _f(r.get("dist"), 0), _f(r.get("decel_dist"), 0)) for r in (active_reds or []))
        fut = ";".join("%s@%s" % (t[1], _f(t[0], 0)) for t in (future_targets or [])[:3])
        row = (
            _f(now, 3), _f(current_time, 3), _f(getattr(o, "bve_location", ""), 2), _f(getattr(o, "bve_speed", ""), 2), str(getattr(o, "bve_brk_notch", "")), _f(getattr(o, "bcPressure", ""), 1),
            str(getattr(o, "effective_limit", "")), str(getattr(o, "base_limit_type", "")), str(getattr(o, "map_head_limit", "")), str(getattr(o, "map_tail_limit", "")),
            str(getattr(o, "bve_signal_limit", "")), _f(getattr(o, "bve_fwd_sig_loc", ""), 1), str(getattr(o, "bve_fwd_sig_limit", "")),
            _f(getattr(o, "bve_clear_dist", ""), 1), _f(getattr(o, "bve_train_length", ""), 1), "1" if is_waiting_tail else "0", str(target_val), _f(target_loc, 1),
            str(disp), color, "1" if blink else "0", _f(getattr(o, "blink_phase", ""), 3), _f(blink_cycle, 3),
            str(red.get("val", "")), _f(red.get("loc", ""), 1), _f(red.get("dist", ""), 1), _f(red.get("decel_dist", ""), 1), _f(red.get("warn_dist", ""), 1), _f(red.get("urgency", ""), 1),
            _f(red.get("calc_v", ""), 2), str(red.get("type", "")),
            str(blue.get("val", "")), _f(blue.get("dist", ""), 1), str(blue.get("type", "")), "1" if blue_suppressed else "0",
            str(len(active_reds or [])), reds, fut, str(key or ""), str(counts.get(key, "")) if key else "", str(getattr(o, "strictest_flashed_val", "")),
        )
        p.write(now, sig, row)
    except Exception:
        pass
