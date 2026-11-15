<#
  Sahil - one-step setup and launcher for Windows.
  Checks the tools you need, offers to install missing ones (with your permission, via winget),
  starts the database + API in Docker, checks they are healthy, and opens the app in Chrome.

  Nothing is installed silently, nothing is deleted, and no administrator rights are requested
  by this script (winget itself may show a Windows prompt when an installer needs one).

  Usage:  .\setup-and-run.ps1            full setup and launch
          .\setup-and-run.ps1 -CheckOnly only report what is installed (changes nothing)
          .\setup-and-run.ps1 -Device android   run on a connected Android device instead of Chrome
#>
param(
    [switch]$CheckOnly,
    [ValidateSet('chrome', 'android')][string]$Device = 'chrome',
    [string]$RepoUrl = 'https://github.com/isa-aldoy/sahil-fintech-demo.git',
    [string]$Branch = ''
)
$ErrorActionPreference = 'Stop'
$ApiUrl = 'http://localhost:8000'
$AppUrl = 'http://localhost:5173'

function Say($text, $color = 'Gray') { Write-Host $text -ForegroundColor $color }
function Step($text) { Write-Host "`n== $text" -ForegroundColor Cyan }
function Fail($text, $fix) {
    Write-Host "`nPROBLEM: $text" -ForegroundColor Red
    if ($fix) { Write-Host "HOW TO FIX: $fix" -ForegroundColor Yellow }
    exit 1
}
function Has($command) { [bool](Get-Command $command -ErrorAction SilentlyContinue) }
function Ask($question) { (Read-Host "$question [y/N]") -match '^(y|yes)$' }
function RandomSecret($bytes = 48) {
    $buffer = New-Object byte[] $bytes
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($buffer)
    ([Convert]::ToBase64String($buffer)) -replace '[^A-Za-z0-9]', ''
}

# Each tool: command to look for, winget package id (official publisher), and why it is needed.
$Tools = @(
    @{ Name = 'Git';            Command = 'git';     Winget = 'Git.Git';               Why = 'downloads and updates the Sahil code' },
    @{ Name = 'Docker Desktop'; Command = 'docker';  Winget = 'Docker.DockerDesktop';  Why = 'runs the database and the API' },
    @{ Name = 'Flutter';        Command = 'flutter'; Winget = 'Google.Flutter';        Why = 'builds and runs the app' },
    @{ Name = 'Google Chrome';  Command = '';        Winget = 'Google.Chrome';         Why = 'shows the app' }
)
function ChromeInstalled {
    foreach ($root in @($env:ProgramFiles, ${env:ProgramFiles(x86)}, $env:LOCALAPPDATA)) {
        if ($root -and (Test-Path (Join-Path $root 'Google\Chrome\Application\chrome.exe'))) { return $true }
    }
    return $false
}

Step 'Checking what is installed'
$missing = @()
foreach ($tool in $Tools) {
    $ok = if ($tool.Command) { Has $tool.Command } else { ChromeInstalled }
    if ($ok) { Say ("  [ok]      {0}" -f $tool.Name) Green }
    else { Say ("  [missing] {0} - {1}" -f $tool.Name, $tool.Why) Yellow; $missing += $tool }
}
if ($CheckOnly) {
    Say "`nCheck finished. Nothing was changed." Cyan
    exit 0
}

