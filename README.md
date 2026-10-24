# my-planner

Dahun 한 사람을 위한 텔레그램 AI 비서입니다. 텔레그램 개인 채팅으로 말을 걸면 비서(Claude)가 답합니다.

- 말로 할 일을 추가하고, 옮기고, 끝내고, 우선순위를 정합니다. 바뀔 때마다 `✓ 추가: …` 같은 확인 문구가 붙습니다.
- 비서가 먼저 연락합니다: 아침 브리핑(평일 09:00, 주말 10:00), 저녁 체크인과 컨디션 버튼 1~5(평일 17:30, 주말 18:00), 일요일 주간 회고(저녁 체크인과 한 메시지). 하루 최대 3번입니다.
- 비서가 제안한 할 일은 초안이고, `✓ 추가` 버튼을 누르거나 "넣어 줘"라고 해야 목록에 오릅니다.
- 명령: `/today`, `/week`, `/pause 3`, `/unpause`, `/plan 주제`, `/done`, `/help`.
- 대화는 이어집니다. 회차 메시지에 답하면 그 대화로, 마지막 메시지 뒤 30분 안이면 같은 대화로(계획 모드는 2시간) 이어서 답합니다.

- 용어: [`GLOSSARY.md`](GLOSSARY.md)
- 설계: [`docs/superpowers/specs/`](docs/superpowers/specs/), 결정 기록: [`docs/adr/`](docs/adr/)

## 준비물

- Windows 11 노트북, Python 3.12 (Microsoft Store판으로 확인했습니다)
- **Windows 시간대는 서울(UTC+09:00)이어야 합니다.** `config.toml`의 `timezone = "Asia/Seoul"`로 회차 시각을 계산하고, 깨우기 작업은 그 시각을 노트북의 로컬 시각으로 등록합니다. 시간대가 다르면 깨우는 시각이 어긋납니다.
- Claude 구독과 Claude Code 로그인. 비서는 API 키가 아니라 이 PC의 구독 로그인으로 Claude를 부릅니다([ADR 0001](docs/adr/0001-subscription-login-for-brain.md)). 로그인이 안 되어 있으면 터미널에서 `claude`를 실행해 `/login` 해 주세요.
- 텔레그램 계정

## 설치

저장소 폴더는 **OneDrive 같은 동기화 폴더 밖에** 둡니다. 동기화 프로그램이 SQLite 파일(WAL)을 건드리면 데이터베이스가 손상될 수 있습니다. 기본 위치는 `E:\my-planner`입니다.

```powershell
cd E:\my-planner
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.lock
.venv\Scripts\python.exe -m pip install -e . --no-deps
```

`requirements.lock`은 정확한 버전 목록입니다. 의존성 범위는 `pyproject.toml`에 있습니다.

## `.env` 만들기

`.env.example`을 `.env`로 복사하고 두 값을 채웁니다. `.env`는 Git에 들어가지 않습니다.

```powershell
copy .env.example .env
notepad .env
```

```
TELEGRAM_BOT_TOKEN=...
OWNER_TELEGRAM_ID=...
```

### 봇 토큰 받기 (BotFather)

