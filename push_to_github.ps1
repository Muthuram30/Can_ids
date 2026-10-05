# ============================================================================
# GitHub Push Script for CAN IDS HIL Project
# ============================================================================
# This script automates pushing the repository to GitHub
#
# Usage: .\push_to_github.ps1
# ============================================================================

$ErrorActionPreference = "Stop"

# Configuration
$repoUrl = "https://github.com/Muthuram30/Can_ids.git"
$branch = "main"

Write-Host "============================================================================" -ForegroundColor Cyan
Write-Host "CAN IDS HIL - GitHub Push Script" -ForegroundColor Cyan
Write-Host "============================================================================" -ForegroundColor Cyan
Write-Host ""

# Check if git is installed
Write-Host "[1/7] Checking Git installation..." -ForegroundColor Yellow
try {
    $gitVersion = git --version
    Write-Host "  ✓ Git found: $gitVersion" -ForegroundColor Green
} catch {
    Write-Host "  ✗ Git not found. Please install Git first." -ForegroundColor Red
    Write-Host "  Download from: https://git-scm.com/download/win" -ForegroundColor Yellow
    exit 1
}

# Check if already a git repository
Write-Host ""
Write-Host "[2/7] Checking repository status..." -ForegroundColor Yellow
if (Test-Path ".git") {
    Write-Host "  ℹ Repository already initialized" -ForegroundColor Yellow
    $reinit = Read-Host "  Reinitialize? (y/N)"
    if ($reinit -eq "y" -or $reinit -eq "Y") {
        Remove-Item -Recurse -Force .git
        git init
        Write-Host "  ✓ Repository reinitialized" -ForegroundColor Green
    }
} else {
    git init
    Write-Host "  ✓ Git repository initialized" -ForegroundColor Green
}

# Add all files
Write-Host ""
Write-Host "[3/7] Adding files to repository..." -ForegroundColor Yellow
git add .
$fileCount = (git diff --cached --name-only).Count
Write-Host "  ✓ Added $fileCount files" -ForegroundColor Green

# Create commit
Write-Host ""
Write-Host "[4/7] Creating commit..." -ForegroundColor Yellow
$commitMessage = @"
Initial commit: CAN IDS HIL Project

- Complete working IDS with ML (Isolation Forest + Random Forest)
- Modular architecture for extensibility
- ESP32 firmware for Motor, Sensor, and Security ECUs
- Comprehensive documentation with hardware photos
- Configuration management via .env
- USB attack demonstration
- Network monitoring and isolation
- Professional GitHub-ready structure

Team: Barath Raj B, Hari Prasanth S T, Mathumitha E, Muthuraman M, Vishal SR
"@

git commit -m $commitMessage
Write-Host "  ✓ Commit created" -ForegroundColor Green

# Add remote
Write-Host ""
Write-Host "[5/7] Configuring remote repository..." -ForegroundColor Yellow
try {
    git remote remove origin 2>$null
} catch {
    # Remote doesn't exist, that's fine
}
git remote add origin $repoUrl
Write-Host "  ✓ Remote added: $repoUrl" -ForegroundColor Green

# Rename branch to main
Write-Host ""
Write-Host "[6/7] Setting branch to '$branch'..." -ForegroundColor Yellow
git branch -M $branch
Write-Host "  ✓ Branch set to '$branch'" -ForegroundColor Green

# Push to GitHub
Write-Host ""
Write-Host "[7/7] Pushing to GitHub..." -ForegroundColor Yellow
Write-Host ""
Write-Host "⚠  You may be prompted for GitHub credentials" -ForegroundColor Yellow
Write-Host "   Username: Muthuram30" -ForegroundColor Cyan
Write-Host "   Password: Use Personal Access Token (PAT)" -ForegroundColor Cyan
Write-Host ""
Write-Host "   Generate PAT at: https://github.com/settings/tokens" -ForegroundColor Cyan
Write-Host "   Required scope: 'repo' (Full control of private repositories)" -ForegroundColor Cyan
Write-Host ""

$pushChoice = Read-Host "Ready to push? (Y/n)"
if ($pushChoice -eq "n" -or $pushChoice -eq "N") {
    Write-Host ""
    Write-Host "Push cancelled. You can push manually later with:" -ForegroundColor Yellow
    Write-Host "  git push -u origin $branch" -ForegroundColor Cyan
    exit 0
}

try {
    git push -u origin $branch
    Write-Host ""
    Write-Host "============================================================================" -ForegroundColor Green
    Write-Host "✓ SUCCESS! Repository pushed to GitHub" -ForegroundColor Green
    Write-Host "============================================================================" -ForegroundColor Green
    Write-Host ""
    Write-Host "View your repository at:" -ForegroundColor Cyan
    Write-Host "  https://github.com/Muthuram30/Can_ids" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "Next steps:" -ForegroundColor Yellow
    Write-Host "  1. Verify images are displaying in README.md" -ForegroundColor White
    Write-Host "  2. Check that all files uploaded correctly" -ForegroundColor White
    Write-Host "  3. Add repository description and topics" -ForegroundColor White
    Write-Host "  4. Consider creating a release (v1.0.0)" -ForegroundColor White
    Write-Host ""
} catch {
    Write-Host ""
    Write-Host "============================================================================" -ForegroundColor Red
    Write-Host "✗ Push failed" -ForegroundColor Red
    Write-Host "============================================================================" -ForegroundColor Red
    Write-Host ""
    Write-Host "Common solutions:" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "1. Authentication error:" -ForegroundColor Cyan
    Write-Host "   - Use Personal Access Token instead of password" -ForegroundColor White
    Write-Host "   - Generate at: https://github.com/settings/tokens" -ForegroundColor White
    Write-Host ""
    Write-Host "2. Repository not empty:" -ForegroundColor Cyan
    Write-Host "   - Force push (⚠ overwrites remote):" -ForegroundColor White
    Write-Host "     git push -u origin $branch --force" -ForegroundColor Gray
    Write-Host "   - Or pull first:" -ForegroundColor White
    Write-Host "     git pull origin $branch --allow-unrelated-histories" -ForegroundColor Gray
    Write-Host "     git push -u origin $branch" -ForegroundColor Gray
    Write-Host ""
    Write-Host "3. Large files:" -ForegroundColor Cyan
    Write-Host "   - Use Git LFS for files >50MB" -ForegroundColor White
    Write-Host ""
    Write-Host "Error details:" -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
    Write-Host ""
    exit 1
}
