<#
.SYNOPSIS
  my-planner를 작업 스케줄러에 등록합니다(스펙 5.1).

.DESCRIPTION
  - 상시 작업 my-planner: 로그온, 절전 복귀(Power-Troubleshooter ID 1), 5분 워치독 트리거.
    배터리에서도 실행, 시간 제한 없음, IgnoreNew, 실패 시 1분 간격 999회 재시작, 작업 폴더는 루트.
  - 구조 작업 my-planner-medic(SP6 자동 복구): 로그온 + 5분 감시 트리거로 `pythonw scripts\medic_boot.py`(medic 실행기)를 띄웁니다.
    시간 제한 없음, IgnoreNew. 운영 작업(my-planner)을 등록할 때만 함께 등록합니다. `-NoMedic`이면 등록하지 않고 있으면 지웁니다.
  - 깨우기 작업 my-planner-wake: 회차 시각 5분 전에 깨우고 pythonw -c pass만 실행합니다.
    시각은 `python -m my_planner.wake_times`가 config.toml과 앱에서 바꾼 체크인 시간(DB, 읽기 전용)으로 계산합니다.
    앱 설정에서 체크인 시간을 바꾸면 BE가 scripts\update_wake_task.ps1로 깨우기 작업만 다시 등록합니다.
    그게 안 됐다는 안내(설정 화면)가 보이거나 config.toml의 회차 시각을 바꾸면 이 스크립트를 다시 실행하세요.
    S4: 깨우기 타이머는 AC 전원에서만 확인했습니다. 배터리에서는 전원 옵션 "절전 모드 해제 타이머 허용"이 정합니다.

  - 개발용 구조 작업(-MedicTaskName my-planner-medic-dev, 배포 흐름 스펙 5.2·5.3): 운영과 같은 템플릿에 이름·경로만 다릅니다.
    개발용 작업(-TaskName이 my-planner가 아님)에만 쓸 수 있고, 운영 my-planner-medic 이름은 거부합니다.

  템플릿(scripts\*.xml.tmpl)의 자리표시자를 채워 state\tasks\에 UTF-16 LE로 저장하고,
  Register-ScheduledTask -Xml로 등록합니다. .env와 비밀값은 읽지도 출력하지도 않습니다.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\register_task.ps1
  powershell -ExecutionPolicy Bypass -File scripts\register_task.ps1 -Root E:\my-planner -NoWake
  powershell -ExecutionPolicy Bypass -File scripts\register_task.ps1 -Root E:\my-planner-dev -TaskName my-planner-dev
    개발용 BE(배포 흐름 스펙 5.2). 이름이 my-planner가 아니면 깨우기 작업은 만들지도 지우지도 않습니다(회차가 없고, 운영 깨우기 작업을 건드리지 않게).
  powershell -ExecutionPolicy Bypass -File scripts\register_task.ps1 -Root E:\my-planner-dev -TaskName my-planner-dev -MedicTaskName my-planner-medic-dev
    개발용 medic(medic-dev)도 함께 등록합니다.
