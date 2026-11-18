# PHASE S05-FIX (read-only pulse contract) - deterministic integration fixture for the four pulse senders built with the shared PausePulseGate:
#   -Adapter Current: Class1 (TScoring.TelemetryB.dll) + the Current Bridge (TScoring.BridgeB.dll, real ScenarioReadyTracker)
#   -Adapter Legacy : the Legacy Telemetry extension (TScoring.TelemetryA.dll) + the Legacy Bridge (TScoring.BridgeA.dll, real ScenarioReadyTracker)
# It judges the contract of the read-only Pause pulse (Owner decisions DQ-0..DQ-5), not a past crash:
#   INV-P1 at most ONE pulse request is pending                       INV-P2 a request made in one scenario generation is dropped (no BVE read) when it runs in another
#   INV-P3 from the start of the teardown until read-ready the pulse does not read BVE (and posts nothing)
#   INV-P4 ScenarioCreated alone is no read permission: the first read comes 500 ms after the LAST generation event (a generation event inside the window restarts it); requests made in the window are
#          not stacked - after read-ready the newest generation is read exactly once                      INV-P5 after Dispose began no queued pulse reaches the body
#   INV-P6 after the formal Tick resumed a queued pulse does not touch the same state                      INV-P7 an exception inside a pulse never reaches the host UI thread
#   PP-13 contract (positive): after a Pause-time reload the pulse still establishes ScenarioReady without a Tick (Bridge) / still enters the body (Telemetry)
# No BVE, no BveEX runtime, no Python, no UDP, no hooks, no product DLL build, no deployment. The DLLs are loaded from memory (read only). By default the freshly BUILT DLLs of this work tree are used;
# -UseInstalled uses the deployed ones (a pre-fix deployment is expected to be RED). The Caller DLL (handshake session of a fake pid) is the installed one. The UI thread is a fake SynchronizationContext
# (Post only queues, the test drains by hand = a UI stall). The gate clock is a fake clock (no sleep). The product timers are never constructed: their private callbacks are invoked directly.
# Class1 / the Legacy session cannot be hosted: the first BVE read inside the pulse body throws a NullReferenceException that the product swallows; a first-chance exception monitor counts these as
# "the body was entered and tried to read BVE" (controls C0 prove the detector). Output: PASS = the invariant holds, FAIL = RED, CTRL-* = a control of the fixture itself (must be OK).
# Exit code: 0 all invariants hold and all controls are OK; 1 an invariant is violated; 2 a control failed / a prerequisite is missing. ASCII-only on purpose.
param(
    [string]$RepositoryRoot = '',      # accepted for the regression runner (Tests\Test-*.ps1 are started with -RepositoryRoot); -Root (the Handshake folder) wins when it is given
    [string]$Root = (Split-Path $PSScriptRoot -Parent),
    [ValidateSet('Current', 'Legacy')][string]$Adapter = 'Current',
    [string]$CallerDll = 'C:\Program Files\mackoy\BveTs6\Input Devices\TScoring.InputDevice.dll',
    [string]$BridgeDll = '',
    [string]$TelemetryDll = '',
    [string]$HostDir = '',
    [string]$OutDir = '',
    [switch]$UseInstalled
)
$publicDocs = Join-Path $env:PUBLIC 'Documents\BveEx'
if (-not $HostDir) { $HostDir = $(if ($Adapter -eq 'Legacy') { Join-Path $publicDocs 'Legacy' } else { Join-Path $publicDocs '2.0' }) }
if ($UseInstalled) {
    if (-not $BridgeDll) { $BridgeDll = Join-Path $HostDir $(if ($Adapter -eq 'Legacy') { 'Extensions\TScoring.BridgeA.dll' } else { 'Extensions\TScoring.BridgeB.dll' }) }
    if (-not $TelemetryDll) { $TelemetryDll = Join-Path $HostDir $(if ($Adapter -eq 'Legacy') { 'Extensions\TScoring.TelemetryA.dll' } else { 'Extensions\TScoring.TelemetryB.dll' }) }
} else {
. (Join-Path $PSScriptRoot '..\Tools\Resolve-TsArtifact.ps1')
    if (-not $BridgeDll) { $BridgeDll = $(if ($Adapter -eq 'Legacy') { (Require-TsArtifact $Root 'TScoring.BridgeA.dll') } else { (Require-TsArtifact $Root 'TScoring.BridgeB.dll') }) }
    if (-not $TelemetryDll) { $TelemetryDll = $(if ($Adapter -eq 'Legacy') { (Require-TsArtifact $Root 'TScoring.TelemetryA.dll') } else { Join-Path (Split-Path $Root -Parent) 'TsScoringPlugin\bin\Release\TScoring.TelemetryB.dll' }) }
}
foreach ($need in $CallerDll, $BridgeDll, $TelemetryDll) { if (-not (Test-Path -LiteralPath $need)) { Write-Host ('PREREQUISITE MISSING: ' + $need + ' (build the DLLs first, or pass -UseInstalled)'); exit 2 } }

