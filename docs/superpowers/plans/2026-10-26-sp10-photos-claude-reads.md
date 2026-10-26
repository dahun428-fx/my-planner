# SP10 사진 남기기 · Claude가 읽고 기록 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan ticket-by-ticket. Steps use checkbox (`- [ ]`) syntax for tracking. 티켓 하나를 끝낼 때마다 `.claude/agents/code-reviewer.md`로 리뷰하고, 지적을 반영한 뒤 다음 티켓으로 간다.

**Goal:** 운영 앱의 메모 쓰기 화면과 채팅에서 사진을 올리면, BE가 사진 파일을 노트북에 남기고 두뇌(구독 Claude)가 읽어 메모로 기록한다.

**Architecture:**
- 새 표 셋(`020_photos.sql`: `photos`, `memo_photos`, `message_photos`), 파일은 `data/photos/`(`store/photos.py`). 쓰기는 즉시 갈래의 새 내부 동작 `store_photo`와 `/actions`의 `attach_photo`·`detach_photo`.
- 사진 읽기 자리 `PhotoReader`, v1은 `ClaudePhotoReader`(도구 없는 한 번 호출, 두뇌 직렬 큐).
- 채팅: `parts`의 `data-photo` → 두뇌 SDK 스트리밍 입력의 이미지 블록. `create_memo(photo_ids?)`.
- 앱: 메모 사진 줄·보기·"사진" 버튼, 채팅 사진 버튼·대기·말풍선 사진, `blob:` 주소로 보이기.

**Tech Stack:** SP9와 같다(Python 3.12, aiohttp, SQLite, Claude Agent SDK / Next.js 15 Pages Router 정적 내보내기, AI SDK `useChat`, Vitest, Playwright). BE 새 의존성 없음(그림 처리는 앱).

**Spec:** [`docs/superpowers/specs/2026-10-26-sp10-photos-claude-reads-design.md`](../specs/2026-10-26-sp10-photos-claude-reads-design.md) (v2.5). 결정 [ADR 0017](../../adr/0017-photos-as-files-claude-reads-first.md). 상위: [SP9](../specs/2026-10-25-sp9-app-tabs-memo-schedule-design.md), [SP3-4](../specs/2026-10-24-sp3-4-life-curve-dashboard-design.md)(API 계약 정본), [SP5](../specs/2026-10-24-sp5-ops-app-design.md). 다음 단계 [SP11](../specs/2026-10-26-sp11-local-ocr-service-design.md).
- 스펙과 이 계획이 다르면 스펙이 맞다. 티켓은 스펙을 다시 쓰지 않고 절을 가리킨다.

## Global Constraints

- 스파이크 S1·S2·S4는 통과했다([결과](../../spikes/2026-10-sp10.md)). S3(아이폰)는 따로 하지 않고, PH-07 뒤 스테이징 앱에서 Dahun이 카메라 버튼을 한 번 눌러 확인한다(Dahun, 2026-10-26). (스펙 15장 Q1~Q5는 2026-10-26 확정) PH-00, PH-01, PH-02는 먼저 해도 된다(두뇌와 무관).
- (5.1) 사진 바이트를 DB에 넣지 않는다. 메모당 10장, 메시지당 4장, 하루(논리적 날짜) 올리기 100장, 사진 읽기 하루 30회, 사진 5,000,000바이트·긴 변 2,048, 작은 사진 256 KiB.
- (5.4) 사진 읽기는 실행 종류 `photo_read`, 도구 0개. 사진 속 글을 지시로 다루지 않는다.
- (5.2) 파일은 한 번 쓰고 바꾸지 않는다. 파일 지우기는 하루 한 번 작업만.
- (5.3) 다른 경로의 본문 상한 64KB는 그대로. 토큰은 헤더로만.
- (6장, 수용 기준 8) 로그·원문 기록·활동·장애 리포트에 사진 바이트, 파일 경로, 사진 읽기 결과 원문을 넣지 않는다(메모 제목 20자는 지금 규칙).
- (4.3) 두뇌는 메모를 고치거나 지우지 않는다. 사진에 대한 메모 자동 만들기는 4.3 조건에서만.
- (Q14) 텔레그램 도구 목록과 화면은 바꾸지 않는다. `create_memo`의 `photo_ids`는 앱 통로에서만 받는다.
- (8장) 새 문구는 스펙 8장 그대로, 금지어 검사에 넣는다. 새 아이콘 24px, 선 1.75, 이모지 없음.
- 마이그레이션 번호는 020이다(019는 기기 연결). 머지 전에 develop의 번호를 다시 확인한다.
- SP3-4·SP1·SP9 Global Constraints(단일 작성자, `mode=ro` 읽기, 시각 UTC 저장, 논리적 날짜 04:00)는 그대로다.
- 브랜치는 `origin/develop`에서, PR 대상은 `develop`.

