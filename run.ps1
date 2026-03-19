<#
.SYNOPSIS
    PowerShell entrypoint for the Social Media Bot.
.PARAMETER Config
    Path to the YAML config file. Default: config.yaml
.PARAMETER DryRun
    Generate content without posting.
.PARAMETER MaxPosts
    Stop after N posts.
#>
param(
    [string]$Config = "config.yaml",
    [switch]$DryRun,
    [int]$MaxPosts = 0
)

$ErrorActionPreference = "Stop"

# Ensure we're in the project root
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Push-Location $ScriptDir

try {
    # Check Python is available
    $python = Get-Command python -ErrorAction SilentlyContinue
    if (-not $python) {
        Write-Error "Python not found on PATH. Install Python 3.12+ and try again."
        exit 1
    }

    # Install dependencies if needed
    if (-not (Test-Path ".venv")) {
        Write-Host "Creating virtual environment..."
        python -m venv .venv
    }

    # Activate venv
    & .\.venv\Scripts\Activate.ps1

    Write-Host "Installing/updating dependencies..."
    pip install -q -r requirements.txt

    # Build command
    $cmd = @("-m", "src.main", "--config", $Config)

    if ($DryRun) {
        $cmd += "--dry-run"
    }

    if ($MaxPosts -gt 0) {
        $cmd += @("--max-posts", $MaxPosts)
    }

    Write-Host "Starting bot..."
    python @cmd
}
finally {
    Pop-Location
}
