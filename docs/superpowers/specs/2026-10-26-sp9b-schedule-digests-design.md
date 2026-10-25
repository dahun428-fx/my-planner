# SP9b 일정 정리 알림 설계

- 상태: v1.1 (2026-10-26)
- 앞선 문서: SP9 스펙 `2026-10-25-sp9-app-tabs-memo-schedule-design.md` 5.3(일정 알림), 8장(체크인 시간 바꾸기, 깨우기 작업), ADR 0015
- 요청: Dahun 2026-10-25 23:07Z "스케줄 기능 같은 경우에는 아침에 리뷰 알림을 주거나, 하루 전날 밤쯤에 리마인드 해줘야할 것 같아."
- 결정: 결정 카드에서 C "둘 다 따로 푸시"를 골랐다. 아침과 밤에 체크인과 따로 일정 정리 알림을 보내고, 두 시각 모두 설정에서 바꿀 수 있다.
- 이름: 이 기능은 **일정 정리 알림**(코드 `digest`)이다. 종류는 아침 알림(`morning`)과 밤 알림(`night`)이다. 기억 카드를 만드는 **정리 루프**(`consolidation`)와 다르므로 문서와 코드에서 "정리"를 혼자 쓰지 않는다(GLOSSARY, 9장).

## 1. 무엇을 만드나

일정마다 오는 알림(SP9 5.3)과 따로, 하루에 많아야 두 번 **일정 정리 알림**을 보낸다.

| 종류 | 코드 | 기본 시각 | 고를 수 있는 시각 | 담는 날 | 제목 |
|---|---|---|---|---|---|
| 아침 알림 | `morning` | 07:30 | 04:00~11:50, 10분 단위 | 보내는 날(현지 날짜) | `오늘 일정 {n}개` |
| 밤 알림 | `night` | 21:30 | 18:00~23:50, 10분 단위 | 보내는 날의 다음 날 | `내일 일정 {n}개` |

- 두뇌를 거치지 않는다. 1분 tick이 판정하고, 일정 알림과 같은 주 통로(앱 웹 푸시, 없으면 텔레그램 대체)로 보낸다.
- 그날 일정이 하나도 없으면 보내지 않는다. 건너뛴 회(`이번만 건너뛰기`)와 끝난 반복은 세지 않는다.
- 시각은 평일과 주말을 나누지 않는다. 종류마다 시각 하나와 켜기/끄기 하나만 있다.
- 고를 수 있는 시각은 체크인 시간 선택기처럼 10분 단위다. 아침 알림은 논리적 날짜 경계(04:00)부터, 밤 알림은 자정 전까지로 범위를 정했다. 그래서 두 종류 모두 보내는 시각의 달력 날짜가 사용자가 느끼는 "오늘"과 같고, 밤 알림의 "내일"이 모레가 되는 일이 없다.
- 기본값은 둘 다 켜짐이다. 기본 시각 07:30과 21:30, 기본 켜짐, 멈춤 중 보냄은 Dahun이 SP9-12 검토 때 확인한다(7장).
- 체크인, 비서가 먼저 거는 말의 하루 상한(`daily_proactive_messages`), 일정 알림 상한(`daily_event_reminders`) 어디에도 세지 않는다. 종류마다 하루 한 번이라 따로 상한이 필요 없다.
- 멈춤(pause) 중에도 보낸다(1.1).

### 1.1 P1 예외

마스터 스펙 P1은 "하루 연락은 아침 브리핑과 저녁 체크인 두 번이 기본"이다. 일정 정리 알림을 기본 켜짐으로 두면 기본 연락이 네 번이 되므로 이것은 P1의 예외다. 예외로 두는 이유는 다음과 같다.

- Dahun이 2026-10-25에 아침 리뷰와 전날 밤 리마인드를 직접 요청했고, 결정 카드 C에서 체크인과 따로 보내는 쪽을 골랐다.
- 그날 일정이 없으면 보내지 않는다. 그래서 일정이 없는 날의 연락은 늘지 않는다.
- 설정에서 종류마다 끌 수 있다.

