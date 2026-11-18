"""Live probe of the F1 menu (observation only, NOT part of the product). Python imports `sitecustomize` at start-up from every PYTHONPATH entry, so the product
is not changed by one byte. It does NOTHING unless
  - TSPROBE_LOG is set (the log file; the TScoring process gets it from the BVE process environment, BVE -> Caller -> python child), and
  - the script being run is a main.py (or TSPROBE_FORCE=1 for the offscreen self-test).
When main.py has defined the Overlay class it wraps a few methods with timers / loggers and writes ONE TEXT LINE per event to TSPROBE_LOG. Every wrapper swallows its
own exceptions: a probe fault can never change the product's behaviour. Remove it by not setting PYTHONPATH / TSPROBE_LOG for the next BVE start.

Line format:  HH:MM:SS.mmm t=<ms since the probe started> KIND key=value ...   (the wall clock is the same clock the driver uses)
Events:
  START   the probe woke up (pid, script)
  ARMED   the Overlay's shared step runs (the scenario is loaded, TScoring is alive)
  TOGGLE  toggle_menu returned (F1 / close): state (0 = menu closed), cursor
  UP / DOWN / BACK   a menu navigation key was handled: state, cursor
  ENTER   handle_menu_enter returned: state='before->after', cursor (before), dur ms, stations
  SETTING set_disp_setting returned: key, value, items (HUD item states)
  PAINT   paintEvent finished (only when it follows an ENTER: since_enter = ms from the ENTER's start to the end of the paint, or when it took > 25 ms)
  STEP / FOLLOW / REPAINT / STALL   the shared step took > 40 ms (or the gap before it > 100 ms) / _follow_bve_window > 15 ms / request_repaint > 8 ms /
                                    the GUI thread did not run a 10 ms watchdog for > 60 ms
Every UP / DOWN / BACK / TOGGLE / ENTER / SETTING line also carries disp=<the 8 HUD switches as 0/1 in settings_keys order>.
"""
import os
import sys
import threading
import time

_LOG = os.environ.get('TSPROBE_LOG')


def _active():
    if not _LOG:
        return False
    if os.environ.get('TSPROBE_FORCE') == '1':
        return True
    try:
        return os.path.basename(sys.argv[0]).lower() == 'main.py'
    except Exception:
        return False


