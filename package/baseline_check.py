"""Baseline guard for ALL deployed TScoring artifacts (Owner 2026-11-18: "make a structure that prevents omissions and wrong degradation when a baseline is raised").

Why: artifact_guard.py protects ONE artifact (TelemetryA: SHA + capability ledger). TelemetryB / BridgeB / BridgeA / InputDevice (the Caller) had no ledger: their baselines lived in reports and memory, the pins in tests were edited by hand, and a pair
or a deploy location could be forgotten (omission) or a rebuild could silently lose features (degradation: the 2026-11-10 accident class). This module makes the baselines ONE tracked file and checks every raise against it.

  package/artifact-baselines.json         the single source of truth: per artifact the baseline SHA-256, source commit, deploy locations (every one), pair, rollback assets, evidence, and a string fingerprint file
  package/baselines/<name>.<sha8>.strings the string fingerprint of the baseline DLL: the .NET names (UTF-8 metadata heap) and string literals (UTF-16 user-string heap) it contains
  package/baselines/allowed-removals.json  intentional removals of a fingerprint string, each with a reason and an Owner reference (without an entry a lost string REFUSES the raise)

  verify                     read-only. Every deploy location holds the baseline SHA (all of them: the Caller has two), no unlisted TScoring.* file sits in a deploy folder, pairs are consistent, the TelemetryA baseline equals the artifact_guard ledger.
  plan --candidate NAME=PATH ... [--unchanged NAME ...] [--remote-ref REF] [--owner-approval ID] [--live-evidence TEXT]
                             read-only. REFUSES when: an artifact is neither a candidate nor declared unchanged (OMISSION); only one member of a pair is raised (PARTIAL PAIR); the candidate lost fingerprint strings that are not allowed
                             (DEGRADATION); a candidate is much smaller than the baseline; the live evidence is missing; the TelemetryA candidate fails artifact_guard (capability).
  promote --plan-json P      writes the new baselines + fingerprints, keeps the old baseline as a rollback asset. Only after a plan without findings.
Exit code 0 = ACCEPT, 1 = REFUSE / findings."""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
MANIFEST = os.path.join(HERE, 'artifact-baselines.json')
FP_DIR = os.path.join(HERE, 'baselines')
ALLOWED = os.path.join(FP_DIR, 'allowed-removals.json')
MIN_SIZE_RATIO = 0.80

_UTF8 = re.compile(rb'[A-Za-z_][A-Za-z0-9_.]{4,}')
_UTF16 = re.compile(rb'(?:[\x20-\x7e]\x00){6,}')
_GUID_LIKE = re.compile(r'^[0-9A-Fa-f]{16,}$')


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest().upper()


def fingerprint_bytes(data):
    """The set of identifier-like names (UTF-8) and string literals (UTF-16) in a .NET assembly image. A heuristic by design: it is a tripwire for LOST features, not a proof."""
    out = set()
    for m in _UTF8.findall(data):
        s = m.decode('ascii', 'ignore')
        if not _GUID_LIKE.match(s) and not s.startswith('RSDS') and 'b__' not in s and 'd__' not in s and '__c' not in s and 'DisplayClass' not in s and not re.search(r'__\d+$', s) and not re.match(r'^_*\d+(_\d+)*$', s.lstrip('_')):   # compiler-generated names / the PDB header are noise, not features
            out.add('n:' + s)
    for m in _UTF16.findall(data):
        s = m.decode('utf-16-le', 'ignore').strip()
        if len(s) >= 6 and not _GUID_LIKE.match(s):
            out.add('s:' + s)
    return out


def fingerprint_file(path):
    return fingerprint_bytes(open(path, 'rb').read())


def load_manifest(path=MANIFEST):
    return json.load(open(path, encoding='utf-8'))


def load_fp(art, root=None):
    p = os.path.join(root or HERE, 'baselines', os.path.basename(art['fingerprint']))
    if not os.path.exists(p):
        return None
    return set(l.rstrip('\n') for l in open(p, encoding='utf-8') if l.strip())


def load_allowed(path=ALLOWED):
    if not os.path.exists(path):
        return {}
    return {(e['artifact'], e['string']): e for e in json.load(open(path, encoding='utf-8')).get('allowed', [])}


def find(manifest, name):
    for a in manifest['artifacts']:
        if a['name'] == name:
            return a
    raise KeyError(name)


