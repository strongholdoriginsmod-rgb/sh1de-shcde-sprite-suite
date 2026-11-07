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
    $plugin = Join-Path $game 'BepInEx\plugins\SpriteSuiteBuildingDamageRuntime'
    [IO.Directory]::CreateDirectory($plugin) | Out-Null
    Copy-Item -LiteralPath $dll -Destination (Join-Path $plugin (Split-Path -Leaf $dll)) -Force
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'examples\info.json') -Destination (Join-Path $plugin 'info.json') -Force
    $settings = Join-Path $plugin 'runtime.json'
    if ($RuntimeConfig) {
        Copy-Item -LiteralPath $RuntimeConfig -Destination $settings -Force
    } elseif (!(Test-Path -LiteralPath $settings)) {
        Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'examples\runtime.json') -Destination $settings
    }
    if ($DamageArchive) {
        $assetDir = Join-Path $plugin 'DamageAssets'
        if (Test-Path -LiteralPath $assetDir) {
            throw "Runtime artwork destination already exists; choose or clear that folder deliberately: $assetDir"
        }
        Expand-Archive -LiteralPath $DamageArchive -DestinationPath $assetDir
        Write-Host "ARTWORK_READY $assetDir"
    }
    Write-Host "INSTALLED $plugin"
    Write-Host 'The runtime loads expanded DamageAssets; use -DamageArchive for automatic ZIP import.'
}
