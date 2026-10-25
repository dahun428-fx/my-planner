"""설정: `root/config.toml`(Git 포함, 개인값 없음)과 `root/.env`(비밀값) (스펙 9).

`root/config.local.toml`(Git 밖)이 있으면 `config.toml` 위에 깊은 병합으로 겹친다(릴리스 흐름 스펙 5.2).

값의 기본은 계획의 Global Constraints다. 모든 경로는 `paths.root` 기준 절대경로다.
"""

from __future__ import annotations

import os
from datetime import time
from pathlib import Path
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict

# 겹쳐 읽기는 표준 라이브러리만 쓰는 medic 모듈의 것을 함께 쓴다(medic은 my_planner를 가져오지 않는다)
from my_planner_medic.toml_overlay import read_overlaid

ROOT_ENV = "MY_PLANNER_ROOT"

Weekday = Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
WEEKDAYS: tuple[Weekday, ...] = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DailyTimes(_Model):
    """매일 도는 루프의 시각. 주말 = 토, 일."""

    weekday: time
    weekend: time


class WeeklyTime(_Model):
    day: Weekday
    time: time

    @property
    def weekday_index(self) -> int:
        """`date.weekday()`와 같은 번호(월=0 … 일=6)."""
        return WEEKDAYS.index(self.day)


class ReviewSchedule(_Model):
    """주간 회고는 일요일만 지원한다. 회고 주(회고 날짜가 든 ISO 주)와 다음 주 계산이 일요일을 전제한다."""

    week: WeeklyTime = WeeklyTime(day="sun", time=time(18, 0))

    @field_validator("week")
    @classmethod
    def _sunday_only(cls, v: WeeklyTime) -> WeeklyTime:
        if v.day != "sun":
            raise ValueError("schedule.review.week.day는 sun만 지원한다")
        return v


class ScheduleConfig(_Model):
    morning_brief: DailyTimes = DailyTimes(weekday=time(9, 0), weekend=time(10, 0))
    evening_checkin: DailyTimes = DailyTimes(weekday=time(17, 30), weekend=time(18, 0))
    review: ReviewSchedule = ReviewSchedule()


class ReplyWindowConfig(_Model):
    """이 시각까지 답하면 같은 회차 대화로 잇는다."""

    morning_brief_until: time = time(12, 0)  # 당일
    evening_checkin_until: time = time(4, 0)  # 다음 날(논리적 날짜 끝)
    review_hours: int = 24


class CatchupLimitConfig(_Model):
    """루프별 한계: 이 시각이 지나면 보내지 않는다."""

    morning_brief_until: time = time(12, 0)  # 당일
    evening_checkin_until: time = time(4, 0)  # 다음 날
    review_days: int = 3


class LimitsConfig(_Model):
    daily_brain_calls: int = 60
    max_turns: int = 10
    daily_proactive_messages: int = 3
    daily_event_reminders: int = 30  # 일정 알림 하루 상한(SP9 5.3). 비서가 먼저 보내는 말(위)에 세지 않는다
    chat_resume_minutes: int = 30
    plan_idle_hours: int = 2
    draft_ttl_days: int = 3
    stale_message_hours: int = 6
    input_max_chars: int = 8000
    brain_timeout_s: float = 300  # 두뇌 호출 한 번의 상한(초). 넘으면 status="error", error="timeout"
    daily_summaries: int = 15  # 대화 요약 하루 상한(SP9 7.2). `daily_brain_calls`에도 센다
    rollup_user_messages: int = 30  # 사용자 메시지가 이보다 많아지면 다음 호출 전에 말아 넣는다(SP9 7.4)
    rollup_tail_lines: int = 6  # 말아 넣은 새 세션·resume 실패에 붙이는 최근 원문 줄 수(SP9 7.3, 7.4)
    reply_window: ReplyWindowConfig = ReplyWindowConfig()
    catchup_limit: CatchupLimitConfig = CatchupLimitConfig()


class PathsConfig(_Model):
    root: Path
    data_dir: Path
    state_dir: Path

    @field_validator("root", "data_dir", "state_dir")
    @classmethod
    def _absolute(cls, v: Path) -> Path:
        if not v.is_absolute():
            raise ValueError("경로는 절대경로여야 한다")
        return v

    @classmethod
    def for_root(cls, root: Path) -> PathsConfig:
        root = Path(root).resolve()
        return cls(root=root, data_dir=root / "data", state_dir=root / "state")


class RetentionConfig(_Model):
    log_days: int = 30
    backup_count: int = 14


API_TOKEN_MIN_CHARS = 43  # secrets.token_urlsafe(32)의 길이. 이보다 짧으면 API를 열지 않는다(계획 빈 곳 4)


class ApiConfig(_Model):
    """HTTP API (SP3-4 스펙 6.1, 14, 15). 127.0.0.1에만 열고 밖에서는 `tailscale serve`로만 닿는다."""

    enabled: bool = True
    host: str = "127.0.0.1"
    port: int = 8787
    cors_origins: list[str] = []  # 정확한 문자열 목록. `*.vercel.app` 같은 와일드카드는 받지 않는다
    # 출처 값의 검사는 CorsPolicy가 한다: 틀려도 API만 열지 않고 BE는 돈다(스펙 15)
    max_body_kb: int = 64


class NotifyConfig(_Model):
    default_primary: Literal["telegram", "app"] = "app"  # app_state.notify_primary가 없을 때