Add-Type -TypeDefinition @'
using System;
using System.Collections.Generic;
using System.Reflection;
using System.Threading;

// the host's UI thread: Post only queues; the test drains by hand (a UI stall = nothing drains)
public class FakeSyncContext : SynchronizationContext
{
    private readonly List<SendOrPostCallback> queue = new List<SendOrPostCallback>();
    public int TotalPosts;
    public override void Post(SendOrPostCallback d, object s) { lock (queue) { queue.Add(d); TotalPosts++; } }
    public override void Send(SendOrPostCallback d, object s) { d(s); }
    public int Pending { get { lock (queue) { return queue.Count; } } }
    public int Drain()
    {
        int n = 0;
        while (true)
        {
            SendOrPostCallback d = null;
            lock (queue) { if (queue.Count == 0) break; d = queue[0]; queue.RemoveAt(0); }
            d(null);
            n++;
        }
        return n;
    }
}

// the fake BVE read of the Bridge tracker: records every read (the proof that BVE objects were touched)
public class ReaderProbe
{
    public object Snap;
    public bool Fail;
    private int reads;
    public object Read()
    {
        Interlocked.Increment(ref reads);
        if (Fail) { throw new System.IO.IOException("boom"); }
        return Snap;
    }
    public int Reads { get { return reads; } }
}

// counts the exceptions raised INSIDE the pulse body by the first BVE read (BveHacker / api unhosted): "the pulse body was entered and read BVE"
public static class BodyEntry
{
    private static int hits;
    public static int Hits { get { return hits; } }
    public static void Reset() { hits = 0; }
    public static void OnFirstChance(object s, System.Runtime.ExceptionServices.FirstChanceExceptionEventArgs e)
    {
        string st = new System.Diagnostics.StackTrace(false).ToString();
        string[] frames = st.Split(new char[] { '\n' }, StringSplitOptions.RemoveEmptyEntries);
        string top = frames.Length > 1 ? frames[1] : "";
        bool c1 = top.Contains("ScoringPlugin.TickCore(") && st.Contains("ScoringPlugin.PausePulse(");
        bool lg = top.Contains("LegacyTelemetrySession.TickCore(") && st.Contains("LegacyTelemetrySession.OnPulse(");
        if (e.Exception is NullReferenceException && (c1 || lg)) { Interlocked.Increment(ref hits); }
    }
    public static void Install() { AppDomain.CurrentDomain.FirstChanceException += OnFirstChance; }
}

public static class TestResolver
{
    public static void Install(string[] dirs)
    {
        AppDomain.CurrentDomain.AssemblyResolve += delegate (object s, ResolveEventArgs e)
        {
            string name = e.Name.Split(',')[0];
            foreach (string dir in dirs)
            {
                foreach (string ext in new string[] { ".dll", ".DLL" })
                {
                    string p = System.IO.Path.Combine(dir, name + ext);
                    if (System.IO.File.Exists(p)) { return Assembly.LoadFrom(p); }
                }
            }
            return null;
        };
    }
}

public class NoticeRecorder
{
    public int Count;
    public void Show(string text) { Interlocked.Increment(ref Count); }
}
'@

