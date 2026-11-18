# PHASE S05-FIX (read-only Pause pulse gate) - deterministic unit suite + mutation check for Shared\PausePulseGate.cs (the gate shared by the four pulse senders).
# The gate source is compiled in memory (the file is never changed), driven with a FAKE clock (no sleep, fully deterministic), and judged against the pulse contract (Owner decisions DQ-0..DQ-5):
#   INV-P1 at most one pending request            INV-P2 a request made in another scenario epoch is discarded
#   INV-P3 no read / no post from teardown until read-ready                INV-P4' ScenarioCreated alone is not a read permission: the epoch must be stable for 500 ms (restarted by every generation event)
#   INV-P5 nothing after Dispose                   INV-P6 a formal Tick suppresses the pulse (request time and callback time)
#   plus: the pending request is always released, the running slot is released by Complete, a lost Post is recoverable.
# Then every mutant of the gate (a rule removed) must be killed by at least one unit check (mutation check). ASCII-only on purpose. Windows PowerShell 5.1.
#   exit 0 = suite green and every mutant killed; 1 = a unit check failed; 2 = a mutant survived / the harness is broken.
param(
    [string]$GateSource = '',
    [string]$RepositoryRoot = '',
    [string]$OutFile = '',
    [switch]$NoMutation
)
Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not $GateSource) { $GateSource = Join-Path (Split-Path $here -Parent) 'Telemetry\Shared\PausePulseGate.cs' }      # $RepositoryRoot is accepted for the regression runner; the gate source is always the one next to this script's tree
$original = [IO.File]::ReadAllText($GateSource)

$script:clock = [long]0
$script:seq = 0

function New-GateType([string]$source, [string]$ns) {
    $s = $source.Replace('namespace TSScoringPlugin.Pulse', 'namespace ' + $ns).Replace('internal ', 'public ')
    Add-Type -TypeDefinition $s -Language CSharp -IgnoreWarnings -ErrorAction Stop
    $asm = [AppDomain]::CurrentDomain.GetAssemblies() | Where-Object { $_.GetType($ns + '.PausePulseGate', $false) } | Select-Object -First 1
    return $asm.GetType($ns + '.PausePulseGate')
}

function New-Gate($type) {
    $fn = [Func[long]]{ $script:clock }
    $ctor = $type.GetConstructor([Type[]]@([Func[long]], [long], [long]))
    return $ctor.Invoke(@($fn, [long]150, [long]500))
}

function Req($g) { $e = 0; $ok = $g.TryRequest([ref]$e); return [pscustomobject]@{ Ok = [bool]$ok; Epoch = [int]$e } }