#>
[CmdletBinding()]
param(
    [string]$Root = '',
    [string]$TaskName = 'my-planner',
    [string]$MedicTaskName = '',
    [switch]$NoWake,
    [switch]$NoMedic
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$MainTask = $TaskName
$WakeTask = 'my-planner-wake'
$MedicTask = 'my-planner-medic'

# Windows PowerShell 5.1은 param 기본값을 계산할 때 $PSScriptRoot가 비어 있다
if (-not $Root) { $Root = Split-Path -Parent $PSScriptRoot }
$Root = (Resolve-Path -LiteralPath $Root).Path.TrimEnd('\')
# 개발용 체크아웃을 운영 작업 이름으로 등록하면 운영 my-planner·my-planner-wake를 덮어쓴다
$localCfg = Join-Path $Root 'config.local.toml'
if ($TaskName -eq 'my-planner' -and (Test-Path -LiteralPath $localCfg) -and
    (Select-String -LiteralPath $localCfg -Pattern '^\s*role\s*=\s*"dev"' -Quiet)) {
    throw "개발용 체크아웃입니다(role = dev). -TaskName my-planner-dev로 등록하세요: $Root"
}
# 개발용 medic 이름은 개발용 작업에만 쓴다: 운영 my-planner-medic을 덮어쓰지 않게
if ($MedicTaskName -and ($TaskName -eq 'my-planner' -or $MedicTaskName -notmatch '^my-planner-medic-.+' -or $NoMedic)) {
    throw '-MedicTaskName은 개발용 작업(-TaskName이 my-planner가 아님)에만, my-planner-medic-<이름> 꼴로만 쓸 수 있고 -NoMedic과 함께 쓸 수 없습니다(운영 이름 보호)'
}
$python = Join-Path $Root '.venv\Scripts\python.exe'
$pythonw = Join-Path $Root '.venv\Scripts\pythonw.exe'
foreach ($exe in @($python, $pythonw)) {
    if (-not (Test-Path -LiteralPath $exe -PathType Leaf)) { throw "venv 실행 파일이 없습니다: $exe" }
}
$user = "$env:USERDOMAIN\$env:USERNAME"
$outDir = Join-Path $Root 'state\tasks'
New-Item -ItemType Directory -Force -Path $outDir | Out-Null
# 템플릿 채우기, 등록, 깨우기 시각(Get-WakeTimes)은 update_wake_task.ps1과 함께 쓴다
. (Join-Path $PSScriptRoot 'task_common.ps1')

function Stop-MedicProcesses {
    # 작업을 멈춰도 실행기가 띄운 자식 python(medic)은 남는다: 이 폴더의 medic 프로세스 트리를 끝낸다
    $r = $Root.ToLowerInvariant() + '\'  # 끝의 \: my-planner-dev 같은 이웃 폴더를 맞히지 않게
    $found = @(Get-CimInstance Win32_Process | Where-Object {
        ($_.Name -eq 'pythonw.exe' -or $_.Name -eq 'python.exe') -and $_.CommandLine -and
        $_.CommandLine.ToLowerInvariant().Contains($r) -and
        ($_.CommandLine -match '(^|\s)-m\s+my_planner_medic(\s|$)' -or $_.CommandLine -match 'medic_boot\.py')
    })
    foreach ($proc in $found) { & taskkill /T /F /PID $proc.ProcessId | Out-Null }
}

$common = @{
    PYTHONW = ConvertTo-XmlText $pythonw
    ROOT    = ConvertTo-XmlText $Root
    USER    = ConvertTo-XmlText $user
}

# 1. 상시 작업
Register-FromXml $MainTask (Expand-Template 'task_my-planner.xml.tmpl' $common)

# 2. 구조 작업 medic (운영 작업, 또는 -MedicTaskName을 준 개발용 작업)
if ($MedicTaskName) {
    Register-FromXml $MedicTaskName (Expand-Template 'task_my-planner-medic.xml.tmpl' $common)
} elseif ($MainTask -ne 'my-planner') {
    Write-Output "medic 작업은 운영($MedicTask)만 둡니다: $MainTask 는 건너뜀"
} elseif ($NoMedic) {
    if (Get-ScheduledTask -TaskName $MedicTask -ErrorAction SilentlyContinue) {
        Stop-ScheduledTask -TaskName $MedicTask -ErrorAction SilentlyContinue
        Stop-MedicProcesses
        Unregister-ScheduledTask -TaskName $MedicTask -Confirm:$false
        Write-Output "medic 작업을 지웠습니다(-NoMedic): $MedicTask"
    } else {
        Write-Output "medic 작업은 등록하지 않았습니다(-NoMedic)"
    }
} else {
    Register-FromXml $MedicTask (Expand-Template 'task_my-planner-medic.xml.tmpl' $common)
}

# 3. 깨우기 작업 (운영 작업만)
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

# 4. 지금 바로 한 번 띄웁니다(이미 실행 중이면 IgnoreNew라 아무 일도 없습니다)
Start-ScheduledTask -TaskName $MainTask
if (($MainTask -eq 'my-planner') -and -not $NoMedic) { Start-ScheduledTask -TaskName $MedicTask }
if ($MedicTaskName) { Start-ScheduledTask -TaskName $MedicTaskName }
Write-Output "시작했습니다: $MainTask. 점검: powershell -ExecutionPolicy Bypass -File scripts\check_tasks.ps1"
