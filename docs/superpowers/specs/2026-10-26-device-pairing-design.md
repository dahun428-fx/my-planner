# 기기 연결 코드 — 설계

- 날짜: 2026-10-26 · 버전 v1.2 (doc-review 2회 반영)
- 요청(Dahun, 2026-10-26 05:12Z): "임시 토큰을 주고 그 토큰을 넣으면 로그인되는 형식으로도 변경될 수 있나? 이 부분을 조금 심플하게 하고 싶은데". 05:14Z: 기기 연결 코드 안에 "ok 해줘".
- 고치는 곳: SP3-4 스펙 6.1(인증, 오류 코드)·13.1(대시보드 연결)·14장(보안), SP5 스펙 4.7(이 기기 연결 해제)·4.8(환경 변수)·5.5.8(연결 화면). 넣을 문장은 10장. 새 ADR 0018(0016·0017은 다른 스레드가 쓰기로 한 번호. 머지할 때 겹치면 다음 빈 번호로 옮긴다). 용어집 "기기 토큰", "연결 코드".

## 1. 문제

새 컴퓨터나 새 브라우저에서 운영 앱이나 대시보드를 열려면 BE 주소(`https://<기계>.<tailnet>.ts.net`)와 43자가 넘는 API 토큰(`API_TOKEN`)을 손으로 옮겨야 한다. 토큰은 노트북 `.env`에만 있으니 노트북에서 복사해 다른 기기로 보내야 하고, 그 사이 채팅이나 메모에 남기 쉽다. 모든 기기가 같은 토큰을 쓰므로 기기 하나를 잃어버리면 토큰을 바꾸고 모든 기기에 다시 넣어야 한다.

## 2. 원칙

1. 새 기기에서는 **6자리 숫자 하나**만 넣는다. BE 주소는 미리 채워 둔다(6.1).
2. 코드는 이미 연결된 기기(또는 노트북 명령)가 만든다. 5분 동안 한 번만 쓸 수 있다.
3. 코드를 쓰면 BE가 **그 기기만의 토큰**(기기 토큰)을 내려 준다. 기기마다 따로 끊을 수 있다.
4. API 토큰은 그대로 통한다. 이미 연결된 기기는 아무것도 하지 않아도 된다. 비상 복구 수단으로 남긴다.
5. BE는 계속 tailnet 안에만 연다. Tailscale은 그대로 필요하고 Funnel은 쓰지 않는다(ADR 0008, README).
6. 코드와 토큰은 로그, 오류 응답 어디에도 쓰지 않는다(SP3-4 14장 그대로).

## 3. 흐름

### 3.1 폰에서 새 컴퓨터를 연결한다(주 경로)

1. 폰 앱 `더 보기 > 연결된 기기`에서 `새 기기 연결`을 누른다.
2. 시트에 코드 `482 913`(세 자리씩 띄움), 남은 시간(`4:59`), 열 주소(앱 주소, 대시보드 주소)가 보인다.
3. 컴퓨터에서 대시보드나 앱 주소를 열면 연결 화면이 뜬다. BE 주소는 채워져 있고 `연결 코드` 칸만 비어 있다.
4. 6자리를 넣으면(여섯 번째 숫자에서 바로) 연결하고 첫 화면으로 간다.
5. 폰의 시트는 `연결됐어요 · Windows · 대시보드`로 바뀌고 목록에 새 기기가 생긴다.

### 3.2 노트북에서 첫 기기를 연결한다

연결된 기기가 하나도 없을 때: 노트북 PowerShell에서 `.venv\Scripts\python.exe -m my_planner pair`(4.7). 코드와 남은 시간을 출력한다.

### 3.3 QR로 컴퓨터·안드로이드·태블릿 탭을 연결한다