function Invoke-Suite($type) {
    $r = New-Object System.Collections.Generic.List[object]
    function Add-Check([string]$id, [string]$text, [bool]$ok) { $r.Add([pscustomobject]@{ Id = $id; Ok = $ok; Text = $text }) }

    # U1 / INV-P3: nothing is requested before the first ScenarioCreated, and after Opened (teardown)
    $script:clock = 10000; $g = New-Gate $type
    Add-Check 'U1' 'INV-P3: no request before any ScenarioCreated (not read-ready)' (-not (Req $g).Ok)
    $g.OnScenarioOpenedOrClosed()
    for ($i = 0; $i -lt 40; $i++) { $script:clock += 16; [void](Req $g) }
    Add-Check 'U2' 'INV-P3: 40 timer firings during a teardown (Opened, no Created) post nothing and reserve nothing' (($g.Requested -eq 0) -and ($g.Pending -eq 0))

    # U3 / INV-P4': the settle boundary (ready exactly 500 ms after ScenarioCreated)
    $script:clock = 20000; $g = New-Gate $type
    $g.OnScenarioOpenedOrClosed(); $g.OnScenarioCreated()
    $a0 = (Req $g).Ok; $script:clock += 499; $a1 = (Req $g).Ok; $script:clock += 1; $a2 = (Req $g).Ok
    Add-Check 'U3' 'INV-P4: ScenarioCreated alone is no permission: refused at +0 and +499 ms, granted at +500 ms' ((-not $a0) -and (-not $a1) -and $a2)

    # U3b / INV-P4': the PRODUCT default settle (Owner 2026-11-17, design 1'; 150 ms provisional, 100 ms final from 2026-11-18; was 500 ms). The suite above runs the rules at an explicit 500 ms; this one pins the shipped value and its boundary.
    $defSettle = [long]$type.GetField('DefaultSettleMs').GetRawConstantValue(); $defGap = [long]$type.GetField('DefaultGapMs').GetRawConstantValue()
    $script:clock = 25000; $fn = [Func[long]]{ $script:clock }
    $g = $type.GetConstructor([Type[]]@([Func[long]], [long], [long])).Invoke(@($fn, $defGap, $defSettle))
    $g.OnScenarioOpenedOrClosed(); $g.OnScenarioCreated()
    $d0 = (Req $g).Ok; $script:clock += ($defSettle - 1); $d1 = (Req $g).Ok; $script:clock += 1; $d2 = (Req $g).Ok
    Add-Check 'U3b' 'INV-P4: the product default settle is 100 ms (gap 150 ms): refused at +0 and +99 ms, granted at +100 ms' (($defSettle -eq 100) -and ($defGap -eq 150) -and (-not $d0) -and (-not $d1) -and $d2)

    # U4 / INV-P4' at callback time: a request made while ready, then Created again, is refused until settled even with the current epoch
    $script:clock = 30000; $g = New-Gate $type
    $g.OnScenarioCreated(); $script:clock += 600
    $g.OnScenarioCreated()
    $cur = $g.Epoch
    Add-Check 'U4' 'INV-P4: TryEnter right after ScenarioCreated (current epoch) is refused until the settle window has passed' (-not $g.TryEnter($cur))
    $script:clock += 500
    $ent = $g.TryEnter($cur)
    Add-Check 'U4b' 'INV-P4: and granted once 500 ms passed' ($ent)
    $g.Complete()

    # U5 / INV-P1: 500 ms and 1000 ms UI stalls at the 16 ms Telemetry period and 50 ms Bridge period leave one pending request
    foreach ($spec in @(@('500ms/16ms', 500, 16), @('1000ms/16ms', 1000, 16), @('500ms/50ms', 500, 50), @('1000ms/50ms', 1000, 50))) {
        $script:clock = 40000; $g = New-Gate $type
        $g.OnScenarioCreated(); $script:clock += 600
        $granted = 0; $n = [int][math]::Floor($spec[1] / $spec[2])
        for ($i = 0; $i -lt $n; $i++) { if ((Req $g).Ok) { $granted++ }; $script:clock += $spec[2] }
        Add-Check ('U5-' + $spec[0]) ('INV-P1: a stall of ' + $spec[0] + ' (' + $n + ' firings) grants ' + $granted + ' request(s), pending=' + $g.Pending + ' (limit 1)') (($granted -eq 1) -and ($g.Pending -eq 1) -and ($g.Coalesced -eq ($n - 1)))
    }

    # U6: the request is released by TryEnter whatever the verdict; the next request is possible
    $script:clock = 50000; $g = New-Gate $type
    $g.OnScenarioCreated(); $script:clock += 600
    $q = Req $g; $okEnter = $g.TryEnter($q.Epoch); $g.Complete()
    $q2 = Req $g
    Add-Check 'U6' 'after TryEnter + Complete the pending request is released and a new one is granted' ($q.Ok -and $okEnter -and ($g.Pending -eq 1) -and $q2.Ok)

    # U7 / INV-P2: a request of epoch N is discarded after a scenario change (Closed, Opened, Created) even when settled again
    $script:clock = 60000; $g = New-Gate $type
    $g.OnScenarioCreated(); $script:clock += 600
    $old = Req $g
    $g.OnScenarioOpenedOrClosed(); $g.OnScenarioOpenedOrClosed(); $g.OnScenarioCreated(); $script:clock += 600
    $stale0 = $g.DiscardedStale
    $staleEnter = $g.TryEnter($old.Epoch)
    Add-Check 'U7' 'INV-P2: a request made in the old generation is refused in the new one (no body entry), counted as stale' ((-not $staleEnter) -and ($g.DiscardedStale -eq ($stale0 + 1)) -and ($g.Pending -eq 0))
    $fresh = Req $g
    Add-Check 'U7b' 'INV-P2: the next request (new epoch) is granted and enters' ($fresh.Ok -and $g.TryEnter($fresh.Epoch))
    $g.Complete()

    # U8: a re-created scenario (Created again, no Opened) also invalidates the outstanding request
    $script:clock = 70000; $g = New-Gate $type
    $g.OnScenarioCreated(); $script:clock += 600
    $old = Req $g
    $g.OnScenarioCreated(); $script:clock += 600
    Add-Check 'U8' 'INV-P2: a second ScenarioCreated bumps the epoch: the older request is refused' (-not $g.TryEnter($old.Epoch))

    # U9 / settle restart: a generation event inside the settle window restarts it from zero
    $script:clock = 80000; $g = New-Gate $type
    $g.OnScenarioCreated(); $script:clock += 300
    $g.OnScenarioOpenedOrClosed(); $g.OnScenarioCreated()
    $script:clock += 300; $early = (Req $g).Ok
    $script:clock += 199; $early2 = (Req $g).Ok
    $script:clock += 1; $late = (Req $g).Ok
    Add-Check 'U9' 'INV-P4: Opened+Created at +300 restarts the settle window: refused at +600 and +799 from the first Created, granted at +500 from the second' ((-not $early) -and (-not $early2) -and $late)

    # U10: Opened during the settle window stops everything until the next Created has settled
    $script:clock = 90000; $g = New-Gate $type
    $g.OnScenarioCreated(); $script:clock += 400
    $g.OnScenarioOpenedOrClosed(); $script:clock += 5000
    $none = (Req $g).Ok
    $g.OnScenarioCreated(); $script:clock += 500
    Add-Check 'U10' 'INV-P3: Opened during the settle window keeps the gate shut however long it takes; the next Created re-opens it after 500 ms' ((-not $none) -and (Req $g).Ok)

    # U11: requests during the settle window are not stacked: after read-ready exactly one request is granted
    $script:clock = 100000; $g = New-Gate $type
    $g.OnScenarioCreated(); $granted = 0
    for ($i = 0; $i -lt 40; $i++) { $script:clock += 16; if ((Req $g).Ok) { $granted++ } }
    Add-Check 'U11' 'settle window: 40 firings in 640 ms grant exactly one request, and it is granted only after read-ready' (($granted -eq 1) -and ($g.Requested -eq 1))

    # U12 / INV-P5: Dispose
    $script:clock = 110000; $g = New-Gate $type
    $g.OnScenarioCreated(); $script:clock += 600
    $q = Req $g
    $g.Dispose()
    Add-Check 'U12' 'INV-P5: after Dispose a queued request does not enter the body' (-not $g.TryEnter($q.Epoch))
    Add-Check 'U12b' 'INV-P5: after Dispose nothing is requested' (-not (Req $g).Ok)
    Add-Check 'U12c' 'INV-P5: Dispose makes the gate not read-ready' (-not $g.IsReadReady)

    # U13 / INV-P6: formal Tick
    $script:clock = 120000; $g = New-Gate $type
    $g.OnScenarioCreated(); $script:clock += 600
    $g.NoteTick()
    $script:clock += 150; $t0 = (Req $g).Ok
    $script:clock += 1; $t1 = (Req $g).Ok
    Add-Check 'U13' 'INV-P6: no request within 150 ms after a formal Tick, granted at 151 ms' ((-not $t0) -and $t1)
    $script:clock = 130000; $g = New-Gate $type
    $g.OnScenarioCreated(); $script:clock += 600
    $q = Req $g
    $g.NoteTick(); $script:clock += 20
    Add-Check 'U14' 'INV-P6: a request queued before the formal Tick resumed is refused at callback time (counted as tick)' ((-not $g.TryEnter($q.Epoch)) -and ($g.DiscardedTick -eq 1))

    # U15: the running slot
    $script:clock = 140000; $g = New-Gate $type
    $g.OnScenarioCreated(); $script:clock += 600
    $q = Req $g; $first = $g.TryEnter($q.Epoch)
    $second = $g.TryEnter($q.Epoch)
    $g.Complete()
    Add-Check 'U15' 'ownership: a second callback while the first runs is refused (re-entry); after Complete the slot is free' ($first -and (-not $second) -and ($g.DiscardedReentry -eq 1) -and $g.TryEnter($q.Epoch))

    # U16: a request that is lost (Post failed) is cancellable; a request never consumed expires
    $script:clock = 150000; $g = New-Gate $type
    $g.OnScenarioCreated(); $script:clock += 600
    $q = Req $g; $g.CancelRequest()
    Add-Check 'U16' 'a failed Post is cancelled: pending is 0 and a new request is granted' (($g.Pending -eq 0) -and (Req $g).Ok)
    $script:clock = 160000; $g = New-Gate $type
    $g.OnScenarioCreated(); $script:clock += 600
    [void](Req $g)
    $script:clock += 9999; $notYet = (Req $g).Ok
    $script:clock += 2; $expired = (Req $g).Ok
    Add-Check 'U17' 'a lost request (never consumed) is replaced after 10 s, not before; counted as expired' ((-not $notYet) -and $expired -and ($g.Expired -eq 1))

    # U18: the discard counters are consistent (nothing is lost silently)
    $script:clock = 170000; $g = New-Gate $type
    $g.OnScenarioCreated(); $script:clock += 600
    $q = Req $g; [void]$g.TryEnter($q.Epoch); $g.Complete()
    Add-Check 'U18' 'diagnostics: Requested=1 Entered=1 and every discard counter is 0 on the happy path' (($g.Requested -eq 1) -and ($g.Entered -eq 1) -and ($g.DiscardedStale + $g.DiscardedNotReady + $g.DiscardedTick + $g.DiscardedDisposed + $g.DiscardedReentry -eq 0))
    return $r
}

