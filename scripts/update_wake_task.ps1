<#
.SYNOPSIS
  깨우기 작업 my-planner-wake의 트리거만 다시 등록합니다(SP9 스펙 8장).

.DESCRIPTION
  앱 설정에서 체크인 시간을 바꾸면 BE(같은 사용자, 관리자 권한 없음)가 이 스크립트를 부릅니다.
  시각은 register_task.ps1과 같은 Get-WakeTimes(`python -m my_planner.wake_times`: config.toml + DB의 바꾼 시각)로
  계산하고, 등록도 같은 Register-FromXml로 합니다(scripts\task_common.ps1). 그때의 DB 값으로 트리거를 다시 만드므로
  여러 번 겹쳐 불러도 마지막 값이 이깁니다.
  - 운영 작업만 다룹니다. 개발용 체크아웃(config.local.toml의 role = "dev")이면 아무것도 하지 않고 끝납니다.
  - 깨우기 작업이 없으면(-NoWake로 등록) 새로 만들지 않고 끝납니다.
  - 실패하면 종료 코드가 0이 아닙니다. BE는 설정 화면에 register_task.ps1을 다시 실행하라는 안내를 보입니다.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\update_wake_task.ps1 -DryRun
    등록하지 않고 "would set N triggers"만 출력합니다(SP9-11 노트북 점검).
#>
[CmdletBinding()]
param(
    [string]$Root = '',
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$WakeTask = 'my-planner-wake'

# Windows PowerShell 5.1은 param 기본값을 계산할 때 $PSScriptRoot가 비어 있다
if (-not $Root) { $Root = Split-Path -Parent $PSScriptRoot }
$Root = (Resolve-Path -LiteralPath $Root).Path.TrimEnd('\')
$localCfg = Join-Path $Root 'config.local.toml'
if ((Test-Path -LiteralPath $localCfg) -and
    (Select-String -LiteralPath $localCfg -Pattern '^\s*role\s*=\s*"dev"' -Quiet)) {
    Write-Output "개발용 체크아웃이라 깨우기 작업을 건드리지 않습니다: $Root"
    exit 0
}
$python = Join-Path $Root '.venv\Scripts\python.exe'
$pythonw = Join-Path $Root '.venv\Scripts\pythonw.exe'
foreach ($exe in @($python, $pythonw)) {
    if (-not (Test-Path -LiteralPath $exe -PathType Leaf)) { throw "venv 실행 파일이 없습니다: $exe" }
}
$user = "$env:USERDOMAIN\$env:USERNAME"
$outDir = Join-Path $Root 'state\tasks'
. (Join-Path $PSScriptRoot 'task_common.ps1')

$times = @(Get-WakeTimes)
$triggers = foreach ($t in $times) {
    Expand-Template 'task_my-planner-wake_trigger.xml.tmpl' @{ TIME = $t.Time; DAYS = $DaysXml[$t.Kind] }
}
if ($DryRun) {
    Write-Output "would set $($times.Count) triggers"
    exit 0
}
if (-not (Get-ScheduledTask -TaskName $WakeTask -ErrorAction SilentlyContinue)) {
    Write-Output "깨우기 작업이 없어 건너뜁니다: $WakeTask"
    exit 0
}
New-Item -ItemType Directory -Force -Path $outDir | Out-Null
$values = @{
    PYTHONW       = ConvertTo-XmlText $pythonw
    ROOT          = ConvertTo-XmlText $Root
    USER          = ConvertTo-XmlText $user
    WAKE_TRIGGERS = ($triggers -join "`r`n")
}
Register-FromXml $WakeTask (Expand-Template 'task_my-planner-wake.xml.tmpl' $values)
