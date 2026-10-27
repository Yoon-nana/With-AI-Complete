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
    $versionCheck='import sys; sys.exit(0 if (3, 10) <= sys.version_info < (3, 15) else 1)'
    if(-not(Test-Path -LiteralPath $python)) {
        $launcher=Get-Command py -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
        $selected=$null
        if($launcher){
            foreach($version in @('3.14','3.13','3.12','3.11','3.10')){
                try { & $launcher.Source ("-$version") -c $versionCheck 2>$null } catch { continue }
                if($LASTEXITCODE -eq 0){$selected=$version;break}
            }
        }
        if(-not $selected){throw 'Python 3.10-3.14 is required. Install one of these versions with the Windows py launcher.'}
        & $launcher.Source ("-$selected") -m venv (Join-Path $RuntimeRoot '.venv')
        if($LASTEXITCODE -ne 0){throw 'Could not create the Python virtual environment.'}
    }
    & $python -c $versionCheck
    if($LASTEXITCODE -ne 0){throw 'This .venv must use Python 3.10-3.14. Extract the ZIP into a fresh folder and run IN_Install.cmd again.'}
    & $python -m pip install kocoafab-robodog==0.2.0 pyserial==3.5
    if($LASTEXITCODE -ne 0){throw 'Dependency installation failed.'}
    & $python -c 'import kocoafab_robodog, serial'
    if($LASTEXITCODE -ne 0){throw 'Robot libraries could not be loaded.'}
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
