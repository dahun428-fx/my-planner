"""ToolEvent → 확인 문구 (스펙 5.5). 도구가 돌려준 이벤트만 근거로 하네스가 만든다."""

from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta
from typing import Any

from my_planner.domain import Area, ToolEvent
from my_planner.status.xp import AREA_LABELS, level_up_to


def _md(d: date) -> str:
    return f"{d.month}/{d.day}"


def _day_label(d: date, today: date) -> str:
    if d == today:
        return "오늘"
    if d == today + timedelta(days=1):
        return "내일"
    return _md(d)


_CADENCE_LABEL = {"day": "오늘", "week": "이번 주", "month": "이번 달", "quarter": "이번 분기", "year": "올해"}


def confirmation_line(e: ToolEvent, today: date) -> str | None:
    """이벤트 하나의 확인 문구 한 줄(SP1 5.5). 문구가 없는 종류는 None. 활동의 `summary`도 이것이다(5.2)."""
    title = e.data.get("title", "")
    if e.kind in MEMO_KINDS:
        return memo_line(e.kind, title)
    if e.kind in HABIT_KINDS:
        day = e.data.get("date")
        return habit_line(
            e.kind, title, label=e.data.get("label"), day=date.fromisoformat(day) if day else None, today=today
        )
    if e.kind == "task_added":
        out = f"✓ 추가: {title}"
        if e.data.get("scheduled_at"):
            at = datetime.fromisoformat(e.data["scheduled_at"])
            return f"{out} ({_md(at.date())} {at:%H:%M})"
        if e.data.get("planned_for"):
            return f"{out} → {_day_label(date.fromisoformat(e.data['planned_for']), today)}"
        return out
    if e.kind == "task_moved":
        pf = e.data.get("planned_for")
        label = _day_label(date.fromisoformat(pf), today) if pf else "날짜 없음"
        return f"✓ 옮김: {title} → {label}"
    if e.kind == "priorities_set":
        label = _CADENCE_LABEL[e.data["cadence"]]
        titles = e.data.get("titles", [])
        if not titles:
            return f"✓ 우선순위({label}): 비움"
        return f"✓ 우선순위({label}): " + " ".join(f"{i}. {t}" for i, t in enumerate(titles, start=1))
    return {
        "task_completed": f"✓ 완료: {title}",
        "task_reopened": f"✓ 되돌림: {title}",
        "task_dropped": f"✓ 내려놓음: {title}",
        "task_updated": f"✓ 바꿈: {title}",
        "tasks_confirmed": f"✓ 확정: {title}",
        # 고정 카드(SP3-4 10장). `title`은 `card_label`
        "card_pinned": f"✓ 카드 고정: {title}",
        "card_unpinned": f"✓ 카드 고정 해제: {title}",
        "cards_reordered": "✓ 카드 순서 바꿈",
        # 회차 차례의 확인(10.1): 바뀐 것은 없다. 회차 메시지 글에 확인 문구 전부를 남긴다(버튼은 짧다)
        "confirm_requested": confirm_requested_summary(e.data.get("summary", "")),
        # 인생 곡선(SP3-4 부록 A, 문구 C1~C4)
        "milestones_confirmed": milestone_confirmed_line(
            title, e.data.get("date_text", ""), e.data.get("kind", ""), e.data.get("area"),
        ),
        "milestone_dropped": dropped_line(title),
        "title_granted": f"칭호: {title}",
        "chapters_confirmed": chapter_confirmed_line(title, e.data.get("start_month", ""), e.data.get("end_month")),
        "chapter_dropped": dropped_line(title),
        "ladder_recorded": ladder_line(e.data.get("period", ""), e.data.get("now"), e.data.get("future")),
        "area_scores_recorded": area_scores_line(e.data.get("period", ""), e.data.get("scores", {})),
        # 비서가 준 경험치(X10, SP3-4 10장)
        "xp_granted_by_secretary": xp_granted_line(e.data.get("amount", 0), e.data.get("reason", "")),
    }.get(e.kind)


# --- 습관 (SP7 스펙 5.4 규칙 H4, 부록 A) ---

# 메모(SP9 6장). 만들기는 스펙 10장·6.3 문구, 나머지는 같은 꼴(SP9-03 판단). 활동 `summary`는 제목 앞 20자로 부른다
_MEMO_LINES = {
    "memo_created": "✓ 메모를 만들었어요: {}",
    "memo_updated": "✓ 메모를 고쳤어요: {}",
    "memo_pinned": "✓ 메모를 고정했어요: {}",
    "memo_unpinned": "✓ 메모 고정을 풀었어요: {}",
    "memo_deleted": "✓ 메모를 지웠어요: {}",
}
MEMO_KINDS = frozenset(_MEMO_LINES)


