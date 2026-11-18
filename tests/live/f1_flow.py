"""The F1 menu autonomous test: the FLOW and its verdicts, independent of how a key reaches the application (a Transport) and of BVE.

  live (BVE): tests/live/f1_autonomous.py   Transport = scan-code key injection into the real BVE (the TScoring child writes the probe log)
  offscreen : tests/test_f1_flow_offscreen.py  Transport = direct calls of the real Overlay handlers (same probe, same log lines, same checks)

The flow reads the F1 menu state ONLY from the probe log (tests/live/probe/sitecustomize.py): never blind. Verdicts:
  PASS          every check held
  FAIL          the setup was valid (the menu opened, the keys were seen) and a CHECK of the F1 contract did not hold: a product finding
  INCONCLUSIVE  the setup did not hold (probe not armed, F1 never opened, a key was never seen, the menu layout is not the expected one): NOT a product finding
F1 changes are NOT persisted (the F1 settings are regenerated from the saved initial defaults at the next scenario load): what is verified is the Overlay's
state (disp_settings through the probe, hud_item_state = what the HUD will draw) and that every change is reverted at the end.
"""
import datetime
import json
import os
import re
import time

LINE = re.compile(r'^(\d\d):(\d\d):(\d\d)\.(\d\d\d) t=([\d.]+) (\w+) ?(.*)$')
REACTION = {'F1': ('TOGGLE',), 'DOWN': ('DOWN',), 'UP': ('UP',), 'ENTER': ('ENTER',), 'BACKSPACE': ('BACK',)}
KEYS = ('time', 'time_left', 'speed', 'limit', 'limit_advance', 'dist', 'handle', 'grad')       # settings_keys order of the Overlay (ENV-1)


class Inconclusive(Exception):
    pass


def parse_line(line):
    m = LINE.match(line)
    if not m:
        return None
    h, mi, s, ms, t, kind, rest = m.groups()
    today = datetime.date.today()
    wall = datetime.datetime(today.year, today.month, today.day, int(h), int(mi), int(s), int(ms) * 1000).timestamp()
    kv = {}
    for part in rest.split(' '):
        if '=' in part:
            k, v = part.split('=', 1)
            kv[k] = v
    return {'wall': wall, 't': float(t), 'kind': kind, 'kv': kv}


class ProbeLog(object):
    def __init__(self, path):
        self.path = path

    def events(self):
        out = []
        if os.path.exists(self.path):
            with open(self.path, 'r', encoding='utf-8', errors='replace') as f:
                for line in f.read().splitlines():
                    e = parse_line(line)
                    if e:
                        out.append(e)
        return out

    def wait_new(self, n_before, kinds, timeout):
        end = time.time() + timeout
        while True:
            ev = self.events()
            for e in ev[n_before:]:
                if e['kind'] in kinds:
                    return e
            if time.time() >= end:
                return None
            time.sleep(0.03)

    def nav(self):
        """newest menu position: dict(state, cursor, disp) or None"""
        for e in reversed(self.events()):
            kv = e['kv']
            if e['kind'] in ('UP', 'DOWN', 'BACK', 'TOGGLE') and kv.get('state', 'None') != 'None':
                cur = kv.get('cursor', 'None')
                return {'state': int(kv['state']), 'cursor': int(cur) if cur not in ('None', '') else -1, 'disp': kv.get('disp', '?'), 'kind': e['kind']}
            if e['kind'] == 'ENTER':
                after = kv.get('state', '').split('->')[-1]
                cur = kv.get('cursor_after', 'None')
                if after.isdigit():
                    return {'state': int(after), 'cursor': int(cur) if cur not in ('None', '') else None, 'disp': kv.get('disp', '?'), 'kind': 'ENTER'}
        return None