- 시트의 QR은 `https://<앱 주소>/connect/#be=<BE 주소>&code=482913`을 담는다. `대시보드용` 전환을 누르면 `https://<대시보드 주소>/settings/#be=…&code=…`.
- `#` 뒤는 브라우저 밖으로 나가지 않으므로 Vercel에도 기록되지 않는다. 연결 화면은 값을 읽자마자 `history.replaceState`로 주소에서 지운다.
- **아이폰·아이패드 Safari 탭에서는 해시를 읽지 않는다.** SP5 4.6·5.5.8대로 탭과 홈 화면 앱은 저장소가 따로이고, 탭에서는 홈 화면에 추가하라는 안내만 보인다. 해시를 읽고 바로 연결하면 코드가 쓰이고 토큰은 쓸모없는 탭에 남는다. 아이폰 홈 화면 앱은 숫자 6자리를 손으로 넣는다(홈 화면 앱은 `start_url`로 열려 해시를 받지 못한다).

## 4. BE

### 4.1 저장

새 이전 `019_devices.sql`(다른 스레드가 먼저 019를 쓰면 다음 빈 번호):

```sql
CREATE TABLE devices (
    id           INTEGER PRIMARY KEY,
    token_hash   TEXT NOT NULL UNIQUE,   -- sha256(토큰) 16진수. 토큰 원문은 저장하지 않는다
    label        TEXT NOT NULL,          -- "iPhone · 앱", "Windows · 대시보드"
    client       TEXT NOT NULL CHECK (client IN ('app', 'dashboard')),
    created_at   TEXT NOT NULL,
    last_used_at TEXT NULL,              -- 하루에 한 번만 갱신한다(4.4)
    revoked_at   TEXT NULL
);
ALTER TABLE push_subscriptions ADD COLUMN device_id INTEGER NULL REFERENCES devices(id);
```

- 기기 토큰은 `secrets.token_urlsafe(32)`(43자). 32바이트 무작위 값이라 소금 없는 sha256으로 충분하다.
- 연결 코드는 DB에 두지 않고 BE 메모리에만 둔다. 재시작하면 사라진다.
- 활동 기록(`activity`)에는 남기지 않는다. 되돌릴 일이 아니고, 언제 연결했는지는 목록의 `created_at`이 보여 준다.

### 4.2 쓰기

ADR 0007대로 쓰기는 Dispatcher 즉시 갈래로만 한다. 두뇌 도구가 아닌 내부 동작 셋을 더한다(`push_subscribe`와 같은 자리).

| 동작 | 하는 일 |
| --- | --- |
| `device_pair` | `devices`에 한 줄 넣고 기기 토큰 사전(4.4)에 더한다 |
| `device_revoke` | `revoked_at`을 쓰고, 그 기기의 푸시 구독에 `disabled_at`을 쓰고, 사전에서 뺀다 |
| `device_touch` | `last_used_at`을 쓴다 |

- 처리기가 `secrets.token_urlsafe(32)`로 토큰을 만들고, `device_pair` 인자에는 `token_hash`·`label`·`client`만 넘긴다. 토큰 원문은 응답에만 담는다(Dispatcher 경로의 로그·기록에도 없다).
- 기기 토큰 사전(`DeviceTokens`, 4.4)은 `build_be`가 만들어 `ApiDeps`와 Dispatcher에 같은 것을 넘긴다. 동작은 DB 커밋이 끝난 뒤 사전을 고친다.

### 4.3 연결 코드

- `PairCodes`(메모리): 살아 있는 코드는 **하나**만. 새로 만들면 전 코드는 사라진다.
- 코드: `secrets.randbelow(10**6)`을 6자리로 채운 문자열. `now >= expires_at`(만든 뒤 5분)이면 만료. 한 번 쓰면 사라진다.
- 같은 코드로 5번 틀리면 그 코드는 사라진다.
- 비교는 `hmac.compare_digest`.
- 상태(`GET /devices/pair`): 코드가 살아 있으면 `waiting`, 만료됐거나 5번 틀려 사라졌으면 `expired`, 쓰였으면 `used`와 그 기기. `used`·`expired`는 새 코드를 만들 때까지, 또는 그 일 뒤 10분까지 그대로 돌려준다. 그 뒤와 코드를 만든 적이 없으면 `none`.