function Find-Nth([string]$text, [string]$needle, [int]$nth) {
    $idx = -1
    for ($k = 0; $k -lt $nth; $k++) { $idx = $text.IndexOf($needle, $idx + 1, [StringComparison]::Ordinal); if ($idx -lt 0) { return -1 } }
    return $idx
}

$lines = New-Object System.Collections.Generic.List[string]
function Out-Line([string]$s) { $lines.Add($s); Write-Host $s }

# ---- 1. the real gate ------------------------------------------------------------------------------------------------------------------------------------------------
$script:seq++
$realType = New-GateType $original ('GateReal' + $script:seq)
$suite = Invoke-Suite $realType
$bad = @($suite | Where-Object { -not $_.Ok })
foreach ($c in $suite) { Out-Line (('{0} {1} {2}' -f $(if ($c.Ok) { 'PASS' } else { 'FAIL' }), $c.Id, $c.Text)) }
Out-Line ('SUMMARY unit checks=' + $suite.Count + ' failed=' + $bad.Count)

# ---- 2. mutation check ----------------------------------------------------------------------------------------------------------------------------------------------
$survivors = New-Object System.Collections.Generic.List[string]
$equivalent = 0
$mutants = @(
    @{ Id = 'M01-coalescing-removed'; Find = 'if (Interlocked.CompareExchange(ref pending, 1, 0) != 0)'; Nth = 1; Replace = 'if (false)' },
    @{ Id = 'M02-generation-check-removed'; Find = 'if (requestEpoch != Volatile.Read(ref epoch))'; Nth = 1; Replace = 'if (false)' },
    @{ Id = 'M03-settle-removed'; Find = 'Interlocked.Exchange(ref readyAtMs, nowMs() + settleMs);'; Nth = 1; Replace = 'Interlocked.Exchange(ref readyAtMs, nowMs());' },
    @{ Id = 'M04-teardown-guard-removed'; Find = 'Interlocked.Exchange(ref readyAtMs, NotReady);'; Nth = 1; Replace = ';' },
    @{ Id = 'M05a-dispose-guard-removed-request'; Find = 'if (Volatile.Read(ref disposed) != 0)'; Nth = 1; Replace = 'if (false)' },
    @{ Id = 'M05b-dispose-guard-removed-enter'; Find = 'if (Volatile.Read(ref disposed) != 0)'; Nth = 2; Replace = 'if (false)' },
    @{ Id = 'M06-pending-release-removed'; Find = 'Interlocked.Exchange(ref pending, 0);      // the request is consumed whatever the verdict is'; Nth = 1; Replace = ';' },
    @{ Id = 'M07a-tick-guard-removed-request'; Find = 'if (now - Interlocked.Read(ref lastTickMs) <= gapMs)'; Nth = 1; Replace = 'if (false)' },
    @{ Id = 'M07b-tick-guard-removed-enter'; Find = 'if (now - Interlocked.Read(ref lastTickMs) <= gapMs)'; Nth = 2; Replace = 'if (false)' },
    @{ Id = 'M08-settle-restart-removed'; Find = 'Interlocked.Exchange(ref readyAtMs, nowMs() + settleMs);'; Nth = 1; Replace = 'Interlocked.CompareExchange(ref readyAtMs, nowMs() + settleMs, NotReady);' },
    @{ Id = 'M09-complete-removed'; Find = 'Volatile.Write(ref running, 0);'; Nth = 1; Replace = ';' },
    @{ Id = 'M10a-settle-guard-removed-request'; Find = 'if (now < Interlocked.Read(ref readyAtMs))'; Nth = 1; Replace = 'if (false)' },
    @{ Id = 'M10b-settle-guard-removed-enter'; Find = 'if (now < Interlocked.Read(ref readyAtMs))'; Nth = 2; Replace = 'if (false)' },
    @{ Id = 'M11-epoch-bump-removed-opened'; Find = 'Interlocked.Increment(ref epoch);'; Nth = 1; Replace = ';'; Equivalent = 'observably equivalent: OnScenarioOpenedOrClosed also makes the gate not ready, so a stale request is refused by the readiness check; the epoch bump is defense in depth' },
    @{ Id = 'M12-epoch-bump-removed-created'; Find = 'Interlocked.Increment(ref epoch);'; Nth = 2; Replace = ';' },
    @{ Id = 'M13-running-slot-removed'; Find = 'if (Interlocked.CompareExchange(ref running, 1, 0) != 0)'; Nth = 1; Replace = 'if (false)' },
    @{ Id = 'M14-pending-expiry-removed'; Find = 'if (now - Interlocked.Read(ref pendingSinceMs) > PendingExpireMs)'; Nth = 1; Replace = 'if (false)' },
    @{ Id = 'M15-cancel-request-noop'; Find = 'Interlocked.Exchange(ref pending, 0);' + "`n" + '        }' + "`n`n" + '        /// <summary>UI thread, the first statement'; Nth = 1; Replace = ';' + "`n" + '        }' + "`n`n" + '        /// <summary>UI thread, the first statement' }
)
if (-not $NoMutation) {
    Out-Line ''
    Out-Line ('--- mutation check: ' + $mutants.Count + ' mutants of the gate (each must be killed by at least one unit check)')
    foreach ($m in $mutants) {
        $pos = Find-Nth $original $m.Find $m.Nth
        if ($pos -lt 0) { Out-Line ('HARNESS ' + $m.Id + ': the mutation anchor was not found (the gate source changed?)'); $survivors.Add($m.Id + ' (anchor missing)'); continue }
        $mutated = $original.Substring(0, $pos) + $m.Replace + $original.Substring($pos + $m.Find.Length)
        $script:seq++
        try { $mt = New-GateType $mutated ('GateMut' + $script:seq) } catch { Out-Line ('HARNESS ' + $m.Id + ': the mutant does not compile: ' + $_.Exception.Message); $survivors.Add($m.Id + ' (no compile)'); continue }
        $res = Invoke-Suite $mt
        $killedBy = @($res | Where-Object { -not $_.Ok } | ForEach-Object { $_.Id })
        if ($killedBy.Count -gt 0) { Out-Line ('KILLED   ' + $m.Id + ' by ' + ($killedBy -join ',')) } elseif ($m.ContainsKey('Equivalent')) { Out-Line ('EQUIVALENT ' + $m.Id + ': ' + $m.Equivalent); $equivalent++ } else { Out-Line ('SURVIVED ' + $m.Id); $survivors.Add($m.Id) }
    }
    Out-Line ('SUMMARY mutants=' + $mutants.Count + ' equivalent=' + $equivalent + ' survived=' + $survivors.Count)
}

if ($OutFile) { [IO.File]::WriteAllLines($OutFile, $lines.ToArray(), (New-Object System.Text.UTF8Encoding($false))) }
if ($bad.Count -gt 0) { exit 1 }
if ($survivors.Count -gt 0) { exit 2 }
exit 0