class Flow(object):
    def __init__(self, transport, plog, require_armed=True, key_timeout=2.5, settle=0.35, log=print):
        self.tp, self.plog, self.require_armed, self.key_timeout, self.settle, self.log = transport, plog, require_armed, key_timeout, settle, log
        self.checks = []
        self.timeline = []
        self.times = {}

    # -- bookkeeping --------------------------------------------------------------------------------------------------------------------------------------
    def check(self, name, ok, detail=''):
        self.checks.append({'name': name, 'ok': bool(ok), 'detail': str(detail)})
        self.log('%s %s %s' % ('PASS' if ok else 'FAIL', name, detail))
        return bool(ok)

    def send(self, key):
        """one key; returns the reaction event. No reaction after one retry = the input path is not working = INCONCLUSIVE (never a product finding)."""
        for attempt in (1, 2):
            n0 = len(self.plog.events())
            t0 = time.time()
            self.tp.press(key)
            e = self.plog.wait_new(n0, REACTION[key], self.key_timeout)
            if e is not None:
                self.timeline.append({'key': key, 'ms_to_reaction': round((e['wall'] - t0) * 1000), 'event': e['kind'], 'kv': e['kv']})
                time.sleep(self.settle)
                return e, t0
            self.log('no reaction to %s (attempt %d)' % (key, attempt))
        raise Inconclusive('no reaction to %s: the key does not reach TScoring (input path / foreground), not a product finding' % key)

    def pos(self):
        p = self.plog.nav()
        if p is None:
            raise Inconclusive('the probe log has no menu position yet')
        return p

    def goto_cursor(self, state, target):
        for _ in range(14):
            p = self.pos()
            if p['state'] != state:
                return False
            if p['cursor'] == target:
                return True
            self.send('DOWN' if (p['cursor'] is None or p['cursor'] < target) else 'UP')
        return self.pos()['cursor'] == target

    def enter(self):
        e, t0 = self.send('ENTER')
        return e, t0

    # -- the flow -----------------------------------------------------------------------------------------------------------------------------------------
    def run(self):
        try:
            self._run()
        except Inconclusive as e:
            return self._verdict('INCONCLUSIVE', str(e))
        failed = [c for c in self.checks if not c['ok']]
        return self._verdict('FAIL' if failed else 'PASS', '%d checks, %d failed' % (len(self.checks), len(failed)))

    def _verdict(self, verdict, why):
        return {'verdict': verdict, 'why': why, 'checks': self.checks, 'timeline': self.timeline, 'times': self.times}

    def _open_menu(self):
        e, _ = self.send('F1')
        if e['kv'].get('state') == '0':                  # it was open and F1 closed it: once more
            e, _ = self.send('F1')
        return e

    def _run(self):
        if self.require_armed and not any(e['kind'] == 'ARMED' for e in self.plog.events()):
            raise Inconclusive('the probe is not armed (no ARMED event): the Overlay did not start or sitecustomize was not loaded')
        e = self._open_menu()
        if e['kv'].get('state') != '1':
            raise Inconclusive('F1 did not open the main menu (state %s)' % e['kv'].get('state'))
        self.check('F1 opens the main menu (state 1) with the cursor on the first row', self.pos()['state'] == 1 and self.pos()['cursor'] == 0, self.pos())
        s0 = self.pos()['disp']
        self.check('the 8 HUD switches are readable from the probe', len(s0) == len(KEYS) and set(s0) <= set('01'), s0)
        if len(s0) != len(KEYS):
            raise Inconclusive('cannot read the HUD switches: disp=%r' % s0)
        self.times['disp_start'] = s0

        # -- the scoring settings pages: 1/3 (state 5) -> 2/3 (6) -> 3/3 (10) and back ------------------------------------------------------------------
        self.goto_cursor(1, 1)
        e, _ = self.enter()
        if e['kv'].get('state') != '1->5':
            raise Inconclusive('the second row of the main menu is not the scoring settings (state %s; scoring already ON?)' % e['kv'].get('state'))
        self.check('main menu row 2 (scoring settings) opens page 1/3 (state 5)', True, e['kv'].get('state'))
        self.goto_cursor(5, 5)
        e, _ = self.enter()
        self.check('page 1/3 row 6 opens page 2/3 (state 6)', e['kv'].get('state') == '5->6', e['kv'].get('state'))
        self.goto_cursor(6, 6)
        e, t_enter = self.enter()
        self.check('page 2/3 row 7 opens page 3/3 (state 10)', e['kv'].get('state') == '6->10', e['kv'].get('state'))
        self.times['enter_to_page3_dur_ms'] = e['kv'].get('dur')
        e, _ = self.send('BACKSPACE')
        p = self.pos()
        self.check('Backspace on page 3/3 returns to page 2/3 with the cursor on row 7', p['state'] == 6 and p['cursor'] == 6, p)
        e, _ = self.send('BACKSPACE')
        p = self.pos()
        self.check('Backspace on page 2/3 returns to page 1/3 with the cursor on row 6', p['state'] == 5 and p['cursor'] == 5, p)
        e, _ = self.send('BACKSPACE')
        p = self.pos()
        self.check('Backspace on page 1/3 returns to the main menu (state 1, cursor 0)', p['state'] == 1 and p['cursor'] == 0, p)
        self.check('visiting the scoring pages changes no HUD switch', p['disp'] == s0, '%s -> %s' % (s0, p['disp']))

        # -- the environment settings (state 4): switch, interlock, revert ----------------------------------------------------------------------------------
        self.goto_cursor(1, 2)
        e, _ = self.enter()
        if e['kv'].get('state') != '1->4':
            raise Inconclusive('the third row of the main menu is not the environment settings (state %s)' % e['kv'].get('state'))
        self.check('main menu row 3 (environment settings) opens state 4', True, e['kv'].get('state'))
        i_speed = KEYS.index('speed')
        self.goto_cursor(4, i_speed)
        n0 = len(self.plog.events())
        self.enter()
        st = self.plog.wait_new(n0, ('SETTING',), 1.5)
        was = s0[i_speed] == '1'
        words = [w.split(':', 1)[1] for w in (st['kv'].get('items', '') if st else '').split(',') if w.startswith('speed:')]
        word = words[0] if words else None
        ok = st is not None and st['kv'].get('key') == 'speed' and st['kv'].get('value') == str(not was) and word in (('user-hidden' if was else 'shown'), 'unavailable')
        self.check('Enter on the speed row switches it (SETTING event; hud_item_state follows: shown / user-hidden, or unavailable when the sender has no such data)', ok,
                   st['kv'] if st else 'no SETTING event')
        d1 = self.pos_or_disp()
        expect = s0[:i_speed] + ('0' if was else '1') + s0[i_speed + 1:]
        self.check('only the speed switch changed', d1 == expect, '%s (expected %s)' % (d1, expect))
        self.enter()
        d2 = self.pos_or_disp()
        self.check('Enter again reverts the speed switch', d2 == s0, '%s (expected %s)' % (d2, s0))

        i_lim, i_adv = KEYS.index('limit'), KEYS.index('limit_advance')
        if s0[i_lim] == '1':
            self.goto_cursor(4, i_lim)
            self.enter()
            d3 = self.pos_or_disp()
            self.check('speed limit OFF forces the speed limit advance OFF (ENV-1 contract)', d3[i_lim] == '0' and d3[i_adv] == '0', d3)
            self.enter()
            d4 = self.pos_or_disp()
            self.check('speed limit back ON leaves the advance as it was set (OFF)', d4[i_lim] == '1' and d4[i_adv] == '0', d4)
        else:
            self.log('speed limit starts OFF: the interlock part is skipped')
        # restore every switch to its start value, whatever the interlock left behind
        for _ in range(3):
            now = self.pos_or_disp()
            wrong = [i for i in range(len(KEYS)) if now[i] != s0[i]]
            if not wrong:
                break
            self.goto_cursor(4, wrong[0])
            self.enter()
        final = self.pos_or_disp()
        self.check('every HUD switch is back to its start value', final == s0, '%s (start %s)' % (final, s0))
        e, _ = self.send('BACKSPACE')
        p = self.pos()
        self.check('Backspace on the environment settings returns to the main menu', p['state'] == 1 and p['cursor'] == 0, p)

        # -- close and reopen -------------------------------------------------------------------------------------------------------------------------------------
        e, _ = self.send('F1')
        self.check('F1 closes the menu (state 0)', e['kv'].get('state') == '0', e['kv'])
        self.check('the HUD switches are unchanged after closing', e['kv'].get('disp') == s0, '%s (start %s)' % (e['kv'].get('disp'), s0))
        e, _ = self.send('F1')
        self.check('F1 reopens the main menu (state 1, cursor 0)', e['kv'].get('state') == '1' and e['kv'].get('cursor') == '0', e['kv'])
        e, _ = self.send('F1')
        self.check('F1 closes it again (state 0)', e['kv'].get('state') == '0', e['kv'])

    def pos_or_disp(self):
        """the HUD switches as of the newest event that carries them"""
        for e in reversed(self.plog.events()):
            if 'disp' in e['kv'] and e['kv']['disp'] not in ('?', ''):
                return e['kv']['disp']
        raise Inconclusive('no event carries the HUD switches')


def write_report(path, result, extra=None):
    out = dict(result)
    out.update(extra or {})
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
