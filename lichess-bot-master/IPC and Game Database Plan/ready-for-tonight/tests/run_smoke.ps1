# One-command smoke test for a freshly built Engine UCI.exe (Windows PowerShell 5.1).
# Runs the REAL python-chess exactly like lichess-bot: handshake + GameId, then 4 engine moves from two working
# directories (the lichess-bot-master root, and an unrelated temp folder). Prints PASS/FAIL and per-move timings.
#
#   powershell -ExecutionPolicy Bypass -File run_smoke.ps1 -Exe "C:\...\lichess-bot-master\engines\Engine UCI.exe"
#
# Note: the engine writes its normal files under <root>\input, <root>\history\<GameId> and <root>\logs.
param(
    [Parameter(Mandatory = $true)][string]$Exe,
    [int]$Moves = 4,
    [string]$OutDir = (Join-Path $env:TEMP ("mrbits-smoke-" + (Get-Date -Format 'yyyyMMdd-HHmmss')))
)
$harness = Join-Path $PSScriptRoot 'smoke_test.py'
$exePath = (Resolve-Path $Exe).Path
$rootDir = Split-Path (Split-Path $exePath -Parent) -Parent
$foreign = Join-Path $OutDir 'foreign-cwd'
New-Item -ItemType Directory -Force $foreign | Out-Null
$env:PYTHONIOENCODING = 'utf-8'

"Engine : $exePath"
"Root   : $rootDir"
"Runtime DLLs found on PATH (must be the CodeBlocks MinGW copies):"
foreach ($dll in 'libstdc++-6.dll', 'libgcc_s_seh-1.dll', 'libwinpthread-1.dll') {
    $hit = (where.exe $dll 2>$null | Select-Object -First 1)
    "   {0,-20} {1}" -f $dll, $(if ($hit) { $hit } else { 'NOT FOUND' })
}

$runs = @(
    @{ Label = 'handshake'; Cwd = $foreign; Moves = 0; MustLeaveCwdEmpty = $true },
    @{ Label = 'from-root'; Cwd = $rootDir; Moves = $Moves; MustLeaveCwdEmpty = $false },
    @{ Label = 'from-foreign-cwd'; Cwd = $foreign; Moves = $Moves; MustLeaveCwdEmpty = $true }
)
$allOk = $true
foreach ($r in $runs) {
    $arguments = @('-B', "`"$harness`"", '--engine', "`"$exePath`"", '--cwd', "`"$($r.Cwd)`"", '--label', $r.Label,
                   '--out', "`"$OutDir`"", '--moves', "$($r.Moves)")
    $null = Start-Process -FilePath 'python' -ArgumentList $arguments -NoNewWindow -Wait -PassThru `
        -RedirectStandardOutput (Join-Path $OutDir "$($r.Label)_stdout.txt") `
        -RedirectStandardError (Join-Path $OutDir "$($r.Label)_stderr.txt")
    $summaryFile = Join-Path $OutDir "$($r.Label)_summary.json"
    if (-not (Test-Path $summaryFile)) { "FAIL  $($r.Label): no summary (see $OutDir)"; $allOk = $false; continue }
    $sum = Get-Content $summaryFile -Raw | ConvertFrom-Json
    $written = @($sum.cwd_new_entries).Count
    $ok = [bool]$sum.ok -and (-not $r.MustLeaveCwdEmpty -or $written -eq 0)
    if (-not $ok) { $allOk = $false }
    $moveText = ($sum.moves | ForEach-Object { "$($_.bestmove) $($_.play_ms)ms" }) -join ', '
    "{0}  {1,-17} handshake {2} ms; moves: {3}; warnings {4}; new files in cwd {5} {6}" -f $(if ($ok) { 'PASS' } else { 'FAIL' }),
        $r.Label, $sum.handshake_ms, $moveText, @($sum.warnings).Count, $written, $(if ($sum.error) { "ERROR: $($sum.error)" } else { '' })
}
"Logs and summaries: $OutDir"
if ($allOk) { 'RESULT: PASS'; exit 0 }
'RESULT: FAIL   (OSError WinError 4551 = Windows Smart App Control blocked this .exe hash: rebuild and retry)'
exit 1
