"""F1 menu autonomous LIVE test: starts BVE (or attaches to a running one) with the probe armed through the environment, injects keys with scan codes while BVE is in
front, and runs tests/live/f1_flow.py. Exit code: 0 PASS, 1 FAIL (a check of the F1 contract did not hold), 2 INCONCLUSIVE (the setup did not hold), 3 usage / BVE did not start.

  python tests\\live\\f1_autonomous.py --scenario "C:\\Users\\<you>\\Documents\\Bvets\\Scenarios\\iida_sanmpe.txt" [--exe <BveTs.exe>] [--out <dir>] [--keep-bve]
  python tests\\live\\f1_autonomous.py --attach <pid> --probe-log <file>      (a BVE that was started with PYTHONPATH=tests\\live\\probe and TSPROBE_LOG=<file>)

The PC must be left alone while it runs (BVE comes to the front, the keys go to it). It changes no file: F1 settings are not persisted, every switch it changes is
reverted and the end state is compared with the start state. Needs BVE 6 with TScoring installed and a scenario that loads quickly. NOT part of the regression runs.
"""
import argparse
import datetime
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import f1_flow  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--scenario')
    ap.add_argument('--exe')
    ap.add_argument('--attach', type=int)
    ap.add_argument('--probe-log')
    ap.add_argument('--out')
    ap.add_argument('--keep-bve', action='store_true')
    ap.add_argument('--load-timeout', type=int, default=400)
    a = ap.parse_args()
    if not a.attach and not a.scenario:
        ap.error('--scenario (or --attach with --probe-log)')
    import live_support as ls
    out = a.out or os.path.join(tempfile.gettempdir(), 'tscoring-live', datetime.datetime.now().strftime('%Y%m%d-%H%M%S'))
    os.makedirs(out, exist_ok=True)
    plog_path = a.probe_log or os.path.join(out, 'probe.log')
    log_file = open(os.path.join(out, 'run.log'), 'a', encoding='utf-8')

    def log(*parts):
        line = '%s %s' % (datetime.datetime.now().strftime('%H:%M:%S.%f')[:-3], ' '.join(str(p) for p in parts))
        print(line, flush=True)
        log_file.write(line + '\n')
        log_file.flush()

    pid = a.attach
    started_here = False
    if pid is None:
        os.environ['PYTHONPATH'] = os.path.join(HERE, 'probe') + (os.pathsep + os.environ['PYTHONPATH'] if os.environ.get('PYTHONPATH') else '')
        os.environ['TSPROBE_LOG'] = plog_path                    # BVE -> Caller -> the TScoring python child inherit it; only a main.py reacts
        try:
            pid = ls.start_bve(a.scenario, a.exe or ls.BVE6)
        except (RuntimeError, FileNotFoundError) as e:
            log('cannot start BVE:', e)
            return 3
        started_here = True
        if pid is None:
            log('BVE did not appear')
            return 3
        log('BVE started, pid', pid)
    elif not a.probe_log:
        ap.error('--attach needs --probe-log')
    plog = f1_flow.ProbeLog(plog_path)
    end = time.time() + a.load_timeout
    while time.time() < end and not any(e['kind'] == 'ARMED' for e in plog.events()):
        if pid not in ls.bve_pids():
            break
        time.sleep(1.0)
    time.sleep(2.0)
    w = ls.main_window(pid)
    if w is None:
        log('INCONCLUSIVE: BVE has no main window')
        return 2
    flow = f1_flow.Flow(ls.BveTransport(pid, w['hwnd']), plog, require_armed=True, log=log)
    result = flow.run()
    f1_flow.write_report(os.path.join(out, 'result.json'), result, {'bve_pid': pid, 'probe_log': plog_path, 'finished': datetime.datetime.now().isoformat(timespec='seconds')})
    log('VERDICT', result['verdict'], '-', result['why'])
    if started_here and not a.keep_bve:
        log('BVE closed' if ls.close_bve(pid) else 'BVE did not close in time (left running)')
    return {'PASS': 0, 'FAIL': 1, 'INCONCLUSIVE': 2}[result['verdict']]


if __name__ == '__main__':
    sys.exit(main())
