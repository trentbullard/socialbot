<#
.SYNOPSIS
    PowerShell entrypoint for the Social Media Bot.
.PARAMETER Config
    Path to the YAML config file. Default: config.yaml
.PARAMETER DryRun
    Generate content without posting.
.PARAMETER PostNow
    Authenticate and post once immediately, then exit.
.PARAMETER MaxPosts
    Stop after N posts.
.PARAMETER DryRunReplies
    Generate sample reply prompts and replies without platform auth.
.PARAMETER ReplyComment
    Sample comment to use with -DryRunReplies. Can be repeated.
#>
param(
    [string]$Config = "config.yaml",
    [switch]$DryRun,
    [switch]$DryRunReplies,
    [switch]$PostNow,
    [int]$MaxPosts = 0,
    [string[]]$ReplyComment = @()
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

    # Load persisted User environment variables (VS Code may not inherit them)
    foreach ($name in @(
        "TWITTER_API_KEY", "TWITTER_API_SECRET",
        "TWITTER_ACCESS_TOKEN", "TWITTER_ACCESS_SECRET",
        "TWITTER_BEARER_TOKEN", "GIPHY_API_KEY"
    )) {
        if (-not [System.Environment]::GetEnvironmentVariable($name)) {
            $val = [System.Environment]::GetEnvironmentVariable($name, "User")
            if ($val) {
                [System.Environment]::SetEnvironmentVariable($name, $val, "Process")
            }
        }
    }

    Write-Host "Installing/updating dependencies..."
    pip install -q -r requirements.txt

    # Build command
    $cmd = @("-m", "src.main", "--config", $Config)

    if ($DryRun) {
        $cmd += "--dry-run"
    }

    if ($DryRunReplies) {
        $cmd += "--dry-run-replies"
    }

    if ($PostNow) {
        $cmd += "--post-now"
    }

    if ($MaxPosts -gt 0) {
        $cmd += @("--max-posts", $MaxPosts)
    }

    foreach ($comment in $ReplyComment) {
        $cmd += @("--reply-comment", $comment)
    }

    Write-Host "Starting bot..."
    python @cmd
}
finally {
    Pop-Location
}