멈춤 중에도 보내는 근거는 일정 알림(SP9 5.3)과 조금 다르다. 일정 알림은 사용자가 일정마다 정한 시각이라 보내지만, 일정 정리 알림은 비서가 모아 보내는 알림이다. 그래도 멈춤은 비서가 먼저 말을 거는 것을 멈추는 것이고, 일정 정리 알림은 사용자가 켜 둔 일정 알림의 묶음이라 보낸다. 이 판단은 SP9-12에서 Dahun이 확인하고, 바꾸라고 하면 판정에 멈춤 조건 하나를 더한다. 이 예외는 ADR 0015에 덧붙임으로 남긴다(9장).

## 2. 본문과 보내는 모양

- 그날 일정을 시작 순으로 늘어놓는다. 하루 종일 일정은 맨 앞에 둔다.
- 한 줄은 `{HH:MM} {제목}`이고, 하루 종일 일정은 `하루 종일 {제목}`이다. 제목은 20자에서 자르고 `…`를 붙인다.
- 세 줄까지만 보이고, 더 있으면 넷째 줄에 `외 {k}개`를 쓴다. 줄 사이는 줄바꿈(`\n`)이다.
- 늦게 보낼 때(3장)는 아직 시작하지 않은 일정만 담는다. 시작이 지난 시각 일정은 빼고, 하루 종일 일정은 남긴다. 남은 것이 없으면 보내지 않는다. 밤 알림은 대개 다음 날 일정이라 뺄 것이 없지만, 자정 뒤에 늦게 보내면 0시대 일정이 빠질 수 있다.
- 제목의 `{n}`은 담은 일정의 개수다. 늦게 보내서 뺀 일정은 세지 않고, 줄로 보인 것과 `외 {k}개`를 합친 수다.
- 푸시를 누르면 `/schedule/?date=YYYY-MM-DD`(담은 날)를 연다.
- 로그에는 종류, 날짜, 개수만 남기고 제목은 남기지 않는다.

### 2.1 푸시 데이터 (`harness/delivery.py`)

`digest_payload(kind, day, title, body, url) -> dict[str, Any]`:

```json
{"type": "digest", "checkin_id": null, "title": "오늘 일정 3개", "body": "하루 종일 휴가\n09:00 팀 회의\n14:00 치과",
 "url": "/schedule/?date=2026-10-27", "tag": "digest:morning:2026-10-27"}
```

- `body`는 `_first_line`으로 자르지 않는다. 줄바꿈을 그대로 둔다(줄 수와 길이는 위 규칙이 이미 묶는다).
- `tag`는 `digest:{kind}:{date}`이고 `date`는 담은 날이다. 같은 날 같은 종류는 폰에서 하나로 겹친다.

`Delivery.deliver_digest(kind, day, title, body, url, *, ttl_s: int) -> Channel | None`:

- `deliver_reminder`와 같은 통로 규칙이다. 실제 통로가 `app`이면 `digest_payload` 푸시(구독마다 한 번, `topic=None`), 아무도 받지 못하면 텔레그램이다. 받은 통로를 돌려주고, 어디에도 못 보냈으면 None이다.
- 텔레그램 대체 문구는 제목, 줄바꿈, 본문이다(`f"{title}\n{body}"`). 일정 알림의 `{title} · {body}` 한 줄과 달리 여러 줄을 그대로 보낸다.
- 푸시 보관 시간 `ttl_s`는 부르는 쪽(`send_digests`)이 정한다. 보낼 때마다 `until - now`를 일정 알림과 같은 범위(`TTL_MIN_S` 1시간부터 `TTL_MAX_S` 하루까지)로 묶는다.

### 2.2 서비스 워커 (`web/app/public/sw.js`)

- 새 sw는 `type === "digest"`이고 `tag`가 빈 문자열이 아닌 문자열이면 그 `tag`를 쓴다. 그 밖의 태그 규칙(`run-…`, `reminder:…`, `notice`)은 그대로다.
- 지금 sw(옛 sw)가 `type: "digest"`를 받으면 `checkin_id`가 없고 `reminder`도 아니라서 태그가 `notice`가 된다. 제목, 본문, 누르면 여는 주소(`mapPushUrl`이 `/schedule/?date=…`를 그대로 둔다)는 맞게 나오지만, 같은 `notice` 태그의 다른 안내(고정 안내, 시험 알림)와 서로 덮어쓴다.
- 그래서 sw 변경은 앱 작업(계획 D2)에 넣고, **앱(Vercel)을 먼저 배포한 뒤** 일정 정리 알림이 든 BE를 노트북에 올린다. BE가 `tag`를 싣는 것은 sw가 BE와 따로 배포되기 때문이다(태그 모양을 BE 한 곳에서 정한다).

