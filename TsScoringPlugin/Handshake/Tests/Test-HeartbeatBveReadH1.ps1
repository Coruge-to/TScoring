# PHASE H-1 (HeartbeatTimer must not read the host from its timer thread) - deterministic fixture for the Current Telemetry (ScoringPlugin, TScoring.TelemetryB.dll). ASCII-only on purpose; Windows PowerShell 5.1.
#
#   .\Test-HeartbeatBveReadH1.ps1 -TelemetryDll <TScoring.TelemetryB.dll> [-HostDir <BveEx 2.0 folder>]
#
# The heartbeat timer of the plugin runs on a thread pool thread. Before H-1 it read BveHacker.IsScenarioCreated (= MainForm.CurrentScenario of the host, no lock, no generation) on every firing.
# After H-1 it reads only two flags that the scenario events and Dispose set (heartbeatScenarioActive, heartbeatDisposed) and composes the datagram text with the pure ComposeHeartbeat.
# The plugin object is created WITHOUT its constructor and WITHOUT a host (BveHacker is null), so ANY access to the host from the heartbeat shows up as a NullReferenceException raised INSIDE
# HeartbeatTimer_Elapsed (counted with a first-chance handler).
#   H-R1 the heartbeat firing with no scenario created does not touch the host (0 exceptions inside the handler)
#   H-R2 ComposeHeartbeat: no scenario -> no datagram; scenario created -> STATUS:LOADED:PAUSED (no Tick for > 100 ms) / RUNNING (a Tick within 100 ms)
#   H-R3 the scenario events drive the flag: Opened -> false, Created -> true, Closed -> false
#   H-R4 the heartbeat firing with a created scenario still does not touch the host
#   H-R5 after Dispose has begun (heartbeatDisposed) the handler returns without a host access and without an exception
#   H-R6 100 concurrent heartbeat firings against concurrent Opened / Created / Closed events: no exception leaves the handler, no host access, no deadlock
# Exit code 0 = every check PASS, 1 = at least one FAIL, 2 = prerequisite missing.
param(
    [Parameter(Mandatory = $true)][string]$TelemetryDll,
    [string]$HostDir = ''
)
$publicDocs = Join-Path $env:PUBLIC 'Documents\BveEx'
if (-not $HostDir) { $HostDir = Join-Path $publicDocs '2.0' }
if (-not (Test-Path -LiteralPath $TelemetryDll)) { Write-Host ('PREREQUISITE MISSING: ' + $TelemetryDll); exit 2 }

Add-Type -TypeDefinition @'
using System;
using System.Reflection;
using System.Threading;