## 작업 방식

- TDD와 명령은 SP9 계획 "작업 방식" 그대로. BE 끝 검증: `python -m pytest -q` → `0 failed`, `ruff check src tests` → `All checks passed!`. 앱: `cd web/app && npm run typecheck && npm run lint:copy && npm test && npm run test:tz && npm run build && npm run check:csp` → 모두 통과.
- BE 응답 모양을 바꾼 티켓은 `npm run gen:types`로 `schema.json`·`types.gen.ts`를 다시 만든다.

## Review Focus

1. **파일과 행의 순서**: 행 트랜잭션이 실패하면 파일이 없어야 하고, 파일 쓰기가 실패하면 행이 없어야 한다. → PH-01 `test_failed_insert_removes_file`, `test_failed_write_leaves_no_row`
2. **다른 경로의 본문 상한**: `client_max_size`를 키운 뒤에도 `/actions`·`/chat`의 chunked 본문이 64KB에서 413. → PH-02 `test_chunked_body_over_64k_rejected_on_actions`
3. **두뇌가 남의 사진을 붙임**: `create_memo(photo_ids)`가 다른 대화의 사진 id를 받으면 `photo_not_in_conversation`. → PH-04 `test_create_memo_rejects_photo_from_other_conversation`
4. **사진만 보낸 메시지**: `NON_TEXT_REPLY`로 가지 않고 두뇌로 가며, 원문 기록에는 `[사진 #id]`만. → PH-04 `test_photo_only_message_goes_to_brain_and_transcript_has_marker`
5. **완전 지우기 조건**: 메모에 붙은 채팅 사진은 대화를 지워도 남고, 메모가 30일 뒤 완전히 지워질 때 함께 지워진다. 아직 어디에도 붙지 않은 새 사진과 빼고 되돌리기를 기다리는 사진은 지우지 않는다. → PH-05 `test_chat_photo_on_memo_survives_conversation_delete`, `test_unlinked_new_photo_not_purged`, `test_detached_photo_kept_30_days`
6. **사진 붙은 메모의 30일 purge**: `foreign_keys=ON`에서 CASCADE로 성공해야 하루 작업이 멈추지 않는다. → PH-01 `test_purge_memo_with_photos_cascades`
7. **두뇌가 사진 id를 앎**: 입력에서 각 이미지 앞에 `[사진 #id]` 글 블록. 다시 보내기·시작 때 다시 넣기도 같은 입력. → PH-04 `test_brain_input_labels_each_image`, `test_resubmit_reloads_photos`

---

## File Structure

```
src/my_planner/
  store/migrations/020_photos.sql      # PH-01
  store/photos.py                      # PH-01: PhotoFiles (경로, 쓰기, JPEG 머리 읽기)
  store/repos/photos.py                # PH-01: Photo, PhotosRepo
  tools/actions.py                     # PH-01: store_photo, attach_photo, detach_photo
  api/photos.py                        # PH-02: POST/GET /photos, POST /photos/{id}/read
  api/server.py                        # PH-02: 경로 등록, 경로별 본문 상한
  api/models.py                        # PH-02: PhotoSaved, PhotoRead, memo 항목 photos
  harness/photo_reader.py              # PH-03: UserContent, ReadResult, PhotoReader, ClaudePhotoReader
  harness/prompts/photo_read.md        # PH-03
  harness/brain.py                     # PH-03: prompt: str | UserContent (Brain, SummaryBrain)
  harness/summaries.py                 # PH-03: _SummaryCaller 틀을 사진 읽기와 나눠 쓴다
  tools/mcp_adapter.py                 # PH-03: photo_read 도구 0개 / PH-04: create_memo 설명
  store/repos/state.py                 # PH-03: usage_state.photo_reads / PH-04: add_pending_inbound + 사진 연결
  api/chat.py                          # PH-04: message_photos()
  api/read.py                          # PH-04: /conversations/{id}/messages의 photos
  domain.py                            # PH-04: Inbound.photo_ids
  harness/dispatcher.py                # PH-04: resubmit_app_row가 사진을 다시 실음
  loop/runner.py                       # PH-04: 시작 때 다시 넣기가 사진을 다시 실음
  tools/memos.py                       # PH-04: create_memo(photo_ids)
  harness/prompts/channel_app.md       # PH-04: 두 줄
  loop/…(하루 한 번 작업)               # PH-05
  store/exports.py                     # PH-05
web/app/src/
  api/photos.ts  lib/shrinkPhoto.ts  lib/photoCache.ts  lib/shiftAnchor.ts   # PH-06
  screens/MemoEditor.tsx  screens/Memos.tsx  components/PhotoStrip.tsx  components/PhotoViewer.tsx  # PH-06
  pages/_document.tsx  (e2e/csp.spec.ts)                                     # PH-06: img-src blob:
  chat/ChatSheet.tsx  chat/PhotoTray.tsx                                     # PH-07
docs/spikes/2026-10-sp10.md            # PH-00
```

