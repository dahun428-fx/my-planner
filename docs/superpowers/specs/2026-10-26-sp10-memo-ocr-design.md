# SP10 메모 사진 글자 읽기(OCR) · 부가 서비스 구조 상세 설계 (추가 기능)

- 상태: 초안 v1.1 (리서치와 계획만. Dahun 결정 전, 15장의 질문 5개는 비서의 추천으로 채워 두었다)
- 작성일: 2026-10-26
- 상위 문서: [마스터 설계](2026-10-23-my-planner-master-design.md), [SP3-4 스펙](2026-10-24-sp3-4-life-curve-dashboard-design.md) (BE HTTP API 계약의 정본), [SP5 운영 앱](2026-10-24-sp5-ops-app-design.md), [SP6 자동 복구](2026-10-24-sp6-auto-recovery-design.md), [배포 흐름](2026-10-24-release-flow-design.md), [SP9 메모](2026-10-25-sp9-app-tabs-memo-schedule-design.md) 6장·9.4
- 근거 자료: 노트북의 `E:\ocr-local-benchmark` (2026-09-30~10-03 실측. 저장소 밖, 3장에 요약)
- 용어: [`GLOSSARY.md`](../../../GLOSSARY.md) (이번에 "부가 서비스", "사진 글자 읽기" 추가), 결정 기록: [ADR 0016](../../adr/0016-add-on-services-run-beside-be.md) 추가(제안)
- 범위: (1) 메모 쓰기 화면에서 사진의 글자를 읽어 본문에 넣는 기능, (2) 이런 추가 기능을 BE와 따로 만들고 따로 배포하는 **부가 서비스** 구조. 사진 글자 읽기가 첫 부가 서비스다. BE(`src/my_planner`) 코드는 바꾸지 않는다.

## 1. 목표와 완료 조건

Dahun은 책 한 쪽, 화이트보드, 안내문, 화면 캡처를 찍어 메모로 남기고 싶다. 메모 쓰기 화면에서 사진을 고르면 몇 초 뒤 읽은 글자가 커서 자리에 들어가고, Dahun이 고친 뒤 평소처럼 저장한다. 사진은 노트북 밖으로 나가지 않고 어디에도 남지 않는다.

**완료 조건 (수용 기준)**

1. 메모 쓰기 화면 도구 줄의 "사진" 버튼을 누르면 아이폰의 사진 찍기/보관함 고르기가 뜬다. 인쇄된 책 한 쪽 사진을 고르면 "사진에서 글자를 읽고 있어요…"가 보이고, 끝나면 읽은 글이 커서 자리에 들어가며 "글자를 넣었어요. 틀린 곳은 고쳐 주세요."가 4초 보인다.
2. 저장한 메모는 SP9 메모와 똑같다(`origin = 'user'`, 첨부 없음). 메모 표·API·두뇌 도구는 바뀌지 않는다.
3. 사진 파일은 노트북 디스크에 쓰이지 않는다(서비스의 임시 폴더와 로그에 없다, 테스트로 확인). 읽은 글자는 앱이 본문에 넣은 뒤 보내는 `DELETE`를 받거나 10분이 지나면 서비스 메모리에서 지운다.
4. 사진 글자 읽기 서비스를 끄면 버튼을 눌렀을 때 "사진 글자 읽기에 닿지 않아요. 노트북이 켜져 있는지 확인해 주세요."가 보이고, 메모 쓰기와 앱의 다른 화면, BE `/health`는 그대로 정상이다.
5. 서비스는 자기 토큰(`OCR_TOKEN`)만 받는다. BE의 `API_TOKEN`으로 부르면 401이고, `OCR_TOKEN`으로 BE를 부르면 401이다.
6. `services/ocr/` 아래만 바뀐 `main` 커밋이 배포되면 서비스만 다시 뜨고 BE 프로세스는 그대로다(BE pid 그대로, medic `deploy_done` 없음).
7. BE는 서비스를 import하지 않고 서비스는 `my_planner`를 import하지 않는다(경계 테스트). 서비스는 `planner.db`를 열지 않는다.
8. 품질 목표(스파이크 S1 뒤 숫자 확정): Dahun의 실제 사진 시험 묶음에서 인쇄 글자 CER 10% 이하, 아이폰 사진 한 장(12MP) 처리 중앙값 15초 이하(노트북 CPU).
9. 12장의 자동 테스트가 모두 통과한다. 새 문구에도 금지어 검사(SP5 10장)가 돈다.

## 2. 범위

| 포함 | 제외 (언제) |
|---|---|
| 메모 쓰기 화면에서 사진 한 장 → 글자 → 본문에 넣기 | 사진을 메모에 첨부·저장 (SP9 Q6 그대로: 나중) |
| 인쇄 글자(책, 문서, 안내문, 화면 캡처, 간판) | 손글씨 품질 보장 (S1에서 재 보고 따로 정한다) |
| 한국어+영어+숫자 | 표 구조 보존, 다단 편집 (나중. 줄 순서만 맞춘다) |
| 노트북 로컬 엔진(PaddleOCR) | 클라우드 모델(Claude·GPT) 읽기 (Q5: 나중, 사진마다 Dahun이 고를 때만) |
| 부가 서비스 구조(저장소 자리, 통신, 인증, 배포, CI 규칙) | 서비스 여러 개를 위한 게이트웨이·서비스 탐색 (필요할 때) |
| 채팅에서 사진 보내기 | (나중. 같은 서비스를 앱 채팅이 부르면 된다, 14장) |
| 텔레그램 사진 | (Q14와 같이 하지 않음) |

## 3. 근거: 기존 OCR 리서치 요약