$ErrorActionPreference = 'Stop'
if (-not $OutDir) { $OutDir = Join-Path $Root ('logs\pulse-contract-s05\' + $Adapter) }
if (Test-Path $OutDir) { Remove-Item $OutDir -Recurse -Force }
New-Item -ItemType Directory -Force $OutDir | Out-Null
$NPI = [Reflection.BindingFlags]'NonPublic,Public,Instance'
$NPS = [Reflection.BindingFlags]'NonPublic,Public,Static'
$results = New-Object System.Collections.Generic.List[object]
function Rec([string]$kind, [string]$id, [string]$text, [bool]$ok) {
    $results.Add([pscustomobject]@{ Kind = $kind; Id = $id; Ok = $ok; Text = $text })
    $tag = if ($kind -eq 'CTRL') { if ($ok) { 'CTRL-OK ' } else { 'CTRL-BAD' } } else { if ($ok) { 'PASS    ' } else { 'FAIL    ' } }
    Write-Host ('{0} {1} {2}' -f $tag, $id, $text)
}
function Note([string]$text) { Write-Host ('NOTE     ' + $text) }

$script:clk = [long]1000000
$clockFn = [Func[long]]{ $script:clk }
function Adv([long]$ms) { $script:clk += $ms }

[TestResolver]::Install(@((Join-Path $env:ProgramW6432 'mackoy\BveTs6'), $HostDir))
if ($Adapter -eq 'Legacy') { [void][Reflection.Assembly]::LoadFrom((Join-Path $HostDir 'AtsEx.PluginHost.dll')) }
[BodyEntry]::Install()
Write-Host ('=== S05 pulse contract fixture, adapter: ' + $Adapter + $(if ($UseInstalled) { ' (INSTALLED DLLs)' } else { ' (built DLLs)' }) + ' ===')
$callerAsm = [Reflection.Assembly]::Load([IO.File]::ReadAllBytes($CallerDll))
$brAsm = [Reflection.Assembly]::Load([IO.File]::ReadAllBytes($BridgeDll))
$tlAsm = [Reflection.Assembly]::Load([IO.File]::ReadAllBytes($TelemetryDll))
foreach ($p in $CallerDll, $BridgeDll, $TelemetryDll) { Note ('loaded ' + (Split-Path $p -Leaf) + ' sha256=' + (Get-FileHash $p).Hash.Substring(0, 16)) }

function New-ProductGate($asm) {
    $gt = $asm.GetType('TSScoringPlugin.Pulse.PausePulseGate')
    if (-not $gt) { return $null }
    $ctor = $gt.GetConstructor($NPI, $null, [Type[]]@([Func[long]], [long], [long]), $null)
    return $ctor.Invoke(@($clockFn, [long]150, [long]500))
}
function GatePending($g) { return [int]$g.GetType().GetProperty('Pending', $NPI).GetValue($g) }
function GateRunning($g) { return [bool]$g.GetType().GetProperty('IsRunning', $NPI).GetValue($g) }
$gateMissing = $null -eq $tlAsm.GetType('TSScoringPlugin.Pulse.PausePulseGate')
if ($gateMissing -or $null -eq $brAsm.GetType('TSScoringPlugin.Pulse.PausePulseGate')) {
    Rec 'INV' 'INV-GATE' 'the product assemblies contain the shared PausePulseGate (a pre-fix build has none: every pulse invariant is then unprotected)' $false
    Write-Host 'SUMMARY invariants held=0 RED=1 controls-bad=0 (no gate in the assembly)'
    exit 1
}

# ----------------------------------------------------------------------------------------------------------------------------------------------------------------
# a sender is described by a small adapter object: how to create it, fire the scenario events, run a timer firing, tick, dispose, and how many times the BVE was read
# ----------------------------------------------------------------------------------------------------------------------------------------------------------------
function Test-Sender([string]$name, [scriptblock]$newSender, [int]$periodMs, [bool]$isBridge) {
    # $newSender returns an object with: Ctx, Gate, Fire($event), Timer(), Tick(), Dispose(), Reads() (BVE reads so far), Established() (Bridge: bool), Fail($bool), Cleanup()
    Write-Host ('--- ' + $name + ' (' + $periodMs + ' ms pulse)')
    function Settle($s) { $s.Fire('Opened'); $s.Fire('Created'); Adv 600 }
    function Stall($s, [int]$ms) { $n = [int][math]::Floor($ms / $periodMs); for ($i = 0; $i -lt $n; $i++) { $s.Timer(); Adv $periodMs }; return $n }

    # control: the detector sees a lone, legitimate pulse (settled, no Tick)
    $s = & $newSender; Settle $s; $r0 = $s.Reads(); $s.Timer(); [void]$s.Ctx.Drain(); $c0 = ($s.Reads() - $r0)
    Rec 'CTRL' ('C0/' + $name) ('detector / positive control: a settled pulse with no Tick posts ' + $s.Ctx.TotalPosts + ' request and enters the body ' + $c0 + ' time (expected 1 / 1)') (($s.Ctx.TotalPosts -eq 1) -and ($c0 -eq 1))
    if ($isBridge) { Rec 'INV' ('PP13/' + $name) ('PP-13 contract: the pulse establishes ScenarioReady after a Pause-time reload WITHOUT a formal Tick (established=' + $s.Established() + ')') ($s.Established()) }
    $s.Cleanup()

    # INV-P1 / UI stalls of 500 and 1000 ms
    foreach ($stall in 500, 1000) {
        $s = & $newSender; Settle $s
        $req = Stall $s $stall
        $posts = $s.Ctx.TotalPosts; $pend = $s.Ctx.Pending; $gp = GatePending $s.Gate
        $r0 = $s.Reads(); $exec = $s.Ctx.Drain(); $entered = $s.Reads() - $r0
        Rec 'INV' ('INV-P1/' + $name + '/stall' + $stall) ("a UI stall of $stall ms ($req firings) leaves $pend pending / $posts posted request(s) (limit 1); on resume $exec callback(s) ran and the body entered $entered time(s) (limit 1)") (($posts -le 1) -and ($pend -le 1) -and ($entered -le 1) -and ($gp -le 1))
        Rec 'CTRL' ('C1/' + $name + '/stall' + $stall) ('after the callbacks ran the gate has no pending request and no running slot') (((GatePending $s.Gate) -eq 0) -and (-not (GateRunning $s.Gate)))
        $s.Cleanup()
    }

    # INV-P3 teardown: either generation event alone (Closed, or Opened) shuts the gate until the next ScenarioCreated has settled
    foreach ($ev in 'Closed', 'Opened') {
        $s = & $newSender; Settle $s
        $s.Fire($ev)
        $r0 = $s.Reads(); $p0 = $s.Ctx.TotalPosts
        $req = Stall $s 1000
        [void]$s.Ctx.Drain()
        Rec 'INV' ('INV-P3/' + $name + '/' + $ev) ("during a teardown / reload (only $ev received, no Created yet) $req firings in 1000 ms posted " + ($s.Ctx.TotalPosts - $p0) + " request(s) and read BVE " + ($s.Reads() - $r0) + " time(s) (limit 0 / 0)") ((($s.Ctx.TotalPosts - $p0) -eq 0) -and (($s.Reads() - $r0) -eq 0))
        $s.Cleanup()
    }

    # INV-P4: right after ScenarioCreated, settle window, exactly one read at read-ready
    $s = & $newSender
    $s.Fire('Opened'); $s.Fire('Created')
    $r0 = $s.Reads(); $p0 = $s.Ctx.TotalPosts
    $fired = 0
    for ($t = 0; $t -lt 496; $t += $periodMs) { $s.Timer(); Adv $periodMs; $fired++ }
    [void]$s.Ctx.Drain()
    $inWindowReads = $s.Reads() - $r0; $inWindowPosts = $s.Ctx.TotalPosts - $p0
    Adv 20
    $s.Timer(); [void]$s.Ctx.Drain()
    $afterReads = $s.Reads() - $r0
    Rec 'INV' ('INV-P4/' + $name) ("inside the 500 ms settle window after ScenarioCreated ($fired firings) $inWindowPosts request(s) were posted and BVE was read $inWindowReads time(s) (limit 0 / 0); after the window exactly one read happened ($afterReads, expected 1)") (($inWindowPosts -eq 0) -and ($inWindowReads -eq 0) -and ($afterReads -eq 1))
    $s.Cleanup()

    # INV-P4: a generation event inside the settle window restarts it
    $s = & $newSender
    $s.Fire('Opened'); $s.Fire('Created'); Adv 300
    $s.Fire('Closed'); $s.Fire('Opened'); $s.Fire('Created')
    $r0 = $s.Reads(); $p0 = $s.Ctx.TotalPosts
    for ($t = 0; $t -lt 400; $t += 25) { Adv 25; $s.Timer() }       # 400 ms after the second Created (700 ms after the first): still inside the restarted window
    [void]$s.Ctx.Drain()
    $early = $s.Reads() - $r0; $earlyPosts = $s.Ctx.TotalPosts - $p0
    Adv 150; $s.Timer(); [void]$s.Ctx.Drain()
    $late = $s.Reads() - $r0
    Rec 'INV' ('INV-P4b/' + $name) ("a generation event at +300 ms restarts the settle window: 400 ms later $earlyPosts request(s) / $early read(s) (limit 0), 550 ms later $late read(s) (expected 1)") (($earlyPosts -eq 0) -and ($early -eq 0) -and ($late -eq 1))
    $s.Cleanup()

    # INV-P2: requests made in generation N, F5 during the stall, then the UI resumes
    $s = & $newSender; Settle $s
    $req = Stall $s 500
    $s.Fire('Closed'); $s.Fire('Opened'); $s.Fire('Created')       # F5 during the stall: generation N+1, created, NOT yet settled
    $r0 = $s.Reads(); $execStale = $s.Ctx.Drain(); $staleReads = $s.Reads() - $r0
    Rec 'INV' ('INV-P2/' + $name) ("$req firings were made in generation N; after an F5 during the stall the $execStale queued callback(s) read BVE $staleReads time(s) in generation N+1 (limit 0)") ($staleReads -eq 0)
    Adv 600; $s.Timer(); $r0 = $s.Reads(); [void]$s.Ctx.Drain()
    Rec 'INV' ('INV-P2b/' + $name) ('after read-ready the NEWEST generation is read exactly once (' + ($s.Reads() - $r0) + ')') (($s.Reads() - $r0) -eq 1)
    $s.Cleanup()

    # INV-P5: Dispose with a request queued
    $s = & $newSender; Settle $s
    $s.Timer(); $before = $s.Ctx.Pending
    $s.Dispose()
    $r0 = $s.Reads(); [void]$s.Ctx.Drain(); $afterDispose = $s.Reads() - $r0
    $p0 = $s.Ctx.TotalPosts; $s.Timer(); $s.Timer()
    Rec 'INV' ('INV-P5/' + $name) ("after Dispose began, $before queued request(s) ran and BVE was read $afterDispose time(s) (limit 0); further timer firings posted " + ($s.Ctx.TotalPosts - $p0) + " (limit 0)") (($afterDispose -eq 0) -and (($s.Ctx.TotalPosts - $p0) -eq 0))
    $s.Cleanup()

    # INV-P6: the formal Tick resumes with a request queued
    $s = & $newSender; Settle $s
    $s.Timer(); $s.Tick()
    $est0 = $s.EstablishedCount(); $r0 = $s.Reads(); [void]$s.Ctx.Drain(); $dup = $s.Reads() - $r0; $est1 = $s.EstablishedCount()
    $p0 = $s.Ctx.TotalPosts; for ($i = 0; $i -lt 5; $i++) { Adv 16; $s.Timer() }
    Rec 'INV' ('INV-P6/' + $name) ("after the formal Tick resumed the queued request read BVE $dup time(s) and changed the Established count $est0 -> $est1 (limit 0 / 0); the following timer firings within the gap posted " + ($s.Ctx.TotalPosts - $p0) + " (limit 0)") (($dup -eq 0) -and ($est0 -eq $est1) -and (($s.Ctx.TotalPosts - $p0) -eq 0))
    $s.Cleanup()

    # INV-P7: an exception inside the pulse never reaches the host; the gate is released
    $s = & $newSender; Settle $s
    $s.Fail($true)
    $s.Timer(); $leak = $null
    try { [void]$s.Ctx.Drain() } catch { $leak = $_.Exception.GetType().Name }
    Rec 'INV' ('INV-P7/' + $name) ("an exception inside the pulse body (BVE reads so far: " + $s.Reads() + ") does not escape to the host UI thread" + $(if ($leak) { " (LEAKED: $leak)" } else { '' })) (($null -eq $leak) -and ($s.Reads() -ge 1))
    Rec 'CTRL' ('C2/' + $name) 'after the exception the gate has no pending request and no running slot (the next pulse can run)' (((GatePending $s.Gate) -eq 0) -and (-not (GateRunning $s.Gate)))
    Adv 20; $s.Fail($false); $s.Timer(); $r0 = $s.Reads(); [void]$s.Ctx.Drain()
    Rec 'INV' ('INV-P7b/' + $name) ('after the exception the next pulse runs normally (BVE reads ' + ($s.Reads() - $r0) + ', expected 1)') (($s.Reads() - $r0) -eq 1)
    $s.Cleanup()
}

# ----------------------------------------------------------------------------------------------------------------------------------------------------------------
# senders
# ----------------------------------------------------------------------------------------------------------------------------------------------------------------
if ($Adapter -eq 'Current') {
    $c1Type = $tlAsm.GetType('TsScoringPlugin.ScoringPlugin')
    function C1Field([string]$n) { return $c1Type.GetField($n, $NPI) }
    $newC1 = {
        $o = [Runtime.Serialization.FormatterServices]::GetUninitializedObject($c1Type)
        $ctx = New-Object FakeSyncContext
        $gate = New-ProductGate $tlAsm
        (C1Field 'pulseContext').SetValue($o, $ctx)
        (C1Field 'pulseGate').SetValue($o, $gate)
        (C1Field 'lastTickTime').SetValue($o, [DateTime]::MinValue)
        (C1Field 'pulseDisposed').SetValue($o, $false)
        $tr = $c1Type.GetField('transport', $NPI)
        $tr.SetValue($o, [Activator]::CreateInstance($tr.FieldType, $true))
        [BodyEntry]::Reset()
        $h = [pscustomobject]@{ Obj = $o; Ctx = $ctx; Gate = $gate }
        $h | Add-Member -MemberType ScriptMethod -Name Fire -Value {
            param($e)
            $m = @{ Opened = 'OnPulseScenarioOpened'; Closed = 'OnPulseScenarioClosed'; Created = 'OnPulseScenarioCreated' }[$e]
            [void]$c1Type.GetMethod($m, $NPI).Invoke($this.Obj, @($null))
        }
        $h | Add-Member -MemberType ScriptMethod -Name Timer -Value { [void]$c1Type.GetMethod('PulseTimerCallback', $NPI).Invoke($this.Obj, @($null)) }
        $h | Add-Member -MemberType ScriptMethod -Name Tick -Value { try { [void]$c1Type.GetMethod('Tick').Invoke($this.Obj, @([TimeSpan]::Zero)) } catch { } }
        $h | Add-Member -MemberType ScriptMethod -Name Dispose -Value { try { [void]$c1Type.GetMethod('Dispose').Invoke($this.Obj, @()) } catch { } }
        $h | Add-Member -MemberType ScriptMethod -Name Reads -Value { return [BodyEntry]::Hits }
        $h | Add-Member -MemberType ScriptMethod -Name Established -Value { return $true }
        $h | Add-Member -MemberType ScriptMethod -Name EstablishedCount -Value { return 0 }
        $h | Add-Member -MemberType ScriptMethod -Name Fail -Value { param($b) }
        $h | Add-Member -MemberType ScriptMethod -Name Cleanup -Value { }
        return $h
    }
    Test-Sender 'Class1' $newC1 16 $false
    Note 'Class1: INV-P7 here observes the NullReferenceException the unhosted body raises (swallowed by the product); a second pulse after it must still run (INV-P7b)'
    # C-control: the re-entrancy guard and the gap guard of the component itself still stop the body
    $h = & $newC1; $h.Fire('Opened'); $h.Fire('Created'); Adv 600
    (C1Field 'pulseRunning').SetValue($h.Obj, $true); $h.Timer(); [void]$h.Ctx.Drain()
    Rec 'CTRL' 'C3/Class1' 'the component re-entrancy guard (pulseRunning) stops the body and releases the gate slot' (([BodyEntry]::Hits -eq 0) -and (-not (GateRunning $h.Gate)) -and ((GatePending $h.Gate) -eq 0))
    Note 'Class1 INV-P6: only the request / callback suppression after the Tick is observable (the Tick body cannot run unhosted); duplicate updates inside a real Tick vs pulse are covered by the gap re-check + the gate, not by a host run'
}

if ($Adapter -eq 'Legacy') {
    $lxType = @($tlAsm.GetTypes() | Where-Object { $_.Name -eq 'TsScoringLegacyTelemetryExtension' })[0]
    $lsType = @($tlAsm.GetTypes() | Where-Object { $_.Name -eq 'LegacyTelemetrySession' })[0]
    function LxField([string]$n) { return $lxType.GetField($n, $NPI) }
    $newLx = {
        $o = [Runtime.Serialization.FormatterServices]::GetUninitializedObject($lxType)
        $s = [Runtime.Serialization.FormatterServices]::GetUninitializedObject($lsType)
        $lsType.GetField('nowMs', $NPI).SetValue($s, ([Func[long]]{ 100000 }))
        $lsType.GetField('lastTickMs', $NPI).SetValue($s, [long]0)
        (LxField 'session').SetValue($o, $s)
        $ctx = New-Object FakeSyncContext
        $gate = New-ProductGate $tlAsm
        (LxField 'pulseContext').SetValue($o, $ctx)
        (LxField 'pulseGate').SetValue($o, $gate)
        [BodyEntry]::Reset()
        $h = [pscustomobject]@{ Obj = $o; Ctx = $ctx; Gate = $gate }
        $h | Add-Member -MemberType ScriptMethod -Name Fire -Value {
            param($e)
            $m = @{ Opened = 'OnScenarioOpened'; Closed = 'OnScenarioClosed'; Created = 'OnScenarioCreated' }[$e]
            [void]$lxType.GetMethod($m, $NPI).Invoke($this.Obj, @($null))
        }
        $h | Add-Member -MemberType ScriptMethod -Name Timer -Value { [void]$lxType.GetMethod('PulseTimerCallback', $NPI).Invoke($this.Obj, @($null)) }
        $h | Add-Member -MemberType ScriptMethod -Name Tick -Value { try { [void]$lxType.GetMethod('Tick').Invoke($this.Obj, @([TimeSpan]::Zero)) } catch { } }
        $h | Add-Member -MemberType ScriptMethod -Name Dispose -Value { try { [void]$lxType.GetMethod('Dispose').Invoke($this.Obj, @()) } catch { } }
        $h | Add-Member -MemberType ScriptMethod -Name Reads -Value { return [BodyEntry]::Hits }
        $h | Add-Member -MemberType ScriptMethod -Name Established -Value { return $true }
        $h | Add-Member -MemberType ScriptMethod -Name EstablishedCount -Value { return 0 }
        $h | Add-Member -MemberType ScriptMethod -Name Fail -Value { param($b) }
        $h | Add-Member -MemberType ScriptMethod -Name Cleanup -Value { }
        return $h
    }
    Test-Sender 'LegacyTelemetry' $newLx 16 $false
    Note 'LegacyTelemetry: the session keeps its own gap re-check (nowMs / lastTickMs); the fixture session has a constant clock, so the gate is what the checks observe'
}

# ----------------------------------------------------------------------------------------------------------------------------------------------------------------
# Bridge (the adapter of this Adapter value + the real ScenarioReadyTracker, a fake BVE reader that counts reads, a real Caller session of a fake pid for the handshake)
# ----------------------------------------------------------------------------------------------------------------------------------------------------------------
$NS = 'TSScoringPlugin.Handshake.'
$sessionType = $callerAsm.GetType($NS + 'HandshakeSession')
$adType = $brAsm.GetType($NS + $(if ($Adapter -eq 'Legacy') { 'TsScoringLegacyBridgePrototype' } else { 'TsScoringBridgePrototype' }))
$ctlType = $brAsm.GetType($NS + 'HandshakeControlPlane')
$trkType = $brAsm.GetType($NS + 'ScenarioReadyTracker')
$snapType = $brAsm.GetType($NS + 'BveSnapshot')
$cLog = $callerAsm.GetType($NS + 'ObservationLog')
$bLog = $brAsm.GetType($NS + 'ObservationLog')
$sessionCtor = $sessionType.GetConstructor($NPI, $null, [Type[]]@([int], [Action[string]]), $null)
$funcSnap = [Func``1].MakeGenericType($snapType)
Add-Type -AssemblyName System.Core
$pidNext = 984000
function LogCfg($type, [string]$path, [int]$fakePid) {
    $type.GetMethod('ResetForTests', $NPS).Invoke($null, @()) | Out-Null
    $type.GetProperty('TestPath', $NPS).SetValue($null, $path)
    $type.GetProperty('TestPid', $NPS).SetValue($null, [int]$fakePid)
    $type.GetProperty('TestMaxBytes', $NPS).SetValue($null, [long]0)
}
function ResetAll { foreach ($t in $cLog, $bLog) { try { $t.GetMethod('ResetForTests', $NPS).Invoke($null, @()) | Out-Null } catch { } } }
function Snap([int]$created = 1) {
    $o = [Activator]::CreateInstance($snapType)
    $f = [Reflection.BindingFlags]'Public,Instance'
    $snapType.GetField('IsScenarioCreated', $f).SetValue($o, $created)
    foreach ($n in 'ScenarioRef', 'TimeManagerRef', 'VehicleLocationRef', 'VehicleLocationFinite', 'VehicleRef') { $snapType.GetField($n, $f).SetValue($o, [bool]($created -eq 1)) }
    $snapType.GetField('Failure', $f).SetValue($o, $null)
    return $o
}
$newBridge = {
    $script:pidNext++; $p = $script:pidNext
    LogCfg $cLog (Join-Path $OutDir ("bridge-$p.log")) $p
    LogCfg $bLog (Join-Path $OutDir ("bridge-$p.log")) $p
    $b = [Runtime.Serialization.FormatterServices]::GetUninitializedObject($adType)
    $f = [Reflection.BindingFlags]'NonPublic,Instance'
    $adType.GetField('loadQpc', $f).SetValue($b, [Diagnostics.Stopwatch]::GetTimestamp())
    $adType.GetField('loadUtcTicks', $f).SetValue($b, [DateTime]::UtcNow.Ticks)
    $adType.GetField('pid', $f).SetValue($b, $p)
    $adType.GetField('instNo', $f).SetValue($b, 1)
    $adType.GetMethod('BeginControl', $NPI).Invoke($b, @($false)) | Out-Null
    $f1 = ({ 1 }) -as [Func[int]]; $f2 = ({ $null }) -as [Func[string]]
    $adType.GetMethod('BeginObservation', $NPI).Invoke($b, @($f1, $f2)) | Out-Null
    $probe = New-Object ReaderProbe
    $probe.Snap = (Snap 1)
    $ex = [System.Linq.Expressions.Expression]
    $rd = $ex::Lambda($funcSnap, $ex::Convert($ex::Call($ex::Constant($probe), [ReaderProbe].GetMethod('Read')), $snapType)).Compile()
    $adType.GetMethod('BeginScenarioReady', $NPI).Invoke($b, @($rd, $null)) | Out-Null
    $ctl = $adType.GetField('control', $NPI).GetValue($b)
    $ctlType.GetMethod('Start', $NPI).Invoke($ctl, @()) | Out-Null
    $rec = New-Object NoticeRecorder
    $del = [Delegate]::CreateDelegate([Action[string]], $rec, 'Show')
    $session = $sessionCtor.Invoke(@($p, $del))
    $sessionType.GetMethod('Start').Invoke($session, @()) | Out-Null
    $sw = [Diagnostics.Stopwatch]::StartNew()
    while ($sw.ElapsedMilliseconds -lt 3000) { if ([bool]$ctlType.GetProperty('HandshakeUp', $NPI).GetValue($ctl)) { break }; Start-Sleep -Milliseconds 5 }
    $ctx = New-Object FakeSyncContext
    $gate = New-ProductGate $brAsm
    $adType.GetField('pulseContext', $NPI).SetValue($b, $ctx)
    $adType.GetField('pulseGate', $NPI).SetValue($b, $gate)
    $adType.GetField('lastTickTicks', $NPI).SetValue($b, [long]0)     # never ticked
    $h = [pscustomobject]@{ B = $b; Ctx = $ctx; Gate = $gate; Probe = $probe; Session = $session; Ctl = $ctl; Ok = ([bool]$ctlType.GetProperty('HandshakeUp', $NPI).GetValue($ctl)) }
    $h | Add-Member -MemberType ScriptMethod -Name Fire -Value {
        param($e)
        $m = @{ Opened = 'OnHackerScenarioOpened'; Closed = 'OnHackerScenarioClosed'; Created = 'OnHackerScenarioCreated' }[$e]
        [void]$adType.GetMethod($m, $NPI).Invoke($this.B, @($null))
    }
    $h | Add-Member -MemberType ScriptMethod -Name Timer -Value { [void]$adType.GetMethod('PulseTimerCallback', $NPI).Invoke($this.B, @($null)) }
    $h | Add-Member -MemberType ScriptMethod -Name Tick -Value { [void]$adType.GetMethod('Tick').Invoke($this.B, @([TimeSpan]::Zero)) }
    $h | Add-Member -MemberType ScriptMethod -Name Dispose -Value { [void]$adType.GetMethod('Dispose').Invoke($this.B, @()) }
    $h | Add-Member -MemberType ScriptMethod -Name Reads -Value { return [int]$this.Probe.Reads }
    $h | Add-Member -MemberType ScriptMethod -Name Established -Value { return [bool]$trkType.GetProperty('IsScenarioReady', $NPI).GetValue($adType.GetField('tracker', $NPI).GetValue($this.B)) }
    $h | Add-Member -MemberType ScriptMethod -Name EstablishedCount -Value { return [int]$trkType.GetProperty('EstablishedCount', $NPI).GetValue($adType.GetField('tracker', $NPI).GetValue($this.B)) }
    $h | Add-Member -MemberType ScriptMethod -Name Fail -Value { param($b) $this.Probe.Fail = [bool]$b }
    $h | Add-Member -MemberType ScriptMethod -Name Cleanup -Value {
        try { $adType.GetMethod('Dispose').Invoke($this.B, @()) | Out-Null } catch { }
        try { $sessionType.GetMethod('End').Invoke($this.Session, @()) | Out-Null } catch { }
    }
    return $h
}
try {
    $probeBridge = & $newBridge
    Rec 'CTRL' 'C0/Bridge' 'the fake handshake session is up (the tracker may publish) and the tracker exists' ($probeBridge.Ok -and ($null -ne $adType.GetField('tracker', $NPI).GetValue($probeBridge.B)))
    $probeBridge.Cleanup()
    Test-Sender ('Bridge-' + $Adapter) $newBridge 50 $true
    if ($Adapter -eq 'Current') {
        # supplementary: the REAL System.Threading.Timer at the product period against a UI thread that does not drain for 500 ms of wall clock, with the gate on the real clock
        Write-Host '--- supplementary: the real System.Threading.Timer (16 ms) against a UI thread that does not drain for 500 ms, gate on the real clock'
        [BodyEntry]::Reset()
        $o = [Runtime.Serialization.FormatterServices]::GetUninitializedObject($c1Type)
        $ctx = New-Object FakeSyncContext
        $realGate = $tlAsm.GetType('TSScoringPlugin.Pulse.PausePulseGate').GetConstructor($NPI, $null, [Type[]]@([Func[long]], [long], [long]), $null).Invoke(@($null, [long]150, [long]500))
        (C1Field 'pulseContext').SetValue($o, $ctx); (C1Field 'pulseGate').SetValue($o, $realGate); (C1Field 'lastTickTime').SetValue($o, [DateTime]::MinValue); (C1Field 'pulseDisposed').SetValue($o, $false)
        $tr = $c1Type.GetField('transport', $NPI); $tr.SetValue($o, [Activator]::CreateInstance($tr.FieldType, $true))
        [void]$c1Type.GetMethod('OnPulseScenarioCreated', $NPI).Invoke($o, @($null))
        $cb = [Threading.TimerCallback]$c1Type.GetMethod('PulseTimerCallback', $NPI).CreateDelegate([Threading.TimerCallback], $o)
        $tm = New-Object Threading.Timer($cb, $null, 0, 16)
        Start-Sleep -Milliseconds 400
        $postsInWindow = $ctx.TotalPosts
        Start-Sleep -Milliseconds 700
        $tm.Dispose(); Start-Sleep -Milliseconds 50
        Rec 'INV' 'INV-P1/Class1-realtimer' ("the real 16 ms timer posted $postsInWindow request(s) within the 400 ms after ScenarioCreated (limit 0: settle) and " + $ctx.TotalPosts + " in total after 1100 ms of stalled UI (limit 1); pending=" + $ctx.Pending) (($postsInWindow -eq 0) -and ($ctx.TotalPosts -le 1) -and ($ctx.Pending -le 1))
    }
}
finally {
    ResetAll
}

Start-Sleep -Milliseconds 300
$ctrlBad = @($results | Where-Object { $_.Kind -eq 'CTRL' -and -not $_.Ok })
$red = @($results | Where-Object { $_.Kind -eq 'INV' -and -not $_.Ok })
$held = @($results | Where-Object { $_.Kind -eq 'INV' -and $_.Ok })
$results | ForEach-Object { ('{0}|{1}|{2}|{3}' -f $_.Kind, $_.Id, $(if ($_.Ok) { 'OK' } else { 'RED' }), $_.Text) } | Set-Content -Path (Join-Path $OutDir ('results-' + $Adapter + '.txt')) -Encoding ASCII
"SUMMARY invariants held=$($held.Count) RED=$($red.Count) controls-bad=$($ctrlBad.Count)"
if ($ctrlBad.Count -gt 0) { 'FIXTURE INVALID (a control failed)'; exit 2 }
if ($red.Count -gt 0) { exit 1 }
exit 0
