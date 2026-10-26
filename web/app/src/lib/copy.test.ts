import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { describe, expect, it } from "vitest";
import { copy, habitMeta, momentDay } from "./copy";

const repoRoot = join(__dirname, "../../../..");
const srcRoot = join(__dirname, "..");
const APP_BANNED = ["연속", "스트릭", "달성률", "보너스가 줄", "스탯이 떨어"];

function readBannedList(): string[] {
  const md = readFileSync(join(repoRoot, "src/my_planner/harness/prompts/system.md"), "utf8");
  const block = md.match(/<!-- banned-words:start -->([\s\S]*?)<!-- banned-words:end -->/);
  if (!block) return [];
  return [...block[1].matchAll(/"([^"]+)"/g)].map((m) => m[1]);
}
const banned = [...readBannedList(), ...APP_BANNED];

it("APP_BANNED holds the SP8 phrases", () => {
  expect(APP_BANNED).toEqual(expect.arrayContaining(["보너스가 줄", "스탯이 떨어"]));
});

// Every copy value as text; template functions are called with sample arguments.
function texts(value: unknown): string[] {
  if (typeof value === "string") return [value];
  if (typeof value === "function") {
    const fn = value as (...args: unknown[]) => unknown;
    const args = (sample: unknown) => Array.from({ length: Math.max(fn.length, 1) }, () => sample);
    return [...texts(fn(...args("00:00"))), ...texts(fn(...args(3)))];
  }
  if (value && typeof value === "object") return Object.values(value).flatMap(texts);
  return [];
}

function sourceFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return name === "test" ? [] : sourceFiles(path);
    return /\.(ts|tsx)$/.test(name) && !/\.test\./.test(name) ? [path] : [];
  });
}