`E:\ocr-local-benchmark`의 보고서(`REPORT.md`, `PUBLIC_REPORT.md`, `research/RESEARCH_REPORT.md`, `research/CLAUDE_AGENT_SDK_OCR.md`, `research/OPUS_100_COMPARISON.md`, `research/CODEX_GPT6_REPORT.md`)에서 이 기능에 필요한 것만 옮긴다. 원 보고서의 단서(표본 크기, 장치가 다른 시간 비교)는 그대로 유효하다.

| 시험 | PaddleOCR PP-OCRv5 한국어 (CPU) | EasyOCR ko+en (GPU) | 그 밖 |
|---|---|---|---|
| 합성 문서 12장, CER | **0.00%**, 1.69초/장 | 1.45%, 0.20초/장 | Qwen2-VL-2B 84~95% (전사 대신 생성·환각) |
| 실제 공공 문서 8쪽(KDoc), 문장 67개 존재 검사 | **56/67 (83.6%)**, 31.2초/쪽 | 15/67 (22.4%), 2.3초/쪽 | GPT-6 Sol(Codex 구독) 62/67, 36초/쪽 |
| 실제 장면 크롭 10,000장(K-STR), micro CER | **25.2%**, 0.15초/장 | 45.6%, 0.035초/장 | Opus 5.5 100장: 완전 일치 67%지만 CER 198.7%(거절·긴 설명 출력 2건) |
| 개발용 100장 탐색, micro CER | 25.8% | 45.5% | PaddleOCR-VL-1.6 32.9%, GLM-OCR 46.5%, Qwen2-VL 56.6% |

여기서 정한 것:

- **엔진은 PaddleOCR PP-OCRv5 한국어(로컬)다.** 세 시험 모두에서 로컬 후보 중 가장 정확했다. EasyOCR는 빠르지만 긴 문장을 많이 놓쳐 메모 용도에 맞지 않는다. 로컬 VLM(Qwen2-VL-2B, GLM-OCR, PaddleOCR-VL)은 8GB GPU에서 느리거나 환각이 있었다.
- **클라우드 모델은 v1에 넣지 않는다.** 사진이 노트북 밖으로 나가고(마스터 P5), 크롭 시험에서 Opus는 흐린 사진에 거절 문장이나 660자 설명을 냈으며, 구독 사용량 한도가 걸린다. 문서 쪽 품질은 좋아 보이지만(GPT-6 62/67) 8쪽뿐이다. 나중에 "정밀하게 읽기"로 Dahun이 사진마다 고르는 선택지로만 검토한다(Q5).
- **비어 있는 칸: 휴대폰 사진, 손글씨, 긴 책 쪽은 재 본 적이 없다.** KDoc는 PDF를 144dpi로 그린 깨끗한 그림이고 K-STR는 간판 크롭이다. 그래서 구현 전에 Dahun의 실제 사진으로 스파이크 S1을 한다(13장).
- **속도가 문제다.** 문서 한 쪽이 CPU에서 31초 걸렸다(PP-OCRv5 mobile). 그래서 API는 작업을 받아 두고 결과를 나중에 가져가는 모양이고(6장), 사진은 앱에서 줄여 보내며(7.2), S1에서 GPU판(`paddlepaddle-gpu`, RTX 3070)과 server 모델을 함께 잰다.
- 재현에 쓴 버전: `paddleocr==3.7.0`, `paddlepaddle==3.3.1`, `numpy==1.26.4`, `opencv-python-headless==4.11.0.86`, Python 3.12.10. 모델 캐시는 `PADDLE_PDX_CACHE_HOME`으로 E: 아래에 두었다(`scripts/env.ps1`). 서비스도 같은 방식으로 캐시를 서비스 폴더 아래에 둔다.

노트북에서 지금 도는 것(2026-10-26 확인): `tailscale serve` 443의 `/`는 OpenClaw 게이트웨이(127.0.0.1:18789, node), `/api`는 BE(8787), `/ocr-report`·`/ocr-research`는 위 보고서 HTML 두 개를 보여 주는 정적 경로다. 8443의 `/`는 개발용 BE(8788)다. OCR을 처리하는 서버는 아직 없다.

## 4. 부가 서비스 구조 검토 (ADR 0016)

### 4.1 무엇이 정해져 있나

- ADR 0007: `planner.db`에 쓰는 프로세스는 BE 하나다. 쓰기는 디스패처의 두 갈래뿐이다.
- ADR 0008·0009: 앱과 대시보드는 Vercel의 정적 페이지이고, 브라우저가 tailnet 안의 BE를 직접 부른다. Vercel에는 서버 코드가 없다.
- ADR 0010·0012: medic이 CI를 통과한 `main`(운영)과 `develop`(개발용) 커밋을 노트북에 배포하고 되돌린다. 배포는 `src/`, `requirements.lock`, `pyproject.toml`, `config.toml`, `scripts/`가 바뀌었을 때만 BE를 다시 띄운다(`RESTART_PATHS`).
- 마스터 P5: 원본 데이터는 노트북에만.
- 선례: `POST /api/v1/body`(SP8 7.2)는 경로마다 다른 토큰(`BODY_TOKEN`)을 쓴다.

### 4.2 저장소 자리