## 3. 판정 (1분 tick)

`judge_digests(*, last_seen_at: datetime, now: datetime, settings: dict[DigestKind, DigestSetting], events: EventsRepo, state: StateRepo, tz: str, day_boundary: time) -> list[PendingDigest]`

**슬롯**: 종류 k와 달력 날짜 x마다 보낼 시각 `at(k, x) = x + 그 종류의 time`(현지)이 하나 있다. 담는 날은 아침 알림이 x, 밤 알림이 x + 1일이다.

1. 지금의 현지 달력 날짜를 d라 하고, 종류마다 x = d - 1, d 두 슬롯을 이 순서로 본다. 꺼진 종류는 건너뛴다.
2. `last_seen_at < at <= now`이고 그 종류의 `digest_last`가 없거나 x보다 앞이면 판정한다.
   - 공백(`now - last_seen_at`) ≤ 3분(`RESUME_GAP`): 보낸다.
   - 깨어남이고 `now - at <= 2시간`(`DIGEST_LATE_MAX`): 늦게 보낸다(본문은 2장).
   - 깨어남이고 2시간이 넘었다: 보내지 않는다. 놓친 알림 카드도 만들지 않는다. 일정 정리 알림은 일정 알림의 덧붙임이라서다.
3. 판정 결과와 상관없이 `app_state.digest_last`의 그 종류 날짜를 x(슬롯의 날짜)로 **보내기 전에** 적는다. 그래서 보내는 도중에 죽어도 두 번 보내지 않는다. 일정 알림과 같은 규칙이다.
4. 그날 담을 일정이 없으면 보내지 않는다(날짜는 적는다).
5. 보내기와 재시도는 `send_reminders`와 같은 방식(최대 2번, 20초·60초)을 쓴다. `PendingDigest.until`은 **보내는 시각(판정한 `now`)의 논리적 날짜 끝**, 곧 다음 `day_boundary`(04:00)다. 재시도는 `until`이 지나면 하지 않고, 푸시 보관 시간도 `until`로 정한다(2.1). 실패는 로그 `digest_failed`만 남긴다(행이 없으니 고칠 것도 없다).

d - 1 슬롯을 보는 까닭: 밤 알림을 23:00으로 두고 22:50에 잠들어 00:30에 깨어나면, 달력 날짜가 바뀌어 d의 슬롯(오늘 23:00)은 아직 오지 않았고 놓친 것은 d - 1의 23:00이다. 90분 늦었으니 늦게 보낸다. 이때 담는 날은 d(달력 기준 오늘)이고, 제목은 논리적 날짜 기준이라 그대로 `내일 일정 {n}개`다(00:30은 아직 논리적 어제다).

- 시각을 바꾼 바로 그날: 새 시각이 지금보다 뒤면 오늘 그 시각에 보낸다. 이미 오늘 판정했으면(`digest_last`가 오늘 슬롯 날짜) 다시 보내지 않는다. 새 시각이 이미 지났으면 오늘은 보내지 않는다(공백 안에 들지 않는다).
- 시계가 뒤로 가거나 `last_seen_at`이 없으면(첫 tick) 판정하지 않는다. 첫 tick에 보내지 않는 것은 받아들인 한계다.
- 판정이 예외를 내면 `digest_error`를 로그로 남기고 그 tick의 일정 정리 알림은 빠진다. 일정 알림 판정과 따로 감싸서 서로 막지 않는다.
- 로그: 판정마다 `digest_judged`(`kind`, `date`, `count`, `outcome`은 `sent`, `late`, `too_late`, `empty` 중 하나). 노트북 확인(6장)은 이 줄로 정시인지 늦게인지 본다.

### 3.1 러너 자리 (`loop/runner.py`)