def memo_line(kind: str, title: str) -> str:
    """메모 확인 문구 한 줄. 본문은 넣지 않고 제목(`memo_title`)만."""
    return _MEMO_LINES[kind].format(title)


HABIT_KINDS = frozenset({"habit_added", "habit_updated", "habit_status_set", "habit_checked", "habit_unchecked"})
_HABIT_STATUS_VERB = {"paused": "쉬어 가기", "active": "다시 시작", "archived": "그만두기"}


def habit_kind_label(kind: str, target_per_week: int | None) -> str:
    """`매일` 또는 `주 {N}회`."""
    return "매일" if kind == "daily" else f"주 {target_per_week}회"


def habit_line(kind: str, title: str, *, label: str | None = None, day: date | None = None, today: date) -> str:
    """부록 A 확인 문구 9개. 활동 `summary`도 이것이다.

    `label`: `habit_added`·`habit_updated`는 주기(`habit_kind_label`), `habit_status_set`은 새 상태
    (`active` | `paused` | `archived`). `day`: 체크한 날짜. 오늘이 아니면 `(10/22)`를 붙인다(`habit_checked`만).
    """
    if kind == "habit_added":
        return f"✓ 습관 추가: {title} ({label})"
    if kind == "habit_updated":
        return f"✓ 습관 고침: {title} ({label})"
    if kind == "habit_status_set":
        return f"✓ 습관 {_HABIT_STATUS_VERB[label or '']}: {title}"
    if kind == "habit_checked":
        return f"✓ 습관: {title}" if day is None or day == today else f"✓ 습관: {title} ({_md(day)})"
    if kind == "habit_unchecked":
        return f"↩ 습관 체크 취소: {title}"
    raise ValueError(f"습관 확인 문구가 없는 종류: {kind}")


# --- 경험치 (SP3-4 9장, 부록 A) ---


def level_line(level: int | None) -> str:
    """부록 A "레벨 오름": `레벨 {N}이 됐어요.`, 오른 레벨이 없으면 빈 글. 확인 문구 끝에 한 줄로 붙인다(9.2)."""
    return f"레벨 {level}이 됐어요." if level is not None else ""


def level_up_line(before: int, after: int) -> str:
    """경험치 합계가 `before` → `after`로 바뀌며 레벨이 올랐으면 그 한 줄. 두 값은 **한 쌓기**의 직전·직후다(`XpGain`)."""
    return level_line(level_up_to(before, after))


def with_level_up(confirmation: str | None, level: int | None) -> str | None:
    """확인 문구(없으면 None) 끝에 그 차례가 넘긴 레벨(`XpGain.level_up`)의 한 줄을 붙인다. 둘 다 없으면 None.
    이미 그 줄로 끝나면 다시 붙이지 않는다."""
    line = level_line(level)
    if line and confirmation and confirmation.endswith(line):
        return confirmation
    joined = "\n".join(x for x in (confirmation, line) if x)
    return joined or None


def xp_granted_line(amount: int, reason: str) -> str:
    """X10 활동 요약·확인 문구: `✓ 경험치 +10: {사유}`."""
    return f"✓ 경험치 +{amount}: {reason}"


def rest_days_summary(days: int) -> str:
    """X9 활동 요약(하루 한 번 작업): `✓ 쉬는 날: 2일`."""
    return f"✓ 쉬는 날: {days}일"


# --- 인생 곡선 (SP3-4 부록 A, 문구 C1~C4) ---

# 사건 종류의 화면 이름(SP8 8.7). 코드 값은 그대로다
KIND_LABELS = {"high": "높은 때", "low": "힘든 때", "turning_point": "전환점"}


def milestone_confirmed_line(title: str, date_text: str, kind: str, area: str | None = None) -> str:
    """부록 A 사건 확정: `✓ 저장: 제주 여행 (2019, 높은 때)`. 영역이 있으면 끝에 붙인다(SP8 8.1):
    `✓ 저장: 제주 여행 (2019, 높은 때, 삶의 질)`."""
    tail = f", {AREA_LABELS[area]}" if area in AREA_LABELS else ""
    return f"✓ 저장: {title} ({date_text}, {KIND_LABELS.get(kind, kind)}{tail})"


