# my-planner

Dahun 한 사람을 위한 텔레그램 AI 비서입니다. 텔레그램 개인 채팅으로 말을 걸면 비서(Claude)가 답합니다. 할 일 정리, 아침 브리핑, 저녁 체크인은 다음 단계에서 붙습니다.

- 용어: [`GLOSSARY.md`](GLOSSARY.md)
- 설계: [`docs/superpowers/specs/`](docs/superpowers/specs/), 결정 기록: [`docs/adr/`](docs/adr/)

## 준비물

- Windows 11 노트북, Python 3.12 (Microsoft Store판으로 확인했습니다)
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

## 데이터는 어디에 남나요

| 위치 | 내용 |
|---|---|
| `state\planner.db` | 원본 데이터(SQLite) |
| `data\transcripts\YYYY\MM\YYYY-MM-DD.md` | 원문 기록. 하루 경계는 04:00이라 새벽 0시~3시 59분의 대화는 전날 파일에 들어갑니다 |
| `state\logs\my-planner.jsonl` | 시스템 로그. 메시지 본문은 남기지 않습니다. 하루 단위로 회전하고 30일 치를 보관합니다 |
| `state\backups\planner-YYYY-MM-DD.db` | DB 백업. 매일 처음 도는 tick에 하나 만들고 최근 14개를 남깁니다 |
| `%USERPROFILE%\.claude\projects\` | Claude Agent SDK가 따로 남기는 **세션 기록 사본**입니다. 원본은 `data\transcripts\`이고, 이 사본에는 가리기 전 내용이 없도록 두뇌에는 가린 글만 넘깁니다. 지우고 싶으면 이 폴더의 my-planner 관련 하위 폴더를 지우면 됩니다 |

- 주민등록번호, 계좌번호로 보이는 숫자, "비밀번호/비번/password/PIN" 뒤의 값은 원문 기록과 두뇌에 넘기기 전에 `[가림]`으로 바뀝니다. 그래도 민감한 정보는 보내지 않는 편이 안전합니다.
- `data\`, `state\`, `.env`는 Git에 들어가지 않습니다. 백업은 로컬·외장 디스크에만 합니다.

## 백업에서 복구하기

DB가 손상되면 비서는 텔레그램으로 "데이터베이스에 문제가 있어요."라고 한 번 알리고, 답하지 않은 채 기다립니다(안전 모드). 자동으로 복구하지 않습니다. PowerShell에서 저장소 폴더(`E:\my-planner`)로 가서 아래 순서로 복구합니다.

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
- 지금은 메시지마다 새 대화로 답합니다. 대화 이어가기와 할 일 도구는 다음 단계에서 붙습니다.

## 개발

```powershell
.venv\Scripts\python.exe -m pip install -e ".[dev]"
.venv\Scripts\python.exe -m pytest -q
```

테스트는 텔레그램이나 Claude에 실제로 연결하지 않습니다. Windows 전용 테스트는 다른 OS에서 건너뜁니다.
