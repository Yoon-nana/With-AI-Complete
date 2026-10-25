param([string]$LaunchUri='aigo-in://open?port=AUTO',[switch]$NoBrowser)
$ErrorActionPreference='Stop'
$mutex=$null;$owned=$false
try {
    if($LaunchUri -notmatch '^aigo-in://open/?\?port=(AUTO|COM[1-9][0-9]{0,3})(?:&(app=(?:hub|kiosk|medication|daywatch|exercise|nap)|device=(?:robot|microbit)))?$'){throw 'Invalid IN helper address.'}
    $port=$Matches[1]
    $selection=$Matches[2]
    $config=Get-Content -LiteralPath (Join-Path $PSScriptRoot 'in-helper.local.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    $mutex=[Threading.Mutex]::new($false,'Local\AigoInLauncher')
    $owned=$mutex.WaitOne(0)
    if(-not $owned){exit 0}
    function Get-InBridge {try{return Invoke-RestMethod -Uri 'http://127.0.0.1:8766/bridge-info' -TimeoutSec 2}catch{return $null}}
    $status=Get-InBridge
    if($null -ne $status -and $status.bridge -ne 'aigo-in-v1'){throw 'Port 8766 is used by another program.'}
    if($null -eq $status){
        New-Item -ItemType Directory -Path $config.logs -Force | Out-Null
        $env:PYTHONIOENCODING='utf-8'
        $backend=Join-Path $PSScriptRoot 'in_bridge.py'
        $process=Start-Process -FilePath $config.python -ArgumentList ('"'+$backend+'"') -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $config.logs 'stdout.log') -RedirectStandardError (Join-Path $config.logs 'stderr.log') -PassThru
        $deadline=[DateTime]::UtcNow.AddSeconds(25)
        do {
            Start-Sleep -Milliseconds 400
            $status=Get-InBridge
            if($status){break}
            if($process.HasExited){throw ('IN helper stopped. See '+(Join-Path $config.logs 'stderr.log'))}
        } while([DateTime]::UtcNow -lt $deadline)
        if(-not $status){throw 'IN helper startup timed out.'}
    }
    $target='http://127.0.0.1:8766/start'
    if($port -ne 'AUTO'){$target+='?robot_port='+$port}
    if($selection){$target+= $(if($target.Contains('?')){'&'}else{'?'})+$selection}
    if(-not $NoBrowser){Start-Process -FilePath $target}
} catch {
    if($NoBrowser){throw}
    Add-Type -AssemblyName PresentationFramework
    [System.Windows.MessageBox]::Show($_.Exception.Message,'IN helper') | Out-Null
} finally {
    if($owned){$mutex.ReleaseMutex()}
    if($mutex){$mutex.Dispose()}
}
