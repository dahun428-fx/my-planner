<#
.SYNOPSIS
  my-planner를 작업 스케줄러에 등록합니다(스펙 5.1).

.DESCRIPTION
  - 상시 작업 my-planner: 로그온, 절전 복귀(Power-Troubleshooter ID 1), 5분 워치독 트리거.
    배터리에서도 실행, 시간 제한 없음, IgnoreNew, 실패 시 1분 간격 999회 재시작, 작업 폴더는 루트.
  - 깨우기 작업 my-planner-wake: 회차 시각 5분 전에 깨우고 pythonw -c pass만 실행합니다.
    시각은 `python -m my_planner.wake_times`가 config.toml에서 계산합니다. 회차 시각을 바꾸면 다시 실행하세요.
    S4: 깨우기 타이머는 AC 전원에서만 확인했습니다. 배터리에서는 전원 옵션 "절전 모드 해제 타이머 허용"이 정합니다.

  템플릿(scripts\*.xml.tmpl)의 자리표시자를 채워 state\tasks\에 UTF-16 LE로 저장하고,
  Register-ScheduledTask -Xml로 등록합니다. .env와 비밀값은 읽지도 출력하지도 않습니다.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\register_task.ps1
  powershell -ExecutionPolicy Bypass -File scripts\register_task.ps1 -Root E:\my-planner -NoWake
  powershell -ExecutionPolicy Bypass -File scripts\register_task.ps1 -Root E:\my-planner-dev -TaskName my-planner-dev
    개발용 BE(배포 흐름 스펙 5.2). 이름이 my-planner가 아니면 깨우기 작업은 만들지도 지우지도 않습니다(회차가 없고, 운영 깨우기 작업을 건드리지 않게).
#>
[CmdletBinding()]
param(
    [string]$Root = '',
    [string]$TaskName = 'my-planner',
    [switch]$NoWake
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$MainTask = $TaskName
$WakeTask = 'my-planner-wake'
$DaysXml = @{
    weekday = '<Monday /><Tuesday /><Wednesday /><Thursday /><Friday />'
    weekend = '<Saturday /><Sunday />'
}

# Windows PowerShell 5.1은 param 기본값을 계산할 때 $PSScriptRoot가 비어 있다
if (-not $Root) { $Root = Split-Path -Parent $PSScriptRoot }
$Root = (Resolve-Path -LiteralPath $Root).Path.TrimEnd('\')
$python = Join-Path $Root '.venv\Scripts\python.exe'
$pythonw = Join-Path $Root '.venv\Scripts\pythonw.exe'
foreach ($exe in @($python, $pythonw)) {
    if (-not (Test-Path -LiteralPath $exe -PathType Leaf)) { throw "venv 실행 파일이 없습니다: $exe" }
}
$user = "$env:USERDOMAIN\$env:USERNAME"
$outDir = Join-Path $Root 'state\tasks'
New-Item -ItemType Directory -Force -Path $outDir | Out-Null

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
    # config.toml의 [schedule]만 읽습니다(.env는 읽지 않음). 한 줄에 하나: "weekday HH:MM" / "weekend HH:MM"
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

$common = @{
    PYTHONW = ConvertTo-XmlText $pythonw
    ROOT    = ConvertTo-XmlText $Root
    USER    = ConvertTo-XmlText $user
}

# 1. 상시 작업
Register-FromXml $MainTask (Expand-Template 'task_my-planner.xml.tmpl' $common)

# 2. 깨우기 작업 (운영 작업만)
if ($MainTask -ne 'my-planner') {
    Write-Output "깨우기 작업은 운영($WakeTask)만 둡니다: $MainTask 는 건너뜀"
} elseif ($NoWake) {
    if (Get-ScheduledTask -TaskName $WakeTask -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $WakeTask -Confirm:$false
        Write-Output "깨우기 작업을 지웠습니다(-NoWake): $WakeTask"
    } else {
        Write-Output "깨우기 작업은 등록하지 않았습니다(-NoWake)"
    }
} else {
    $triggers = foreach ($t in Get-WakeTimes) {
        Expand-Template 'task_my-planner-wake_trigger.xml.tmpl' @{ TIME = $t.Time; DAYS = $DaysXml[$t.Kind] }
        Write-Verbose "깨우기 시각: $($t.Kind) $($t.Time)"
    }
    $values = $common.Clone()
    $values['WAKE_TRIGGERS'] = ($triggers -join "`r`n")
    Register-FromXml $WakeTask (Expand-Template 'task_my-planner-wake.xml.tmpl' $values)
}

# 3. 지금 바로 한 번 띄웁니다(이미 실행 중이면 IgnoreNew라 아무 일도 없습니다)
Start-ScheduledTask -TaskName $MainTask
Write-Output "시작했습니다: $MainTask. 점검: powershell -ExecutionPolicy Bypass -File scripts\check_tasks.ps1"