### 4.4 인증

`auth` 미들웨어(SP3-4 6.1, SP8 7.2)를 이렇게 고친다.

1. `limiter.blocked()`면 지금처럼 `429`.
2. 경로 틀이 `POST /api/v1/pair`면 Bearer를 보지 않고 처리기로 넘긴다(캘린더 구독과 같은 자리).
3. `/body`와 캘린더 `?key=`는 지금 그대로다. 기기 토큰은 받지 않는다.
4. `POST /api/v1/internal/notify`(SP6 복구 감시자)는 API 토큰만 받는다.
5. 그 밖의 경로는 **API 토큰 또는 끊지 않은 기기 토큰**을 받는다. 먼저 `bearer_ok(header, API_TOKEN)`, 아니면 Bearer 값의 sha256을 기기 토큰 사전에서 찾는다. 찾으면 `DEVICE_ID_KEY = web.RequestKey("device_id", int)`에 둔다.
6. 둘 다 아니면 지금처럼 실패를 세고 `401 unauthorized`.

- 기기 토큰 사전(`DeviceTokens`, 메모리): 끊지 않은 기기의 `token_hash → device_id`. 시작할 때 DB에서 읽고, `device_pair`·`device_revoke`가 DB에 쓴 뒤 같이 고친다. 요청마다 DB를 읽지 않는다.
- `last_used_at`: 사전에 기기마다 마지막으로 쓴 날짜(`settings.timezone` 기준)를 같이 둔다. 오늘과 다르면 처리기가 끝난 뒤 먼저 사전의 날짜를 오늘로 바꾸고(같은 날 다른 요청이 다시 부르지 않게), 그다음 지금 쓰기 처리기처럼 `apply_action(device_touch)`를 한 번 부른다. 실패하면 `device_touch_failed` 경고 한 줄만 남긴다.
- **안전 모드**(DB를 못 연 상태)에서는 사전이 비어 있다. 이때 `/health`는 `Authorization: Bearer <아무 값>` 형식이면 값을 보지 않고 실패로 세지 않은 채 `safe_mode_view`를 준다(버전과 시각 같은 상태만 있고 데이터는 없다). 헤더가 없거나 형식이 다르면 `401`. `/pair`를 포함한 다른 경로는 지금처럼 `503 safe_mode`.

### 4.5 경로

| 경로 | 인증 | 하는 일 |
| --- | --- | --- |
| `POST /api/v1/devices/pair` | API 토큰 또는 기기 토큰 | 코드를 만든다. `201 {code, expires_at}` |
| `GET /api/v1/devices/pair` | 위와 같음 | `{state: "waiting" \| "used" \| "expired" \| "none", device?: {id, label}}`. 시트가 2초마다 부른다 |
| `POST /api/v1/pair` | **없음**(코드가 인증) | 본문 `{code, client, label}` → `201 {token, device: {id, label, client}}` |
| `GET /api/v1/devices` | API 토큰 또는 기기 토큰 | 끊지 않은 기기 `[{id, label, client, created_at, last_used_at, this_device}]`, 만든 순서 |
| `DELETE /api/v1/devices/{id}` | 위와 같음 | `device_revoke`. `204`. 없는 id나 이미 끊은 id면 `404 not_found` |

`POST /api/v1/pair`:
- `Content-Type: application/json`이 아니면 `400 invalid_request`. 그래서 사전 요청 없는 단순 요청(`text/plain` 폼)으로는 다른 출처가 코드를 소진할 수 없다.
- 본문: `code`는 숫자 6자리 문자열, `client`는 `app`·`dashboard`, `label`은 1~40자이고 제어 문자·줄바꿈이 없다. 다르면 `400 invalid_request`.
- 틀린 코드, 만료된 코드, 코드 없음은 모두 `401 bad_code` `코드가 맞지 않거나 만료됐어요.`(어느 쪽인지 말하지 않는다). 지금 `AuthLimiter`에 실패로 센다.
- 응답에 `Cache-Control: no-store`.
- CORS와 사설 네트워크 사전 요청(`OPTIONS`)은 지금 `cors_middleware`가 경로와 상관없이 처리하므로 바꿀 것이 없다. 허용 출처는 `cors_origins` 그대로다.

