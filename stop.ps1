<# Stops the Sahil database and API. Your demo data is kept.
   To also erase the demo data:  .\stop.ps1 -EraseData   (asks you to confirm first) #>
param([switch]$EraseData)
Set-Location $PSScriptRoot
if ($EraseData) {
    if ((Read-Host 'This permanently deletes the demo database. Type ERASE to continue') -ne 'ERASE') {
        Write-Host 'Nothing was deleted.'; exit 0
    }
    docker compose down --volumes
} else {
    docker compose down
}
if ($LASTEXITCODE -eq 0) { Write-Host 'Sahil is stopped.' -ForegroundColor Green }
else { Write-Host 'Could not stop Sahil. Is Docker Desktop running?' -ForegroundColor Red; exit 1 }