def verify(manifest, deploy_override=None):
    findings = []
    dirs = {}
    for a in manifest['artifacts']:
        for loc in a['deploy']:
            p = loc if not deploy_override else deploy_override(loc)
            dirs.setdefault(os.path.dirname(p), set()).add(os.path.basename(p))
            if not os.path.exists(p):
                findings.append('missing: %s (%s)' % (p, a['name']))
            elif sha256_file(p) != a['baseline']['sha256'].upper():
                findings.append('sha-mismatch: %s is %s, baseline %s' % (p, sha256_file(p)[:8], a['baseline']['sha256'][:8]))
    for d, listed in dirs.items():
        if os.path.isdir(d):
            for f in os.listdir(d):
                if f.lower().startswith('tscoring.') and f.lower().endswith('.dll') and f not in listed:
                    findings.append('unlisted TScoring file in a deploy folder: %s' % os.path.join(d, f))
    pairs = {}
    for a in manifest['artifacts']:
        if a.get('pair'):
            pairs.setdefault(a['pair'], set()).add(a['baseline'].get('promotedAt', '?') + '|' + a['baseline'].get('sourceCommit', '?')[:8])
    for pair, stamps in pairs.items():
        if len(stamps) > 1:
            findings.append('pair %s is not consistent (members differ in promotion date / source commit): %s' % (pair, sorted(stamps)))
    for a in manifest['artifacts']:
        fp = load_fp(a)
        if fp is None:
            findings.append('fingerprint file missing for %s' % a['name'])
    return findings


def plan(manifest, candidates, unchanged, live_evidence=None, owner_approval=None, remote_ref=None, allowed=None, ledger_check=None):
    """candidates: {name: path}; returns (findings, details)."""
    findings = []
    allowed = allowed if allowed is not None else load_allowed()
    names = [a['name'] for a in manifest['artifacts']]
    for n in candidates:
        if n not in names:
            findings.append('unknown artifact: %s' % n)
    unknown_un = [n for n in unchanged if n not in names]
    for n in unknown_un:
        findings.append('unknown unchanged artifact: %s' % n)
    for n in names:
        if n not in candidates and n not in unchanged:
            findings.append('OMISSION: %s is neither a candidate nor declared unchanged' % n)
        if n in candidates and n in unchanged:
            findings.append('contradiction: %s is both a candidate and unchanged' % n)
    pairs = {}
    for a in manifest['artifacts']:
        if a.get('pair'):
            pairs.setdefault(a['pair'], []).append(a['name'])
    for pair, members in pairs.items():
        raised = [m for m in members if m in candidates and sha256_file(candidates[m]) != find(manifest, m)['baseline']['sha256'].upper()]
        if raised and len(raised) != len(members) and not owner_approval:
            findings.append('PARTIAL PAIR: %s raised %s but not %s (a pair is raised together; an Owner approval id is needed otherwise)' % (pair, raised, [m for m in members if m not in raised]))
    details = {}
    for n, p in candidates.items():
        if n not in names:
            continue
        a = find(manifest, n)
        cand_sha = sha256_file(p)
        base_fp = load_fp(a) or set()
        cand_fp = fingerprint_file(p)
        lost = sorted(s for s in base_fp - cand_fp if (n, s) not in allowed)
        allowed_used = sorted(s for s in base_fp - cand_fp if (n, s) in allowed)
        ratio = os.path.getsize(p) / float(max(1, a['baseline'].get('size', os.path.getsize(p))))
        details[n] = {'sha256': cand_sha, 'baseline': a['baseline']['sha256'], 'changed': cand_sha != a['baseline']['sha256'].upper(), 'lost': lost, 'allowed_removals_used': allowed_used,
                      'size_ratio': round(ratio, 3), 'fingerprint_size': len(cand_fp), 'new_strings': len(cand_fp - base_fp)}
        if lost:
            findings.append('DEGRADATION: %s lost %d fingerprint string(s) that are not allowed: %s%s' % (n, len(lost), lost[:6], ' ...' if len(lost) > 6 else ''))
        if ratio < MIN_SIZE_RATIO:
            findings.append('DEGRADATION: %s is only %.0f %% of the baseline size' % (n, ratio * 100))
        if details[n]['changed'] and not live_evidence:
            findings.append('no live evidence given for %s (a raise needs the live acceptance reference)' % n)
        if details[n]['changed'] and ledger_check is not None:
            res = ledger_check(n, p)
            if res:
                findings.append(res)
    return findings, details