목록:
- `this_device`는 요청을 보낸 기기 토큰의 기기면 true. API 토큰으로 부르면 모두 false.
- API 토큰은 목록에 나오지 않고 끊을 수 없다.

시도 한도(예): 한 코드는 5번 틀리면 사라지고, 틀린 시도는 모두 `AuthLimiter`에 센다. 1~10번째 시도는 `401 bad_code`이고(6~10번째는 이미 사라진 코드에 대한 시도), 10번째 실패에서 막기가 시작되어 11번째부터 1분 동안 모든 요청이 `429 too_many_auth_failures`다. 코드 하나를 맞힐 확률은 5/10⁶.

### 4.6 푸시 구독

- `POST /push/subscriptions`가 기기 토큰으로 오면 `device_id`를 같이 저장하고, API 토큰이면 NULL이다.
- upsert(`ON CONFLICT(endpoint)`)는 `device_id = excluded.device_id`로 덮는다(마지막으로 구독한 쪽이 주인). 끊긴 기기의 endpoint를 다른 연결이 다시 구독하면 지금처럼 `disabled_at = NULL`로 되살아나고 주인이 바뀐다.
- 기기를 끊으면 `device_id`가 그 기기인 구독에 `disabled_at`을 쓴다.

### 4.7 CLI `pair`

`cli.py`에 `pair`를 더한다. `.env`의 `API_TOKEN`으로 `POST http://127.0.0.1:<[api] port>/api/v1/devices/pair`를 부른다(주소는 `[api] host`가 아니라 언제나 `127.0.0.1`. BE가 다른 주소에만 열려 있으면 "꺼짐"으로 보인다). 토큰은 출력하지 않는다.

| 결과 | 출력 | 끝 코드 |
| --- | --- | --- |
| `201` | `연결 코드: 482 913 (5분 동안, 한 번만)` | 0 |
| 닿지 않음 | `BE가 꺼져 있어요. 작업을 켜고 다시 해 주세요.` | 1 |
| `401` | `.env의 API_TOKEN이 BE와 달라요.` | 1 |
| `429` | `잠시 뒤에 다시 해 주세요.` | 1 |
| `503 safe_mode` | `BE가 안전 모드예요. 상태부터 확인해 주세요.` | 1 |
| 그 밖 | `코드를 만들지 못했어요 (<상태 코드>).` | 1 |
| `API_TOKEN` 없음 | `.env에 API_TOKEN이 없어요.` | 1 |

## 5. 운영 앱

### 5.1 연결된 기기 화면(`/devices/`)

- `더 보기`에 `연결된 기기` 줄을 더한다(`연결` 줄 아래).
- 목록: 라벨, 둘째 줄 `마지막 사용 10월 26일`(오늘이면 `오늘`, 없으면 `연결 10월 26일`), 이 기기에는 `이 기기` 표시. 줄을 누르면 `연결 끊기`(확인 한 번: `이 기기에서 다시 쓰려면 새 코드가 필요해요.`).
- 목록 아래 `다른 기기 모두 끊기`(확인 한 번). `this_device`가 아닌 기기마다 `DELETE`를 부른다.
- 목록 아래 고정 문구: `노트북 열쇠(.env)로 연결한 기기는 여기 나오지 않아요.` (화면에서는 지금처럼 토큰을 "열쇠"라고 부른다. 문서의 "API 토큰"과 같은 것이다.)
- 이 기기를 끊으면 저장한 연결을 지우고 연결 화면으로 간다.
- 맨 위 버튼 `새 기기 연결` → 5.2의 시트.

