param([string]$RuntimeRoot='')
if(-not $RuntimeRoot){
    $folder=Get-Item -LiteralPath $PSScriptRoot
    while($null -ne $folder){
        if(Test-Path -LiteralPath (Join-Path $folder.FullName '.venv\Scripts\python.exe')){$RuntimeRoot=$folder.FullName;break}
        $folder=$folder.Parent
    }
    if(-not $RuntimeRoot){$RuntimeRoot=$PSScriptRoot}
}
$ErrorActionPreference='Stop'
try {
    $python=Join-Path ([IO.Path]::GetFullPath($RuntimeRoot)) '.venv\Scripts\python.exe'
    if(-not(Test-Path -LiteralPath $python)) {
        & py -3.13 -m venv (Join-Path $RuntimeRoot '.venv')
        if($LASTEXITCODE -ne 0){throw 'Install Python 3.13 first.'}
    }
    & $python -m pip install kocoafab-robodog==0.2.0 pyserial==3.5
    if($LASTEXITCODE -ne 0){throw 'Dependency installation failed.'}
    $logs=Join-Path ([IO.Path]::GetFullPath($RuntimeRoot)) 'work\aigo-in-runtime'
    New-Item -ItemType Directory -Path $logs -Force | Out-Null
    @{python=$python;logs=$logs}|ConvertTo-Json|Set-Content -LiteralPath (Join-Path $PSScriptRoot 'in-helper.local.json') -Encoding UTF8
    $key='HKCU:\Software\Classes\aigo-in'
    New-Item -Path $key -Force | Out-Null
    Set-Item -LiteralPath $key -Value 'URL:AIGO IN helper'
    New-ItemProperty -LiteralPath $key -Name 'URL Protocol' -Value '' -PropertyType String -Force | Out-Null
    $openKey=Join-Path $key 'shell\open\command'
    New-Item -Path $openKey -Force | Out-Null
    $ps=Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    Set-Item -LiteralPath $openKey -Value ('"'+$ps+'" -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "'+(Join-Path $PSScriptRoot 'IN_Launch.ps1')+'" -LaunchUri "%1"')
    Write-Host 'IN helper installed. Open IN_Start.html.' -ForegroundColor Green
} catch {Write-Error $_;exit 1}
