import { describe, expect, it } from "vitest";
import schema from "../api/schema.json";
import { LOOP_LABELS, SKIP_REASON_LABELS, checkinLabel, loopLabel, runStatusLabel, skipLabel } from "./labels";

const enumOf = (name: string): string[] => {
  const health = schema.models.Health as unknown as { $defs: Record<string, { enum?: string[] }> };
  return health.$defs[name]?.enum ?? [];
};

describe("labels", () => {
  it("skip reason labels", () => {
    expect(skipLabel("late")).toBe("건너뜀(한계 시각 지남)");
    expect(skipLabel("merged_into_return")).toBe("건너뜀(복귀 인사로 합침)");
    expect(skipLabel("paused")).toBe("건너뜀(/pause 중)");
    expect(skipLabel("daily_cap")).toBe("건너뜀(하루 두뇌 호출 상한)");
    expect(skipLabel("auth")).toBe("건너뜀(로그인·결제 문제)");
    expect(skipLabel("rate_limit")).toBe("건너뜀(사용 한도)");
    expect(skipLabel("added_later")).toBe("건너뜀");
    expect(skipLabel(null)).toBe("건너뜀");
    expect(Object.keys(SKIP_REASON_LABELS).sort()).toEqual(enumOf("SkipReason").sort());
  });

  it("run status labels", () => {
    expect(runStatusLabel({ status: "done", skip_reason: null })).toBe("보냄");
    expect(runStatusLabel({ status: "pending", skip_reason: null })).toBe("예정");
    expect(runStatusLabel({ status: "queued", skip_reason: null })).toBe("예정");
    expect(runStatusLabel({ status: "running", skip_reason: null })).toBe("보내는 중");
    expect(runStatusLabel({ status: "failed", skip_reason: null })).toBe("전송 안 됨");
    expect(runStatusLabel({ status: "interrupted", skip_reason: null })).toBe("전송 안 됨");
    expect(runStatusLabel({ status: "skipped", skip_reason: "late" })).toBe("건너뜀(한계 시각 지남)");
    expect(runStatusLabel({ status: "added_later", skip_reason: null })).toBe("—");
  });

  it("loop names are the push titles of appendix A", () => {
    expect(LOOP_LABELS).toEqual({ morning_brief: "아침 브리핑", evening_checkin: "저녁 체크인", review: "주간 회고", return: "다시 이어서" });
    expect(loopLabel("added_later")).toBe("알림");
  });

  it("check-in labels", () => {
    expect(checkinLabel("answered")).toBe("답함");
    expect(checkinLabel("pending")).toBe("답 기다림");
    expect(checkinLabel("missed")).toBe("지나감");
    expect(checkinLabel(null)).toBeNull();
  });
});