def chapter_confirmed_line(title: str, start_month: str, end_month: str | None) -> str:
    """문구 C2: `✓ 저장: {제목} ({시작}~{끝 또는 "지금"})`."""
    return f"✓ 저장: {title} ({start_month}~{end_month or '지금'})"


def dropped_line(title: str) -> str:
    """부록 A 사건 빼기, 문구 C3 챕터 빼기: `✗ 뺐어요: {제목}`."""
    return f"✗ 뺐어요: {title}"


def ladder_line(period: str, now: int | None, future: int | None) -> str:
    """문구 C4(두뇌·`/actions`가 `record_ladder_score`로 기록할 때): 없는 쪽은 ` · ` 조각째 뺀다."""
    bits = [f"지금 {now}" if now is not None else None, f"5년 뒤 {future}" if future is not None else None]
    return f"✓ 사다리를 기록했어요 ({period}): " + " · ".join(b for b in bits if b is not None)


def area_scores_line(period: str, scores: dict[str, int]) -> str:
    """문구 C1: 넣은 영역만, SP1 영역 순서. `✓ 영역 점수를 기록했어요 (2026-Q4): 커리어 7 · 경제 5`."""
    parts = [f"{AREA_LABELS[a.value]} {scores[a.value]}" for a in Area if a.value in scores]  # SP1 영역 순서
    return f"✓ 영역 점수를 기록했어요 ({period}): " + " · ".join(parts)


def render_confirmations(events: list[ToolEvent], today: date) -> str:
    """이벤트마다 한 줄. 문구가 없는 종류(조회 등)는 건너뛴다. 없으면 빈 문자열."""
    lines = [ln for e in events if (ln := confirmation_line(e, today)) is not None]
    return "\n".join(lines)


def titles_summary(verb: str, titles: list[str]) -> str:
    """할 일 여럿을 한 활동으로 남길 때의 한 줄: `✓ 확정: 물 마시기, 스트레칭`."""
    return f"✓ {verb}: " + ", ".join(titles)


def condition_summary(score: int) -> str:
    """컨디션 기록 활동의 한 줄. SP1 버튼 답과 같은 문구이고 메모는 넣지 않는다(5.2)."""
    return f"컨디션 {score} 기록했어요."


_CARD_LABEL = {"ui_todo_list": "할 일 목록", "ui_choice": "고르기", "ui_summary_card": "요약"}


def card_label(component: str, props: Any) -> str:
    """카드 확인 문구의 이름: props의 제목(`title`, `ui_choice`는 `question`), 없으면 컴포넌트 이름."""
    p = props if isinstance(props, dict) else {}
    name = p.get("title") if component != "ui_choice" else p.get("question")
    return name.strip() if isinstance(name, str) and name.strip() else _CARD_LABEL.get(component, component)


def drafts_expired_summary(count: int) -> str:
    return f"✓ 초안 정리: {count}개"


# --- 회차 차례의 확인 문구 (SP3-4 10.1 A2). `pending_confirms.summary`, 앱 `ui_confirm`, 텔레그램 `✓ 확인:` 버튼 ---


def confirm_drop_summary(title: str) -> str:
    return f"할 일을 내려놓아요: {title}"


def confirm_priorities_summary(label: str, titles: list[str]) -> str:
    """`label`은 `period_label`(`오늘`, `이번 분기`, `2027-Q1`)."""
    if not titles:
        return f"{label} 우선순위를 비워요"
    return f"{label} 우선순위를 바꿔요: " + " ".join(f"{i}. {t}" for i, t in enumerate(titles, start=1))


def confirm_schedule_summary(title: str, at: datetime | None) -> str:
    """`scheduled_at`을 바꾸는 `update_task`. `at`은 현지 시각."""
    if at is None:
        return f"시각을 지워요: {title}"
    return f"시각을 바꿔요: {title} → {_md(at.date())} {at:%H:%M}"


def confirm_move_summary(title: str, planned_for: date | None, today: date) -> str:
    """시각 있는 할 일의 `move_task`."""
    label = _day_label(planned_for, today) if planned_for is not None else "날짜 없음"
    return f"날짜를 옮겨요: {title} → {label}"


# 텔레그램 확인 버튼(`✓ {아래} 16자`): 짧은 동작 이름과 대상. 확인 문구 전부는 메시지 글과 앱 카드에 있다


def confirm_button_drop(title: str) -> str:
    return f"내려놓기: {title}"


def confirm_button_priorities(label: str) -> str:
    return f"우선순위: {label}"


def confirm_button_schedule(title: str) -> str:
    return f"일정 변경: {title}"


