<# Runs every automated test: backend (inside Docker, against a throw-away PostgreSQL database),
   the end-to-end smoke check, and the Flutter tests. #>
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$failed = @()
function Run($name, [scriptblock]$block) {
    Write-Host "`n== $name" -ForegroundColor Cyan
    & $block
    if ($LASTEXITCODE -ne 0) { $script:failed += $name; Write-Host "FAILED: $name" -ForegroundColor Red }
    else { Write-Host "PASSED: $name" -ForegroundColor Green }
}
if (-not (Test-Path '.env')) { Write-Host 'Run setup-and-run.ps1 first (it creates .env).' -ForegroundColor Yellow; exit 1 }

Run 'Backend, security and concurrency tests' {
    docker compose up -d db
    docker compose exec -T db psql -U sahil -d sahil -c 'CREATE DATABASE sahil_test' 2>$null | Out-Null
    $global:LASTEXITCODE = 0
    docker compose run --rm --no-deps -T --user root -v "${PWD}/backend/tests:/srv/tests:ro" -v "${PWD}/backend/requirements-dev.txt:/srv/requirements-dev.txt:ro" -v "${PWD}/backend/pytest.ini:/srv/pytest.ini:ro" `
        --entrypoint sh api -c 'pip install -q --root-user-action=ignore -r requirements-dev.txt && TEST_DATABASE_URL=$(echo "$DATABASE_URL" | sed "s#/sahil\$#/sahil_test#") python -m pytest -p no:cacheprovider'
}
Run 'End-to-end smoke check (API must be running)' {
    $h = Invoke-RestMethod 'http://localhost:8000/health' -TimeoutSec 5
    $global:LASTEXITCODE = if ($h.status -eq 'ok') { 0 } else { 1 }
}
if (Get-Command flutter -ErrorAction SilentlyContinue) {
    Run 'Flutter analyze' { flutter analyze --no-fatal-infos }
    Run 'Flutter tests' { flutter test }
} else { Write-Host "`nFlutter is not installed - app tests skipped." -ForegroundColor Yellow }

if ($failed.Count) { Write-Host "`n$($failed.Count) group(s) failed: $($failed -join ', ')" -ForegroundColor Red; exit 1 }
Write-Host "`nAll tests passed." -ForegroundColor Green
