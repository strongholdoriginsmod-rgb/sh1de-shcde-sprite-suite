# Builds a separate opt-in BepInEx runtime plugin against the selected game.
# Does NOT install or replace any game file unless -Install is specified.
param(
    [Parameter(Mandatory=$true)][string]$GameRoot,
    [string]$Output = (Join-Path $PSScriptRoot 'output'),
    [string]$Csc = "$env:WINDIR\Microsoft.NET\Framework64\v4.0.30319\csc.exe",
    [string]$DamageArchive = "",
    [string]$RuntimeConfig = "",
    [switch]$Install
)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
# Use the host PowerShell's modules even when launched from an embedded
# PowerShell with its own PSModulePath.
Import-Module (Join-Path $PSHOME 'Modules\Microsoft.PowerShell.Utility') -ErrorAction Stop
if ($Install -and $DamageArchive) {
    Import-Module (Join-Path $PSHOME 'Modules\Microsoft.PowerShell.Archive') -ErrorAction Stop
}
$game = (Resolve-Path -LiteralPath $GameRoot).Path
$references = @(
    'BepInEx\core\BepInEx.dll',
    'BepInEx\core\0Harmony.dll',
    'BepInEx\plugins\000shcdese\SHCDESE.dll',
    'Stronghold Crusader Definitive Edition_Data\Managed\Assembly-CSharp.dll',
    'Stronghold Crusader Definitive Edition_Data\Managed\UnityEngine.dll',
    'Stronghold Crusader Definitive Edition_Data\Managed\UnityEngine.CoreModule.dll',
    'Stronghold Crusader Definitive Edition_Data\Managed\UnityEngine.TilemapModule.dll',
    'Stronghold Crusader Definitive Edition_Data\Managed\UnityEngine.GridModule.dll',
    'Stronghold Crusader Definitive Edition_Data\Managed\UnityEngine.ImageConversionModule.dll',
    'Stronghold Crusader Definitive Edition_Data\Managed\UnityEngine.JSONSerializeModule.dll',
    'Stronghold Crusader Definitive Edition_Data\Managed\UnityEngine.InputLegacyModule.dll'
)
if (!(Test-Path -LiteralPath $Csc -PathType Leaf)) { throw "C# compiler not found: $Csc" }
$args = @('/nologo','/target:library','/optimize+')
foreach ($path in $references) {
    $ref = Join-Path $game $path
    if (!(Test-Path -LiteralPath $ref -PathType Leaf)) { throw "Missing game reference: $ref" }
    $args += ('/reference:'+$ref)
}
# SHCDESE builds may expose native value types from RedBird.Core and
# netstandard. Reference them if the selected game actually ships them.
foreach ($file in @(
    (Join-Path $game 'BepInEx\plugins\000shcdese\RedBird.Core.dll'),
    (Join-Path $game 'BepInEx\core\RedBird.Core.dll'),
    (Join-Path $game 'Stronghold Crusader Definitive Edition_Data\Managed\netstandard.dll')
)) {
    if (Test-Path -LiteralPath $file -PathType Leaf) { $args += ('/reference:'+$file) }
}
$out = [IO.Path]::GetFullPath($Output)
[IO.Directory]::CreateDirectory($out) | Out-Null
$dll = Join-Path $out 'SpriteSuite.BuildingDamage.Live.dll'
$args += ('/out:' + $dll)
$args += (Join-Path $PSScriptRoot 'runtime\BuildingDamageStageLogic.cs')
$args += (Join-Path $PSScriptRoot 'runtime\DamageJsonParser.cs')
$args += (Join-Path $PSScriptRoot 'runtime\BuildingDamageLiveMod.cs')
& $Csc @args
if ($LASTEXITCODE -ne 0 -or !(Test-Path -LiteralPath $dll)) { throw 'C# compilation failed' }
Write-Host "COMPILED $dll"
$sha = (Get-FileHash -LiteralPath $dll -Algorithm SHA256).Hash.ToLowerInvariant()
Write-Host "SHA256 $sha"
if ($Install) {
    $bep = Join-Path $game 'BepInEx'
    $plugin = Join-Path $bep 'plugins\SpriteSuiteBuildingDamageRuntime'
    $settings = Join-Path $plugin 'runtime.json'
    $lockPath = Join-Path $bep '.spritesuite-buildingdamage-install.lock'
    $lock = [IO.File]::Open($lockPath, 'OpenOrCreate', 'ReadWrite', 'None')
    $stage = $null
    $artStage = $null
    $keepRecovery = $false
    $changed = New-Object System.Collections.Generic.List[object]
    try {
        $config = $RuntimeConfig
        if (!$config -and !(Test-Path -LiteralPath $settings)) {
            $config = Join-Path $PSScriptRoot 'examples\runtime.json'
        }

        # Prepare the archive before replacing any installed file. Stage it
        # next to its chosen destination so publishing uses a same-volume move.
        if ($DamageArchive) {
            $activeConfig = $settings
            if ($config) { $activeConfig = $config }
            $parsed = Get-Content -Raw -Encoding UTF8 -LiteralPath $activeConfig | ConvertFrom-Json
            $artLocation = $parsed.damageDirectory
            if ([string]::IsNullOrWhiteSpace($artLocation)) { $artLocation = 'DamageAssets' }
            if (![IO.Path]::IsPathRooted($artLocation)) {
                $artLocation = Join-Path $plugin $artLocation
            }
            $assetDir = [IO.Path]::GetFullPath($artLocation)
            if (Test-Path -LiteralPath $assetDir) {
                throw "Runtime artwork destination already exists: $assetDir"
            }
            $artParent = Split-Path -Parent $assetDir
            [IO.Directory]::CreateDirectory($artParent) | Out-Null
            $artParent = (Resolve-Path -LiteralPath $artParent).Path
            $assetDir = Join-Path $artParent (Split-Path -Leaf $assetDir)
            $artStage = Join-Path $artParent ('.spritesuite-art-' + [Guid]::NewGuid().ToString('N'))
            Expand-Archive -LiteralPath $DamageArchive -DestinationPath $artStage
            if (!(Test-Path -LiteralPath (Join-Path $artStage 'damage-manifest.json') -PathType Leaf)) {
                throw 'The ZIP does not contain damage-manifest.json at its root.'
            }
        }

        $sources = [ordered]@{
            (Split-Path -Leaf $dll) = $dll
            'info.json' = (Join-Path $PSScriptRoot 'examples\info.json')
        }
        if ($config) { $sources['runtime.json'] = $config }
        $stage = Join-Path $bep ('.spritesuite-install-' + [Guid]::NewGuid().ToString('N'))
        [IO.Directory]::CreateDirectory($stage) | Out-Null
        foreach ($name in $sources.Keys) {
            Copy-Item -LiteralPath $sources[$name] -Destination (Join-Path $stage $name)
        }

        [IO.Directory]::CreateDirectory($plugin) | Out-Null
        foreach ($name in $sources.Keys) {
            $source = Join-Path $stage $name
            $target = Join-Path $plugin $name
            $backup = $null
            if (Test-Path -LiteralPath $target) {
                $backup = Join-Path $stage ($name + '.previous')
                [IO.File]::Replace($source, $target, $backup)
            } else {
                [IO.File]::Move($source, $target)
            }
            $changed.Add(@{ target = $target; backup = $backup })
        }
        if ($artStage) {
            [IO.Directory]::Move($artStage, $assetDir)
        }
    } catch {
        $installError = $_
        for ($i = $changed.Count - 1; $i -ge 0; $i--) {
            $entry = $changed[$i]
            try {
                if ($entry.backup) {
                    [IO.File]::Copy($entry.backup, $entry.target, $true)
                } else {
                    [IO.File]::Delete($entry.target)
                }
            } catch {
                $keepRecovery = $true
                Write-Warning "Could not roll back $($entry.target). Recovery files: $stage"
            }
        }
        if ($artStage -and (Test-Path -LiteralPath $artStage)) {
            Write-Warning "Unpublished artwork staging: $artStage"
        }
        throw $installError
    } finally {
        try {
            if ($stage -and !$keepRecovery -and (Test-Path -LiteralPath $stage -PathType Container)) {
                # Only this invocation's staging files and empty directory.
                foreach ($name in $sources.Keys) {
                    [IO.File]::Delete((Join-Path $stage $name))
                    [IO.File]::Delete((Join-Path $stage ($name + '.previous')))
                }
                [IO.Directory]::Delete($stage)
            }
        } catch {
            Write-Warning "Could not clear installation staging: $stage"
        } finally {
            $lock.Dispose()
        }
    }
    if ($artStage) { Write-Host "ARTWORK_READY $assetDir" }
    Write-Host "INSTALLED $plugin"
}