### 5.2 새 기기 연결 시트

- 코드(큰 글씨, 세 자리씩), 남은 시간, 열 주소, QR, `코드 다시 만들기`.
- 앱 주소는 `location.origin`. 대시보드 주소는 앱의 선택 환경 변수 `NEXT_PUBLIC_DASHBOARD_URL`(예: `https://my-planner-dashboard-seven.vercel.app`). 없으면 대시보드 주소 줄과 `대시보드용` QR 전환을 숨긴다.
- QR은 브라우저에서 그린다(작은 QR 라이브러리를 앱 번들에 넣는다. 외부 QR 서비스에 코드를 보내지 않는다).
- 시트가 열려 있는 동안 2초마다 `GET /devices/pair`. `used`면 `연결됐어요 · <라벨>`을 보여 주고 목록을 새로 읽는다. `expired`면 `코드가 만료됐어요 · 다시 만들기`. 시트를 닫으면 묻기를 멈춘다(코드는 BE에서 만료까지 산다).

### 5.3 연결 화면(`/connect/`)

- 기본은 `연결 코드` 모드: BE 주소 칸(6.1로 채웠으면 접힘, `주소 바꾸기`로 편다) + 숫자 6칸(`inputmode="numeric"`, `autocomplete="one-time-code"`, 붙여 넣으면 나눠 채움).
- 여섯 번째 숫자가 들어오면 바로 `POST /pair` → 받은 토큰으로 `/health` 확인 → 저장 → 첫 화면. 아이폰 홈 화면 앱의 알림 허용 흐름(SP5 F1)은 지금처럼 이 눌림에 붙인다. 숫자 입력이 끝나는 순간이 사용자의 동작이 아니면 권한 창이 뜨지 않으므로, 홈 화면 앱에서는 자동 제출하지 않고 `알림 허용하고 시작하기` 버튼을 누르게 한다.
- 아래 작은 링크 `열쇠로 연결`을 누르면 지금의 주소 + 토큰 화면이다.
- 주소 끝 `#be=…&code=…`(아이폰·아이패드 Safari 탭이 아닐 때만, 3.3)가 있으면 두 칸을 채우고 바로 진행한다. 해시의 `be`가 6.1의 기본 주소보다 이긴다(연결된 기기가 실제로 쓰는 주소다).
- `/pair` 호출은 `apiFetch`의 401 접기를 쓰지 않고 오류 본문의 `code`를 읽는다:
  - `401 bad_code` → `코드가 맞지 않거나 만료됐어요. 연결된 기기에서 새 코드를 만들어 주세요.` 칸을 비운다.
  - `401 unauthorized` → 옛 BE(`/pair`가 없어 인증이 먼저 막는다) → `BE를 먼저 업데이트해야 해요. 지금은 열쇠로 연결해 주세요.` 토큰 모드로 바꾼다.
  - 닿지 않음, `429`, `503`은 지금 연결 화면 문구 그대로.

### 5.4 이 기기 연결 해제(SP5 4.7)

연결 코드로 연결하면 앱은 `mp.tokenKind = "device"`와 `mp.deviceId = <POST /pair 응답의 device.id>`를 같이 저장한다(대시보드는 `mp.connection` JSON의 `Conn`에 `kind`, `deviceId`를 더한다). 둘 다 연결 해제 때 지운다. 저장한 토큰이 기기 토큰이면 먼저 `DELETE /devices/{this}`를 부르고(실패해도 계속), 그다음 지금처럼 이 기기의 연결을 지운다. API 토큰이면 지금 그대로다.

## 6. 대시보드

