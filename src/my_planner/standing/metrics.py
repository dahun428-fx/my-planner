"""측정값 지표 목록과 검사 (SP13 스펙 6.2). 저장소와 도구가 같은 `validate`를 쓴다."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import date
from typing import Literal

MetricKind = Literal["num", "enum", "multi"]


@dataclass(frozen=True)
class MetricDef:
    name: str
    label: str
    kind: MetricKind
    unit: str | None
    lo: float | None
    hi: float | None
    values: tuple[str, ...] = ()


def _num(name: str, label: str, unit: str | None, lo: float, hi: float) -> MetricDef:
    return MetricDef(name, label, "num", unit, lo, hi)


def _enum(name: str, label: str, *values: str) -> MetricDef:
    return MetricDef(name, label, "enum", None, None, None, values)


_DEFS: tuple[MetricDef, ...] = (
    _num("profile_birth_year", "출생 연도", None, 1930, 9999),  # 위쪽 끝은 검사 때 올해 - 15
    _enum("profile_sex", "성별", "m", "f"),
    _enum("profile_region", "권역", "capital", "other"),
    _enum("profile_job_family", "직군", "ai_ml", "dev_general", "other"),
    _num("height_cm", "키", "cm", 140, 220),
    _num("weight_kg", "몸무게", "kg", 35, 200),
    _num("body_fat_pct", "체지방률", "%", 3, 60),
    _num("fat_free_mass_kg", "제지방량", "kg", 25, 120),
    _num("skeletal_muscle_kg", "골격근량", "kg", 15, 70),
    _num("waist_cm", "허리둘레", "cm", 50, 150),
    _num("face_rating", "얼굴 평가(참고)", "점", 0, 100),
    _num("grooming_rating", "관리 평가", "점", 0, 100),
    _num("bp_sys", "수축기 혈압", "mmHg", 70, 250),
    _num("bp_dia", "이완기 혈압", "mmHg", 40, 150),
    _num("fasting_glucose", "공복 혈당", "mg/dL", 40, 400),
    _num("ldl", "LDL 콜레스테롤", "mg/dL", 20, 400),
    _num("alt", "ALT(간 수치)", "U/L", 1, 1000),
    _enum("checkup_flag", "건강검진 판정", "normal", "watch", "abnormal"),
    _num("shuttle_run_laps", "왕복오래달리기", "회", 0, 200),
    _num("grip_rel_pct", "상대 악력", "%", 10, 150),
    _num("situp_per_min", "윗몸일으키기(분당)", "회", 0, 100),
    _num("run_6k_min", "6km 달리기", "분", 15, 120),
    _num("squat_1rm_kg", "스쿼트 1RM", "kg", 0, 400),
    _num("bench_1rm_kg", "벤치프레스 1RM", "kg", 0, 400),
    _num("deadlift_1rm_kg", "데드리프트 1RM", "kg", 0, 400),
    _enum("smoking", "흡연", "none", "quit", "current"),
    _enum("drinking", "음주", "none", "monthly_binge", "high_risk"),
    _num("exercise_days_week", "주당 운동일", "일", 0, 7),
    _num("salary_krw", "연봉(세전)", "원", 1_000_000, 2_000_000_000),
    _num("company_tier", "회사 등급", "점", 0, 20),
    _num("role_points", "직무 점수", "점", 0, 15),
    _num("years_exp", "경력", "년", 0, 50),
    _num("level_points", "직급 점수", "점", 0, 6),
    _num("outside_activity_count", "사외 활동 수", "개", 0, 5),
    _num("recruiter_contacts_6m", "최근 6개월 채용 연락", "건", 0, 200),
    _num("offer_ratio", "오퍼 비율(최고 오퍼÷현재 연봉)", "배", 0.5, 5),
    _num("net_worth_krw", "순자산", "원", -5e9, 1e11),
    _num("monthly_saving_krw", "월 저축", "원", -1e8, 1e8),
    _num("monthly_net_income_krw", "월 실수령", "원", 0, 1e8),
    _num("savings_rate_pct", "저축률", "%", -100, 100),
    _num("support_people", "기댈 사람 수", "명", 0, 50),
    _num("monthly_meetups", "월 모임 횟수", "회", 0, 60),
    _enum("dating_status", "연애 상태", "single", "dating", "married"),
    _enum("lonely_often", "자주 외로움", "yes", "no"),
    MetricDef("cert", "자격", "multi", None, None, None),
    _enum("education_tier", "학벌", "hs", "college2", "local_private", "seoul_mid_low", "seoul_mid_high", "top"),
    _enum("double_major", "복수전공", "yes", "no"),
    _num("family_net_worth_krw", "집안 순자산", "원", -1e10, 1e12),
    _enum("family_support", "집안 지원", "none", "receive", "support"),
    _enum("family_parent_60plus", "부모 60세 이상", "yes", "no"),
)

METRICS: dict[str, MetricDef] = {d.name: d for d in _DEFS}

_BIRTH_YEAR_MIN_AGE = 15
_CERT_FIXED = frozenset({"jlpt_n1", "jlpt_n2", "engineer_info", "aice_associate", "pro_license"})
_TOEIC = re.compile(r"toeic:([0-9]{1,3})")
_OTHER = re.compile(r"other:[A-Za-z0-9_]{1,30}")


def _cert_ok(value: str) -> bool:
    if value in _CERT_FIXED:
        return True
    m = _TOEIC.fullmatch(value)
    if m:
        return 10 <= int(m.group(1)) <= 990
    return _OTHER.fullmatch(value) is not None


def validate(metric: str, value: float | str, measured_on: date, today: date) -> str | None:
    """오류 문구 또는 None. `today`는 논리적 날짜가 아니라 달력상 현지 날짜다(그날 결과지가 거절되지 않게)."""
    d = METRICS.get(metric)
    if d is None:
        return "모르는 측정값이에요."
    bad = f"{d.label} 값이 맞지 않아요."
    if d.kind == "num":
        if isinstance(value, bool) or not isinstance(value, int | float) or math.isnan(value):
            return bad
        hi = today.year - _BIRTH_YEAR_MIN_AGE if metric == "profile_birth_year" else d.hi
        if not (d.lo <= value <= hi):  # type: ignore[operator]
            return bad
    elif d.kind == "enum":
        if not isinstance(value, str) or value not in d.values:
            return bad
    elif not isinstance(value, str) or not _cert_ok(value):
        return bad
    if measured_on > today:
        return "측정일이 오늘보다 늦어요."
    return None


# SP14 스펙 5.3: 운동메이트도 받는 건강·외모 지표(측정값 저장 사건의 영역 `health`)
HEALTH_LOOKS_METRICS: frozenset[str] = frozenset({
    "weight_kg", "body_fat_pct", "fat_free_mass_kg", "skeletal_muscle_kg", "waist_cm", "face_rating",
    "grooming_rating", "bp_sys", "bp_dia", "fasting_glucose", "ldl", "alt", "checkup_flag", "shuttle_run_laps",
    "grip_rel_pct", "situp_per_min", "run_6k_min", "squat_1rm_kg", "bench_1rm_kg", "deadlift_1rm_kg", "smoking",
    "drinking", "exercise_days_week",
})
_AREA_BY_METRIC: dict[str, str] = {
    **dict.fromkeys(HEALTH_LOOKS_METRICS, "health"),
    **dict.fromkeys(
        ("salary_krw", "company_tier", "role_points", "years_exp", "level_points", "outside_activity_count",
         "recruiter_contacts_6m", "offer_ratio"), "career"),
    **dict.fromkeys(("net_worth_krw", "monthly_saving_krw", "monthly_net_income_krw", "savings_rate_pct"), "finance"),
    **dict.fromkeys(("support_people", "monthly_meetups", "dating_status", "lonely_often"), "relationships"),
    "cert": "learning",
}


def metric_area(metric: str) -> str | None:
    """측정값 지표의 영역(사건 기록용). 프로필·키·학벌·복수전공·집안은 `None`."""
    return _AREA_BY_METRIC.get(metric)
