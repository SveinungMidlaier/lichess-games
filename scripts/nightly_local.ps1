# Nattlig analyse på egen PC: henter nye partier (synket av GitHub Actions), analyserer dem
# med Stockfish, lichess-puzzler-tagger og Maia-1900, oppdaterer fokusplanen og pusher.
# Kjøres av Windows Oppgaveplanlegger (oppgaven "lichess-games nightly").
$ErrorActionPreference = 'Continue'
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo
$log = Join-Path $repo 'analysis\out\nightly.log'
function Log($msg) { "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')  $msg" | Out-File -FilePath $log -Append -Encoding utf8 }

$env:PYTHONIOENCODING = 'utf-8'
Log 'Start'
git pull --rebase --autostash 2>&1 | Out-File -FilePath $log -Append -Encoding utf8
python analysis/engine.py --nodes 50000 --workers 28 2>&1 | Select-Object -Last 2 | Out-File -FilePath $log -Append -Encoding utf8
python analysis/moments.py --last 3000 --workers 28 2>&1 | Where-Object { $_ -notmatch 'stderr' } | Select-Object -Last 2 | Out-File -FilePath $log -Append -Encoding utf8
python analysis/track.py 2>&1 | Select-Object -First 12 | Out-File -FilePath $log -Append -Encoding utf8

git add focus analysis/out/evals.ndjson analysis/out/moments.ndjson analysis/out/focus.json
git diff --cached --quiet
if ($LASTEXITCODE -ne 0) {
    git commit -m "Analyse og fokusfremdrift $(Get-Date -Format 'yyyy-MM-dd')" 2>&1 | Out-File -FilePath $log -Append -Encoding utf8
    git push 2>&1 | Out-File -FilePath $log -Append -Encoding utf8
}
Log 'Ferdig'
