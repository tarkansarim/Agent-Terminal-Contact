param(
    [switch]$DryRun,
    [switch]$Force,
    [switch]$Check
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Write-Usage {
    @"
Usage:
  pwsh scripts/install.ps1 [-DryRun] [-Force]
  pwsh scripts/install.ps1 -Check

Installs AgentTerminalContact for the current user on Windows:
  - writes agent-contact.ps1 and agent-contact.cmd shims under `$BIN_DIR or ~/.local/bin
  - copies skills/agent-tmux-control/SKILL.md into `$CODEX_HOME/skills/agent-tmux-control/SKILL.md

Forced skill replacement backs up prior skill files under this repo's ignored
backups/install/ tree, not under `$CODEX_HOME.

The source-owned agent-tmux wrapper is Bash/tmux-specific and is installed by
scripts/install.sh on Linux/WSL. This Windows installer intentionally installs
agent-contact and the Codex skill snapshot only.
"@
}

function Resolve-RepoRoot {
    $scriptDir = Split-Path -Parent $PSCommandPath
    return (Resolve-Path (Join-Path $scriptDir "..")).Path
}

function Get-HomeDir {
    if ($env:USERPROFILE) {
        return $env:USERPROFILE
    }
    if ($env:HOME) {
        return $env:HOME
    }
    return [Environment]::GetFolderPath("UserProfile")
}

function Invoke-InstallAction {
    param([scriptblock]$Action, [string]$Description)
    if ($DryRun) {
        Write-Output "dry-run: $Description"
        return
    }
    & $Action
}

function Copy-WithBackup {
    param(
        [string]$Source,
        [string]$Target,
        [string]$BackupDir,
        [string]$Label
    )
    if (Test-Path -LiteralPath $Target) {
        $existing = Get-Content -LiteralPath $Target -Raw
        $desired = Get-Content -LiteralPath $Source -Raw
        if ($existing -ne $desired) {
            if (-not $Force) {
                throw "install.ps1: refusing to overwrite divergent $Label without -Force: $Target"
            }
            Invoke-InstallAction {
                New-Item -ItemType Directory -Force -Path $BackupDir | Out-Null
                $stamp = Get-Date -Format "yyyyMMddTHHmmss"
                Copy-Item -LiteralPath $Target -Destination (Join-Path $BackupDir "$Label.bak-$stamp") -Force
            } "backup divergent $Label to $BackupDir"
        }
    }
    Invoke-InstallAction {
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Target) | Out-Null
        Copy-Item -LiteralPath $Source -Destination $Target -Force
    } "copy $Source -> $Target"
}

function Assert-FileBytesMatch {
    param([string]$Expected, [string]$Actual, [string]$Label)
    if (-not (Test-Path -LiteralPath $Actual -PathType Leaf)) {
        throw "install.ps1: $Label is missing: $Actual"
    }
    $expectedText = Get-Content -LiteralPath $Expected -Raw
    $actualText = Get-Content -LiteralPath $Actual -Raw
    if ($expectedText -ne $actualText) {
        throw "install.ps1: $Label differs from repo source: $Actual"
    }
}

function Resolve-CommandSource {
    param([string]$Name)
    $command = Get-Command $Name -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -eq $command) {
        return $null
    }
    $sourceProperty = $command.PSObject.Properties["Source"]
    if ($sourceProperty -and $sourceProperty.Value) {
        return $sourceProperty.Value
    }
    return $command.Path
}

function Assert-CommandResolvesTo {
    param(
        [string]$Name,
        [string[]]$AllowedTargets
    )
    $source = Resolve-CommandSource $Name
    if (-not $source) {
        throw "install.ps1: $Name is not discoverable on PATH; add $BinDir to PATH before running -Check"
    }
    $resolvedSource = [System.IO.Path]::GetFullPath($source)
    foreach ($target in $AllowedTargets) {
        if ($resolvedSource -eq [System.IO.Path]::GetFullPath($target)) {
            return
        }
    }
    throw "install.ps1: $Name resolves to a different command on PATH: $source"
}

function Move-LegacyProviderRootBackups {
    param(
        [string]$LegacyBackupDir,
        [string]$BackupDir
    )
    if (-not (Test-Path -LiteralPath $LegacyBackupDir)) {
        return
    }
    Invoke-InstallAction {
        $children = Get-ChildItem -LiteralPath $LegacyBackupDir -Force
        if ($children.Count -gt 0) {
            New-Item -ItemType Directory -Force -Path $BackupDir | Out-Null
        }
        foreach ($child in $children) {
            $destination = Join-Path $BackupDir $child.Name
            if (Test-Path -LiteralPath $destination) {
                $stamp = Get-Date -Format "yyyyMMddTHHmmss"
                $destination = Join-Path $BackupDir "$($child.Name).$stamp"
            }
            Move-Item -LiteralPath $child.FullName -Destination $destination
        }
        $legacyCleanupDirs = @(
            $LegacyBackupDir,
            (Split-Path -Parent $LegacyBackupDir),
            (Split-Path -Parent (Split-Path -Parent $LegacyBackupDir))
        )
        foreach ($cleanupDir in $legacyCleanupDirs) {
            if (-not (Test-Path -LiteralPath $cleanupDir)) {
                continue
            }
            $remaining = Get-ChildItem -LiteralPath $cleanupDir -Force -ErrorAction SilentlyContinue
            if ($remaining -and $remaining.Count -gt 0) {
                break
            }
            Remove-Item -LiteralPath $cleanupDir -Force
        }
    } "relocate legacy provider-root backups from $LegacyBackupDir to $BackupDir"
}

$Root = Resolve-RepoRoot
$HomeDir = Get-HomeDir
$CodexHome = if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path $HomeDir ".codex" }
$BinDir = if ($env:BIN_DIR) { $env:BIN_DIR } else { Join-Path (Join-Path $HomeDir ".local") "bin" }
$BackupRoot = if ($env:AGENT_TERMINAL_CONTACT_BACKUP_ROOT) { $env:AGENT_TERMINAL_CONTACT_BACKUP_ROOT } else { Join-Path $Root "backups/install" }
$SkillSource = Join-Path $Root "skills/agent-tmux-control/SKILL.md"
$SkillTarget = Join-Path $CodexHome "skills/agent-tmux-control/SKILL.md"
$SkillBackupDir = Join-Path $BackupRoot "codex/agent-tmux-control"
$LegacySkillBackupDir = Join-Path $CodexHome "agent-terminal-contact/backups/agent-tmux-control"
$ShimPs1Source = Join-Path $Root "bin/agent-contact.ps1"
$ShimCmdSource = Join-Path $Root "bin/agent-contact.cmd"
$ShimPs1 = Join-Path $BinDir "agent-contact.ps1"
$ShimCmd = Join-Path $BinDir "agent-contact.cmd"
$RootMarker = Join-Path $BinDir "agent-contact.root"

if ($Check) {
    Assert-FileBytesMatch $ShimPs1Source $ShimPs1 "agent-contact.ps1 shim"
    Assert-FileBytesMatch $ShimCmdSource $ShimCmd "agent-contact.cmd shim"
    Assert-FileBytesMatch $SkillSource $SkillTarget "agent-tmux-control skill"
    if (-not (Test-Path -LiteralPath $RootMarker -PathType Leaf)) {
        throw "install.ps1: agent-contact root marker is missing: $RootMarker"
    }
    $InstalledRoot = (Get-Content -LiteralPath $RootMarker -Raw).Trim()
    if ($InstalledRoot -ne $Root) {
        throw "install.ps1: agent-contact root marker points somewhere else: $RootMarker"
    }
    Assert-CommandResolvesTo "agent-contact" @($ShimCmd, $ShimPs1)
    Assert-CommandResolvesTo "agent-contact.cmd" @($ShimCmd)
    Write-Output "agent-contact Windows install check: ok"
    Write-Output "agent-contact.ps1: $ShimPs1"
    Write-Output "agent-contact.cmd: $ShimCmd"
    Write-Output "agent-tmux-control skill: $SkillTarget"
    exit 0
}

Copy-WithBackup $ShimPs1Source $ShimPs1 $BinDir "agent-contact.ps1"
Copy-WithBackup $ShimCmdSource $ShimCmd $BinDir "agent-contact.cmd"
Copy-WithBackup $SkillSource $SkillTarget $SkillBackupDir "SKILL.md"
Move-LegacyProviderRootBackups $LegacySkillBackupDir $SkillBackupDir
Invoke-InstallAction {
    New-Item -ItemType Directory -Force -Path $BinDir | Out-Null
    Set-Content -LiteralPath $RootMarker -Value $Root -Encoding UTF8NoBOM
} "write $RootMarker"

Write-Output "agent-contact.ps1: $ShimPs1"
Write-Output "agent-contact.cmd: $ShimCmd"
Write-Output "agent-tmux-control skill: $SkillTarget"
Write-Output "agent-tmux wrapper: Linux/WSL only; use scripts/install.sh there"