- 설정 화면(`/settings/`)의 연결 칸을 5.3과 같은 `연결 코드` 모드로 바꾼다(`client: "dashboard"`, 자동 제출). 토큰 모드는 아래 링크로 남긴다. 해시 규칙도 5.3과 같다.
- 대시보드는 읽기 전용이므로(ADR 0008) 코드를 만들거나 기기 목록을 보는 화면은 없다. 끊기는 앱에서 한다. 설정의 `연결 지우기`는 5.4처럼 기기 토큰이면 `DELETE /devices/{this}`를 먼저 부른다(BE 쓰기지만 자기 연결을 지우는 일이라 읽기 전용 원칙의 예외로 둔다).

### 6.1 BE 주소 미리 채우기

- 앱과 대시보드에 선택 환경 변수 `NEXT_PUBLIC_DEFAULT_BE_URL`(예: `https://desktop-thqvhb3.tailbe947d.ts.net`). 있으면 연결 화면의 주소 칸을 채우고 접는다. 없으면 지금처럼 빈 칸이다.
- 이 값은 정적 파일에 들어가 누구나 볼 수 있다. 기계 이름이 드러나지만 tailnet 밖에서는 닿지 않고, tailnet 이름은 이미 `NEXT_PUBLIC_CONNECT_SRC`에 들어 있다. 토큰은 여전히 빌드에 넣지 않는다.
- 값은 `normalizeBeUrl` 검사를 통과해야 쓴다. 통과하지 못하면 빈 칸이다.
- Vercel 설정은 Dahun이 한다. 운영(main)은 운영 BE, 개발(develop)은 개발 BE(`:8443`).

### 6.2 기기 이름

클라이언트가 `navigator.userAgent`로 `iPhone`·`iPad`·`Android`·`Mac`·`Windows`·`Linux`·`기기` 중 하나를 고르고 `· 앱`/`· 대시보드`를 붙인다. 이름 바꾸기는 이번 범위가 아니다.

## 7. 하지 않는 것

- 아이디·비밀번호 로그인, 외부 로그인(OAuth). 사용자는 Dahun 한 명이고 tailnet이 첫 문이다.
- 기기 토큰 만료. 쓰지 않는 기기는 목록에서 끊는다.
- API 토큰 없애기. 비상 복구 수단으로 남긴다.
- 텔레그램으로 코드 보내기(텔레그램에 새 기능을 더하지 않는다).
- 기기마다 권한 나누기. 기기 토큰은 API 토큰과 같은 경로를 연다(`/internal/notify` 빼고). 그래서 기기 토큰을 훔친 사람은 끊기기 전에 새 코드를 만들어 다른 기기를 붙일 수 있다. 막는 방법은 `다른 기기 모두 끊기`이고, 그래도 걱정되면 API 토큰을 바꾼다(ADR 0018 대가). 끊기는 활동 기록에 남지 않으므로 훔친 토큰으로 끊어도 흔적은 목록에서 기기가 사라진 것뿐이다.

## 8. 배포 순서

1. BE(4장)를 develop에 머지 → 개발 BE에서 확인 → main 승격 → 노트북 pull과 작업 다시 켜기(Dahun).
2. 앱·대시보드(5·6장)는 BE보다 먼저 나가도 된다. 옛 BE에서는 `/pair`가 `401 unauthorized`이므로 토큰 모드로 간다(5.3).
3. Vercel 환경 변수 `NEXT_PUBLIC_DEFAULT_BE_URL`(앱·대시보드), `NEXT_PUBLIC_DASHBOARD_URL`(앱)을 넣고 다시 배포(Dahun, 선택).

## 9. 시험

