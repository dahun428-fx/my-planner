<#
.SYNOPSIS
  작업 등록 스크립트가 함께 쓰는 함수(register_task.ps1, update_wake_task.ps1). 직접 실행하지 않고 dot-source합니다.

.DESCRIPTION
  부르는 스크립트가 미리 정해 둘 변수: $Root(루트), $python(.venv python.exe), $outDir(state\tasks).
#>

$DaysXml = @{
    weekday = '<Monday /><Tuesday /><Wednesday /><Thursday /><Friday />'
    weekend = '<Saturday /><Sunday />'
}

function ConvertTo-XmlText([string]$Value) {
    return [System.Security.SecurityElement]::Escape($Value)
}

function Expand-Template([string]$Name, [hashtable]$Values) {
    $text = Get-Content -Raw -Encoding UTF8 -LiteralPath (Join-Path $PSScriptRoot $Name)
    foreach ($key in $Values.Keys) {
        $text = $text.Replace('{{' + $key + '}}', $Values[$key])
    }
    if ($text.Contains('{{')) { throw "채우지 않은 자리표시자가 남았습니다: $Name" }
    return $text
}

function Register-FromXml([string]$TaskName, [string]$Xml) {
    $path = Join-Path $outDir "$TaskName.xml"
    Set-Content -LiteralPath $path -Value $Xml -Encoding Unicode -NoNewline  # UTF-16 LE (BOM)
    Register-ScheduledTask -Xml (Get-Content -Raw -LiteralPath $path) -TaskName $TaskName -Force | Out-Null
    Write-Output "등록했습니다: $TaskName ($path)"
}

function Get-WakeTimes {
    # config.toml의 [schedule]과 앱에서 바꾼 체크인 시간(DB, 읽기 전용)을 읽습니다(.env는 읽지 않음). 한 줄에 하나: "weekday HH:MM" / "weekend HH:MM"
    $saved = $env:MY_PLANNER_ROOT
    try {
        $env:MY_PLANNER_ROOT = $Root
        $lines = @(& $python -m my_planner.wake_times)
        if ($LASTEXITCODE -ne 0) { throw "wake_times 실행이 끝까지 되지 않았습니다(종료 코드 $LASTEXITCODE)" }
    } finally {
        $env:MY_PLANNER_ROOT = $saved
    }
    $times = @()
    foreach ($line in $lines) {
        if ("$line".Trim() -notmatch '^(weekday|weekend) ([0-2][0-9]:[0-5][0-9])$') {
            throw "wake_times 출력 형식이 다릅니다: $line"
        }
        $times += [pscustomobject]@{ Kind = $Matches[1]; Time = $Matches[2] }
    }
    if ($times.Count -eq 0) { throw 'wake_times가 시각을 하나도 내지 않았습니다' }
    return $times
}