if ($missing.Count -gt 0) {
    if (-not (Has 'winget')) {
        Fail 'Some tools are missing and Windows Package Manager (winget) is not available.' `
             'Install "App Installer" from the Microsoft Store, or install the tools listed above from their official websites, then run this again.'
    }
    foreach ($tool in $missing) {
        if (Ask ("Install {0} now from its official publisher using winget?" -f $tool.Name)) {
            Say "Installing $($tool.Name). Windows may ask for permission because the installer writes to Program Files." Gray
            winget install --id $tool.Winget --exact --source winget --accept-source-agreements --accept-package-agreements
            if ($LASTEXITCODE -ne 0) { Fail "$($tool.Name) could not be installed." 'Install it manually from its official website and run this again.' }
        } else {
            Fail "$($tool.Name) is required." 'Run this script again and answer y, or install it yourself.'
        }
    }
    Say "`nTools were installed. Please CLOSE this window, start Docker Desktop once, then run START-SAHIL again." Yellow
    exit 0
}

Step 'Getting the Sahil code'
$here = $PSScriptRoot
if ($here -and (Test-Path (Join-Path $here 'docker-compose.yml'))) {
    $repo = $here
    Say "  Using the copy in $repo"
    if ((Test-Path (Join-Path $repo '.git')) -and -not (git -C $repo status --porcelain)) {
        git -C $repo pull --ff-only 2>$null | Out-Null   # only fast-forward: never overwrites your work
    } else { Say '  You have local changes (or no git folder), so the code was left exactly as it is.' }
} else {
    $repo = Join-Path $HOME 'sahil-fintech-demo'
    if (Test-Path (Join-Path $repo '.git')) {
        Say "  Updating $repo"
        if (git -C $repo status --porcelain) { Say '  You have local changes, so the update was skipped.' Yellow }
        else { git -C $repo pull --ff-only }
    } elseif (Test-Path $repo) {
        Fail "$repo already exists but is not a Sahil checkout." 'Rename or move that folder, then run this again. Nothing was deleted.'
    } else {
        git clone $RepoUrl $repo
        if ($LASTEXITCODE -ne 0) { Fail 'Could not download the code.' 'Check your internet connection.' }
    }
    if ($Branch) { git -C $repo checkout $Branch }
}
Set-Location $repo

Step 'Creating local settings (.env)'
$envFile = Join-Path $repo '.env'
if (Test-Path $envFile) {
    Say '  .env already exists - keeping it.'
} else {
    $geminiKey = Read-Host '  Optional: paste a Google Gemini API key for the AI assistant (or press Enter to skip)'
    @(
        '# Local demo settings. Generated on this computer. Do not share or commit this file.'
        "POSTGRES_PASSWORD=$(RandomSecret 24)"
        "JWT_SECRET=$(RandomSecret 48)"
        "GEMINI_API_KEY=$($geminiKey.Trim())"
        'GEMINI_MODEL=gemini-2.5-flash-lite'
    ) | Set-Content -Path $envFile -Encoding ascii
    Say '  Created .env with fresh random secrets (the file is ignored by git).' Green
}

Step 'Starting the database and API (Docker)'
docker info *> $null
if ($LASTEXITCODE -ne 0) { Fail 'Docker is installed but not running.' 'Open Docker Desktop, wait until it says "Engine running", then run this again.' }
docker compose up -d --build
if ($LASTEXITCODE -ne 0) { Fail 'Docker could not start Sahil.' 'Run "docker compose logs" in this folder to see why.' }

Step 'Checking that the API is healthy'
$healthy = $false
foreach ($i in 1..60) {
    try {
        $health = Invoke-RestMethod "$ApiUrl/health" -TimeoutSec 3
        if ($health.status -eq 'ok') { $healthy = $true; break }
    } catch { Start-Sleep -Seconds 2 }
}
if (-not $healthy) { Fail 'The API did not become healthy in time.' 'Run "docker compose logs api" to see the error.' }
Say "  API is up. Assistant mode: $($health.assistant)" Green
try {
    $login = Invoke-RestMethod "$ApiUrl/api/v1/auth/login" -Method Post -ContentType 'application/json' `
        -Body '{"email":"demo@sahil.example","password":"Sahil-Demo-2026"}'
    if ($login.access_token) { Say '  Demo sign-in works.' Green }
} catch { Fail 'The demo account could not sign in.' 'Run "docker compose logs api".' }

Step 'Preparing the app'
if (-not (Test-Path (Join-Path $repo 'web'))) {
    flutter create . --platforms=web,android --project-name sahil_fintech_demo | Out-Null
}
flutter pub get
if ($LASTEXITCODE -ne 0) { Fail 'Flutter could not download its packages.' 'Run "flutter doctor" and follow its advice.' }

Write-Host ''
Write-Host '  SAHIL IS READY' -ForegroundColor Green
Write-Host "  App:      $AppUrl"
Write-Host "  API docs: $ApiUrl/docs"
Write-Host '  Demo sign-in:  demo@sahil.example  /  Sahil-Demo-2026   (fictional account)'
Write-Host '  Keep this window open while you use the app. Press q here to close the app; run stop.ps1 to stop the server.'
Write-Host ''
if ($Device -eq 'android') {
    # 10.0.2.2 is how an Android emulator reaches this computer.
    flutter run -d android --dart-define=API_BASE_URL=http://10.0.2.2:8000
} else {
    flutter run -d chrome --web-port 5173 --dart-define=API_BASE_URL=$ApiUrl
}
