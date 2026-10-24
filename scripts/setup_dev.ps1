<#
.SYNOPSIS
  노트북에 개발용 BE(my-planner-dev)를 설치합니다(배포 흐름 스펙 5.2, 8장 D5).

.DESCRIPTION
  develop 브랜치의 별도 체크아웃(기본 E:\my-planner-dev) 안에서 실행합니다. 운영 체크아웃은 건드리지 않습니다.
  1. 브랜치가 develop인지 확인
  2. .venv 만들기와 설치(없을 때만)
  3. config.local.toml 쓰기(없을 때만): role = "dev", 포트, 스테이징 CORS
  4. .env 쓰기(없을 때만): 새 API_TOKEN 하나. 텔레그램·VAPID는 넣지 않습니다
  5. 작업 스케줄러에 my-planner-dev 등록(깨우기 작업 없음)
  6. tailscale serve로 https://<노트북>.<tailnet>.ts.net:<HttpsPort> → 127.0.0.1:<Port>
  토큰 값은 화면에 출력하지 않습니다. 스테이징 앱에 넣을 때는 .env에서 복사합니다.
  medic-dev(config.medic.local.toml, my-planner-medic-dev 작업, staging/be)는 SP6 후속 티켓이 들어오면 따로 설치합니다.
  그 전까지 개발용 BE는 손으로 git pull 후 작업을 다시 시작해야 갱신됩니다(배포 흐름 스펙 6.3).

.EXAMPLE
  git clone https://github.com/dahun428-fx/my-planner.git -b develop E:\my-planner-dev
  cd E:\my-planner-dev
  powershell -ExecutionPolicy Bypass -File scripts\setup_dev.ps1
#>
[CmdletBinding()]
param(
    [string]$Root = '',
    [int]$Port = 8788,
    [int]$HttpsPort = 8443,
    [string[]]$CorsOrigins = @(
        'https://my-planner-git-develop-dahun428-fxs-projects.vercel.app',
        'https://my-planner-dashboard-git-develop-dahun428-fxs-projects.vercel.app'
    )
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

if (-not $Root) { $Root = Split-Path -Parent $PSScriptRoot }
$Root = (Resolve-Path -LiteralPath $Root).Path.TrimEnd('\')
Set-Location -LiteralPath $Root
# powershell -File은 -CorsOrigins a,b를 문자열 하나로 넘긴다
$CorsOrigins = @($CorsOrigins | ForEach-Object { $_ -split ',' } | ForEach-Object { $_.Trim() } | Where-Object { $_ })

# 1. develop 체크아웃인지
$branch = (& git -C $Root rev-parse --abbrev-ref HEAD).Trim()
if ($branch -ne 'develop') { throw "develop 체크아웃에서 실행하세요(지금: $branch)" }

# 2. venv
$python = Join-Path $Root '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    & py -3.12 -m venv (Join-Path $Root '.venv')
    if ($LASTEXITCODE -ne 0) { throw 'venv를 만들지 못했습니다(py -3.12)' }
    & $python -m pip install -q -r (Join-Path $Root 'requirements.lock')
    if ($LASTEXITCODE -ne 0) { throw 'requirements.lock 설치 실패' }
    & $python -m pip install -q -e $Root --no-deps
    if ($LASTEXITCODE -ne 0) { throw 'my-planner 설치 실패' }
    Write-Output '만들었습니다: .venv'
}

# 3. config.local.toml (Git에 넣지 않음)
$local = Join-Path $Root 'config.local.toml'
if (-not (Test-Path -LiteralPath $local)) {
    $origins = ($CorsOrigins | ForEach-Object { '"' + $_ + '"' }) -join ', '
    $text = @"
# 개발용 BE(배포 흐름 스펙 5.2). config.toml 위에 겹쳐 읽는다. 비밀값은 두지 않는다
[runtime]
role = "dev"

[api]
port = $Port
cors_origins = [$origins]
"@
    [System.IO.File]::WriteAllText($local, $text + "`r`n", (New-Object System.Text.UTF8Encoding $false))
    Write-Output "만들었습니다: config.local.toml (포트 $Port)"
} else {
    Write-Output 'config.local.toml이 이미 있어 그대로 둡니다'
}

# 4. .env (Git에 넣지 않음). 운영 .env를 복사하지 않는다
$envPath = Join-Path $Root '.env'
if (-not (Test-Path -LiteralPath $envPath)) {
    $token = (& $python -m my_planner gen-token).Trim()
    if ($LASTEXITCODE -ne 0 -or -not $token) { throw 'gen-token 실패' }
    $text = "# 개발용 BE. 텔레그램·VAPID 없음(role = dev)`r`nAPI_TOKEN=$token`r`n"
    [System.IO.File]::WriteAllText($envPath, $text, (New-Object System.Text.UTF8Encoding $false))
    Write-Output '만들었습니다: .env (새 API_TOKEN)'
} else {
    Write-Output '.env가 이미 있어 그대로 둡니다'
}

# 5. 작업 스케줄러
& (Join-Path $PSScriptRoot 'register_task.ps1') -Root $Root -TaskName 'my-planner-dev'

# 6. tailnet HTTPS (운영 443과 따로)
& tailscale serve --bg "--https=$HttpsPort" "http://127.0.0.1:$Port"
if ($LASTEXITCODE -ne 0) { throw 'tailscale serve 실패' }
$savedEncoding = [Console]::OutputEncoding
try {
    [Console]::OutputEncoding = [Text.Encoding]::UTF8  # 장치 이름에 한글이 있어도 JSON이 깨지지 않게
    $status = (& tailscale status --json | Out-String) | ConvertFrom-Json
} finally {
    [Console]::OutputEncoding = $savedEncoding
}
$dns = ''
if ($status.PSObject.Properties['Self'] -and $status.Self.PSObject.Properties['DNSName']) { $dns = "$($status.Self.DNSName)".TrimEnd('.') }
if (-not $dns) { throw 'tailnet 이름을 못 읽었습니다(MagicDNS와 HTTPS 인증서가 켜져 있는지 확인)' }
Write-Output "개발용 BE 주소: https://${dns}:$HttpsPort  (스테이징 앱 연결 화면에 넣고, 토큰은 .env의 API_TOKEN)"