- `Runner.tick`에서 `self._remind(last_seen, now)` 바로 다음에 `self._digest(last_seen, now)`를 부른다. 둘 다 `if not self.checkins` 조기 반환과 하트비트(`last_seen_at` 기록)보다 앞이다.
- `_digest`는 `_remind`와 같은 조건에서 돈다. `self.events is None` 또는 `last_seen is None`이면 건너뛴다. `_remind`가 `role = "dev"`(`checkins=False`)에서도 돌므로 `_digest`도 그렇다.
- 설정은 tick마다 `self.state.get_digest_settings(self.settings.schedule.digest)`로 읽고, `digest_last`는 `self.state`로 직접 적는다(`judge_digests`에 `state=self.state`).
- 보내기는 `send_digests`를 asyncio 작업으로 띄우고 `self.reminder_tasks`에 넣는다. 그래서 종료 때 `drain_reminders`가 함께 기다리고 취소한다. 이벤트 루프 밖이거나 `reminder_delivery`가 없으면 로그 `digests_no_loop`만 남긴다.

### 3.2 절전 방지

Windows는 타이머로 깨운 뒤 사용자 입력이 없으면 무인 유휴 시간(기본 약 2분) 뒤 다시 재울 수 있다. 지금 `keep_awake`는 디스패처(`_AwakeRefs`, 큐에 일이 있을 때)에만 주입되고 `Runner`에는 그런 고리가 없다. 그래서 이번에는 고리를 새로 만들지 않고, 노트북 확인(6장)에서 "잠든 상태에서 07:25에 깨어나 07:30에 정시로 보냄"을 본다. 이 확인이 실패하면(07:30 전에 다시 잠들어 `late`가 되면) 후속으로 일정 정리 알림만의 앞당김 시간(`DIGEST_WAKE_LEAD`)을 5분에서 1분으로 줄인다.

## 4. 저장

마이그레이션은 없다. `app_state`에 두 키를 더한다.

- `digest_settings`: `{"morning": {"on": true, "time": "07:30"}, "night": {"on": true, "time": "21:30"}}`. 없거나 잘못된 칸, 범위 밖 시각, 깨진 JSON은 config 값을 쓴다(예외 없음).
- `digest_last`: `{"morning": "YYYY-MM-DD", "night": "YYYY-MM-DD"}`. 판정한 마지막 슬롯 날짜(현지 달력 날짜, 3장).
- 해석 함수 `parse_digest_settings(raw, defaults: DigestConfig)`는 `loop/digests.py`에 두고, `StateRepo.get_digest_settings`와 `wake_times.load_digest_settings`가 함께 쓴다(`loop/schedule.parse_overrides`와 같은 자리 나눔).

config.toml 기본값:

```toml
[schedule.digest]
morning = "07:30"
night = "21:30"
morning_on = true
night_on = true
```

`config._Model`은 `extra="forbid"`라서 `ScheduleConfig.digest: DigestConfig`를 config.toml과 **같은 커밋**에 더한다. `DigestConfig`도 1장의 범위와 10분 단위를 검사한다(벗어나면 config 로드 오류).

## 5. API와 앱

- `GET /api/v1/settings/digests` → `{"morning": {"on", "time"}, "night": {"on", "time"}, "wake_updated": bool}`. `wake_updated`는 체크인 시간과 같은 `not state.wake_task_stale()`다.
- `PUT /api/v1/settings/digests`: 바꿀 종류 하나를 받는다(`{"kind", "on", "time"}`, 체크인 시간 PUT이 칸 하나를 받는 것과 같다). `time`은 `HH:MM`이고 1장의 범위 안 10분 단위여야 한다. 4시 경계와 상관없이 현지 시각 그대로다. 범위 밖, 10분 단위가 아닌 값, 모르는 `kind`는 `422 digest_time_invalid`.
  - 멱등 키는 없다. 체크인 시간 PUT처럼 `client_msg_id`를 받지 않고, 즉시 갈래 `endpoint="push"`라서 `api_idempotency`도 쓰지 않는다. 대신 자연 멱등이다. 지금과 같은 값이면 아무것도 적지 않고, 활동과 되돌리기를 만들지 않으며, 깨우기 작업도 다시 등록하지 않는다(`activity_id`, `undo_id`, `applies`가 null).
  - 바뀌면 즉시 갈래로 적용하고 활동 한 줄을 남긴다(5.1). 되돌리기는 토스트로 한다(SP9-01과 같다).
  - 답: `{"morning", "night", "wake_updated", "applies", "activity_id", "undo_id"}`. `applies`는 `today`(오늘 슬롯이 아직 판정 전이고 새 설정이 오늘 슬롯을 정한다) 또는 `tomorrow`. "오늘"은 논리적 날짜(04:00 경계)다.