if _active():
    _T0 = time.perf_counter()
    _lock = threading.Lock()
    STEP_MS = 40.0

    def _w(kind, **kw):
        try:
            t = (time.perf_counter() - _T0) * 1000.0
            now = time.time()
            wall = time.strftime('%H:%M:%S', time.localtime(now)) + ('.%03d' % (int((now % 1) * 1000)))
            line = '%s t=%.1f %s ' % (wall, t, kind) + ' '.join('%s=%s' % (k, v) for k, v in kw.items()) + '\n'
            with _lock:
                with open(_LOG, 'a', encoding='utf-8') as f:
                    f.write(line)
        except Exception:
            pass

    _w('START', pid=os.getpid(), script=os.path.basename(sys.argv[0]), argv=' '.join(sys.argv[1:])[:120])

    _state = {'enter_start': None, 'enter_to': None, 'last_step': None, 'last_dog': None}

    def _disp(self):
        """the HUD switches as a string of 0/1 in settings_keys order (keys not set count as 1, as hud_item_state reads them)"""
        try:
            keys = list(getattr(self, 'settings_keys', []) or [])
            return ''.join('1' if self.disp_settings.get(k, True) else '0' for k in keys)
        except Exception:
            return '?'

    def _items(self):
        try:
            hud_ui = sys.modules.get('hud_ui')
            return ','.join('%s:%s' % (k, hud_ui.hud_item_state(self, k)) for k in self.settings_keys)
        except Exception:
            return '?'

    def _wrap(cls, name, make):
        try:
            orig = getattr(cls, name, None)
            if orig is None or getattr(orig, '_tsprobe', False):
                return False
            fn = make(orig)
            fn._tsprobe = True
            setattr(cls, name, fn)
            return True
        except Exception:
            return False

    def _install(cls):
        def mk_enter(orig):
            def handle_menu_enter(self, *a, **k):
                t0 = time.perf_counter()
                before = getattr(self, 'menu_state', None)
                cur = getattr(self, 'menu_cursor', None)
                try:
                    return orig(self, *a, **k)
                finally:
                    try:
                        dt = (time.perf_counter() - t0) * 1000.0
                        after = getattr(self, 'menu_state', None)
                        _w('ENTER', state='%s->%s' % (before, after), cursor=cur, cursor_after=getattr(self, 'menu_cursor', None), dur=round(dt, 2),
                           stations=len(getattr(self, 'station_list', []) or []), disp=_disp(self))
                        _state['enter_start'] = t0
                        _state['enter_to'] = after
                    except Exception:
                        pass
            return handle_menu_enter

        def mk_nav(kind):
            def mk(orig):
                def nav(self, *a, **k):
                    try:
                        return orig(self, *a, **k)
                    finally:
                        try:
                            _w(kind, state=getattr(self, 'menu_state', None), cursor=getattr(self, 'menu_cursor', None), cx=getattr(self, 'menu_cursor_x', None), disp=_disp(self))
                        except Exception:
                            pass
                return nav
            return mk

        def mk_setting(orig):
            def set_disp_setting(self, key, enabled, *a, **k):
                try:
                    return orig(self, key, enabled, *a, **k)
                finally:
                    try:
                        _w('SETTING', key=key, value=bool(self.disp_settings.get(key, True)), items=_items(self), disp=_disp(self))
                    except Exception:
                        pass
            return set_disp_setting

        def mk_paint(orig):
            def paintEvent(self, event):
                t0 = time.perf_counter()
                try:
                    return orig(self, event)
                finally:
                    try:
                        t1 = time.perf_counter()
                        ms = getattr(self, 'menu_state', None)
                        extra = {}
                        if _state['enter_start'] is not None and ms == _state['enter_to']:
                            extra['since_enter'] = round((t1 - _state['enter_start']) * 1000.0, 1)
                            _state['enter_start'] = None
                        if extra or (t1 - t0) * 1000.0 > 25.0:
                            _w('PAINT', dur=round((t1 - t0) * 1000.0, 2), state=ms, **extra)
                    except Exception:
                        pass
            return paintEvent

        def mk_step(orig):
            def _run_input_and_scoring_step(self, *a, **k):
                arm(self)
                t0 = time.perf_counter()
                gap = None if _state['last_step'] is None else (t0 - _state['last_step']) * 1000.0
                _state['last_step'] = t0
                try:
                    return orig(self, *a, **k)
                finally:
                    try:
                        dt = (time.perf_counter() - t0) * 1000.0
                        if dt > STEP_MS or (gap is not None and gap > 100.0):
                            _w('STEP', dur=round(dt, 1), gap=(round(gap, 1) if gap is not None else None), state=getattr(self, 'menu_state', None))
                    except Exception:
                        pass
            return _run_input_and_scoring_step

        def mk_timed(kind, threshold_ms):
            def mk(orig):
                def timed(self, *a, **k):
                    t0 = time.perf_counter()
                    try:
                        return orig(self, *a, **k)
                    finally:
                        try:
                            dt = (time.perf_counter() - t0) * 1000.0
                            if dt > threshold_ms:
                                _w(kind, dur=round(dt, 1), state=getattr(self, 'menu_state', None))
                        except Exception:
                            pass
                return timed
            return mk

        def arm(self):
            if getattr(self, '_tsprobe_dog', None) is not None:
                return
            try:
                from PyQt6.QtCore import QTimer
                dog = QTimer(self)
                dog.setInterval(10)

                def tick():
                    now = time.perf_counter()
                    last = _state['last_dog']
                    _state['last_dog'] = now
                    if last is not None and (now - last) * 1000.0 > 60.0:
                        _w('STALL', gap=round((now - last) * 1000.0, 1), state=getattr(self, 'menu_state', None))
                dog.timeout.connect(tick)
                dog.start()
                self._tsprobe_dog = dog
                _w('ARMED', cls=cls.__name__, disp=_disp(self))
            except Exception as e:
                self._tsprobe_dog = False
                _w('ARMFAIL', err=repr(e)[:100])

        wraps = (('handle_menu_enter', mk_enter), ('paintEvent', mk_paint), ('_run_input_and_scoring_step', mk_step), ('_follow_bve_window', mk_timed('FOLLOW', 15.0)),
                 ('request_repaint', mk_timed('REPAINT', 8.0)), ('handle_menu_up', mk_nav('UP')), ('handle_menu_down', mk_nav('DOWN')), ('handle_menu_backspace', mk_nav('BACK')),
                 ('toggle_menu', mk_nav('TOGGLE')), ('set_disp_setting', mk_setting))
        for name, make in wraps:
            if not _wrap(cls, name, make):
                _w('WRAPFAIL', name=name)

    def _watch():
        for _ in range(600):                        # up to 60 s: main.py defines Overlay at import time, long before the loop runs
            for mod in (sys.modules.get('__main__'), sys.modules.get('main')):
                cls = getattr(mod, 'Overlay', None) if mod is not None else None
                if cls is not None and hasattr(cls, 'handle_menu_enter'):
                    _install(cls)
                    return
            time.sleep(0.1)
        _w('NOOVERLAY')

    threading.Thread(target=_watch, name='tsprobe-install', daemon=True).start()