1. 텔레그램에서 [@BotFather](https://t.me/BotFather)를 찾아 대화를 시작합니다.
2. `/newbot`을 보내고, 봇 이름과 사용자명(`..._bot`으로 끝나야 합니다)을 정합니다.
3. BotFather가 알려 주는 토큰(`123456789:ABC...` 형식)을 `TELEGRAM_BOT_TOKEN`에 넣습니다.
4. 토큰은 비밀번호처럼 다룹니다. 새어 나갔으면 BotFather에서 `/revoke`로 바꿉니다.

### 본인 텔레그램 ID 확인

비서는 이 ID의 개인 채팅에만 답합니다. 다른 사람이나 그룹 채팅의 메시지는 무시합니다.

1. 텔레그램에서 [@userinfobot](https://t.me/userinfobot)에게 아무 메시지나 보냅니다.
2. 답장에 나오는 숫자 `Id`를 `OWNER_TELEGRAM_ID`에 넣습니다. (사용자명 `@...`이 아니라 숫자입니다.)
3. 만든 봇과의 대화창을 열어 **시작(/start)** 을 한 번 눌러 둡니다. 봇은 먼저 대화를 연 사람에게만 메시지를 보낼 수 있습니다.

## 실행

```powershell
.venv\Scripts\python.exe -m my_planner
```

- 텔레그램에서 봇에게 "안녕"이라고 보내면 답이 옵니다.
- 끄려면 이 콘솔 창에서 Ctrl+C를 누릅니다. 진행 중인 답은 최대 30초 기다렸다가 끝냅니다.
- 이미 실행 중이면 새로 띄운 프로세스는 바로 끝납니다(단일 실행 잠금 `state\my-planner.lock`).
- 다른 폴더의 데이터를 쓰려면 환경변수 `MY_PLANNER_ROOT`에 저장소 루트를 지정합니다.

설정값(회차 시각, 상한, 보관 기간)은 `config.toml`에 있습니다. 개인값은 넣지 않습니다.

## 늘 켜 두기 (작업 스케줄러)

콘솔 없이 늘 돌게 하려면 작업 스케줄러에 등록합니다. 관리자 권한은 필요 없습니다. 등록 스크립트와 점검 스크립트는 `.env`를 읽거나 비밀값을 출력하지 않습니다.

**등록**

콘솔에서 `python -m my_planner`로 띄워 둔 비서가 있으면 먼저 Ctrl+C로 끕니다. 켜 둔 채 등록하면 작업이 띄운 프로세스가 단일 실행 잠금 때문에 바로 끝나고, 점검에서 `State is Running`이 `FAIL`로 나옵니다.

```powershell
powershell -ExecutionPolicy Bypass -File scripts\register_task.ps1
```

- 상시 작업 `my-planner`: 로그온할 때, 절전에서 깨어날 때, 그리고 5분마다(워치독) `pythonw -m my_planner`를 띄웁니다. 이미 실행 중이면 아무 일도 하지 않으니 중복으로 뜨지 않습니다. 프로세스가 죽으면 5분 안에 워치독이 다시 띄웁니다. 배터리에서도 돌고, 시간 제한이 없습니다.
- 깨우기 작업 `my-planner-wake`: 회차 시각 5분 전(기본값이면 평일 08:55·17:25, 주말 09:55·17:55)에 노트북을 절전에서 깨웁니다. 하는 일은 없습니다(`pythonw -c pass`). 시각은 `config.toml`에서 계산합니다. **회차 시각을 바꾸면 등록 스크립트를 다시 실행합니다.**
- 저장소가 다른 폴더에 있으면 `-Root D:\my-planner`, 깨우기 작업 없이 등록하려면 `-NoWake`를 붙입니다.
- 등록한 XML은 `state\tasks\`에 남습니다.

**깨우기는 AC 전원에서만 확인했습니다(S4).** 이 노트북의 전원 옵션은 배터리에서 "절전 모드 해제 타이머 허용"이 꺼져 있어서, 전원 케이블을 뽑아 두면 깨우지 못합니다. 그래도 다음에 켜질 때 따라잡기로 알맞게 보냅니다. 배터리에서도 깨우려면 제어판 > 전원 옵션 > 설정 변경 > 고급 전원 관리 옵션 변경 > 절전 > 절전 모드 해제 타이머 허용 > 배터리 사용을 "사용"으로 바꿉니다(비서는 이 설정을 바꾸지 않습니다). 덮개를 닫은 상태는 아직 확인하지 않았습니다.

**점검**

```powershell
powershell -ExecutionPolicy Bypass -File scripts\check_tasks.ps1
```

설정마다 한 줄씩 `OK` 또는 `FAIL`이 나옵니다. `FAIL`이 하나라도 있으면 종료 코드가 1입니다. `-NoWake`로 등록했으면 점검에도 `-NoWake`를 붙입니다. 시작·절전 복귀 기록은 `state\logs\my-planner.jsonl`의 `starting`, `resume_detected`, `polling_restarted`에서 볼 수 있습니다.

**지우기**

```powershell
Stop-ScheduledTask -TaskName my-planner
Unregister-ScheduledTask -TaskName my-planner -Confirm:$false
Unregister-ScheduledTask -TaskName my-planner-wake -Confirm:$false
```

## 자동 복구 (medic)

비서(`my-planner`)와 따로 도는 작은 프로그램 `my-planner-medic`이 비서를 지켜봅니다. 비서 로그에 새 오류가 나거나 `/health`가 나빠지면 GitHub에 `incident` 이슈를 열고, GitHub Actions의 수리 워크플로(`repair.yml`)가 고친 PR이 CI를 통과해 `main`에 머지되면 medic이 노트북에 배포합니다. 수리는 핫픽스라 `main`에서 따서 `main`으로 가고, `sync-develop.yml`이 `develop`에 합칩니다. `watch.yml`(2시간마다)은 하트비트·토큰 만료를 확인하고 멈춘 수리를 다시 부르며, `signal.yml`은 `main`의 Vercel 빌드 실패와 CI 실패를 이슈로 엽니다. 배포 뒤 10분 안에 같은 문제가 다시 나면 이전 커밋과 DB로 되돌리고 텔레그램으로 알립니다. medic은 표준 라이브러리만 쓰고 `state\medic.db`만 씁니다(되돌릴 때 `planner.db`를 백업으로 바꾸는 것 하나가 예외입니다). 로그는 `state\logs\medic.log`에 남고 토큰과 메시지 본문은 적지 않습니다.

**처음 한 번 넣어 둘 것**

- 저장소 시크릿 4개(Settings > Secrets and variables > Actions): `CLAUDE_CODE_OAUTH_TOKEN`(노트북에서 `claude setup-token`), `REPAIR_PAT`(fine-grained PAT, 이 저장소만: Issues·Pull requests·Contents 읽기·쓰기, Actions 읽기·쓰기. Actions 쓰기는 `watch.yml`이 `repair.yml`을 다시 부를 때 씁니다), `TELEGRAM_BOT_TOKEN`, `OWNER_TELEGRAM_ID`(뒤의 둘은 `.env`와 같은 값).
- 저장소 변수: `AUTO_REPAIR`(`on`/`off`, 없으면 켜짐), `PAT_EXPIRES`(PAT 만료일 `YYYY-MM-DD`). `RELEASE_PAT_EXPIRES`·`DEV_PAT_EXPIRES`가 있으면 그 토큰도 함께 알립니다. `REPAIR_MAX_FAILURES`(기본 2)와 `REPAIR_MAX_MERGES_PER_DAY`(기본 3)는 바꾸고 싶을 때만 넣습니다.
- 라벨 `auto-repair` 하나를 미리 만들어 둡니다(Issues > Labels). 수리 PR을 열 때 붙이는 라벨이고, 나머지 라벨(`incident`, `repairing`, `failed-N` 등)은 처음 쓸 때 저절로 생깁니다.
- Settings > Actions > General > Workflow permissions는 기본값(읽기 전용)으로 둡니다. 쓰기는 모두 `REPAIR_PAT`으로 해서 "Allow GitHub Actions to create and approve pull requests"는 켜지 않아도 됩니다.
- 노트북 `.env`에 1개: `MEDIC_GITHUB_TOKEN`(fine-grained PAT, 이 저장소만: Issues 읽기·쓰기, Contents 읽기, Actions 읽기, Commit statuses 읽기). 시크릿은 `.env`와 저장소 시크릿에만 둡니다. 이슈·로그·커밋에는 남지 않습니다.
- 작업 등록: `scripts\register_task.ps1`이 `my-planner`와 함께 `my-planner-medic`도 등록합니다(medic 없이 등록하려면 `-NoMedic`, 점검에도 `-NoMedic`). 이 작업은 로그온할 때와 5분마다 `pythonw scripts\medic_boot.py`를 띄우고, 실행기가 `python -m my_planner_medic`을 자식으로 실행합니다. 점검 출력에 `my-planner-medic` 줄이 `OK`로 나와야 합니다.

**끄기**

- 수리만 멈추기: 저장소 변수 `AUTO_REPAIR`를 `off`로 바꿉니다. 이슈는 계속 열리지만 Claude가 고치려 하지 않고, `watch.yml`도 수리를 다시 부르지 않습니다(죽은 시도 정리만 합니다).
- medic 전체 멈추기: `config.medic.toml`에 `enabled = false`를 적고 medic을 다시 띄웁니다(하트비트만 보내고 감시·배포는 하지 않습니다). 작업 자체를 없애려면 `register_task.ps1 -NoMedic`을 다시 실행합니다.

**medic 자신의 갱신**

배포에 `src\my_planner_medic\`이 들어 있으면 medic은 확인을 마친 뒤 종료 코드 3으로 끝나고 실행기가 새 코드로 바로 다시 띄웁니다. 새 medic이 시작 후 60초 안에 연속 3번 죽으면 실행기가 `state\medic-last-good.json`의 커밋으로 `src\my_planner_medic\`만 되돌리고(`git checkout <sha> -- src/my_planner_medic`), 그 배포 커밋을 건너뛸 목록에 넣습니다. 이때 `git status`에 `src\my_planner_medic\` 변경이 보이는 것은 정상이며, 다음 배포 때 medic이 알아서 정리합니다. 이것도 안 되면 medic 하트비트가 끊겨 텔레그램으로 알림이 옵니다.

**`failed-<sha>`에서 손으로 되살리기**

스키마가 바뀐 배포가 되돌려지면 되돌리기 직전의 DB가 `state\backups\failed-<sha>\`(`planner.db`와 WAL 파일)에 남습니다. 되돌린 뒤 사이에 쓴 할 일·컨디션을 살리려면 위 "백업에서 복구하기"와 같은 순서(작업 끄고 멈추기, 지금 DB 옆으로 옮기기, 복사, 켜기)에서 복사할 파일만 `failed-<sha>\planner.db`로 바꿉니다. 옛 코드와 스키마가 달라서 열리지 않을 수 있으니, 필요한 행만 `sqlite3`로 꺼내는 편이 안전합니다. `failed-*`는 최근 3개만 남습니다.

**PAT 만료**

PAT은 만료일을 1년으로 두고 `PAT_EXPIRES` 변수에 같은 날짜를 적습니다. 만료 30일 전부터 하루 한 번 텔레그램으로 알려 줍니다. 새 토큰을 만들어 `REPAIR_PAT` 시크릿, `.env`의 `MEDIC_GITHUB_TOKEN`을 바꾸고 `PAT_EXPIRES`를 고친 뒤 medic을 다시 띄웁니다. 작업만 멈추면 자식 `python`(실제 medic)이 남을 수 있으니, 저장소 폴더(`E:\my-planner`)에서 아래로 자식까지 끝냅니다. 5분 안에 감시 트리거가 새 `.env`로 다시 띄웁니다.

```powershell
Stop-ScheduledTask -TaskName my-planner-medic
$r = (Get-Location).Path.ToLowerInvariant() + '\'
Get-CimInstance Win32_Process | Where-Object {
    $_.Name -in 'python.exe', 'pythonw.exe' -and $_.CommandLine -and $_.CommandLine.ToLowerInvariant().Contains($r) -and
    ($_.CommandLine -match '-m\s+my_planner_medic' -or $_.CommandLine -match 'medic_boot\.py') } |
    ForEach-Object { taskkill /T /F /PID $_.ProcessId }
```

실행기(`scripts\medic_boot.py`) 자체가 배포로 바뀌어도 이미 떠 있는 실행기는 그대로입니다. 다음 로그온이나 위 절차로 작업을 다시 시작하면 새 실행기가 뜹니다. medic을 `enabled = false`로 꺼 두어도 시작할 때 끊긴 배포의 되돌림은 끝까지 하고(`my-planner` 작업이 꺼진 채 남지 않게), 그 뒤로는 하트비트만 보냅니다.

## API 열기

운영 앱이 쓰는 API(`/api/v1/*`)는 BE가 `127.0.0.1:8787`에서만 엽니다. 폰과 다른 기기에서는 Tailscale `serve`로 **내 tailnet 안에만** 엽니다.

**토큰과 푸시 키**

`.env`에 `API_TOKEN`이 없거나 43자보다 짧으면 API를 열지 않습니다(로그 `api_token_missing`). 아래 두 명령은 값을 화면에 출력하므로, 출력을 채팅이나 문서에 붙이지 말고 `.env`에만 넣습니다.

```powershell
.venv\Scripts\python.exe -m my_planner gen-token
```

```powershell
.venv\Scripts\python.exe -m my_planner gen-vapid
```

```
API_TOKEN=...
VAPID_PUBLIC_KEY=...
VAPID_PRIVATE_KEY=...
VAPID_SUBJECT=mailto:<받을 수 있는 주소>
```

`.env`를 바꾼 뒤에는 작업을 다시 켭니다(`Stop-ScheduledTask -TaskName my-planner` 뒤 `Start-ScheduledTask -TaskName my-planner`). 로그에 `api_started`가 나오면 열린 것입니다.

**tailnet에 열기**

1. Tailscale 관리 화면(DNS)에서 MagicDNS와 HTTPS 인증서를 켭니다.
2. 443에 다른 `serve` 항목이 없으면:

   ```powershell
   tailscale serve --bg --https=443 http://127.0.0.1:8787
   ```

   443의 `/`를 이미 다른 서비스가 쓰고 있으면 그 항목은 두고 `/api`만 붙입니다:

   ```powershell
   tailscale serve --bg --https=443 --set-path=/api http://127.0.0.1:8787/api
   ```

   파일 경로(`path`) 항목이 이미 있으면 `serve` 설정을 바꿀 때 관리자 PowerShell이 필요합니다(아니면 `must be a Windows local admin to serve a path`).
3. `tailscale serve status`가 `(tailnet only)`인지, `tailscale funnel status`에 Funnel 항목이 없는지 확인합니다.
4. tailnet 기기에서 `https://<기계>.<tailnet>.ts.net/api/v1/health`를 `Authorization: Bearer <API_TOKEN>` 헤더로 열면 `"status": "ok"`, 토큰 없이 열면 `401`입니다.

**Funnel은 절대 쓰지 않습니다.** `tailscale funnel`은 API를 인터넷 전체에 엽니다. 토큰 하나만으로 할 일과 대화 기록에 닿을 수 있으니 tailnet 밖으로 열지 않습니다.

허용 출처(CORS)는 `config.toml`의 `[api] cors_origins`에 정확한 주소로만 넣습니다. 운영 앱 `https://my-planner-beige-eight.vercel.app`과 대시보드 `https://my-planner-dashboard-seven.vercel.app` 두 개입니다(끝에 `/` 없이):

```toml
[api]
cors_origins = ["https://my-planner-beige-eight.vercel.app", "https://my-planner-dashboard-seven.vercel.app"]
```

`*.vercel.app` 같은 와일드카드나 미리보기 주소 패턴은 넣지 않습니다. `config.toml`을 바꾼 뒤에도 작업을 다시 켭니다. 다시 켜지 않으면 앱 연결 화면이 "주소에 닿지 않아요"에서 막힙니다.

**토큰 바꾸기**

토큰이 새어 나갔거나 기기를 잃어버렸으면:

1. `gen-token`으로 새 토큰을 만들어 `.env`의 `API_TOKEN` 줄을 바꿉니다.
2. 작업을 다시 켭니다. 옛 토큰은 바로 `401`이 됩니다.
3. 운영 앱 설정에 새 토큰을 넣습니다.

VAPID 키를 바꾸면 기존 푸시 구독이 모두 끊기므로, 키가 새어 나갔을 때만 바꾸고 바꾼 뒤 앱에서 알림을 다시 켭니다.

## 운영 앱

폰에서 쓰는 운영 앱(`web/app/`)은 Vercel에 정적 파일로 올라가 있습니다: `https://my-planner-beige-eight.vercel.app`. 앱은 데이터를 갖지 않고, 폰이 tailnet 안의 BE(`/api/v1/*`)를 직접 부릅니다.

**Vercel 프로젝트 설정**

- Root Directory: `web/app`. 빌드 설정은 `web/app/vercel.json`이 고정합니다(Framework 없음, `npm run build`, 출력 `out`).
- 환경 변수는 `NEXT_PUBLIC_CONNECT_SRC=https://*.<tailnet>.ts.net` 하나뿐입니다. CSP `connect-src`에 들어가고, 연결 화면이 받아들이는 주소 범위도 이 값으로 정해집니다(`*`는 이름 한 칸만 맞습니다). 없으면 빌드가 멈추고, 틀리면 연결 화면이 "이 앱에서 쓸 수 있는 주소가 아니에요"를 띄웁니다. 값을 바꾸면 다시 배포합니다. 토큰은 빌드나 환경 변수에 넣지 않습니다.
- 운영 주소를 바꾸면 `config.toml`의 `[api] cors_origins`도 새 주소로 바꿉니다. 미리보기 배포 주소는 허용하지 않으므로 미리보기에서는 BE에 닿지 않습니다.

**폰에서 연결하기**

1. 폰에 Tailscale을 켜고, Safari로 앱 주소를 엽니다.
2. 공유 → 홈 화면에 추가로 설치하고, 홈 화면 아이콘으로 엽니다. Safari 탭과 홈 화면 앱은 저장 공간이 따로라서, 연결은 홈 화면 앱에서 합니다(iOS 웹 푸시도 설치한 앱에서만 됩니다).
3. 연결 화면에 BE 주소 `https://<기계>.<tailnet>.ts.net`과 `API_TOKEN`을 넣습니다. 토큰은 이 기기 안에만 남습니다.
4. 설정 › 이 기기 알림에서 허용하기를 누르고 "시험 알림 보내기"로 확인합니다. VAPID 키가 없으면 알림은 텔레그램으로 갑니다(위 "토큰과 푸시 키").

## 대시보드

인생곡선, 상태 창, 할 일과 컨디션, BE 상태를 보는 읽기 전용 대시보드(`web/dashboard/`)도 Vercel에 정적 파일로 올립니다. 운영 앱과 같은 BE와 같은 `API_TOKEN`을 씁니다.

**Vercel 프로젝트 설정**

- 운영 앱과 **다른 프로젝트**로 만들고, Root Directory는 `web/dashboard`입니다. 빌드 설정은 `web/dashboard/vercel.json`이 고정합니다(Framework 없음, `npm run build`, 출력 `out`).
- 환경 변수는 운영 앱과 같은 `NEXT_PUBLIC_CONNECT_SRC=https://*.<tailnet>.ts.net` 하나뿐입니다. CSP `connect-src`에 들어가며, 없으면 빌드가 멈추고 틀리면 BE에 닿지 않습니다. 값을 바꾸면 다시 배포합니다. BE 주소와 토큰은 넣지 않습니다(정적 파일은 누구나 받을 수 있습니다). Vercel 분석은 켜지 않습니다.
- 배포 주소가 정해지면 `config.toml`의 `[api] cors_origins`에 그 주소를 **더합니다**(운영 앱 주소는 그대로 둡니다). 그 뒤 작업을 다시 켭니다.

  ```toml
  [api]
  cors_origins = ["https://my-planner-beige-eight.vercel.app", "https://my-planner-dashboard-seven.vercel.app"]
  ```

**연결하기**

1. 폰이나 노트북에서 Tailscale을 켜고 대시보드 주소를 엽니다.
2. 설정 화면에 BE 주소 `https://<기계>.<tailnet>.ts.net`과 `API_TOKEN`을 넣고 "연결 확인"을 누릅니다. 둘은 그 브라우저 안에만 남습니다.
3. 처음 연결할 때 데스크톱이나 Android Chrome이 로컬 네트워크 접근 권한 창을 띄울 수 있습니다(사설망 접근, PNA). 뜨면 허용합니다. 브라우저와 버전에 따라 안 뜰 수도 있습니다.
4. 화면 위 연결 표시줄에 "BE 꺼짐"이 보이면 BE에 닿지 않는 것입니다. 노트북이 꺼졌거나 잠들었는지, my-planner가 돌고 있는지, 폰과 노트북의 Tailscale이 켜져 있는지 봅니다. 마지막으로 응답한 시각이 함께 나옵니다.

**인생 시드 가져오기**

처음 한 번, 검토를 마친 시드 파일에서 챕터와 사건을 가져옵니다. 점수는 가져오지 않습니다(회고에서 답할 때 생깁니다).

명령은 모두 저장소 폴더(`E:\my-planner`)에서 실행합니다.

1. 시드 파일을 노트북의 `data\seed\` 아래로 옮기고, 검토를 마쳤으면 `meta.reviewed`를 `true`로 넣습니다. `sensitive: true`이거나 `storage` 키가 있는 항목은 `confirmed: true`를 넣은 것만 가져옵니다.
2. my-planner를 멈춥니다. 5분마다 도는 워치독이 다시 띄우지 않도록 작업을 잠시 끕니다.

   ```powershell
   Disable-ScheduledTask -TaskName my-planner
   Stop-ScheduledTask -TaskName my-planner
   ```

   그리고 미리 봅니다. 가져올 개수와 건너뛸 이유별 개수만 나오고 내용은 나오지 않습니다. 가져올 개수가 파일의 챕터·사건 수에서 확인 안 한 민감 항목을 뺀 것과 맞는지 봅니다. `invalid`가 있으면 형식이 틀린 항목이 있는 것입니다.

   ```powershell
   .venv\Scripts\python.exe -m my_planner seed-life data\seed\<파일> --dry-run
   ```

3. 개수가 맞으면 `--dry-run` 없이 한 번 더 실행해 가져오고, 작업을 다시 켭니다.

   ```powershell
   Enable-ScheduledTask -TaskName my-planner
   Start-ScheduledTask -TaskName my-planner
   ```

4. 노트북 밖에 만든 사본(클라우드 파일, 메신저 등)은 직접 지웁니다.

종료 코드: `0` 끝남, `3` my-planner가 실행 중, `4` 이미 가져옴, `5` `meta.reviewed`가 `true`가 아님, `6` 읽을 수 없거나 JSON이 아닌 파일, 또는 DB가 항목을 거절함(이때는 아무것도 저장되지 않습니다).

## 데이터는 어디에 남나요

| 위치 | 내용 |
|---|---|
| `state\planner.db` | 원본 데이터(SQLite) |
| `data\transcripts\YYYY\MM\YYYY-MM-DD.md` | 원문 기록. 하루 경계는 04:00이라 새벽 0시~3시 59분의 대화는 전날 파일에 들어갑니다 |
| `state\logs\my-planner.jsonl` | 시스템 로그. 메시지 본문은 남기지 않습니다. 하루 단위로 회전하고 30일 치를 보관합니다 |
| `data\seed\` | 인생 시드 파일(가져오기 전 원본). Git에 들어가지 않습니다 |
| `data\curve\chapters.md` | 인생 챕터와 사건을 사람이 읽게 내보낸 파일 |
| `state\backups\planner-YYYY-MM-DD.db` | DB 백업. 매일 처음 도는 tick에 하나 만들고 최근 14개를 남깁니다 |
| `%USERPROFILE%\.claude\projects\` | Claude Agent SDK가 따로 남기는 **세션 기록 사본**입니다. 원본은 `data\transcripts\`이고, 이 사본에는 가리기 전 내용이 없도록 두뇌에는 가린 글만 넘깁니다. 지우고 싶으면 이 폴더의 my-planner 관련 하위 폴더를 지우면 됩니다 |

- 주민등록번호, 계좌번호로 보이는 숫자(10~14자리), "비밀번호/비번/password/PIN" 뒤의 값(영문자나 숫자가 있을 때)은 원문 기록과 두뇌에 넘기기 전에 `[가림]`으로 바뀝니다. 휴대전화, 하이픈이 있는 유선 번호, `+82` 번호는 그대로 둡니다(하이픈 없는 유선 번호는 가려집니다). **카드번호(15~16자리)는 가리지 않습니다.** 민감한 정보는 보내지 않는 편이 안전합니다.
- `data\`, `state\`, `.env`는 Git에 들어가지 않습니다. 백업은 로컬·외장 디스크에만 합니다.

## 백업에서 복구하기

시작할 때 DB를 `PRAGMA quick_check`로 검사합니다. DB가 손상되면 비서는 텔레그램으로 "데이터베이스에 문제가 있어요."라고 한 번 알리고, 답하지 않은 채 기다립니다(안전 모드, 로그 `safe_mode`). 자동으로 복구하지 않습니다. 디스크나 잠금 오류처럼 손상이 아닌 문제면 안전 모드에 들어가지 않고 프로세스가 끝나며, 5분 워치독이 다시 띄웁니다. PowerShell에서 저장소 폴더(`E:\my-planner`)로 가서 아래 순서로 복구합니다.

1. 작업을 멈춥니다. 5분 워치독이 다시 띄우지 않도록 끄고 멈춥니다(콘솔에서 실행 중이면 Ctrl+C).
   ```powershell
   Disable-ScheduledTask -TaskName my-planner
   Stop-ScheduledTask -TaskName my-planner
   ```
2. 지금 DB는 지우지 않고 옆으로 옮겨 둔 뒤, 가장 최근 백업을 `state\planner.db`로 복사합니다. 파일 이름의 날짜는 `state\backups\`에서 가장 최근 것으로 바꿉니다. 옛 DB의 WAL 파일이 남아 있으면 지웁니다. 다시 시작해도 같은 알림이 오면 하루 앞 백업으로 다시 해 봅니다.
   ```powershell
   Move-Item state\planner.db state\planner.db.broken -Force
   Remove-Item state\planner.db-wal, state\planner.db-shm -ErrorAction SilentlyContinue
   Copy-Item state\backups\planner-2026-10-23.db state\planner.db
   ```
3. 알림 표식을 지웁니다. 다음에 또 문제가 생기면 다시 알리게 됩니다.
   ```powershell
   Remove-Item state\integrity_notice_sent -ErrorAction SilentlyContinue
   ```
4. 다시 시작합니다.
   ```powershell
   Enable-ScheduledTask -TaskName my-planner
   Start-ScheduledTask -TaskName my-planner
   ```

백업 날짜 뒤에 나눈 대화는 `data\transcripts\`에 남아 있지만, 그 사이에 바뀐 할 일과 컨디션은 백업 시점으로 돌아갑니다.

## 알아 둘 점

- **텔레그램은 받아 가지 않은 메시지를 24시간까지만 보관합니다.** PC가 24시간 넘게 꺼져 있었다면 그동안 보낸 메시지는 사라질 수 있습니다.
- 사진, 스티커, 음성 같은 글이 아닌 메시지에는 "지금은 글로만 이야기할 수 있어요."라고 답합니다. 수정한 메시지는 다시 읽지 않습니다.
- 받은 메시지는 답하기 전에 DB에 먼저 저장합니다. 답하는 도중 PC가 꺼지거나 로그오프해도 다음에 켜질 때 그 메시지에 답합니다(할 일 변경은 두 번 되지 않습니다). 드물게 같은 답이 두 번 올 수 있고, 메시지를 받은 직후 몇 밀리초 안에 꺼지면 그 메시지는 사라질 수 있습니다.
- 노트북이 잠든 동안 보낸 답도 보낸 시각으로 판단해, 그 시각에 답하던 회차 대화로 이어집니다.
- Claude 사용 한도에 닿거나 로그인이 풀리면 메시지마다 그 안내로 답합니다. 비서가 먼저 보내는 안내는 하루(사용 한도는 한도 구간)에 한 번입니다. 명령은 계속 쓸 수 있습니다.

## 개발

```powershell
.venv\Scripts\python.exe -m pip install -e ".[dev]"
.venv\Scripts\python.exe -m pytest -q
```

테스트는 텔레그램이나 Claude에 실제로 연결하지 않습니다. Windows 전용 테스트는 다른 OS에서 건너뜁니다.