- 앱 더보기 → 설정에서 "체크인 시간" 아래에 "일정 정리 알림" 칸을 둔다. 두 줄이고, 줄마다 이름("아침에 오늘 일정", "밤에 내일 일정"), 켜기/끄기 스위치, 시간 선택이 있다. 끄면 시간 선택은 흐리게 보인다. 시간 선택은 체크인 시간처럼 10분 단위 목록이다.
- 토스트 문구는 체크인 시간과 같은 `오늘부터 적용돼요`, `내일부터 적용돼요`이고, 되돌리기 단추가 붙는다.
- BE에 `/settings/digests`가 없으면(404, 앱을 먼저 배포한 사이) 그 칸을 그리지 않는다.
- 앱 설명 한 줄: `일정이 있는 날만 보내요.`
- 채팅 도구는 만들지 않는다. 바꾸고 싶다고 하면 비서는 설정 화면을 알려 준다(YAGNI, 나중에 더할 수 있다).
- 텔레그램 UI는 만들지 않는다(Q14). 다만 앱 푸시를 못 받는 상태면 대체 통로 규칙에 따라 텔레그램으로 간다.

### 5.1 쓰기 경로와 되돌리기

체크인 시간(SP9 8장)과 같은 모양으로 잇는다.

- `PUT /settings/digests`(`api/push.py`의 `put_digest_settings`)는 본문을 검사한 뒤 `dispatcher.apply_action(ActionRequest("set_digest_settings", {"kind", "on", "time"}, actor="user", channel="app", endpoint="push"))`를 부른다. `put_notify`가 쓰는 `_request`와 같다.
- `tools/actions.py`: `"set_digest_settings": ActionSpec("apply_digest_settings", public=False, endpoint="push")`. 채팅 도구와 확인 카드가 없어 `/actions`에서는 부를 수 없다.
- `tools/digest_settings.py`의 `DigestSettingTools.apply_digest_settings`(Tools mixin, `CheckinTimeTools`와 같은 자리)가 한 트랜잭션 안에서 `state.set_digest_settings`와 `record_activity(kind="digest_set", target="digest:{kind}", risk="low", undo={"kind", "setting": 바꾸기 전 값})`를 한다.
- 활동 한 줄: `✓ 일정 정리 알림 바꿈: 아침 07:30 → 08:00`, `✓ 일정 정리 알림 바꿈: 밤 끔`, `✓ 일정 정리 알림 바꿈: 밤 켬 21:30`. 되돌림 한 줄(`confirmations.undo_summary`에 규칙 하나): `↩ 되돌림: 아침 일정 정리 알림`.
- `register_undo("digest_set", _undo_digest_settings)`: 바꾸기 전 값을 그대로 다시 적는다. `digest_last`는 건드리지 않는다(이미 판정한 슬롯을 되살리지 않는다).
- 깨우기 작업: PUT이 실제로 바꿨을 때 `api/actions.refresh_wake(deps)`를 부른다(`windows.refresh_wake_task`를 직접 부르지 않는다). `post_undo`는 지금 `_undid_checkin_time`(`a.kind == CHECKIN_KIND`)일 때만 `refresh_wake`를 부르므로, 이것을 `_undid_wake_change`로 바꾸고 `a.kind in WAKE_KINDS`(`frozenset({CHECKIN_KIND, DIGEST_KIND})`)로 넓힌다. 그래야 되돌린 뒤 깨우기 작업이 옛 시각으로 남지 않는다.

## 6. 깨우기 작업

