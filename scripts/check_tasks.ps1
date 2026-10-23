<#
.SYNOPSIS
  작업 스케줄러에 등록된 my-planner 작업의 값을 점검합니다(스펙 5.1).

.DESCRIPTION
  점검한 설정마다 한 줄씩 OK 또는 FAIL을 출력합니다. FAIL이 하나라도 있으면 종료 코드 1입니다.
  .env와 비밀값은 읽지도 출력하지도 않습니다.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\check_tasks.ps1
  powershell -ExecutionPolicy Bypass -File scripts\check_tasks.ps1 -Root E:\my-planner -NoWake
#>
[CmdletBinding()]
param(
    [string]$Root = (Split-Path -Parent $PSScriptRoot),
    [switch]$NoWake
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$MainTask = 'my-planner'
$WakeTask = 'my-planner-wake'
# MSFT_TaskWeeklyTrigger.DaysOfWeek 비트: 일 1, 월 2, 화 4, 수 8, 목 16, 금 32, 토 64
$DaysMask = @{ weekday = 62; weekend = 65 }

$Root = (Resolve-Path -LiteralPath $Root).Path.TrimEnd('\')
$python = Join-Path $Root '.venv\Scripts\python.exe'
$pythonw = Join-Path $Root '.venv\Scripts\pythonw.exe'
$script:Fails = 0

function Test-Value([string]$Name, $Expected, $Actual) {
    if ("$Actual" -eq "$Expected") {
        Write-Output "OK   $Name = $Actual"
    } else {
        Write-Output "FAIL $Name = '$Actual' (expected '$Expected')"
        $script:Fails++
    }
}

function Find-Task([string]$TaskName) {
    # 아무것도 출력하지 않습니다(함수의 출력은 반환값에 섞입니다)
    return Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
}

function Test-Common([string]$Prefix, $Task, [string]$Arguments) {
    $s = $Task.Settings
    Test-Value "$Prefix DisallowStartIfOnBatteries" 'False' $s.DisallowStartIfOnBatteries
    Test-Value "$Prefix StopIfGoingOnBatteries" 'False' $s.StopIfGoingOnBatteries
    Test-Value "$Prefix MultipleInstances" 'IgnoreNew' $s.MultipleInstances
    Test-Value "$Prefix Principal.LogonType" 'Interactive' $Task.Principal.LogonType
    Test-Value "$Prefix Actions.Count" 1 @($Task.Actions).Count
    $action = @($Task.Actions)[0]
    Test-Value "$Prefix Action.Execute" $pythonw $action.Execute
    Test-Value "$Prefix Action.Arguments" $Arguments $action.Arguments
}

function Get-WakeTimes {
    $saved = $env:MY_PLANNER_ROOT
    try {
        $env:MY_PLANNER_ROOT = $Root
        $lines = @(& $python -m my_planner.wake_times)
        if ($LASTEXITCODE -ne 0) { throw "wake_times exit code $LASTEXITCODE" }
    } finally {
        $env:MY_PLANNER_ROOT = $saved
    }
    return $lines | ForEach-Object { "$_".Trim() } | Where-Object { $_ }
}

# 1. 상시 작업
$main = Find-Task $MainTask
Test-Value "$MainTask registered" 'True' ($null -ne $main)
if ($null -ne $main) {
    $p = $MainTask
    Test-Common $p $main '-m my_planner'
    Test-Value "$p ExecutionTimeLimit" 'PT0S' $main.Settings.ExecutionTimeLimit
    Test-Value "$p RestartCount" 999 $main.Settings.RestartCount
    Test-Value "$p RestartInterval" 'PT1M' $main.Settings.RestartInterval
    Test-Value "$p Action.WorkingDirectory" $Root @($main.Actions)[0].WorkingDirectory

    $triggers = @($main.Triggers)
    $logon = @($triggers | Where-Object { $_.CimClass.CimClassName -eq 'MSFT_TaskLogonTrigger' })
    $resumeTrigger = @($triggers | Where-Object { $_.CimClass.CimClassName -eq 'MSFT_TaskEventTrigger' })
    $time = @($triggers | Where-Object { $_.CimClass.CimClassName -eq 'MSFT_TaskTimeTrigger' })
    Test-Value "$p Triggers.Count" 3 $triggers.Count
    Test-Value "$p LogonTrigger.Count" 1 $logon.Count
    Test-Value "$p EventTrigger.Count" 1 $resumeTrigger.Count
    if ($resumeTrigger.Count -eq 1) {
        $sub = "$($resumeTrigger[0].Subscription)"
        $resume = ($sub -like "*Microsoft-Windows-Power-Troubleshooter*") -and ($sub -like '*EventID=1]*') -and ($sub -like '*Path="System"*')
        Test-Value "$p EventTrigger is Power-Troubleshooter ID 1 (System)" 'True' $resume
    }
    Test-Value "$p TimeTrigger.Count" 1 $time.Count
    if ($time.Count -eq 1) {
        Test-Value "$p TimeTrigger.Repetition.Interval" 'PT5M' $time[0].Repetition.Interval
    }
    foreach ($t in $triggers) {
        Test-Value "$p $($t.CimClass.CimClassName).Enabled" 'True' $t.Enabled
    }
    Test-Value "$p State is Running" 'Running' $main.State
}

# 2. 깨우기 작업
if ($NoWake) {
    $absent = $null -eq (Find-Task $WakeTask)
    Test-Value "$WakeTask not registered (-NoWake)" 'True' $absent
} else {
    $wake = Find-Task $WakeTask
    Test-Value "$WakeTask registered" 'True' ($null -ne $wake)
    if ($null -ne $wake) {
        $p = $WakeTask
        Test-Common $p $wake '-c pass'
        Test-Value "$p WakeToRun" 'True' $wake.Settings.WakeToRun

        $registered = @()
        foreach ($t in @($wake.Triggers)) {
            $kind = '?'
            foreach ($k in $DaysMask.Keys) { if ($DaysMask[$k] -eq [int]$t.DaysOfWeek) { $kind = $k } }
            $hhmm = if ("$($t.StartBoundary)" -match 'T(\d{2}:\d{2})') { $Matches[1] } else { '?' }
            $registered += "$kind $hhmm"
        }
        $expected = @(Get-WakeTimes)
        Test-Value "$p Triggers.Count" $expected.Count $registered.Count
        foreach ($line in $expected) {
            Test-Value "$p trigger '$line'" 'True' ($registered -contains $line)
        }
    }
}

if ($script:Fails -gt 0) {
    Write-Output "FAIL total: $script:Fails"
    exit 1
}
Write-Output 'OK   all checks passed'
exit 0