BE(`pytest`):
- `test_pair_code_six_digits_expires_after_5_minutes`(가짜 시계 4:59 통과, 5:00 `401 bad_code`)
- `test_pair_code_single_use`, `test_new_code_replaces_old`, `test_five_wrong_codes_kill_code`
- `test_pair_status_waiting_used_expired_none`(쓰인 뒤 10분 지나면 `none`)
- `test_pair_without_bearer_returns_device_token_once`(DB에는 sha256만, 원문 없음, `Cache-Control: no-store`)
- `test_pair_rejects_non_json_content_type`, `test_pair_label_rejects_control_chars`
- `test_device_token_reads_today`, `test_revoked_device_token_401`, `test_api_token_still_works`
- `test_device_token_rejected_on_body_calendar_and_internal_notify`
- `test_wrong_codes_count_in_auth_limiter`(1~10번째 `401 bad_code`, 11번째 `429 too_many_auth_failures`)
- `test_revoke_disables_device_push_subscriptions`, `test_resubscribe_moves_device_id`
- `test_delete_unknown_or_revoked_device_404`
- `test_devices_list_marks_this_device_and_hides_api_token`
- `test_last_used_at_written_once_per_day`(같은 날 두 번째 요청에 `device_touch` 없음)
- `test_safe_mode_health_any_bearer_not_401_not_counted`, `test_safe_mode_health_no_header_401`, `test_safe_mode_pair_503`
- `test_code_and_token_never_logged`(Dispatcher 경로를 포함한 로그 캡처에 코드·토큰 문자열 없음)
- `test_cli_pair_prints_code`, `test_cli_pair_be_down_exit_1`, `test_cli_pair_401_exit_1`, `test_cli_pair_safe_mode_exit_1`

앱·대시보드(`vitest`):
- 연결 코드 6칸: 붙여 넣기 나눠 채움, 여섯 번째 숫자에 자동 제출(홈 화면 앱은 버튼), `bad_code` 문구와 칸 비움, `401 unauthorized`에서 토큰 모드로.
- `#be=…&code=…`로 채우고 주소에서 지움. 아이폰 Safari 탭에서는 해시를 읽지 않고 안내만.
- `NEXT_PUBLIC_DEFAULT_BE_URL` 있음/없음/검사 실패. 해시 `be`가 기본 주소보다 이김.
- 연결된 기기: 이 기기 끊기 → 연결 화면, 다른 기기 모두 끊기, 시트의 `used`/`expired`, `NEXT_PUBLIC_DASHBOARD_URL` 없으면 대시보드 줄 숨김.
- 이 기기 연결 해제: 기기 토큰이면 `DELETE /devices/{this}`를 부르고, 실패해도 연결을 지움.

손 확인(노트북·아이폰, Dahun): 폰에서 코드 만들기 → 다른 컴퓨터 대시보드에서 6자리로 연결 → 폰 목록에 생김 → 끊기 → 그 컴퓨터가 `401`로 연결 화면에 감. `my_planner pair`로 코드 출력.

## 10. 상위 스펙에 넣을 문장

- SP3-4 6.1: "`Authorization: Bearer`는 API 토큰 또는 끊지 않은 기기 토큰(기기 연결 스펙 4.4)을 받는다. `POST /pair`는 Bearer 없이 연결 코드로 인증한다." 오류 코드 표에 `401 bad_code`.
- SP3-4 13.1: "BE URL은 빌드에 넣지 않는다"를 "BE URL은 선택 환경 변수 `NEXT_PUBLIC_DEFAULT_BE_URL`로 미리 채울 수 있다(기기 연결 스펙 6.1). 토큰은 빌드에 넣지 않는다"로.
- SP3-4 14장 토큰 행: "바꾸려면 기기마다 다시 넣는다"를 "기기마다 기기 토큰을 받고 하나씩 끊는다. API 토큰을 바꾸면 API 토큰으로 연결한 기기만 다시 넣는다"로.
- SP5 4.7: 저장 표에 `mp.tokenKind`, `mp.deviceId`(연결 해제 때 지움). 이 기기 연결 해제는 기기 토큰이면 BE에서도 끊는다(기기 연결 스펙 5.4).
- SP5 4.8: 바뀌는 환경 변수에 `NEXT_PUBLIC_DEFAULT_BE_URL`, `NEXT_PUBLIC_DASHBOARD_URL`(둘 다 선택).
- SP5 5.5.8: 연결 화면 기본은 연결 코드 모드, 토큰 입력은 아래 링크(기기 연결 스펙 5.3).