- `wake_times`가 켜진 일정 정리 알림 시각도 5분 이른 시각으로 내보낸다. 줄 모양은 `daily HH:MM`이다(`DayKind`에 `daily`를 더한다).
- 설정은 `wake_times.load_digest_settings(root)`가 DB `app_state.digest_settings`를 읽기 전용(`mode=ro`)으로 읽고 config `[schedule.digest]`와 합친다. DB가 없거나 못 읽거나 JSON이 깨졌으면 config 값이다.
- 겹침: 같은 `(종류, 시각)` 줄만 하나로 둔다. `daily 17:25`와 `weekday 17:25`처럼 종류가 다르면 트리거 두 개로 남긴다. 같은 때 두 번 깨우는 것은 해가 없다.
- 스크립트 세 곳을 함께 바꾼다.
  - `scripts/task_common.ps1` `$DaysXml`에 `daily = '<Sunday /><Monday /><Tuesday /><Wednesday /><Thursday /><Friday /><Saturday />'`.
  - `scripts/task_common.ps1` `Get-WakeTimes`의 정규식을 `^(weekday|weekend|daily) ([0-2][0-9]:[0-5][0-9])$`로. 안 바꾸면 `daily` 줄에서 throw하고 `update_wake_task.ps1`, `register_task.ps1`이 모두 실패한다(`wake_updated: false` 고정).
  - `scripts/check_tasks.ps1` `$DaysMask`에 `daily = 127`. 안 바꾸면 매일 트리거를 `?`로 읽어 점검이 FAIL이다.
- `PUT /settings/digests`가 바꿨을 때와 `digest_set`을 되돌렸을 때 체크인 시간과 같은 `refresh_wake`를 부른다(5.1). 실패하면 `wake_updated: false`이고, 설정 화면에 SP9 8장과 같은 안내가 뜬다.
- 노트북에서 할 확인(SP9-11에 더한다).
  - `update_wake_task.ps1 -DryRun`의 트리거 수가 켜진 종류 수(기본 2)만큼 늘었는지, `check_tasks.ps1`이 `OK   all checks passed`인지.
  - 21:25에 노트북이 깨어 21:30에 밤 알림이 오는지.
  - 잠든 상태에서 07:25에 깨어나 07:30에 아침 알림이 정시로 오는지. 로그 `digest_judged`의 `outcome`이 `sent`여야 하고 `late`면 실패다(3.2).

## 7. 지어 넣은 문구와 선택 (SP9-12에서 Dahun 확인)

문구: `오늘 일정 {n}개`, `내일 일정 {n}개`, `하루 종일 {제목}`, `외 {k}개`, `✓ 일정 정리 알림 바꿈: …`(5.1의 세 모양), `↩ 되돌림: {아침|밤} 일정 정리 알림`, `일정 정리 알림`, `아침에 오늘 일정`, `밤에 내일 일정`, `일정이 있는 날만 보내요.`, 오류 `일정 정리 알림 시간은 아침 04:00~11:50, 밤 18:00~23:50 사이에서 10분 단위로 정할 수 있어요.`

선택: 기본 시각 07:30·21:30, 기본 켜짐(P1 예외, 1.1), 멈춤 중 보냄(1.1), 고를 수 있는 범위(1장), 늦게 보내는 한도 2시간.

## 8. 시험

- 판정: 정시 공백 1분이면 보낸다. 깨어나 1시간 늦으면 늦게 보내고, 시작이 지난 일정은 빼며 제목 `{n}`은 뺀 뒤의 개수다. 3시간 늦으면 안 보낸다. 밤 23:00 설정, 22:50 잠듦, 00:30 깨어남이면 늦게 보낸다(d - 1 슬롯, 담는 날 d, `digest_last`는 d - 1). 같은 날 두 번 tick이 겹쳐도 한 번만 보낸다. 일정이 없으면 안 보낸다. 꺼져 있으면 안 보낸다. 건너뛴 회는 세지 않는다. 시각을 오늘 더 늦게 바꾸면 그 시각에 보낸다. 이미 판정한 날 다시 바꾸면 안 보낸다. 판정 예외가 일정 알림을 막지 않는다. `role = "dev"`에서도 판정한다. `last_seen_at`이 없으면 건너뛴다.
- 보내기: `digest_payload`의 `type`, `tag`, 줄바꿈 유지. 텔레그램 대체 문구가 제목, 줄바꿈, 본문이다. `ttl_s`가 `until - now`를 1시간부터 하루까지로 묶은 값이다. `until`이 지나면 다시 보내지 않는다. 끝내 못 보내면 `digest_failed` 로그만 남는다. `drain_reminders`가 보내는 중인 작업을 기다린다.
- 본문: 세 줄과 `외 k개`, 하루 종일 일정이 맨 앞, 20자 자르기.
- 저장: `digest_settings` JSON이 깨지거나 칸이 범위 밖이면 config 값이고 예외가 없다. `get_digest_last`는 없는 종류에 None을 준다.
- API: GET 기본값, PUT 한 종류 갱신, 422(범위 밖, 10분 단위 아님, 모르는 종류), 같은 값 PUT은 활동·되돌리기·깨우기 갱신이 없다, 활동 한 줄, 되돌리기가 이전 값을 되살리고 `refresh_wake`를 부른다, PUT이 `refresh_wake`를 부른다, `applies`.
- wake_times: 켜진 시각이 `daily` 줄로 나오고, 꺼지면 빠지고, 같은 `(종류, 시각)`만 하나로 둔다. `daily`와 `weekday`의 같은 시각은 둘 다 나온다. DB의 `digest_settings`가 깨졌으면 config 값이다.
- 스크립트: `task_common.ps1` 정규식과 `$DaysXml`, `check_tasks.ps1` `$DaysMask`에 `daily`가 있다(텍스트 시험).
- 앱: 설정 칸 렌더, 스위치, 시간 바꾸기 PUT, 토스트와 되돌리기, 끄면 시간 흐림, 실패 안내, 404면 칸 없음, 금지어 시험에 새 문구 추가.
- sw.js: `type: "digest"`면 payload `tag`로 보이고, 누르면 url을 연다. `tag`가 없으면 예전처럼 `notice`다.