def confirm_button_move(title: str) -> str:
    return f"옮기기: {title}"


def _ro(word: str) -> str:
    """조사 `로`/`으로`. 받침이 없거나 ㄹ 받침이면 `로`. 한글로 끝나지 않으면 `(으)로`."""
    last = word[-1:] if word else ""
    if "가" <= last <= "힣":
        jong = (ord(last) - 0xAC00) % 28
        return "로" if jong in (0, 8) else "으로"
    return "(으)로"


def confirm_habit_update_summary(title: str, label: str) -> str:
    """회차 차례의 `update_habit`(규칙 H7, 계획 문구 표): `{제목} 습관을 {매일 | 주 N회}로 바꿀까요?`."""
    return f"{title} 습관을 {label}로 바꿀까요?"


def confirm_habit_rename_summary(before: str, after: str) -> str:
    """이름만 바꾸는 `update_habit`: `{이전 제목} 습관 이름을 {새 제목}(으)로 바꿀까요?`."""
    return f"{before} 습관 이름을 {after}{_ro(after)} 바꿀까요?"


def confirm_habit_edit_summary(title: str) -> str:
    """주기가 바뀌지 않는 그 밖의 `update_habit`(영역만, 제목과 영역): `{제목} 습관을 고칠까요?`."""
    return f"{title} 습관을 고칠까요?"


def confirm_habit_archive_summary(title: str) -> str:
    """`set_habit_status(archived)`의 확인 요청(부록 A, 앱 `/actions`와 회차 차례가 같다)."""
    return f"{title} 습관을 그만둘까요? 기록은 남아요."


def confirm_button_habit_update(title: str) -> str:
    return f"습관 고치기: {title}"


def confirm_button_habit_archive(title: str) -> str:
    return f"그만두기: {title}"


def confirm_requested_summary(summary: str) -> str:
    """활동 `confirm_requested`의 한 줄(바뀐 것 없음, 6.4.4)."""
    return f"확인을 기다려요: {summary}"


def confirm_declined_summary(summary: str) -> str:
    return f"✗ 그대로 뒀어요 ({summary})"


_UNDO_VERB = {"되돌림": "다시 열기"}  # `✓ 되돌림: 운동`(다시 연 것)을 되돌리면 "운동 되돌림"이 겹친다
# `confirmation_line`이 `추가`·`옮김` 뒤에 붙이는 날짜 꼬리. 제목 안의 "→ X"는 건드리지 않는다
_DATE_TAIL = re.compile(r"( → (오늘|내일|날짜 없음|\d{1,2}/\d{1,2})| \(\d{1,2}/\d{1,2} \d{2}:\d{2}\))$")
_DATE_TAIL_VERBS = frozenset({"추가", "옮김"})
_SUMMARY = re.compile(r"^✓ (?P<verb>[^:]+): (?P<rest>.*)$")
_BARE = re.compile(r"^✓ (?P<verb>[^:]+)$")  # 대상 이름이 없는 한 줄(`✓ 카드 순서 바꿈`)
_CONDITION = re.compile(r"^(?P<what>컨디션 \d+) 기록했어요\.$")
# 곡선 기록(C1, C4): 점수 줄은 요지에서 빼고 기간만 둔다
_CURVE_RECORD = re.compile(r"^✓ (?P<what>사다리|영역 점수)를 기록했어요 \((?P<period>[^)]+)\): ")
# `저장`(사건·챕터 확정) 뒤의 날짜·종류(·영역) 꼬리: `(2019, 높은 때)`, `(2019, 높은 때, 삶의 질)`, `(2019-03~지금)`
_KIND_NAMES = "|".join(re.escape(v) for v in KIND_LABELS.values())
_AREA_NAMES = "|".join(re.escape(v) for v in AREA_LABELS.values())
_SAVE_TAIL = re.compile(
    rf" \((\d{{4}}(-\d{{2}}){{0,2}}, ({_KIND_NAMES})(, ({_AREA_NAMES}))?|\d{{4}}-\d{{2}}~(\d{{4}}-\d{{2}}|지금))\)"
)


# 습관 확인 문구(SP7 부록 A): `✓ 습관 추가: 운동 (주 3회)`, `✓ 습관: 운동 (10/22)`, `↩ 습관 체크 취소: 운동`
_HABIT_SUMMARY = re.compile(r"^[✓↩] (?P<verb>습관[^:]*): (?P<rest>.*)$")
_HABIT_TAIL = re.compile(r" \((매일|주 \d회|\d{1,2}/\d{1,2})\)$")


