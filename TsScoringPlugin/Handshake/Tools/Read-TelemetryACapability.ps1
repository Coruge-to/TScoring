# Reads the CAPABILITY of a TScoring.TelemetryA DLL from the DLL itself (never from a declaration) and writes one JSON object to stdout.
# OD-X11 v2 (Owner 2026-11-15). ASCII-only on purpose; Windows PowerShell 5.1. Nothing is executed from the DLL: it is loaded REFLECTION-ONLY from a byte copy, so no static constructor runs and the file is not locked.
#   -Dll <path>
# Output fields: ok, error, path, sha256, sizeBytes, assemblyName, assemblyVersion, executionCompiledIn, featureBits, jumpCapabilityAdvertised, metadata{TScoring.*}, capabilityTokens[]
# executionCompiledIn = the const LegacyJumpBuild.ExecutionCompiledIn (the metadata Constant row; the IL that uses it is the same const). featureBits = LegacyJumpFeatures.All when the execution is compiled in, else 0
# (LegacyJumpControlPlane advertises FeatureBits = executionEnabled ? LegacyJumpExecutor.ImplementedFeatures : 0).
param([Parameter(Mandatory = $true)][string]$Dll)
Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'
$result = [ordered]@{ ok = $false; error = ''; path = $Dll; sha256 = ''; sizeBytes = 0; assemblyName = ''; assemblyVersion = ''; executionCompiledIn = $null; featureBits = $null; jumpCapabilityAdvertised = $null; metadata = [ordered]@{}; capabilityTokens = @() }
try {
    if (-not (Test-Path -LiteralPath $Dll)) { throw 'dll-absent' }
    $bytes = [System.IO.File]::ReadAllBytes($Dll)
    $result.sizeBytes = $bytes.Length
    $sha = [System.Security.Cryptography.SHA256]::Create()
    $result.sha256 = ([System.BitConverter]::ToString($sha.ComputeHash($bytes))).Replace('-', '')
    $asm = [System.Reflection.Assembly]::ReflectionOnlyLoad($bytes)
    $result.assemblyName = $asm.GetName().Name
    $result.assemblyVersion = $asm.GetName().Version.ToString()
    foreach ($a in $asm.GetCustomAttributesData()) {
        if ($a.AttributeType.Name -eq 'AssemblyMetadataAttribute') {
            $k = [string]$a.ConstructorArguments[0].Value
            if ($k.StartsWith('TScoring.')) { $result.metadata[$k] = [string]$a.ConstructorArguments[1].Value }
        }
    }
    $types = $null
    try { $types = $asm.GetTypes() } catch [System.Reflection.ReflectionTypeLoadException] { $types = @($_.Exception.Types | Where-Object { $null -ne $_ }) }
    $flags = [System.Reflection.BindingFlags]'Static,Public,NonPublic'
    $build = $types | Where-Object { $_.FullName -eq 'TSScoringPlugin.Telemetry.LegacyJumpBuild' } | Select-Object -First 1
    if ($null -eq $build) { throw 'LegacyJumpBuild-type-absent' }
    $field = $build.GetField('ExecutionCompiledIn', $flags)
    if ($null -eq $field) { throw 'ExecutionCompiledIn-field-absent' }
    $result.executionCompiledIn = [bool]$field.GetRawConstantValue()
    $feat = $types | Where-Object { $_.FullName -eq 'TSScoringPlugin.Telemetry.LegacyJumpFeatures' } | Select-Object -First 1
    $all = 0
    if ($null -ne $feat) { $f2 = $feat.GetField('All', $flags); if ($null -ne $f2) { $all = [int]$f2.GetRawConstantValue() } }
    $result.featureBits = if ($result.executionCompiledIn) { $all } else { 0 }
    $result.jumpCapabilityAdvertised = ($result.executionCompiledIn -and $result.featureBits -ne 0)
    # capability tokens (the 11-10 kit checked these names): present as type or member names / strings of the DLL
    $text = [System.Text.Encoding]::ASCII.GetString($bytes) + [System.Text.Encoding]::Unicode.GetString($bytes)
    $tokens = @()
    foreach ($t in @('PTPAIR', 'PseudoTurnbackPairCodec', 'ACCELZ')) { if ($text.Contains($t)) { $tokens += $t } }
    $result.capabilityTokens = $tokens
    $result.ok = $true
}
catch {
    $result.error = $_.Exception.Message
}
($result | ConvertTo-Json -Depth 4 -Compress)
if ($result.ok) { exit 0 } else { exit 3 }