## 9. 문서 갱신

- `GLOSSARY.md` 스케줄 묶음(`놓친 알림` 다음)에 아래를 더한다.

  > **일정 정리 알림** (`digest`): _SP9b 초안_
  > 하루에 많아야 두 번, 그날 일정을 모아 보내는 푸시. 아침 알림(`morning`)은 오늘 일정, 밤 알림(`night`)은 내일 일정을 담고, 일정이 없는 날은 보내지 않는다. 두뇌를 거치지 않는다. 기억 카드를 만드는 **정리 루프**(`consolidation`)와 다르다.
  > _쓰지 않음_: 정리(혼자 쓸 때), 다이제스트, 일정 요약

- `docs/adr/0015-schedule-is-not-a-task.md`에 덧붙임 한 문단을 더한다.

  > 덧붙임 (2026-10-26, SP9b): 일정 정리 알림은 일정 알림과 같은 통로와 규칙(두뇌 없음, 멈춤 중에도 보냄, 비서가 먼저 거는 말의 상한에 세지 않음)을 쓴다. 다만 사용자가 일정마다 고른 시각이 아니라 비서가 모아 보내는 알림이고, 기본 켜짐이라 하루 연락이 기본 두 번이라는 P1의 예외다. Dahun이 2026-10-25에 직접 요청했고(결정 카드 C), 일정이 없는 날은 보내지 않으며, 종류마다 끌 수 있다. 상세는 [SP9b 스펙](../superpowers/specs/2026-10-26-sp9b-schedule-digests-design.md).

- SP9 스펙 15장에 14번 "일정 정리 알림 기본 켜짐, 멈춤 중 보냄, 기본 시각 07:30·21:30(SP9b 7장)"을 더하고, 변경 기록에 한 줄을 더한다: `- v2.5 (2026-10-26): 일정 정리 알림은 SP9b 스펙(2026-10-26-sp9b-schedule-digests-design.md)으로 따로 둔다. 15장 14번 추가.`

## 변경 기록

- v1 (2026-10-26): 결정 카드 C로 첫 초안.
- v1.1 (2026-10-26): 문서 리뷰 1 반영. 이름을 일정 정리 알림(`digest`)으로 고정, 푸시 데이터와 `deliver_digest`·`send_digests`·TTL·텔레그램 대체 모양, `daily` 깨우기 종류와 스크립트 세 곳, 쓰기 경로와 되돌리기·`post_undo` 깨우기 갱신, 멱등 키 대신 자연 멱등, d - 1 슬롯 판정, 10분 단위와 범위, 러너 자리, `DigestConfig`와 `load_digest_settings`, P1 예외와 ADR 덧붙임, 절전 확인, sw 배포 순서, `until`은 보낸 시각의 논리적 날짜 끝, `{n}` 정의, 활동 `digest_set`과 토스트 문구, 문서 갱신 단계.
