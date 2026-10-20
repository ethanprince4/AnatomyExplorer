param([Parameter(Mandatory=$true)][string]$Workspace,
      [Parameter(Mandatory=$true)][Int64]$TargetFree)
$ErrorActionPreference = 'Stop'
if ($env:GITHUB_ACTIONS -ne 'true' -or $env:RUNNER_ENVIRONMENT -ne 'github-hosted') {
    throw 'Toolchain cleanup is restricted to disposable GitHub-hosted runners'
}
$workspacePath = (Resolve-Path -LiteralPath $Workspace).Path
$drive = [System.IO.Path]::GetPathRoot($workspacePath)
# Modern Android/.NET SDKs are unused. Keep Windows' .NET Framework C# compiler,
# Visual Studio/runtime DLLs, Python, Node/Git and Inno Setup intact.
$allowedTargets = @('C:\Android\android-sdk', 'C:\Program Files\dotnet')
foreach ($target in $allowedTargets) {
    $free = [System.IO.DriveInfo]::new($drive).AvailableFreeSpace
    if ($free -ge $TargetFree) { break }
    if ([System.IO.Path]::GetPathRoot($target) -ine $drive) { continue }
    if (Test-Path -LiteralPath $target) {
        $item = Get-Item -LiteralPath $target
        $resolved = (Resolve-Path -LiteralPath $target).Path.TrimEnd('\')
        if ($resolved -ine $target.TrimEnd('\') -or
            ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
            throw "Refusing unexpected cleanup target: $target"
        }
        Write-Output "Removing unused preinstalled toolchain $resolved"
        Remove-Item -LiteralPath $resolved -Recurse -Force
    }
}
Write-Output "Workspace volume $drive has $([System.IO.DriveInfo]::new($drive).AvailableFreeSpace) free bytes"