# `checkin_set_line`의 되돌림: `✓ 체크인 시간 바꿈: 평일 아침 07:00 → 07:30 (내일부터)` → `평일 아침 체크인 시간 07:30 → 07:00`
_CHECKIN_SET = re.compile(
    r"^✓ 체크인 시간 바꿈: (?P<slot>\S+ \S+) (?P<before>\d\d:\d\d) → (?P<after>\d\d:\d\d)"
)


def undo_summary(summary: str) -> str:
    """되돌림 확인(부록 A): `↩ 되돌림: {확인 문구 요지}`. `✓ 완료: 운동` → `↩ 되돌림: 운동 완료`.

    요지는 원래 활동의 확인 문구에서 만든다: 날짜 꼬리(`→ 내일`, `(10/25 14:00)`)는 떼고, 우선순위는 목록 이름만.
    습관은 주기·날짜 꼬리를 떼고 `운동 습관 체크`, `운동 습관 쉬어 가기`처럼 둔다.
    """
    if (ck := _CHECKIN_SET.match(summary)) is not None:
        return f"↩ 되돌림: {ck['slot']} 체크인 시간 {ck['after']} → {ck['before']}"
    if (h := _HABIT_SUMMARY.match(summary)) is not None:
        verb = "습관 체크" if h["verb"] == "습관" else h["verb"]
        return f"↩ 되돌림: {_HABIT_TAIL.sub('', h['rest'])} {verb}"
    if (cr := _CURVE_RECORD.match(summary)) is not None:
        return f"↩ 되돌림: {cr['what']} 기록 ({cr['period']})"
    if (m := _SUMMARY.match(summary)) is not None:
        verb, rest = m["verb"], m["rest"]
        if verb == "저장":
            rest = _SAVE_TAIL.sub("", rest)
        if verb.startswith("우선순위"):
            gist = verb
        else:
            if verb in _DATE_TAIL_VERBS:
                rest = _DATE_TAIL.sub("", rest)
            gist = f"{rest} {_UNDO_VERB.get(verb, verb)}"
    elif (b := _BARE.match(summary)) is not None:
        gist = b["verb"]
    elif (c := _CONDITION.match(summary)) is not None:
        gist = f"{c['what']} 기록"
    else:
        gist = summary
    return f"↩ 되돌림: {gist}"


def period_label(cadence: str, period: str, current: str) -> str:
    """지금 기간이면 `이번 분기` 같은 말, 아니면 기간 그대로(`2027-Q1`)."""
    return _CADENCE_LABEL[cadence] if period == current else period


def draft_dropped_reply(title: str) -> str:
    """`✗ 빼기` 버튼을 눌렀을 때의 알림. 버튼 낱말에 맞춘다(`drop_task`의 "내려놓음"과 다르다)."""
    return f"✗ 뺐어요: {title}"


# --- 체크인 시간 (SP9 8장, 10장 문구) ---

CHECKIN_LOOP_LABEL = {"morning_brief": "아침", "evening_checkin": "저녁"}
CHECKIN_DAY_LABEL = {"weekday": "평일", "weekend": "주말"}
CHECKIN_APPLIES_LABEL = {"today": "오늘부터", "tomorrow": "내일부터"}


def slot_label(loop: str, day_type: str) -> str:
    """`평일 아침` 같은 칸 이름(10장)."""
    return f"{CHECKIN_DAY_LABEL[day_type]} {CHECKIN_LOOP_LABEL[str(getattr(loop, 'value', loop))]}"


def confirm_checkin_summary(loop: str, day_type: str, before: time, after: time, applies: str) -> str:
    """두뇌 도구의 확인 문구(8장): `체크인 시간을 바꿔요: 평일 아침 09:00 → 09:30 (내일부터)`."""
    return (
        f"체크인 시간을 바꿔요: {slot_label(loop, day_type)} {before:%H:%M} → {after:%H:%M} "
        f"({CHECKIN_APPLIES_LABEL[applies]})"
    )


def checkin_set_line(loop: str, day_type: str, before: time, after: time, applies: str) -> str:
    """적용한 활동 한 줄: `✓ 체크인 시간 바꿈: 평일 아침 09:00 → 09:30 (내일부터)`."""
    return (
        f"✓ 체크인 시간 바꿈: {slot_label(loop, day_type)} {before:%H:%M} → {after:%H:%M} "
        f"({CHECKIN_APPLIES_LABEL[applies]})"
    )