| 안 | 내용 | 장점 | 단점 |
|---|---|---|---|
| A. 서비스마다 새 저장소 | `dahun428-fx/my-planner-ocr` | 기록·권한·배포가 완전히 따로 | CI, 자동 복구(repair/watch/signal), medic 배포, 리뷰 에이전트, 문서, develop→main 승격을 저장소마다 다시 만든다. 앱 화면은 어차피 이 저장소에 있어서 기능 하나가 PR 두 개로 나뉜다 |
| **B. 같은 저장소의 `services/<이름>/` (추천)** | 자기 `pyproject.toml`·잠금 파일·가상환경·테스트·설정·실행 작업을 가진 독립 프로젝트 | 기능 하나가 PR 하나. CI·리뷰·문서·승격 흐름을 그대로 쓴다. 경로 필터로 CI와 배포를 서비스마다 따로 한다 | 저장소가 커진다. 경계(서로 import 안 함)를 테스트로 지켜야 한다 |
| C. BE 안의 모듈 | `src/my_planner/ocr/` | 가장 간단 | 마이크로서비스가 아니다. Paddle 의존성(수백 MB, numpy 고정)이 BE 잠금 파일에 들어가고, 무거운 CPU 작업과 네이티브 충돌이 비서 이벤트 루프와 같은 프로세스에 있다. OCR만 바꿔도 BE가 다시 뜬다 |

추천은 **B**다. "개별 프로젝트, 개별 배포"는 서비스마다 자기 의존성·프로세스·버전·배포·되돌림을 갖는 것으로 지키고, 저장소는 나누지 않는다. 나중에 서비스가 다른 기계로 가거나 다른 사람이 쓰게 되면 `git subtree split`으로 그 폴더만 떼어 낸다. 서비스 쪽 계약(6장)이 HTTP뿐이라 뗄 때 바뀌는 것이 없다.

### 4.3 서로 어떻게 말하나

| 안 | 흐름 | 판단 |
|---|---|---|
| **1. 앱이 서비스를 바로 부른다 (추천)** | 앱 → `https://<노트북>.ts.net/svc/ocr/v1/…` → 서비스. 글자를 받은 앱이 Dahun 확인 뒤 기존 `POST /api/v1/actions` `create_memo`/`update_memo`로 BE에 저장 | BE 코드 변경 0. 단일 작성자 그대로. BE가 큰 사진을 받지 않는다(지금 본문 상한 64KB) |
| 2. BE가 관문이 되어 넘긴다 | 앱 → BE `/api/v1/ocr` → 서비스 | 토큰 하나로 끝나지만 BE를 바꿔야 하고, 사진이 BE를 지나며, 서비스 배포가 BE 계약에 묶인다 |
| 3. 두뇌 도구가 서비스를 부른다 | 채팅 → 두뇌 → 도구 → 서비스 | 채팅에서 사진을 보내는 나중 기능에 맞다. v1 범위 밖(14장) |

서비스가 비서 데이터를 바꿔야 하는 날이 오면, 서비스는 DB 파일이 아니라 BE에 새로 만든 **경로 전용 토큰** 엔드포인트(`/body`와 같은 방식)를 부른다. 그것은 그때의 BE 스펙에서 정한다.

### 4.4 인증

| 안 | 판단 |
|---|---|
| **a. 서비스마다 자기 토큰 (추천)** | `OCR_TOKEN`(43자 이상)을 서비스의 `.env`에만 둔다. 서비스는 `API_TOKEN`을 모른다: 서비스가 뚫려도 할 일·메모를 바꿀 수 없다. 앱 설정에서 기기마다 한 번 넣는다(7.4). `/body`의 `BODY_TOKEN`과 같은 생각 |
| b. `API_TOKEN`을 그대로 받는다 | 넣을 칸이 하나 줄지만 서비스가 전체 쓰기 열쇠를 갖는다 |
| c. 서비스가 받은 토큰을 BE에 물어본다 | 서비스가 토큰을 저장하지 않지만 BE가 꺼지면 서비스도 못 쓰고, 묻는 데 쓸 BE 경로가 필요하다 |

### 4.5 노출과 배포