def promote(manifest, plan_details, evidence, source_commit, at, fp_root=HERE):
    new = json.loads(json.dumps(manifest))
    for a in new['artifacts']:
        d = plan_details.get(a['name'])
        if not d or not d['changed']:
            continue
        a.setdefault('rollback', []).append({'sha256': a['baseline']['sha256'], 'sourceCommit': a['baseline'].get('sourceCommit'), 'promotedAt': a['baseline'].get('promotedAt'), 'note': 'previous baseline (ordinary rollback target)'})
        a['baseline'] = {'sha256': d['sha256'], 'sourceCommit': source_commit, 'promotedAt': at, 'size': d.get('size'), 'evidence': evidence}
    return new


def _cli_verify(args):
    m = load_manifest(args.manifest)
    f = verify(m)
    for x in f:
        print('FINDING', x)
    print('RESULT: %s  artifacts=%d findings=%d' % ('ACCEPT' if not f else 'REFUSE', len(m['artifacts']), len(f)))
    return 0 if not f else 1


def _cli_plan(args):
    m = load_manifest(args.manifest)
    cands = dict(c.split('=', 1) for c in (args.candidate or []))

    def ledger_check(name, path):
        if name != 'TScoring.TelemetryA.dll':
            return None
        r = subprocess.run([sys.executable, '-B', os.path.join(HERE, 'artifact_guard.py'), 'check', '--stage', 'promote', '--dll', path, '--deployed', find(m, name)['deploy'][0],
                            '--remote-ref', args.remote_ref or 'origin/refactor/state-transitions'], capture_output=True, text=True)
        out = (r.stdout + r.stderr).strip().splitlines()
        return None if r.returncode == 0 else 'TelemetryA artifact_guard: ' + (out[-1] if out else 'refused')

    f, d = plan(m, cands, args.unchanged or [], args.live_evidence, args.owner_approval, args.remote_ref, ledger_check=ledger_check)
    for x in f:
        print('FINDING', x)
    for n, v in d.items():
        print('  %-26s %s -> %s  changed=%s lost=%d allowedRemovals=%d newStrings=%d sizeRatio=%s' % (n, v['baseline'][:8], v['sha256'][:8], v['changed'], len(v['lost']), len(v['allowed_removals_used']), v['new_strings'], v['size_ratio']))
    print('RESULT: %s  findings=%d' % ('ACCEPT' if not f else 'REFUSE', len(f)))
    return 0 if not f else 1


def _cli_promote(args):
    """Runs the same plan; only a plan without findings writes: the new manifest (old baseline kept as a rollback entry) and the fingerprint file of every raised artifact."""
    rc = _cli_plan(args)
    if rc != 0:
        print('NOT PROMOTED: the plan has findings')
        return 1
    m = load_manifest(args.manifest)
    cands = dict(c.split('=', 1) for c in (args.candidate or []))
    f, d = plan(m, cands, args.unchanged or [], args.live_evidence, args.owner_approval, args.remote_ref)
    for n, p in cands.items():
        d[n]['size'] = os.path.getsize(p)
    new = promote(m, d, args.live_evidence, args.source_commit, args.at)
    for a in new['artifacts']:
        if a['name'] in cands and d[a['name']]['changed']:
            fpname = '%s.%s.strings' % (a['name'], a['baseline']['sha256'][:8])
            os.makedirs(FP_DIR, exist_ok=True)
            open(os.path.join(FP_DIR, fpname), 'w', encoding='utf-8', newline='\n').write('\n'.join(sorted(fingerprint_file(cands[a['name']]))) + '\n')
            a['fingerprint'] = 'baselines/' + fpname
    new['updated'] = args.at
    open(args.manifest, 'w', encoding='utf-8', newline='\n').write(json.dumps(new, indent=1, ensure_ascii=False) + '\n')
    print('PROMOTED: manifest rewritten (%s); deploy the candidates yourself and run verify' % args.manifest)
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    sub = ap.add_subparsers(dest='cmd')
    v = sub.add_parser('verify'); v.add_argument('--manifest', default=MANIFEST)
    for name in ('plan', 'promote'):
        p = sub.add_parser(name); p.add_argument('--manifest', default=MANIFEST); p.add_argument('--candidate', action='append'); p.add_argument('--unchanged', action='append')
        p.add_argument('--remote-ref'); p.add_argument('--owner-approval'); p.add_argument('--live-evidence')
        if name == 'promote':
            p.add_argument('--source-commit', required=True); p.add_argument('--at', required=True)
    a = ap.parse_args(argv)
    if a.cmd == 'verify':
        return _cli_verify(a)
    if a.cmd == 'plan':
        return _cli_plan(a)
    if a.cmd == 'promote':
        return _cli_promote(a)
    ap.print_help()
    return 2


if __name__ == '__main__':
    sys.exit(main())