## Interfaces

```python
# store/repos/photos.py
@dataclass(frozen=True)
class Photo:
    id: int; sha256: str; path: str; thumb_path: str; bytes: int; width: int; height: int
    origin: Literal["memo", "chat"]; read_text: str | None; created_at: datetime; unlinked_at: datetime | None

class PhotosRepo:
    def get(self, conn, photo_id: int) -> Photo | None: ...
    def is_live(self, conn, photo_id: int) -> bool: ...                                       # 스펙 5.1 살아 있는 사진
    def insert(self, conn, *, sha256: str, path: str, thumb_path: str, bytes: int, width: int, height: int,
               origin: str, now: datetime) -> Photo: ...
    def attach(self, conn, memo_id: int, photo_id: int) -> int: ...                           # 가장 작은 빈 위치. TooManyPhotos, PhotoInUse
    def detach(self, conn, memo_id: int, photo_id: int, now: datetime) -> None: ...           # unlinked_at = now
    def for_memo(self, conn, memo_id: int) -> list[Photo]: ...
    def for_message(self, conn, inbound_id: int) -> list[Photo]: ...
    def link_message(self, conn, inbound_id: int, conversation_id: int, photo_ids: list[int]) -> None: ...   # INSERT OR IGNORE
    def in_conversation(self, conn, conversation_id: int, photo_ids: list[int]) -> bool: ...
    def set_read_text(self, conn, photo_id: int, text: str) -> None: ...
    def purgeable(self, conn, now: datetime) -> list[Photo]: ...                              # 스펙 5.6 1번
    def uploaded_on(self, conn, logical_day: date) -> int: ...

# store/photos.py
class PhotoFiles:
    def __init__(self, root: Path) -> None: ...                        # data/photos
    def jpeg_size(self, data: bytes) -> tuple[int, int]: ...           # PhotoUnreadable / PhotoNotJpeg
    def write_incoming(self, image: bytes, thumb: bytes) -> tuple[Path, Path]: ...    # 갈래 밖(to_thread), fsync
    def place(self, incoming: tuple[Path, Path], photo_id: int, sha256: str, local_day: date) -> tuple[str, str]: ...  # 갈래 안, 덮어쓰지 않는 이름 바꾸기
    def remove(self, *rel_paths: str) -> None: ...                     # PermissionError 세 번 다시
    def orphans(self, known: set[str], older_than: datetime) -> list[str]: ...

# harness/photo_reader.py
UserContent = list[dict[str, Any]]
@dataclass(frozen=True)
class ReadResult:
    text: str
    unreadable: bool
class PhotoReader(Protocol):
    name: str
    async def read(self, photo_id: int, image: bytes) -> ReadResult: ...

# harness/brain.py (바뀌는 시그니처)
class Brain:
    async def run(self, prompt: str | UserContent, *, session_id: str | None, run_ctx: RunContext, ...) -> BrainResult: ...
# SummaryBrain 프로토콜과 _SummaryCaller도 prompt: str | UserContent를 받는다
```

```ts
// web/app/src/api/photos.ts (BE apiFetch를 쓴다: 같은 BE, 같은 키)
export function uploadPhoto(conn: Conn, p: { image: Blob; thumb: Blob; origin: "memo" | "chat"; clientMsgId: string }): Promise<ApiResult<{ id: number; width: number; height: number; bytes: number }>>;
export function readPhoto(conn: Conn, id: number): Promise<ApiResult<{ text: string; unreadable: boolean }>>;
export function photoBlobUrl(conn: Conn, id: number, size: "thumb" | "full"): Promise<string | null>;   // photoCache를 거친다
// web/app/src/lib/shrinkPhoto.ts
export function shrinkPhoto(file: File): Promise<{ image: Blob; thumb: Blob }>;   // 스펙 7.2
// web/app/src/lib/shiftAnchor.ts
export function shiftAnchor(prev: string, next: string, anchor: number): number; // 스펙 7.4
```

---

## 티켓

### PH-00 스파이크 S1~S4 (스펙 13장)

