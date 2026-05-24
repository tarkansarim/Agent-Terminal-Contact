$ErrorActionPreference = "Stop"

$RootMarker = Join-Path $PSScriptRoot "agent-contact.root"
if (Test-Path -LiteralPath $RootMarker -PathType Leaf) {
    $Root = (Get-Content -LiteralPath $RootMarker -Raw).Trim()
} else {
    $Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
}

$Src = Join-Path $Root "src"
$separator = [IO.Path]::PathSeparator
if ($env:PYTHONPATH) {
    $env:PYTHONPATH = "$Src$separator$env:PYTHONPATH"
} else {
    $env:PYTHONPATH = $Src
}

python -m agent_terminal_contact.cli @args
exit $LASTEXITCODE
