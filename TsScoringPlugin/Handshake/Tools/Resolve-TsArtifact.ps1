# One way for the PowerShell tests to find a built TScoring artifact (Owner 2026-11-18: no copying DLLs into out\ / dist\ just to run a test).
#   Resolve-TsArtifact -Root <the Handshake folder> -Name <TScoring.*.dll>   -> a path, or $null
#   Require-TsArtifact -Root <..> -Name <..>                                  -> a path, or prints "SKIP (INCONCLUSIVE)" and ENDS THE SCRIPT with exit 0 (an artifact that is not there is "cannot be checked", not "failed")
# Order: (1) the DEPLOYED baseline of package\artifact-baselines.json (the single source of truth for baselines), accepted only when its SHA-256 equals the baseline;
#        (2) a developer's own build output of this clone (out\ / dist\), if it exists. Nothing is ever copied.
# ASCII-only on purpose (Windows PowerShell 5.1). The functions are global so that a script that dot-sources this file once can call them from any scope.
function global:Resolve-TsArtifact {
    param([Parameter(Mandatory = $true)][string]$Root, [Parameter(Mandatory = $true)][string]$Name)
    $repo = Split-Path (Split-Path $Root -Parent) -Parent
    $manifest = Join-Path $repo 'package\artifact-baselines.json'
    if (Test-Path -LiteralPath $manifest) {
        try {
            $m = [System.IO.File]::ReadAllText($manifest, [System.Text.Encoding]::UTF8) | ConvertFrom-Json
            $a = @($m.artifacts | Where-Object { $_.name -eq $Name })
            if ($a.Count -eq 1) {
                foreach ($p in @($a[0].deploy)) {
                    if (Test-Path -LiteralPath $p) {
                        $sha = (Get-FileHash -LiteralPath $p -Algorithm SHA256).Hash
                        if ($sha -eq ([string]$a[0].baseline.sha256).ToUpperInvariant()) { return $p }
                    }
                }
            }
        } catch { }
    }
    foreach ($rel in 'Telemetry\Legacy\out', 'Bridge\Legacy\out', 'Bridge\out', 'dist') {
        $p = Join-Path (Join-Path $Root $rel) $Name
        if (Test-Path -LiteralPath $p) { return $p }
    }
    return $null
}
function global:Require-TsArtifact {
    param([Parameter(Mandatory = $true)][string]$Root, [Parameter(Mandatory = $true)][string]$Name)
    $p = Resolve-TsArtifact -Root $Root -Name $Name
    if (-not $p) {
        Write-Host ('SKIP (INCONCLUSIVE): the artifact ' + $Name + ' is neither the deployed baseline of package\artifact-baselines.json nor a local build output; this script cannot check it here.')
        exit 0
    }
    return $p
}