// counts NullReferenceExceptions raised while HeartbeatTimer_Elapsed is on the stack = the handler touched the (absent) host
public static class HeartbeatProbe
{
    private static int hits;
    public static int Hits { get { return hits; } }
    public static void Reset() { hits = 0; }
    public static void OnFirstChance(object s, System.Runtime.ExceptionServices.FirstChanceExceptionEventArgs e)
    {
        if (e.Exception is NullReferenceException)
        {
            string st = new System.Diagnostics.StackTrace(false).ToString();
            if (st.Contains("HeartbeatTimer_Elapsed")) { Interlocked.Increment(ref hits); }
        }
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
'@

$ErrorActionPreference = 'Stop'
$NPI = [Reflection.BindingFlags]'NonPublic,Public,Instance'
$NPS = [Reflection.BindingFlags]'NonPublic,Public,Static'
$results = New-Object System.Collections.Generic.List[object]
function Rec([string]$id, [string]$text, [bool]$ok) {
    $results.Add([pscustomobject]@{ Id = $id; Ok = $ok; Text = $text })
    Write-Host ('{0} {1} {2}' -f $(if ($ok) { 'PASS' } else { 'FAIL' }), $id, $text)
}
[TestResolver]::Install(@((Join-Path $env:ProgramW6432 'mackoy\BveTs6'), $HostDir))
[HeartbeatProbe]::Install()
Write-Host ('=== H-1 heartbeat fixture: ' + (Split-Path $TelemetryDll -Leaf) + ' sha256=' + (Get-FileHash $TelemetryDll).Hash.Substring(0, 16) + ' ===')
$asm = [Reflection.Assembly]::Load([IO.File]::ReadAllBytes($TelemetryDll))
$type = $asm.GetType('TsScoringPlugin.ScoringPlugin')
if (-not $type) { Write-Host 'PREREQUISITE MISSING: type TsScoringPlugin.ScoringPlugin'; exit 2 }
$gateType = $asm.GetType('TSScoringPlugin.Pulse.PausePulseGate')

function New-Plugin {
    $o = [Runtime.Serialization.FormatterServices]::GetUninitializedObject($type)
    if ($gateType) { $type.GetField('pulseGate', $NPI).SetValue($o, [Activator]::CreateInstance($gateType, $true)) }
    return $o
}
function Fire($o) { $m = $type.GetMethod('HeartbeatTimer_Elapsed', $NPI); try { [void]$m.Invoke($o, @($null, $null)); return $null } catch { return $_.Exception } }
$flagField = $type.GetField('heartbeatScenarioActive', $NPI)
$disposedField = $type.GetField('heartbeatDisposed', $NPI)
$compose = $type.GetMethod('ComposeHeartbeat', $NPS)

# H-R1
[HeartbeatProbe]::Reset()
$o = New-Plugin
$ex = Fire $o
Rec 'H-R1' ('the heartbeat with no scenario created does not touch the host (exceptions inside the handler: ' + [HeartbeatProbe]::Hits + ', must be 0)') (([HeartbeatProbe]::Hits -eq 0) -and ($null -eq $ex))

# H-R2
if ($compose) {
    $now = [DateTime]::Now
    $none = $compose.Invoke($null, @($false, $now, [DateTime]::MinValue))
    $paused = $compose.Invoke($null, @($true, $now, [DateTime]::MinValue))
    $running = $compose.Invoke($null, @($true, $now, $now.AddMilliseconds(-50)))
    $edge = $compose.Invoke($null, @($true, $now, $now.AddMilliseconds(-100)))
    $over = $compose.Invoke($null, @($true, $now, $now.AddMilliseconds(-101)))
    $txt = { param($b) if ($null -eq $b) { '<null>' } else { [Text.Encoding]::UTF8.GetString($b) } }
    Rec 'H-R2' ('ComposeHeartbeat: no scenario -> ' + (& $txt $none) + '; no Tick ever -> ' + (& $txt $paused) + '; Tick 50 ms ago -> ' + (& $txt $running) + '; 100 ms -> ' + (& $txt $edge) + '; 101 ms -> ' + (& $txt $over)) (($null -eq $none) -and ((& $txt $paused) -ceq 'STATUS:LOADED:PAUSED') -and ((& $txt $running) -ceq 'STATUS:LOADED:RUNNING') -and ((& $txt $edge) -ceq 'STATUS:LOADED:RUNNING') -and ((& $txt $over) -ceq 'STATUS:LOADED:PAUSED'))
} else {
    Rec 'H-R2' 'ComposeHeartbeat does not exist (the heartbeat text is composed inside the handler, from a read of the host)' $false
}

# H-R3
if ($flagField) {
    $o = New-Plugin
    $opened = $type.GetMethod('OnPulseScenarioOpened', $NPI); $closed = $type.GetMethod('OnPulseScenarioClosed', $NPI); $created = $type.GetMethod('OnPulseScenarioCreated', $NPI)
    $s0 = [bool]$flagField.GetValue($o)
    [void]$created.Invoke($o, @($null)); $s1 = [bool]$flagField.GetValue($o)
    [void]$opened.Invoke($o, @($null)); $s2 = [bool]$flagField.GetValue($o)
    [void]$created.Invoke($o, @($null)); $s3 = [bool]$flagField.GetValue($o)
    [void]$closed.Invoke($o, @($null)); $s4 = [bool]$flagField.GetValue($o)
    Rec 'H-R3' ('flag: start ' + $s0 + ', Created ' + $s1 + ', Opened ' + $s2 + ', Created ' + $s3 + ', Closed ' + $s4) ((-not $s0) -and $s1 -and (-not $s2) -and $s3 -and (-not $s4))
} else {
    Rec 'H-R3' 'there is no event driven flag (heartbeatScenarioActive)' $false
}

# H-R4
if ($flagField) {
    [HeartbeatProbe]::Reset()
    $o = New-Plugin
    $flagField.SetValue($o, $true)
    $ex = Fire $o
    Rec 'H-R4' ('the heartbeat with a created scenario does not touch the host (exceptions inside the handler: ' + [HeartbeatProbe]::Hits + ', must be 0)') (([HeartbeatProbe]::Hits -eq 0) -and ($null -eq $ex))
} else {
    [HeartbeatProbe]::Reset()
    $o = New-Plugin
    $ex = Fire $o
    Rec 'H-R4' ('the heartbeat reads the host on every firing (exceptions inside the handler: ' + [HeartbeatProbe]::Hits + ')') $false
}

# H-R5
if ($disposedField -and $flagField) {
    # a send path that cannot work (an uninitialised router, an unbound UdpClient): any attempt to SEND raises a NullReferenceException inside the handler, so "did it try to send" becomes countable
    $routerType = $asm.GetType('TSScoringPlugin.DataPlane.CurrentTelemetryRouter')
    $routerField = $type.GetField('router', $NPI); $udpField = $type.GetField('udpClient', $NPI)
    function Arm-SendPath($o) {
        if ($routerType -and $routerField -and $udpField) { $routerField.SetValue($o, [Runtime.Serialization.FormatterServices]::GetUninitializedObject($routerType)); $udpField.SetValue($o, (New-Object Net.Sockets.UdpClient)) }
    }
    # control: scenario created, NOT disposed: the handler does try to send (so the check below can detect a missing early return)
    [HeartbeatProbe]::Reset()
    $o = New-Plugin; Arm-SendPath $o; $flagField.SetValue($o, $true)
    $null = Fire $o
    $tries = [HeartbeatProbe]::Hits
    [HeartbeatProbe]::Reset()
    $o = New-Plugin; Arm-SendPath $o
    $flagField.SetValue($o, $true); $disposedField.SetValue($o, $true)
    $ex = Fire $o
    Rec 'H-R5' ('after Dispose began the handler returns before any send (send attempts: ' + [HeartbeatProbe]::Hits + ' must be 0; the same object not disposed tries: ' + $tries + ' must be >= 1; leaked: ' + $(if ($ex) { $ex.GetType().Name } else { 'none' }) + ')') (([HeartbeatProbe]::Hits -eq 0) -and ($tries -ge 1) -and ($null -eq $ex))
} else {
    Rec 'H-R5' 'there is no Dispose flag (heartbeatDisposed)' $false
}

# H-R6
if ($flagField) {
    [HeartbeatProbe]::Reset()
    $o = New-Plugin
    $opened = $type.GetMethod('OnPulseScenarioOpened', $NPI); $closed = $type.GetMethod('OnPulseScenarioClosed', $NPI); $created = $type.GetMethod('OnPulseScenarioCreated', $NPI)
    $fire = $type.GetMethod('HeartbeatTimer_Elapsed', $NPI)
    $pool = [Collections.Generic.List[object]]::new()
    $errs = [Collections.Concurrent.ConcurrentBag[string]]::new()
    $hb = {
        param($o, $fire, $errs)
        for ($i = 0; $i -lt 100; $i++) { try { [void]$fire.Invoke($o, @($null, $null)) } catch { $errs.Add($_.Exception.GetType().Name) } }
    }
    $ev = {
        param($o, $opened, $closed, $created, $errs)
        for ($i = 0; $i -lt 100; $i++) { try { [void]$opened.Invoke($o, @($null)); [void]$created.Invoke($o, @($null)); [void]$closed.Invoke($o, @($null)); [void]$created.Invoke($o, @($null)) } catch { $errs.Add($_.Exception.GetType().Name) } }
    }
    $jobs = @()
    foreach ($k in 1..4) {
        $ps = [powershell]::Create(); [void]$ps.AddScript($hb).AddArgument($o).AddArgument($fire).AddArgument($errs); $jobs += [pscustomobject]@{ Ps = $ps; H = $ps.BeginInvoke() }
    }
    $ps = [powershell]::Create(); [void]$ps.AddScript($ev).AddArgument($o).AddArgument($opened).AddArgument($closed).AddArgument($created).AddArgument($errs); $jobs += [pscustomobject]@{ Ps = $ps; H = $ps.BeginInvoke() }
    $done = $true
    foreach ($j in $jobs) { if (-not $j.H.AsyncWaitHandle.WaitOne(60000)) { $done = $false } else { [void]$j.Ps.EndInvoke($j.H) } ; $j.Ps.Dispose() }
    Rec 'H-R6' ('400 heartbeat firings against 400 event bursts: finished ' + $done + ', exceptions leaked ' + $errs.Count + ', host accesses ' + [HeartbeatProbe]::Hits + ' (must be finished / 0 / 0)') ($done -and ($errs.Count -eq 0) -and ([HeartbeatProbe]::Hits -eq 0))
} else {
    Rec 'H-R6' 'not meaningful without the event driven flag' $false
}

$failed = @($results | Where-Object { -not $_.Ok }).Count
Write-Host ('SUMMARY checks=' + $results.Count + ' failed=' + $failed)
if ($failed -eq 0) { exit 0 } else { exit 1 }