브랜치 `docs/sp10-spikes`. 시험 코드는 `spikes/`(Git 밖) 또는 `E:\ocr-local-benchmark\scripts\`에, 결과 요약만 `docs/spikes/2026-10-sp10.md`.

- [ ] S1: `.venv\Scripts\python spikes\sp10_s1.py --image <사진> [--four]`가 BE `build_options()`로 만든 설정 그대로 스트리밍 입력(`[사진 #1]` 글 + 이미지 + "이 사진에 뭐라고 써 있어?", `--four`면 네 장)을 보내고, 받은 `session_id`로 `resume`해 "방금 사진 #1의 첫 줄을 다시 말해 줘"를 보낸다. 기대 출력 줄: `first_ok=True`, `resume_ok=True`(둘째 답에 첫 줄), `session_file=<경로> bytes=<n> has_base64=<True|False>`, `input_tokens=<첫 호출>,<둘째 호출>`.
- [ ] S2: 리서치 데이터(스펙 13장 S2). `E:\ocr-local-benchmark\venv-claude\Scripts\python.exe E:\ocr-local-benchmark\scripts\bench_sp10_s2.py --track kdoc|kstr_dev100 --prompt photo_read.md`(`bench_claude_agent_sdk.py`를 복사해 지시만 바꾼 것). 기대 출력 줄: `kdoc pass=<n>/67`, `kstr_dev100 cer=<x>% exact=<k>/100 refusals=<r> explanations=<e>`. 판정: `r + e < 2`이고 `n >= 56`.
- [ ] S3: 노트북 임시 정적 서버 + `tailscale serve`의 임시 경로(Dahun 확인 뒤, 끝나면 끔)에서 시험 페이지를 아이폰 Safari와 홈 화면 앱으로 열어 사진 고르기, HEIC, 12MP와 48MP 사진의 `createImageBitmap` resize 줄이기 시간·메모리 오류, 5MB `multipart` 올리기 확인. 판정: 화면의 `pick ok / heic ok / shrink12 <ms> / shrink48 <ms> / upload ok` 다섯 줄이 두 상태에서 모두 ok.
- [ ] S4: `.venv\Scripts\python spikes\sp10_s4.py`가 aiohttp `client_max_size=64KiB` 그대로에서 `/photos` 처리기가 `request.multipart()`로 5.5MiB를 읽고, `/actions`의 chunked 65KB 본문이 413인지 확인. 기대 출력 줄: `photos_5_5mib=201`, `photos_5_6mib=413`, `actions_chunked_65k=413`.
- 끝: 결과에 따라 스펙 v2.1 PR(S1이 실패하면 5.5를 "사진 읽기 결과 글을 두뇌에 준다"로 바꾼다).

### PH-01 저장: 020, 파일, 즉시 갈래

- [ ] `020_photos.sql`(스펙 5.1, CASCADE, `UNIQUE(photo_id)`, `usage_state.photo_reads`), `store/photos.py`(5.2), `store/repos/photos.py`, `tools/actions.py`의 `store_photo`·`attach_photo`·`detach_photo`(되돌리기, 활동 `summary`에 경로·읽은 글 없음, id는 `target`, `updated_at` 안 바꿈), `REJECT_CODES`에 새 코드.
- [ ] `create_memo` 동작(앱 `/actions`)에 `photo_ids`(스펙 5.3). `update_memo`는 사진을 받지 않는다. 메모 지우기·되돌리기는 연결을 그대로 둔다(살아 있는 사진 정의로 숨김, 수용 기준 6).
- [ ] 테스트: `test_photos_store.py`(스펙 12장, Review Focus 1·6), 마이그레이션 시험.
- 검증: BE 명령 → `0 failed`, `All checks passed!`.

### PH-02 API (PH-00 S4 뒤)

- [ ] `api/photos.py`: `POST /photos`(`request.multipart()` 스트림, 바이트 세기, `to_thread` 쓰기, `client_msg_id` 재생), `GET /photos/{id}`(`?size=thumb`, `no-store`, 살아 있지 않으면 404), `GET /memos` 항목 `photos`. `server.py`: 경로 등록, `body_limit`의 경로 틀 상한(`client_max_size`는 그대로), `/health`의 `disk_low`.
- [ ] `config.toml`: `api.max_photo_bytes = 5000000`, `limits.daily_photos = 100`, `limits.daily_photo_reads = 30`, `photos.reader = "claude"`, `photos.cleanup = true`.
- [ ] 테스트: `test_photos_api.py`(스펙 12장, Review Focus 2). `npm run gen:types`.
- 검증: BE 명령 → `0 failed`.

### PH-03 사진 읽기 (S1·Q 답 뒤)

- [ ] `brain.py`: `prompt: str | UserContent`(글만이면 지금 경로), 스트리밍 입력 만들기 함수. `SummaryBrain`·`_SummaryCaller` 시그니처도 함께.
- [ ] `RunKind`에 `"photo_read"`, `mcp_adapter`의 도구 0개 조건에 더함, 세션 파일 지우기·`brain_calls` 세기(하루 끝 예약분 유지).
- [ ] `photo_reader.py`, `prompts/photo_read.md`(스펙 5.4, 거절 틀 목록 포함), `POST /photos/{id}/read`(두뇌 큐, 하루 30회 `usage_state.photo_reads`, 같은 사진 동시 요청 하나로 묶기, `read_text` 저장).
- [ ] 테스트: `test_photo_reader.py`(스펙 12장).
- 검증: BE 명령 → `0 failed`.

### PH-04 채팅 사진

- [ ] `chat.py` `message_photos()`와 검사(스펙 5.5), 사진만 있는 메시지 → 두뇌, 두뇌 입력(각 이미지 앞 `[사진 #id]` 글 블록), 원문 기록 표시.
- [ ] `state.py` `add_pending_inbound`와 같은 트랜잭션의 `link_message`, `domain.Inbound.photo_ids`, `dispatcher.resubmit_app_row`·`runner`의 시작 때 다시 넣기가 `for_message`로 사진을 다시 실음.
- [ ] `api/read.py` `GET /conversations/{id}/messages` 항목 `photos`.
- [ ] `tools/memos.py` `create_memo(photo_ids?)`(앱 통로만, 이 대화 사진만), 확인 문구 "(사진 {n}장)", 되돌리기는 소프트 삭제(연결 유지), `channel_app.md` 두 줄.
- [ ] 대화 지우기(SP9 7.7)에 `message_photos` 지우기.
- [ ] 테스트: `test_chat_photos.py`(스펙 12장, Review Focus 3·4·7), `test_mcp_adapter.py` 도구 설명 갱신, 텔레그램 도구 목록 그대로. `npm run gen:types`.
- 검증: BE 명령 → `0 failed`.

### PH-05 하루 한 번 작업과 내보내기

- [ ] 스펙 5.6 1~5번, `photos.cleanup` 스위치.
- [ ] 테스트: `test_photos_daily.py`(스펙 12장, Review Focus 5), `test_redaction.py` 더하기.
- 검증: BE 명령 → `0 failed`.

### PH-06 앱: 메모 사진

- [ ] `api/photos.ts`, `lib/shrinkPhoto.ts`(7.2, `createImageBitmap` resize), `lib/photoCache.ts`(7.3, 메모리 60장), `lib/shiftAnchor.ts`(7.4).
- [ ] `PhotoStrip`, `PhotoViewer`, 메모 쓰기 화면 "사진" 버튼과 흐름(7.1), 메모 목록 작은 사진, `pages/_document.tsx` CSP `img-src blob:`와 `e2e/csp.spec.ts`, 문구(8장).
- [ ] 테스트: 스펙 12장 앱 항목 중 메모 쪽, `test_shift_anchor_cases`, Playwright: 가짜 BE로 사진 고르기 → 사진 줄 → 글 들어감 → 저장 요청에 `photo_ids`.
- 검증: 앱 명령 → 모두 통과.

### PH-07 앱: 채팅 사진

- [ ] 채팅 버튼 둘: 카메라(`capture="environment"`, 찍으면 바로 올리고 보냄, 실패하면 대기 줄에 남김)와 사진(`multiple`). `PhotoTray`(대기 4장, ✕), 사진만 있어도 보내기(`send()`의 빈 글 조건), 보내기 때 올리기 → `sendMessage({parts, metadata})`, 말풍선 사진 격자, 다시 연 대화의 `photos`, 올리기 실패 시 보내지 않음(7.5).
- [ ] 테스트: 스펙 12장 앱 항목 중 채팅 쪽, 보낸 본문의 `parts`에 `data-photo`, 사진만 보내기.
- 검증: 앱 명령 → 모두 통과, `npm run e2e -- chat` → 통과.

### PH-08 노트북 수용 확인 (손으로, Dahun과)

- [ ] 수용 기준 1~3, 5~7. 5번: 읽기 없이 사진 20장만 올리기 전후 `(Get-Item data\planner.db).Length` 증가분 < 올린 사진 바이트 합의 1%, 그날 백업 파일도 같은 기준. 6번: 메모 지우기 → 사진 `GET` 404 → 되돌리기 → 사진 다시 보임.
- [ ] 결과를 `docs/acceptance/sp10-checklist.md`에.
