// Screen words of the dashboard (spec 13.1, 13.2, appendix A). Kept here so one test can read them all.
import type { HealthRun, SkipReason } from "../api/types.gen";

// Appendix A push titles; an unknown loop reads as the notice title.
export const LOOP_LABELS: Record<HealthRun["loop"], string> = {
  morning_brief: "아침 브리핑",
  evening_checkin: "저녁 체크인",
  review: "주간 회고",
  return: "다시 이어서",
};

export function loopLabel(loop: string): string {
  return (LOOP_LABELS as Record<string, string>)[loop] ?? "알림";
}

// Gap 10: short forms of docs/acceptance/sp1-checklist.md's meanings.
export const SKIP_REASON_LABELS: Record<SkipReason, string> = {
  late: "한계 시각 지남",
  merged_into_return: "복귀 인사로 합침",
  paused: "/pause 중",
  daily_cap: "하루 두뇌 호출 상한",
  auth: "로그인·결제 문제",
  rate_limit: "사용 한도",
};

export function skipLabel(reason: string | null): string {
  const shown = reason === null ? undefined : (SKIP_REASON_LABELS as Record<string, string>)[reason];
  return shown ? `건너뜀(${shown})` : "건너뜀";
}

// `interrupted` (the BE stopped while sending, SP1 5.1) was not sent either.
const STATUS_LABELS: Record<string, string> = {
  done: "보냄",
  pending: "예정",
  queued: "예정",
  running: "보내는 중",
  failed: "전송 안 됨",
  interrupted: "전송 안 됨",
};

export function runStatusLabel(run: Pick<HealthRun, "status" | "skip_reason">): string {
  if (run.status === "skipped") return skipLabel(run.skip_reason);
  return STATUS_LABELS[run.status] ?? "—";
}

const CHECKIN_LABELS: Record<string, string> = { answered: "답함", pending: "답 기다림", missed: "지나감" };

export function checkinLabel(state: string | null): string | null {
  return state === null ? null : (CHECKIN_LABELS[state] ?? null);
}

export const CHANNEL_LABELS: Record<string, string> = { app: "앱", telegram: "텔레그램" };
export const channelLabel = (c: string) => CHANNEL_LABELS[c] ?? c;

export const POLLING_LABELS: Record<string, string> = { running: "연결됨", down: "끊김", stopped: "멈춤" };
export const AUTH_LABELS: Record<string, string> = {
  ok: "정상",
  login: "다시 로그인 필요",
  billing: "결제 확인 필요",
  unknown: "확인 전",
};

// Common states (spec 13.1 table, verbatim).
export const STATE_TEXT = {
  offline: "BE가 켜지면 다시 보여 드릴게요.",
  unauthorized: "토큰이 맞지 않아요. 설정에서 다시 넣어 주세요.",
  rate_limited: "잠시 뒤에 다시 시도해 주세요.",
  safe_mode: "데이터베이스 점검이 필요해요. PC에서 README의 복구 절차를 따라 주세요.",
  broken: (code: string) => `BE가 응답했지만 이 화면을 그리지 못했어요 (${code}).`,
} as const;

export const BAND_TEXT = {
  on: (hhmmss: string) => `BE 켜짐 · ${hhmmss} 응답`,
  onNoTime: "BE 켜짐",
  off: (when: string | null) => `BE 꺼짐 · 마지막 응답 ${when ?? "기록 없음"}`,
  checking: "연결 확인 중",
  check: "연결 확인",
} as const;

export const HEALTH_TEXT = {
  title: "비서 상태",
  version: (app: string, api: string, schema: number | null) => `my-planner ${app} · API ${api} · 스키마 ${schema ?? "—"}`,
  lastTick: (hhmm: string | null) => `마지막 tick ${hhmm ?? "—"}`,
  polling: "텔레그램 폴링",
  login: "Claude 로그인",
  noLimit: "사용 한도 없음",
  limitedUntil: (hhmm: string) => `사용 한도 ${hhmm}까지`,
  noPause: "멈춤 없음",
  pausedUntil: (when: string) => `${when}까지 멈춤`,
  primary: (primary: string, effective: string) => `주 통로 ${primary} (지금 ${effective})`,
  push: (n: number) => `푸시 구독 ${n}`,
  runsHeading: "오늘 회차",
  noRuns: "오늘 예정된 회차가 아직 없어요.",
  brainCalls: "두뇌 호출",
  proactive: "먼저 보낸 메시지",
  noWarnings: "최근 24시간 경고 없음",
  warnings: (total: number, parts: string) => `최근 24시간 경고·오류 ${total}${parts ? ` (${parts})` : ""}`,
} as const;

export const SETTINGS_TEXT = {
  title: "설정",
  intro: "BE 주소와 API 토큰은 이 브라우저에만 저장해요.",
  url: "BE 주소",
  urlHint: "https://노트북.tailnet.ts.net/api/v1",
  token: "API 토큰",
  check: "연결 확인",
  checking: "확인 중",
  ok: "연결했어요.",
  saved: "저장했어요.",
  home: "비서 상태 보기",
  urlErrors: {
    not_https: "https 주소만 넣을 수 있어요.",
    out_of_range: "이 대시보드가 허용한 tailnet 주소가 아니에요.",
    invalid: "주소 형식이 맞지 않아요.",
  },
  tokenMissing: "토큰을 넣어 주세요.",
  tokenInvalid: "토큰에는 영문, 숫자, 기호만 들어가요.",
} as const;

export const NAV_TEXT = { brand: "my-planner", status: "비서 상태", settings: "설정", label: "화면" } as const;
