# Build the isolated in-memory HP/fire value QA plugin (NOT production mod).
param(
    [Parameter(Mandatory=$true)][string]$GameRoot,
    [Parameter(Mandatory=$true)][string]$Output
)
$ErrorActionPreference = 'Stop'
$g=(Resolve-Path -LiteralPath $GameRoot).Path
$compiler="$env:WINDIR\Microsoft.NET\Framework64\v4.0.30319\csc.exe"
$out=[IO.Path]::GetFullPath($Output)
[IO.Directory]::CreateDirectory($out)|Out-Null
$dll=Join-Path $out 'SpriteSuite.BuildingDamage.HealthQA.dll'
$refs=@(
 'BepInEx\core\BepInEx.dll',
 'BepInEx\plugins\000shcdese\SHCDESE.dll',
 'Stronghold Crusader Definitive Edition_Data\Managed\Assembly-CSharp.dll',
 'Stronghold Crusader Definitive Edition_Data\Managed\UnityEngine.dll',
 'Stronghold Crusader Definitive Edition_Data\Managed\UnityEngine.CoreModule.dll'
)
$argv=@('/nologo','/target:library','/optimize+',('/out:'+$dll))
foreach($p in $refs){
 $ref=Join-Path $g $p
 if(!(Test-Path -LiteralPath $ref)){throw ('Missing reference '+$ref)}
 $argv+=('/reference:'+$ref)
}
foreach($p in @('BepInEx\plugins\000shcdese\RedBird.Core.dll',
               'Stronghold Crusader Definitive Edition_Data\Managed\netstandard.dll')){
 $ref=Join-Path $g $p
 if(Test-Path -LiteralPath $ref){$argv+=('/reference:'+$ref)}
}
$argv+=(Join-Path $PSScriptRoot 'DamageHealthCanary.cs')
& $compiler @argv
if($LASTEXITCODE -ne 0 -or !(Test-Path -LiteralPath $dll)){throw 'Health QA compile failed'}
'HP_FIRE_HEALTH_QA_COMPILED='+ $dll
'HP_FIRE_HEALTH_QA_SHA256='+(Get-FileHash -LiteralPath $dll -Algorithm SHA256).Hash.ToLowerInvariant()