describe("copy", () => {
  it("banned list is read", () => {
    expect(readBannedList()).toContain("놓쳤어요");
  });

  it("no banned words", () => {
    const values = texts(copy);
    expect(values.length).toBeGreaterThan(20);
    const inCopy = values.filter((t) => banned.some((w) => t.includes(w)));
    expect(inCopy).toEqual([]);
    const inSource = sourceFiles(srcRoot).flatMap((file) => {
      const body = readFileSync(file, "utf8");
      return banned.filter((w) => body.includes(w)).map((w) => `${relative(srcRoot, file)}: ${w}`);
    });
    expect(inSource).toEqual([]);
  });

  it("banned list has the SP7 words", () => {
    // SP7 7장: SP7-05 added these to the system.md block the app reads.
    const list = readBannedList();
    for (const w of ["끊겼", "며칠째", "남음"]) expect(list).toContain(w);
    for (const w of ["밀렸다", "놓쳤다", "실패"]) expect(list).toContain(w);
  });

  it("chat card copy is SP6 appendix A verbatim", () => {
    const p = copy.parts;
    expect([p.thisWeek, p.nextWeek, p.lastWeek]).toEqual(["이번 주", "다음 주", "지난주"]);
    expect(p.weekRange("10월 26일", "11월 1일")).toBe("10월 26일 ~ 11월 1일");
    expect(p.dayHead(26, "월")).toBe("26일 월");
    expect(p.dayHeadToday).toBe(" · 오늘");
    expect(p.otherDay).toBe("다른 날로 할게요");
    expect(p.alreadySettled).toBe("이미 정리된 할 일이에요");
    expect(p.noDate).toBe("날짜 없음");
    expect(Object.values(p.changeChip)).toEqual(["추가", "옮김", "완료", "다시 엶", "뺌", "고침", "확정"]);
    expect(p.prevTitle("치과")).toBe("이전 제목: 치과");
    expect(p.editedOnly).toBe("내용을 고쳤어요");
    expect(p.confirmedDraft).toBe("초안을 확정했어요");
    expect(p.changeAria("10월 25일 (일)", "10월 27일 (화)")).toBe("이전 10월 25일 (일), 지금 10월 27일 (화)");
    expect(p.resultCount(2)).toBe("바뀐 할 일 2개");
    expect(p.outsideHead).toEqual({ moved: "기간 밖으로 옮긴 것", dropped: "뺀 것", noDate: "날짜 없는 것" });
    expect(p.openTodos).toBe("할 일 화면에서 보기");
    expect(p.openActivity).toBe("기록에서 보기");
    expect(p.periodFailed).toBe("할 일을 불러오지 못했어요");
  });

  it("moments copy is SP8 appendix A verbatim", () => {
    const c = copy.statusScreen;
    expect([c.momentsHeading, c.hiddenGroup(2), c.older]).toEqual(["이룬 순간", "숨긴 순간 2개", "지난 순간 더 보기"]);
    expect([c.hide, c.delete, c.unhide, c.more, c.hidden, c.unhidden]).toEqual(["숨기기", "지우기", "다시 보이기", "더 보기", "숨겼어요", "다시 보여요"]);
    expect([c.deleteAsk, c.deleteGo, c.deleteKeep]).toEqual(["이 순간을 지울까요? 되돌릴 수 없어요.", "지우기", "그대로 두기"]);
    expect(c.momentsEmpty).toBe("하루가 끝나면 비서가 그날 해낸 일을 몇 줄로 남겨 둬요.");
    expect(momentDay("2026-10-24")).toBe("10월 24일 (토)");
  });

  it("habit copy is appendix A verbatim", () => {
    expect(copy.habits.heading).toBe("습관");
    expect(copy.habits.manage).toBe("관리");
    expect(copy.habits.todayLine).toBe("오늘 습관");
    expect(copy.habits.addRow).toBe("습관 추가하기");
    expect(copy.habits.empty).toBe("챙기고 싶은 습관을 더해 보세요. 매일 하는 것도, 주 몇 번 하는 것도 돼요.");
    expect(copy.habits.weekOfTarget(2, 3)).toBe("이번 주 2번 · 목표 3번");
    expect(copy.habits.weekMet).toBe("이번 주 목표만큼 했어요");
    expect(copy.habits.week(4)).toBe("이번 주 4번");
    expect(copy.habits.lastWeek(3)).toBe("지난주 3번");
    expect(copy.habits.weekOf(10, 5, 1)).toBe("10월 5일 주 1번");
  });

  it("habit screen copy is spec 6.2 verbatim", () => {
    // SP9 9.1 moved the habits screen under more: "‹ 더보기".
    expect(copy.habits.back).toBe("‹ 더보기");
    expect(copy.checkin.back).toBe("‹ 오늘");
    expect(copy.habits.active).toBe("챙기는 습관");
    expect(copy.habits.paused).toBe("쉬는 습관");
    expect(copy.habits.archived).toBe("그만둔 습관");
    expect(copy.habits.resume).toBe("다시 시작");
    expect(copy.habits.edit).toBe("고치기");
    expect(copy.habits.pause).toBe("쉬어 가기");
    expect(copy.habits.archive).toBe("그만두기");
    expect(copy.habits.daily).toBe("매일");
    expect(copy.habits.weekly).toBe("주 N회");
    expect(copy.habits.weeklyN(3)).toBe("주 3회");
    expect(copy.habits.addSubmit).toBe("추가");
    expect(copy.habits.save).toBe("저장");
  });

  it("habit copy has no banned word, ratio or what is left", () => {
    const values = texts(copy.habits);
    expect(values.length).toBeGreaterThan(5);
    for (const t of values) {
      expect(banned.filter((w) => t.includes(w))).toEqual([]);
      expect(t).not.toMatch(/%|남음|남은|\d+\s*\/\s*\d+/);
    }
  });

  it("habitMeta picks the line by kind and count", () => {
    expect(habitMeta({ kind: "daily", target_per_week: null, week_count: 4 })).toBe("이번 주 4번");
    expect(habitMeta({ kind: "daily", target_per_week: null, week_count: 0 })).toBe("이번 주 0번");
    expect(habitMeta({ kind: "weekly", target_per_week: 3, week_count: 2 })).toBe("이번 주 2번 · 목표 3번");
    expect(habitMeta({ kind: "weekly", target_per_week: 3, week_count: 3 })).toBe("이번 주 목표만큼 했어요");
    // Over the target is still "met", never a count above it.
    expect(habitMeta({ kind: "weekly", target_per_week: 2, week_count: 5 })).toBe("이번 주 목표만큼 했어요");
  });

  it("more copy is SP9 10장 verbatim", () => {
    const m = copy.more;
    expect([m.title, m.settings, m.activity, m.habits, m.status, m.connect].join(" · ")).toBe("더보기 · 설정 · 기록 · 습관 · 상태창 · 기기 연결");
    expect(m.back).toBe("‹ 더보기");
    expect(copy.habits.back).toBe(m.back);
    expect(copy.connect.back).toBe(m.back);
    for (const t of texts(m)) expect(banned.filter((w) => t.includes(w))).toEqual([]);
  });

  it("checkin times copy is SP9 10장 verbatim", () => {
    const c = copy.checkinTimes;
    expect([c.heading, c.weekdayMorning, c.weekdayEvening, c.weekendMorning, c.weekendEvening, c.fromToday, c.fromTomorrow, c.wakeStale].join(" · ")).toBe(
      "체크인 시간 · 평일 아침 · 평일 저녁 · 주말 아침 · 주말 저녁 · 오늘부터 적용돼요 · 내일부터 적용돼요 · 노트북을 깨우는 시각은 아직 그대로예요. register_task.ps1을 다시 실행해 주세요.",
    );
    expect(c.reviewNote).toBe("주말 저녁은 일요일 주간 회고 시각이기도 해요."); // 9.7
    for (const t of texts(c)) expect(banned.filter((w) => t.includes(w))).toEqual([]);
  });

  it("digest copy is SP9b 7장 verbatim", () => {
    const d = copy.digests;
    expect([d.heading, d.morning, d.night, d.note].join(" · ")).toBe("일정 정리 알림 · 아침에 오늘 일정 · 밤에 내일 일정 · 일정이 있는 날만 보내요.");
    expect([d.fromToday, d.fromTomorrow]).toEqual([copy.checkinTimes.fromToday, copy.checkinTimes.fromTomorrow]); // 5장: 체크인 시간과 같은 토스트
    expect(d.wakeStale).toBe(copy.checkinTimes.wakeStale);
    for (const t of texts(d)) expect(banned.filter((w) => t.includes(w))).toEqual([]);
  });

  it("SP9 9.6 chat activity copy", () => {
    expect(copy.chat.changedMany(3)).toBe("✓ 3개를 바꿨어요"); // taste-skill-ignore: BE confirmation prefix (R4b), not UI
    expect(copy.chat.undonePartly(1)).toBe("1개만 되돌렸어요");
    const values = [copy.chat.changed, copy.chat.undone, ...texts(copy.chat.changedMany), ...texts(copy.chat.undonePartly)];
    expect(values.length).toBeGreaterThan(3);
    for (const t of values) expect(banned.filter((w) => t.includes(w))).toEqual([]);
  });

  it("conversation list and quick chip copy is SP9 10장 verbatim (9.5 sentences)", () => {
    const c = copy.chat;
    expect([c.pastConversations, c.newConversation, c.deleteAsk].join(" · ")).toBe("지난 대화 · 새 대화 · 이 대화를 지울까요? 되돌릴 수 없어요.");
    const chips = [c.chips.todo, c.chips.event, c.chips.memo, c.chips.today, c.chips.checkin, c.chips.review, c.chips.next];
    expect(chips.map((x) => x.label).join(" · ")).toBe("할 일 추가 · 일정 추가 · 메모하기 · 오늘 정리해줘 · 체크인 하기 · 이번 주 돌아보기 · 다음 일정 보기");
    expect(chips.map((x) => x.text)).toEqual(["할 일 추가할래요", "일정 하나 추가할래요", "메모 하나 남길래요", "오늘 정리해줘", "체크인 할게요", "이번 주 돌아볼래요", "다음 일정 알려줘"]);
    expect([c.groups.today, c.groups.yesterday, c.groups.thisWeek, c.groups.month(10)]).toEqual(["오늘", "어제", "이번 주", "10월"]);
    expect(c.checkinTag).toBe("체크인");
    const values = [
      c.pastConversations, c.deleteAsk, c.delete, c.keep, c.backToChat, c.untitled, c.search, c.noConversations, c.noMatch, c.moreConversations,
      c.chipsLabel, ...texts(c.groups), ...texts(c.chips),
    ];
    for (const t of values) expect(banned.filter((w) => t.includes(w))).toEqual([]);
  });

  it("areas are glossary names", () => {
    expect(Object.values(copy.areas)).toEqual(["커리어", "경제", "건강", "관계", "배움", "삶의 질"]);
  });

  it("loops use appendix A names", () => {
    expect(copy.loops).toEqual({
      morning_brief: "아침 브리핑",
      evening_checkin: "저녁 체크인",
      review: "주간 회고",
      return: "다시 이어서",
    });
  });

  it("templates fill values", () => {
    expect(copy.errors.block("shape")).toBe("이 부분을 불러오지 못했어요 (shape)");
    expect(copy.status.limited("21:30")).toBe("비서가 21:30까지 답을 쉬어요");
  });
});