class VapidConfig(_Model):
    """웹 푸시 VAPID 키(SP3-4 스펙 14, 15). `.env`에만 둔다. 셋 다 있을 때만 `Settings.vapid`가 생긴다."""

    public_key: str  # base64url(비압축 P-256 공개키 65바이트). `GET /push/vapid-public-key`가 준다
    private_key: SecretStr  # base64url(원시 32바이트). 로그·응답에 나오지 않는다
    subject: str  # `mailto:` 주소


class RuntimeConfig(_Model):
    """`dev`(노트북 개발용 BE, 릴리스 흐름 스펙 5.2): 텔레그램(폴링·보내기)과 회차 스케줄러·따라잡기를 끈다.
    API, health, 회차 외 정리는 그대로 돈다."""

    role: Literal["prod", "dev"] = "prod"


class Settings(_Model):
    telegram_bot_token: SecretStr | None  # role = "dev"에서만 None일 수 있다
    owner_telegram_id: int | None
    timezone: str = "Asia/Seoul"
    day_boundary: time = time(4, 0)
    schedule: ScheduleConfig = ScheduleConfig()
    limits: LimitsConfig = LimitsConfig()
    paths: PathsConfig
    retention: RetentionConfig = RetentionConfig()
    api: ApiConfig = ApiConfig()
    notify: NotifyConfig = NotifyConfig()
    api_token: SecretStr | None = None  # .env의 API_TOKEN. 없거나 짧으면 API를 열지 않는다
    # .env의 BODY_TOKEN(SP8 7.2). `POST /body`만 된다. 없거나 짧거나 API_TOKEN과 같으면 그 경로만 열지 않는다
    body_token: SecretStr | None = None
    vapid: VapidConfig | None = None  # .env의 VAPID_*. 없으면 푸시만 꺼진다(`/push/*`는 404, 실제 통로는 telegram)
    runtime: RuntimeConfig = RuntimeConfig()

    @model_validator(mode="after")
    def _telegram_required_in_prod(self) -> Settings:
        if self.runtime.role == "prod" and (self.telegram_bot_token is None or self.owner_telegram_id is None):
            raise ValueError("role = prod에는 TELEGRAM_BOT_TOKEN, OWNER_TELEGRAM_ID가 있어야 한다")
        return self


class _Secrets(BaseSettings):
    """비밀값만 환경변수와 `.env`에서 읽는다(환경변수가 `.env`보다 먼저)."""

    model_config = SettingsConfigDict(extra="ignore", env_file_encoding="utf-8")

    telegram_bot_token: SecretStr = Field(validation_alias="TELEGRAM_BOT_TOKEN")
    owner_telegram_id: int = Field(validation_alias="OWNER_TELEGRAM_ID")
    api_token: SecretStr | None = Field(default=None, validation_alias="API_TOKEN")
    body_token: SecretStr | None = Field(default=None, validation_alias="BODY_TOKEN")
    vapid_public_key: str | None = Field(default=None, validation_alias="VAPID_PUBLIC_KEY")
    vapid_private_key: SecretStr | None = Field(default=None, validation_alias="VAPID_PRIVATE_KEY")
    vapid_subject: str | None = Field(default=None, validation_alias="VAPID_SUBJECT")

    def vapid(self) -> VapidConfig | None:
        """셋 다 비어 있지 않을 때만. 하나라도 없으면 푸시를 끈다(값은 남기지 않는다)."""
        private = self.vapid_private_key.get_secret_value().strip() if self.vapid_private_key is not None else ""
        public = (self.vapid_public_key or "").strip()
        subject = (self.vapid_subject or "").strip()
        if not (private and public and subject):
            return None
        return VapidConfig(public_key=public, private_key=SecretStr(private), subject=subject)


class _DevSecrets(_Secrets):
    """role = "dev": 텔레그램 값이 없어도 읽는다(있으면 그대로 읽는다)."""

    telegram_bot_token: SecretStr | None = Field(default=None, validation_alias="TELEGRAM_BOT_TOKEN")  # type: ignore[assignment]
    owner_telegram_id: int | None = Field(default=None, validation_alias="OWNER_TELEGRAM_ID")  # type: ignore[assignment]


def resolve_root() -> Path:
    """`MY_PLANNER_ROOT`가 있으면 그 값, 없으면 패키지 위치에서 두 단계 위(`src/my_planner` → 저장소 루트)."""
    env = os.environ.get(ROOT_ENV)
    if env:
        return Path(env).expanduser().resolve()
    return Path(__file__).resolve().parents[2]


def load_settings(root: Path) -> Settings:
    root = Path(root).resolve()
    data: dict[str, Any] = read_overlaid(root / "config.toml", root / "config.local.toml")
    # 합친 결과에 건다
    for key in ("telegram_bot_token", "owner_telegram_id", "api_token", "body_token", "vapid", "paths"):
        if key in data:
            raise ValueError(f"config.toml에 {key}를 두지 않는다")
    runtime = data.get("runtime")
    dev = isinstance(runtime, dict) and runtime.get("role") == "dev"
    secrets = (_DevSecrets if dev else _Secrets)(_env_file=root / ".env")  # type: ignore[call-arg]
    return Settings(
        telegram_bot_token=secrets.telegram_bot_token,
        owner_telegram_id=secrets.owner_telegram_id,
        api_token=secrets.api_token,
        body_token=secrets.body_token,
        vapid=secrets.vapid(),
        paths=PathsConfig.for_root(root),
        **data,
    )