- 서비스는 `127.0.0.1:<포트>`에서만 듣는다. tailnet에는 `tailscale serve`로 **`/svc/<이름>`** 아래에 연다(Funnel 없음). 운영은 443, 개발용은 8443. 앞으로의 서비스도 `/svc/` 아래에 모은다.
- 서비스마다 작업 스케줄러 작업 `my-planner-<이름>`(개발용 `my-planner-<이름>-dev`), 단일 실행 잠금, 공개 `GET /svc/<이름>/health`.
- **서비스는 자기 git worktree에서 돈다**, 분리된 HEAD로 커밋 하나에 고정. BE 체크아웃을 같이 쓰지 않으므로, BE를 배포·되돌려도 서비스 코드는 그대로고 서비스를 배포·되돌려도 BE 코드는 그대로다.

  | | 운영 | 개발용 |
  |---|---|---|
  | worktree (어느 저장소의) | `E:\my-planner-services\<이름>` (`E:\my-planner`의 worktree) | `E:\my-planner-services\<이름>-dev` (`E:\my-planner-dev`의 worktree) |
  | 실행 상태(로그, 잠금, `deploy.json`) | `E:\my-planner\state\<이름>\` | `E:\my-planner-dev\state\<이름>\` |
  | 서비스 `.env`, `.venv`, `cache\` | worktree 안 `services\<이름>\` | 같음 |
  | `deploy.ps1`을 실행하는 사본 | `E:\my-planner\services\<이름>\scripts\deploy.ps1` | `E:\my-planner-dev\services\<이름>\scripts\deploy.ps1` |

  `deploy.ps1`은 worktree 안의 자기 사본이 아니라 BE 체크아웃의 사본으로 돈다. 그래서 되돌릴 때도 같은 스크립트 판이 끝까지 돈다.
- 배포 스크립트 `deploy.ps1 -Name <이름> -Sha <커밋>`: worktree를 그 커밋으로 옮기고, 잠금 파일이 바뀌었으면 설치하고, 작업을 다시 띄우고, 2분 안에 health가 `ok`가 아니면 앞 커밋으로 되돌린다. 서비스는 DB가 없으므로 되돌림은 코드와 가상환경뿐이다: 잠금 파일이 달랐으면 앞 커밋의 잠금 파일로 다시 설치한다.
- medic은 나중 티켓(계획 OCR-09)에서 `services/<이름>/`가 바뀐 CI 통과 커밋에 이 스크립트를 부른다. 그 전에는 Dahun이나 스레드가 손으로 부른다.
- **CI는 서비스마다 따로 된 워크플로**(`ci-ocr.yml`, 이름 `ci-ocr`, `on.push.paths`/`on.pull_request.paths: services/ocr/**`)다. 기존 `ci.yml`(이름 `ci`)에는 작업을 더하지 않는다. medic은 커밋의 `ci` 실행 결론만 보고 BE를 배포하므로(`my_planner_medic/github.py` `ci_conclusion`), 서비스 테스트가 실패해도 BE 배포·자동 수리가 막히지 않고, 서비스를 건드리지 않은 커밋에 서비스 CI가 없어도 문제없다. 서비스 배포(OCR-09)는 `ci-ocr` 결론을 본다. 승격 검사(`staging/be`)는 v1에서 바꾸지 않는다.

## 5. 사진 글자 읽기 서비스 (`services/ocr`)

### 5.1 폴더

```
services/ocr/
  pyproject.toml          # 이름 my-planner-ocr, 패키지 my_planner_ocr, Python 3.12
  requirements.lock       # 정확한 버전(3장)
  config.toml             # 포트, 상한, 엔진 설정. 개인값 없음
  .env.example            # OCR_TOKEN=
  README.md               # 설치, 실행, 등록, 배포, 지우기
  src/my_planner_ocr/
    __main__.py           # python -m my_planner_ocr [serve|gen-token]
    config.py  server.py  auth.py  cors.py  jobs.py  engine.py  layout.py  imaging.py  logs.py
  requirements-ci.txt     # CI용(Paddle 없음): aiohttp, Pillow, pytest, ruff
  scripts/register_task.ps1  check_task.ps1  deploy.ps1  task_my-planner-ocr.xml.tmpl
  tests/
```

Git에 넣지 않는 것: `services/ocr/.venv/`, `services/ocr/.env`, `services/ocr/config.local.toml`, `state/ocr/`는 루트 `.gitignore`의 기존 줄(`.venv/`, `.env`, `config.local.toml`, `state/`)이 이미 막는다. 새로 더하는 줄은 `services/ocr/cache/`(모델·Paddle 캐시) 하나다.

### 5.2 설정 (`services/ocr/config.toml`)

```toml
[server]
host = "127.0.0.1"
port = 8790                 # 개발용은 config.local.toml에서 8791
path_prefix = "/svc/ocr"
cors_origins = ["https://my-planner-beige-eight.vercel.app"]   # 운영 앱만. 정확한 문자열, 와일드카드 없음

[limits]
max_image_mb = 8            # 8 MiB = 8 × 1024 × 1024 바이트. aiohttp client_max_size는 이 값 + 64KiB
max_waiting = 3             # 기다리는 작업 상한. 넘으면 429
job_timeout_s = 120
result_ttl_min = 10

[engine]
name = "paddleocr"
lang = "korean"
device = "cpu"              # S1 뒤 "gpu:0"일 수 있다
cpu_threads = 4             # 비서·OpenClaw가 굶지 않게
max_side_px = 2048          # 서비스가 한 번 더 줄이는 긴 변
low_score = 0.6             # 이보다 낮은 줄을 "흐릿한 줄"로 센다
idle_unload_min = 15        # 이만큼 쉬면 모델을 내려 메모리를 돌려준다
```

개발용 서비스는 `E:\my-planner-dev`의 worktree에서 `services/ocr/config.local.toml`로 `port = 8791`, `cors_origins = 스테이징 앱 별칭 두 개`(배포 흐름 스펙의 CORS 행과 같은 값)를 덮어쓴다.

### 5.3 처리 흐름

**엔진 검사(시작할 때).** `import paddleocr`가 되고 설정한 모델 파일이 캐시에 있는지 본다. 검사 실패, 또는 마지막 불러오기 실패가 있으면 엔진은 "쓸 수 없음"이다: `health`는 `ok: false`, `POST`는 503. 그래서 설치가 깨진 배포는 `deploy.ps1`의 health 확인에서 걸린다. 모델 파일이 없으면 시작 때 한 번 받는다(S5에서 시간을 잰다).

아래 1번은 요청 처리기에서, 2번부터는 일꾼에서 한다.

1. `POST`로 받은 바이트를 메모리에서만 연다(Pillow). JPEG·PNG·WebP만, 그 밖은 415. EXIF 방향대로 돌리고 RGB로 바꾼 뒤 긴 변을 `max_side_px`로 줄인다. 파일로 쓰지 않는다.
2. 작업 큐는 하나, 일꾼도 하나다(동시에 한 장). 엔진은 첫 작업 때 메모리에 올리고 `idle_unload_min` 동안 쉬면 내린다.
3. 엔진 호출은 별도 스레드에서 한다. `job_timeout_s`가 지나면 그 작업을 `failed/timeout`으로 알리지만, 파이썬 스레드는 멈출 수 없으므로 **일꾼은 그 호출이 실제로 끝날 때까지 다음 작업을 시작하지 않는다**(동시에 한 장, 메모리 상한 유지). 그동안 `health`는 그대로 `ok`이고 기다리는 작업의 `ahead`가 줄지 않는다.
4. 엔진이 낸 줄(글자, 점수, 상자)을 `layout.py`가 묶는다. 두 상자의 세로 겹침 ÷ 둘 중 작은 상자 높이 ≥ 0.5이면 같은 줄이다. 같은 줄은 왼쪽부터 공백 하나로 잇고, 묶은 줄의 점수는 들어간 상자 점수의 최솟값이다. 줄은 위(세로 중심)에서 아래로. 줄 사이 간격(아래 줄 위끝 − 위 줄 아래끝)이 줄 높이 중앙값의 1.5배를 넘으면 빈 줄을 하나 넣는다. 응답의 `lines`는 **묶은 줄**이고, `low`는 묶은 줄 중 점수가 `low_score` 미만인 수다. 예: 상자 A(y 10~30, 0.95), B(y 14~32, 0.55), C(y 80~100, 0.9), 줄 높이 중앙값 20 → `lines` = [A B (0.55), C (0.9)], A·B와 C 사이 간격 48 > 30이라 빈 줄 하나, `low` = 1.
5. 결과는 메모리에 `result_ttl_min` 동안 둔다. `GET`은 결과를 지우지 않는다(앱이 응답을 잃어도 다시 물을 수 있게). 앱은 글을 넣은 뒤 `DELETE`를 보내고, 그때 지운다.
6. `pythonw`로 돌면 `sys.stdout`이 없다. 시작할 때 stdout·stderr를 `state/ocr/logs/stdio.log`로 돌린다(모델 내려받기 진행 표시가 프로세스를 죽이지 않게). 이 파일도 5.4 규칙을 따르도록 Paddle 로그 수준을 경고 이상으로 둔다.

### 5.4 로그

`state/ocr/logs/ocr.jsonl`에 `job_done {ms, w, h, lines, low}`, `job_failed {code}`, `auth_failed`, `engine_loaded {ms}`, `engine_unloaded`만 남긴다. 읽은 글자, 사진, 토큰, 요청 본문은 남기지 않는다.

## 6. HTTP 계약 (`/svc/ocr`)

모든 경로는 `path_prefix` 아래다. `health`만 토큰이 없고, 나머지는 `Authorization: Bearer <OCR_TOKEN>`. 실패 10회/분이면 1분 동안 429(BE `AuthLimiter`와 같은 규칙, 코드는 복사하고 import하지 않는다). CORS는 BE `api/cors.py`와 같은 규칙(정확한 출처, 사전 요청 204, 사설망 접근 헤더, 오류 응답에도 헤더).

| 경로 | 응답 |
|---|---|
| `GET /health` | `200 {"ok": true, "service": "ocr", "version": "<짧은 커밋>", "engine": "paddleocr 3.7.0 korean", "model": "loaded" \| "idle"}`. 엔진이 "쓸 수 없음"(5.3 엔진 검사)이면 `ok: false` |
| `POST /v1/jobs` | 본문은 사진 바이트 그대로(`Content-Type: image/jpeg` 등, multipart 아님). `202 {"job_id": "<32자 hex>", "state": "queued", "ahead": n}` |
| `GET /v1/jobs/{job_id}` | `200 {"job_id", "state": "queued" \| "running" \| "done" \| "failed", "ahead"?, "text"?, "lines"?: [{"text", "score"}], "low"?, "elapsed_ms"?, "error"?}`. `queued`면 `ahead`. `done`이면 `text`, `lines`(5.3 4번의 묶은 줄), `low`, `elapsed_ms`. `failed`면 `error`. 결과를 지우지 않는다 |
| `DELETE /v1/jobs/{job_id}` | `204`. 기다리는 작업이면 취소, 도는 작업이면 끝난 뒤 결과를 버림, 끝난 작업이면 결과를 지운다 |

오류 코드(`{"error": "<code>"}`): `401 unauthorized`, `404 job_not_found`(없거나 지웠거나 10분 지남), `413 image_too_large`, `415 unsupported_image`, `422 image_unreadable`, `429 busy`(기다리는 작업 `max_waiting`개) 또는 `rate_limited`, `503 engine_unavailable`. 작업 실패 `error`: `timeout`, `engine_error`, `no_text`(줄 0개).

## 7. 운영 앱

### 7.1 메모 쓰기 화면 (SP9 9.4에 더한다)

- 키보드 위 도구 줄(목록, 체크박스, 굵게, 영역, 완료)의 영역 앞에 글 버튼 "사진"을 더한다(지금 도구 줄과 같은 글 버튼, `copy.memos.toolbar.photo`). 사진 글자 읽기 키가 없는 기기(7.4)에서는 버튼이 없다. 앱이 BE 연결 끊김 상태면 버튼이 흐려지고 누르면 "닿지 않음" 문구를 보인다.
- 누르면 `<input type="file" accept="image/*">`를 연다(아이폰이 "사진 찍기 / 사진 보관함"을 띄운다). 한 장만. 읽는 동안 버튼은 흐려진다(한 번에 한 장).
- 읽는 동안 도구 줄 위에 한 줄 띠 "사진에서 글자를 읽고 있어요…"와 "취소"가 보인다(`DELETE`). 기다리는 중이면 "앞에 {n}장이 있어요"를 덧붙인다. 그동안에도 글을 쓸 수 있다.
- **넣을 자리(앵커)**: 버튼을 누를 때의 커서 위치를 앵커로 잡는다. 읽는 동안 본문이 바뀔 때마다 `shiftAnchor(prev, next, anchor)`로 옮긴다: 바뀐 구간(앞뒤 공통 부분을 뺀 가운데)이 앵커보다 완전히 앞이면 늘어나거나 줄어든 글자 수만큼 옮기고, 완전히 뒤면 그대로, 앵커를 덮으면 바뀐 구간의 새 끝으로 옮긴다. 0보다 작거나 본문 길이보다 크면 그 끝으로 자른다.
- 끝나면 `text`를 앵커에 넣는다. 앵커 바로 앞 글자가 줄바꿈이 아니면 줄바꿈 하나를, 앵커가 본문 처음이면 아무것도 붙이지 않는다. 뒤도 같다(앵커 바로 뒤가 줄바꿈이 아니고 본문 끝이 아니면 줄바꿈 하나). 넣은 뒤 `DELETE`를 보낸다. 그다음은 평소 쓰기와 같다: 입력이 멈추고 1초 뒤 저장(SP9 9.4).
- 읽는 중에 "완료"를 눌러 읽기 상태가 되면 띠는 화면 위쪽 같은 자리에 그대로 남고, 끝나면 같은 규칙으로 넣고 바로 저장한다(읽기 상태 유지).
- `low`가 1 이상이면 넣은 뒤 "흐릿한 줄 {n}개가 있어요. 확인해 주세요."를 보인다.
- 넣으면 20,000자를 넘는 경우, 넘는 부분을 넣지 않고 "메모는 20,000자까지라 뒷부분은 넣지 못했어요."를 보인다. 글자 수는 BE와 같은 코드 포인트 단위로 센다(`[...s].length`. BE는 파이썬 `len`과 SQLite `length`로 센다).
- 앱이 백그라운드로 갔다 돌아오면 같은 `job_id`로 다시 묻는다(작업 id는 화면 상태에만, 저장하지 않는다). `GET`은 결과를 지우지 않으므로 응답을 잃었어도 다시 받는다. 화면을 떠나면 `DELETE`.

### 7.2 사진 줄이기 (앱)

`createImageBitmap`(`imageOrientation: "from-image"`) → 캔버스 긴 변 2,048px(서비스 `max_side_px`와 같은 값. 서비스가 다시 줄이지 않아도 되고 올리는 양이 준다) → JPEG 품질 0.85 `Blob`. 이렇게 하면 HEIC가 JPEG가 되고 EXIF(위치 정보 포함)가 빠지며 대개 1~2MB다. 결과가 8MB를 넘으면 품질 0.7로 한 번 더 줄인다. 실패하면 "이 사진은 읽을 수 없어요."

### 7.3 부르기

- 주소는 BE 주소에서 만든다: `<beUrl>/svc/ocr/v1/...` (`beUrl`은 이미 `https://<노트북>.ts.net` 출처뿐이다). 그래서 CSP `connect-src`는 그대로다.
- 결과 묻기: 1초마다. 앱의 시간 재기는 `state`가 처음 `running`이 된 때부터이고 한도는 `job_timeout_s + 15`초(135초)다. 서비스의 `failed/timeout`이 먼저 온다. 그래도 135초가 지나면 `DELETE`하고 시간 초과 문구를 보인다. `queued`인 동안은 `ahead`가 줄어드는 한 계속 묻고, 같은 `ahead`로 135초가 지나면 같게 끝낸다.
- 새 파일 `web/app/src/api/ocr.ts`(타입은 손으로 쓴다. BE `types.gen.ts`와 섞지 않는다). **BE용 `apiFetch`와 `reportResult`를 쓰지 않는 자체 `fetch`**다: `apiFetch`는 `Authorization`에 BE 키(`mp.token`)를 붙이고 `reportResult`는 실패를 BE 연결 상태로 바꾸기 때문이다. 서비스에는 `mp.ocrToken`만 보내고, 서비스 실패는 앱의 BE 연결 상태(끊김 띠)를 바꾸지 않는다.

### 7.4 설정 (더보기 → 설정)

- "사진 글자 읽기" 묶음: 키 입력칸(BE 키와 같은 모양), 저장하면 `GET /svc/ocr/health`와 토큰 확인용 `GET /svc/ocr/v1/jobs/` + 32자 `0`(401이면 키 틀림, 404면 맞음)으로 상태 한 줄을 보인다. "키 지우기"로 지운다(SP5 "이 기기 연결 해제"와 헷갈리지 않게 다른 말).
- 키는 `localStorage`의 `mp.ocrToken`. "이 기기 연결 해제"(SP5)는 이미 `mp.*`를 모두 지우므로(`lib/snapshot.ts`) 따로 지우는 코드는 없다. 시험으로 확인만 한다.

## 8. 문구 (새 고정 문구)

| 자리 | 문구 |
|---|---|
| 버튼 | 사진 |
| 읽는 중 | 사진에서 글자를 읽고 있어요… · 앞에 {n}장이 있어요 · 취소 |
| 끝 | 글자를 넣었어요. 틀린 곳은 고쳐 주세요. |
| 흐릿함 | 흐릿한 줄 {n}개가 있어요. 확인해 주세요. |
| 글자 없음 | 사진에서 글자를 찾지 못했어요. |
| 닿지 않음 | 사진 글자 읽기에 닿지 않아요. 노트북이 켜져 있는지 확인해 주세요. |
| 바쁨 | 지금 다른 사진을 읽고 있어요. 잠시 뒤에 다시 해 주세요. |
| 너무 큼·못 읽음 | 사진이 너무 커요. · 이 사진은 읽을 수 없어요. |
| 시간 초과 | 시간이 너무 걸려 멈췄어요. 사진을 줄이거나 나눠 찍어 주세요. |
| 길이 상한 | 메모는 20,000자까지라 뒷부분은 넣지 못했어요. |
| 설정 | 사진 글자 읽기 · 키 · 연결됐어요 · 키가 맞지 않아요. · 키 지우기 |
| 키 틀림(쓰기 화면) | 사진 글자 읽기 키가 맞지 않아요. 설정에서 다시 넣어 주세요. |

**응답 → 문구**

| 서비스 응답 | 문구 |
|---|---|
| `fetch` 실패(네트워크), `503 engine_unavailable`, `404 job_not_found`(묻는 중) | 닿지 않음 |
| `401 unauthorized` | 키 틀림(쓰기 화면) |
| `429 busy`, `429 rate_limited` | 바쁨 |
| `413 image_too_large` | 사진이 너무 커요. |
| `415 unsupported_image`, `422 image_unreadable`, 앱 줄이기 실패 | 이 사진은 읽을 수 없어요. |
| `failed/no_text` | 글자 없음 |
| `failed/timeout`, 앱 135초 한도 | 시간 초과 |
| `failed/engine_error` | 닿지 않음 |

## 9. BE와 다른 문서에 미치는 것

- BE 코드, 마이그레이션, API 계약(`/api/v1`), 두뇌 도구: **바뀌지 않는다.**
- `config.toml`의 BE `cors_origins`: 바뀌지 않는다(서비스는 자기 설정을 쓴다).
- 루트 `.gitignore`: `services/ocr/cache/` 한 줄.
- `ci.yml`: 바뀌지 않는다. 새 워크플로 `ci-ocr.yml`(4.5).
- 마스터 설계의 저장소 구조: ADR 0016을 받아들이면 `services/`를 더한다.
- `tailscale serve`: 443 `/svc/ocr` → `http://127.0.0.1:8790/svc/ocr`, 8443 `/svc/ocr` → `http://127.0.0.1:8791/svc/ocr`. 노트북 네트워크 설정이라 Dahun 확인 뒤 한다.
- SP9 스펙 2장 "사진·파일 첨부 (Q6: 나중)"은 그대로다. 사진은 글자를 뽑는 데만 쓰고 남기지 않는다.

## 10. 보안과 개인정보

- 사진과 글자는 노트북 밖으로 나가지 않는다(Vercel은 HTML·JS만, 앱 → tailnet → 노트북). 클라우드 모델 호출 없음.
- 서비스는 사진을 디스크에 쓰지 않는다. Paddle이 내부 임시 파일을 쓰는지는 S1에서 `TEMP`를 서비스 전용 폴더로 두고 처리 전후 비교로 확인한다. 쓰면 작업 끝에 그 폴더를 비운다.
- 서비스는 `API_TOKEN`, `planner.db`, BE `.env`를 읽지 않는다. 서비스 프로세스가 열 수 있는 경로를 테스트로 막을 수는 없으므로, 설정 로더가 서비스 폴더의 `.env`만 읽는 것을 테스트한다.
- 앱이 보내기 전에 EXIF를 지운다(7.2).

## 11. 실패와 장애

| 상황 | 결과 |
|---|---|
| 서비스 프로세스 없음 | 앱: "닿지 않음" 문구. 5분 안에 작업 스케줄러 워치독이 다시 띄운다 |
| 엔진 불러오기 실패(설치 깨짐) | `health ok: false`, `POST` 503. 앱: "닿지 않음" |
| 노트북 메모리 부족 | 엔진 오류 → `failed/engine_error`. 쉬면 모델을 내린다(5.2) |
| 처리 중 서비스 재시작 | 작업이 사라져 `GET`이 404 → 앱: "닿지 않음"과 같은 문구 |
| 배포 뒤 health 실패 | `deploy.ps1`이 앞 커밋으로 되돌린다 |

v1에서 medic은 서비스 로그를 보지 않는다. 서비스 장애는 앱 문구로만 드러난다(OCR-09에서 medic 감시를 더한다).

## 12. 테스트

서비스(`services/ocr/tests`, `pytest`, 엔진은 가짜로 바꿔 끼운다):

- `test_auth.py`: `OCR_TOKEN` 맞음/틀림/없음, `OCR_TOKEN`이 아닌 43자 토큰 401, 10회 실패 뒤 429, 상수 시간 비교.
- `test_server.py`: 8 MiB 사진은 처리기까지 오고(aiohttp가 먼저 413을 내지 않음) 8 MiB + 1바이트는 413 `image_too_large`, 엔진 "쓸 수 없음"이면 health `ok: false`와 POST 503.
- `test_cors.py`: 허용 출처 사전 요청 204와 헤더, 사설망 헤더, 허용 밖 출처는 헤더 없음, 401 응답에도 헤더.
- `test_jobs.py`: 202→running→done, `GET`을 두 번 해도 같은 결과, `DELETE` 뒤 404, 10분 TTL, `max_waiting` 넘으면 429, 취소, 시간 초과 뒤 그 호출이 끝나기 전에는 다음 작업이 시작되지 않음, 동시에 한 장.
- `test_imaging.py`: EXIF 방향 6을 돌림, 긴 변 줄이기, 8MB 초과 413, GIF 415, 깨진 JPEG 422, **임시 폴더에 파일이 생기지 않음**.
- `test_layout.py`: 5.3 4번의 예시(A·B·C) 그대로, 겹침 0.49는 다른 줄, 줄 순서, 빈 결과 → `no_text`.
- `test_logs.py`: 로그에 글자·토큰·사진 바이트가 없음.
- `test_boundary.py`: `services/ocr/src`에 `my_planner`(`my_planner_ocr` 제외) import 없음, 루트 `src/`에 `my_planner_ocr` import 없음, `services/ocr/src`에 `planner.db`, `DB_PATH`, `API_TOKEN` 문자열 없음, 설정 로더가 서비스 폴더 밖 `.env`를 읽지 않음.
- `test_engine_real.py`(표시 `engine`, CI에서 건너뜀): 합성 한국어 그림 한 장(리서치 `make_data.py` 방식)을 실제 Paddle로 읽어 CER 5% 이하.

앱(Vitest, Playwright):

- 사진 버튼은 키가 있을 때만 보임, `shiftAnchor`(앞에서 늘림·줄임, 뒤에서 바꿈, 앵커 덮음), 앞뒤 줄바꿈 규칙(본문 처음·끝 포함), 넣은 뒤 `DELETE` 한 번, 응답을 잃고 다시 물어도 넣기 한 번, 읽기 상태에서 끝나면 넣고 저장, 20,000자(코드 포인트) 자르기, 8장 "응답 → 문구" 표의 모든 행(`fetch` 실패 포함), 서비스 실패가 BE 연결 상태를 바꾸지 않음, `/svc/ocr` 요청 헤더에 `mp.token` 값이 없음, "이 기기 연결 해제" 뒤 `mp.ocrToken` 없음, 새 문구 금지어 검사, `check:csp` 통과.

노트북(손으로, 계획의 OCR-08): 수용 기준 1, 4~8을 실제 아이폰과 노트북에서 확인한다.

## 13. 스파이크 (구현 전)

- **S1 실제 사진 품질과 속도.** Dahun이 찍은 사진 20장(책 쪽 5, 문서·안내문 5, 화면 캡처 4, 간판·포장 3, 손글씨 3). 사진과 손으로 쓴 정답은 `E:\ocr-local-benchmark\data\memo_s1\`에만 둔다(저장소 밖). 세 설정을 잰다: PP-OCRv5 mobile CPU, PP-OCRv5 server CPU, GPU판. 지표는 기존 `research_metrics.py`의 CER와 장당 시간. 이것으로 1장 기준 8번 숫자, `device`, 모델, `max_side_px`를 정한다. 손글씨 CER가 30%를 넘으면 손글씨는 "되지 않을 수 있음"으로 앱 문구에 적는다.
- **S2 `tailscale serve` 경로.** 443에 `/svc/ocr`를 더해도 `/`(OpenClaw), `/api`, `/ocr-report`, `/ocr-research`가 그대로인지, 접두사가 그대로 넘어가는지, 8MB 본문과 120초 연결이 통과하는지.
- **S3 아이폰 PWA 사진 고르기.** 홈 화면 앱에서 `accept="image/*"`가 카메라/보관함을 띄우는지, HEIC가 `createImageBitmap`으로 열리는지, 12MP 캔버스 줄이기가 메모리 오류 없이 되는지, 백그라운드 뒤 이어 묻기.
- **S4 메모리.** BE + OpenClaw + 서비스(모델 올림)가 함께 있을 때 노트북 메모리(16GB)와 `idle_unload_min` 뒤 돌려받는 양.
- **S5 설치.** 서비스 `.venv`에 3장의 잠금 버전이 Python 3.12에서 깔리고, 캐시·임시 파일이 모두 E:에 남는지(리서치 때 C:로 샌 이력이 있다).

## 14. 나중에 (이 스펙 밖)

- 채팅에 사진 보내기: 앱 채팅이 같은 서비스로 글자를 뽑아 메시지 본문에 붙인다. 두뇌는 사진을 보지 않는다.
- 정밀하게 읽기(Q5): Dahun이 사진마다 고르면 BE 두뇌(구독)가 사진을 읽는다. 리서치의 거절·긴 설명 출력을 막는 프로토콜을 개발용 묶음에서 먼저 재야 한다.
- 메모에 사진 첨부(SP9 Q6).
- medic의 서비스 감시와 자동 배포(OCR-09), 승격 검사에 `staging/ocr`.

## 15. 미결 사항 (Dahun 확인)

| # | 질문 | 비서 추천 |
|---|---|---|
| Q1 | 부가 서비스를 어디에 두나 | 같은 저장소의 `services/<이름>/` + 서비스마다 자기 worktree에서 실행(4.2, 4.5). 따로 떼야 할 때 `subtree split` |
| Q2 | 주로 무엇을 찍나 | 인쇄 글자(책·문서·화면·간판) 우선. 손글씨는 S1 결과를 보고 정한다 |
| Q3 | 서비스 키 | 서비스마다 따로(`OCR_TOKEN`), 앱 설정에 기기마다 한 번 넣는다(4.4 a) |
| Q4 | 사진을 남기나 | 남기지 않는다. 글자만 메모에 들어간다(SP9 Q6 그대로) |
| Q5 | 클라우드 모델로 읽기 | v1은 하지 않는다. 나중에 사진마다 고르는 "정밀하게 읽기"로만 검토 |

## 변경 기록

- v1.1 (2026-10-26): 문서 리뷰 반영. CI를 `ci-ocr.yml`로 분리(BE 배포가 막히지 않게), `GET`은 결과를 지우지 않고 앱이 넣은 뒤 `DELETE`, 앱은 BE `apiFetch`를 쓰지 않는 자체 fetch, 시간 초과 뒤 일꾼 대기, 시작 때 엔진 검사, 개발용 CORS, 응답→문구 표, 넣을 자리 규칙, 되돌림 때 재설치, 경로 표, 본문 크기, pythonw 출력, 줄 묶기 수치.
- v1 (2026-10-26): 첫 초안. `E:\ocr-local-benchmark` 리서치 요약, 부가 서비스 구조 검토, 서비스·앱 설계, 스파이크 다섯.
