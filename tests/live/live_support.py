"""Windows side of the live tests: key injection WITH SCAN CODES, the foreground window, starting / closing BVE. Self-contained (pywin32 only).

Why scan codes: BVE ignores injected keys, but TScoring reads its keys through a keyboard hook while BVE is in front (Overlay._handle_keys: keyboard.is_pressed +
is_bve_active); that hook identifies a key by its scan code, so keybd_event(vk, MapVirtualKey(vk), ...) reaches it. F1 needs no on-screen keyboard.
Safety: a key is sent ONLY while the foreground window belongs to the BVE process; otherwise the foreground is taken (AttachThreadInput, never a blind ALT tap, which
puts BVE into system-menu mode and stalls it) and, if that fails, the caller is told (INCONCLUSIVE), nothing is typed into another application.
"""
import ctypes
import os
import subprocess
import time
from ctypes import wintypes

import win32api
import win32con
import win32gui
import win32process

VK = {'F1': 0x70, 'ENTER': 0x0D, 'BACKSPACE': 0x08, 'UP': 0x26, 'DOWN': 0x28, 'LEFT': 0x25, 'RIGHT': 0x27}
EXTENDED = {0x26, 0x28, 0x25, 0x27, 0x2E, 0x24, 0x23}
BVE6 = r'C:\Program Files\mackoy\BveTs6\BveTs.exe'


def fg_pid():
    h = win32gui.GetForegroundWindow()
    return win32process.GetWindowThreadProcessId(h)[1] if h else 0


def bve_pids(exe_name='BveTs.exe'):
    out = subprocess.run(['tasklist', '/FI', 'IMAGENAME eq %s' % exe_name, '/FO', 'CSV', '/NH'], capture_output=True, text=True, encoding='utf-8', errors='replace').stdout
    return [int(line.split('","')[1]) for line in out.splitlines() if line.startswith('"')]


def windows(pid):
    rows = []

    def cb(h, _):
        if win32process.GetWindowThreadProcessId(h)[1] == pid:
            rows.append({'hwnd': h, 'visible': bool(win32gui.IsWindowVisible(h)), 'rect': win32gui.GetWindowRect(h), 'title': win32gui.GetWindowText(h), 'class': win32gui.GetClassName(h)})
        return True
    win32gui.EnumWindows(cb, None)
    return rows


def main_window(pid):
    for w in windows(pid):
        if w['visible'] and w['title'].lower().startswith('bve') and (w['rect'][2] - w['rect'][0]) > 300:
            return w
    return None


def bring_fg(hwnd):
    """foreground by AttachThreadInput; leaves the system-menu mode if the window was in it. Returns True when the window's process is in front afterwards."""
    if win32gui.IsIconic(hwnd):
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
    try:
        fg = win32gui.GetForegroundWindow()
        if fg != hwnd:
            cur = ctypes.windll.kernel32.GetCurrentThreadId()
            fgt = win32process.GetWindowThreadProcessId(fg)[0] if fg else 0
            tgt = win32process.GetWindowThreadProcessId(hwnd)[0]
            others = {fgt, tgt} - {cur, 0}
            for o in others:
                ctypes.windll.user32.AttachThreadInput(cur, o, True)
            try:
                win32gui.SetForegroundWindow(hwnd)
            finally:
                for o in others:
                    ctypes.windll.user32.AttachThreadInput(cur, o, False)
    except Exception:
        pass
    time.sleep(0.4)
    try:
        class _GTI(ctypes.Structure):
            _fields_ = [('cbSize', wintypes.DWORD), ('flags', wintypes.DWORD), ('hwndActive', wintypes.HWND), ('hwndFocus', wintypes.HWND), ('hwndCapture', wintypes.HWND),
                        ('hwndMenuOwner', wintypes.HWND), ('hwndMoveSize', wintypes.HWND), ('hwndCaret', wintypes.HWND), ('rcCaret', wintypes.RECT)]
        g = _GTI()
        g.cbSize = ctypes.sizeof(g)
        ctypes.windll.user32.GetGUIThreadInfo(win32process.GetWindowThreadProcessId(hwnd)[0], ctypes.byref(g))
        if (g.flags & 4) or g.hwndMenuOwner:                     # system-menu mode: one ALT tap leaves it
            win32api.keybd_event(0x12, 0, 0, 0)
            time.sleep(0.05)
            win32api.keybd_event(0x12, 0, win32con.KEYEVENTF_KEYUP, 0)
            time.sleep(0.4)
    except Exception:
        pass
    return win32process.GetWindowThreadProcessId(win32gui.GetForegroundWindow())[1] == win32process.GetWindowThreadProcessId(hwnd)[1]


class BveTransport(object):
    """Transport of tests/live/f1_flow.py: a key into the real BVE (foreground-guarded)."""

    def __init__(self, pid, hwnd, hold=0.15):
        self.pid, self.hwnd, self.hold = pid, hwnd, hold

    def press(self, key):
        if fg_pid() != self.pid and not bring_fg(self.hwnd):
            from f1_flow import Inconclusive
            raise Inconclusive('BVE could not be brought to the foreground (foreground pid %s): nothing was typed' % fg_pid())
        if win32api.GetAsyncKeyState(win32con.VK_LBUTTON) & 0x8000:
            from f1_flow import Inconclusive
            raise Inconclusive('the left mouse button is down (the PC is in use): nothing was typed')
        vk = VK[key]
        ext = win32con.KEYEVENTF_EXTENDEDKEY if vk in EXTENDED else 0
        win32api.keybd_event(vk, win32api.MapVirtualKey(vk, 0), ext, 0)
        time.sleep(self.hold)                                    # long enough for one 16 ms poll, shorter than the 0.4 s key-repeat threshold of the arrow keys
        win32api.keybd_event(vk, win32api.MapVirtualKey(vk, 0), ext | win32con.KEYEVENTF_KEYUP, 0)


def start_bve(scenario, exe=BVE6, timeout=90):
    """starts BVE with the scenario file as its command-line argument; returns the new pid (None when it did not appear)."""
    before = set(bve_pids())
    if before:
        raise RuntimeError('a BveTs.exe is already running: %s' % sorted(before))
    if not os.path.exists(scenario):
        raise FileNotFoundError(scenario)
    subprocess.Popen([exe, scenario], cwd=os.path.dirname(exe))
    end = time.time() + timeout
    while time.time() < end:
        new = [p for p in bve_pids() if p not in before]
        if new and main_window(new[0]):
            return new[0]
        time.sleep(0.3)
    return None


def close_bve(pid, timeout=30):
    """closes BVE the way a user does (WM_CLOSE to its main window); never kills it. Returns True when the process is gone. (A SlimDX exit crash of BVE is known and not ours.)"""
    w = main_window(pid)
    if w:
        win32gui.PostMessage(w['hwnd'], win32con.WM_CLOSE, 0, 0)
    end = time.time() + timeout
    while time.time() < end:
        if pid not in bve_pids():
            return True
        time.sleep(0.5)
    return pid not in bve_pids()
