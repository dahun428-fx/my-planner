import "fake-indexeddb/auto";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { clear } from "idb-keyval";
import { http, HttpResponse } from "msw";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { EventDetail } from "../api/types.gen";
import { copy } from "../lib/copy";
import { ev } from "../test/events";
import { renderWithProviders } from "../test/render";
import { BASE, server } from "../test/server";
import { EventDetailSheet, EventFormSheet } from "./EventSheet";

afterEach(async () => {
  await clear();
});

const S = copy.schedule;

function actions() {
  const bodies: Record<string, unknown>[] = [];
  server.use(
    http.post(`${BASE}/actions`, async ({ request }) => {
      bodies.push((await request.json()) as Record<string, unknown>);
      return HttpResponse.json({ status: "applied", activity_id: 81, undo_id: 81, result: {}, confirmation: "✓ 일정 추가: 치과 (10/27 14:00)" });
    }),
  );
  return bodies;
}

const detailOf = (over: Partial<EventDetail> = {}): EventDetail => ({
  id: 3,
  title: "팀 회의",
  date: "2026-10-20",
  time: "09:30",
  all_day: false,
  duration_min: null,
  repeat: "weekly",
  weekdays: ["tue"],
  repeat_until: null,
  remind_min: 30,
  area: "career",
  note: "회의실 3층",
  origin: "user",
  skipped_dates: [],
  created_at: "2026-10-20T00:00:00Z",
  updated_at: "2026-10-20T00:00:00Z",
  ...over,
});

function serveDetail(d: EventDetail) {
  server.use(http.get(`${BASE}/events/${d.id}`, () => HttpResponse.json(d)));
}

const remindGroup = () => screen.getByRole("group", { name: S.remindLabel });
const pressed = (name: string) => within(remindGroup()).getByRole("button", { name });

describe("EventFormSheet (spec 9.2 add sheet)", () => {
  it("the reminder is 10분 전 unless picked; the six choices in 10장 order", async () => {
    renderWithProviders(<EventFormSheet open event={null} date="2026-10-27" onClose={() => {}} onSaved={() => {}} />);
    const labels = within(remindGroup()).getAllByRole("button").map((b) => b.textContent);
    expect(labels).toEqual(["정시", "10분 전", "30분 전", "1시간 전", "하루 전", "알림 없음"]);
    expect(pressed(S.remind[10])).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByLabelText(S.dateLabel)).toHaveValue("2026-10-27");
  });

  it("all-day hides 10·30·60 and its default is 정시; back to a time, 10분 전 again", async () => {
    const user = userEvent.setup();
    renderWithProviders(<EventFormSheet open event={null} date="2026-10-27" onClose={() => {}} onSaved={() => {}} />);
    await user.click(screen.getByRole("switch", { name: S.allDay }));
    expect(within(remindGroup()).getAllByRole("button").map((b) => b.textContent)).toEqual(["정시", "하루 전", "알림 없음"]);
    expect(pressed(S.remind[0])).toHaveAttribute("aria-pressed", "true");
    expect(screen.queryByLabelText(S.timeLabel)).not.toBeInTheDocument();
    await user.click(screen.getByRole("switch", { name: S.allDay }));
    expect(pressed(S.remind[10])).toHaveAttribute("aria-pressed", "true");
  });

  it("a picked 30분 전 turns to 정시 when all-day goes on; a picked 하루 전 stays", async () => {
    const user = userEvent.setup();
    renderWithProviders(<EventFormSheet open event={null} date="2026-10-27" onClose={() => {}} onSaved={() => {}} />);
    await user.click(pressed(S.remind[30]));
    await user.click(screen.getByRole("switch", { name: S.allDay }));
    expect(pressed(S.remind[0])).toHaveAttribute("aria-pressed", "true");
    await user.click(pressed(S.remind[1440]));
    await user.click(screen.getByRole("switch", { name: S.allDay }));
    await user.click(screen.getByRole("switch", { name: S.allDay }));
    expect(pressed(S.remind[1440])).toHaveAttribute("aria-pressed", "true");
  });

  it("adds: create_event with the 5.6 fields, then closes and tells the screen", async () => {
    const bodies = actions();
    const onClose = vi.fn();
    const onSaved = vi.fn();
    const user = userEvent.setup();
    renderWithProviders(<EventFormSheet open event={null} date="2026-10-27" onClose={onClose} onSaved={onSaved} />);
    const add = screen.getByRole("button", { name: S.addSubmit });
    expect(add).toBeDisabled(); // no title yet
    await user.type(screen.getByLabelText(S.titleLabel), "  치과 ");
    await user.clear(screen.getByLabelText(S.timeLabel));
    await user.type(screen.getByLabelText(S.timeLabel), "14:00");
    await user.click(pressed(S.remind[30]));
    await user.click(within(screen.getByRole("group", { name: S.areaLabel })).getByRole("button", { name: copy.areas.health }));
    await user.click(add);
    await waitFor(() => expect(bodies).toHaveLength(1));
    expect(bodies[0]).toMatchObject({
      action: "create_event",
      args: { title: "치과", date: "2026-10-27", all_day: false, time: "14:00", repeat: "none", weekdays: null, remind_min: 30, area: "health", note: "" },
    });
    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(onSaved).toHaveBeenCalled();
  });

  it("매주 shows seven weekday toggles with the day's own on; the chosen days go in Monday order", async () => {
    const bodies = actions();
    const user = userEvent.setup();
    renderWithProviders(<EventFormSheet open event={null} date="2026-10-27" onClose={() => {}} onSaved={() => {}} />);
    expect(screen.queryByRole("group", { name: S.weekdaysLabel })).not.toBeInTheDocument();
    await user.click(screen.getByRole("radio", { name: S.repeat.weekly }));
    const days = within(screen.getByRole("group", { name: S.weekdaysLabel })).getAllByRole("button");
    expect(days.map((b) => b.textContent)).toEqual(["월", "화", "수", "목", "금", "토", "일"]);
    expect(days[1]).toHaveAttribute("aria-pressed", "true"); // 10/27 is a Tuesday
    await user.click(days[4]);
    await user.click(days[0]);
    await user.type(screen.getByLabelText(S.titleLabel), "팀 회의");
    await user.click(screen.getByRole("button", { name: S.addSubmit }));
    await waitFor(() => expect(bodies).toHaveLength(1));
    expect(bodies[0]).toMatchObject({ args: { repeat: "weekly", weekdays: ["mon", "tue", "fri"] } });
  });

  it("매주 with no day on cannot be added", async () => {
    const user = userEvent.setup();
    renderWithProviders(<EventFormSheet open event={null} date="2026-10-27" onClose={() => {}} onSaved={() => {}} />);
    await user.type(screen.getByLabelText(S.titleLabel), "팀 회의");
    await user.click(screen.getByRole("radio", { name: S.repeat.weekly }));
    await user.click(within(screen.getByRole("group", { name: S.weekdaysLabel })).getByRole("button", { name: "화" }));
    expect(screen.getByRole("button", { name: S.addSubmit })).toBeDisabled();
  });

  it("editing fills the fields from the definition and saves with update_event", async () => {
    const bodies = actions();
    const user = userEvent.setup();
    renderWithProviders(<EventFormSheet open event={detailOf()} date="2026-10-27" onClose={() => {}} onSaved={() => {}} />);
    expect(screen.getByRole("dialog", { name: S.editTitle })).toBeInTheDocument();
    expect(screen.getByLabelText(S.titleLabel)).toHaveValue("팀 회의");
    expect(screen.getByLabelText(S.dateLabel)).toHaveValue("2026-10-20");
    expect(pressed(S.remind[30])).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByLabelText(S.noteLabel)).toHaveValue("회의실 3층");
    await user.click(screen.getByRole("button", { name: S.save }));
    await waitFor(() => expect(bodies).toHaveLength(1));
    expect(bodies[0]).toMatchObject({ action: "update_event", args: { id: 3, title: "팀 회의", time: "09:30", repeat: "weekly", weekdays: ["tue"], remind_min: 30, area: "career" } });
  });

  it("a refused reminder shows the BE's sentence and keeps the sheet open", async () => {
    server.use(
      http.post(`${BASE}/actions`, () =>
        HttpResponse.json(
          { status: "rejected", activity_id: null, error: { code: "remind_invalid", message: "하루 종일 일정의 알림은 정시(0, 그날 09:00)나 하루 전(1440)만 고를 수 있어요." } },
          { status: 422 },
        ),
      ),
    );
    const onClose = vi.fn();
    const user = userEvent.setup();
    renderWithProviders(<EventFormSheet open event={null} date="2026-10-27" onClose={onClose} onSaved={() => {}} />);
    await user.type(screen.getByLabelText(S.titleLabel), "치과");
    await user.click(screen.getByRole("button", { name: S.addSubmit }));
    expect(await screen.findByText(/하루 종일 일정의 알림은/)).toBeInTheDocument();
    expect(onClose).not.toHaveBeenCalled();
  });
});

describe("EventDetailSheet (spec 9.2 detail sheet)", () => {
  const meeting = ev(3, "2026-10-27", "09:30", { title: "팀 회의", repeat: "weekly", remind_min: 30, area: "career" });
  const dentist = ev(1, "2026-10-27", "14:00", { title: "치과" });

  it("a repeating event: 고치기 and the three buttons; the definition's 때 and reminder", async () => {
    serveDetail(detailOf());
    renderWithProviders(<EventDetailSheet item={meeting} writable onClose={() => {}} onEdit={() => {}} onChanged={() => {}} />);
    const sheet = screen.getByRole("dialog", { name: "팀 회의" });
    expect(await within(sheet).findByText("매주 화 09:30")).toBeInTheDocument();
    expect(within(sheet).getByText(/알림 30분 전/)).toBeInTheDocument();
    expect(within(sheet).getByText("회의실 3층")).toBeInTheDocument();
    const names = within(sheet).getAllByRole("button").map((b) => b.textContent);
    expect(names).toEqual([S.edit, S.skipOne, S.endFollowing, S.deleteAll]);
  });

  it("이번만 건너뛰기 asks first; the change sends delete_event one with that day", async () => {
    serveDetail(detailOf());
    const bodies = actions();
    const onChanged = vi.fn();
    const onClose = vi.fn();
    const user = userEvent.setup();
    renderWithProviders(<EventDetailSheet item={meeting} writable onClose={onClose} onEdit={() => {}} onChanged={onChanged} />);
    await user.click(screen.getByRole("button", { name: S.skipOne }));
    expect(await screen.findByText(S.askOne("팀 회의", "10/27"))).toBeInTheDocument();
    expect(bodies).toHaveLength(0);
    await user.click(screen.getByRole("button", { name: S.skipOne }));
    await waitFor(() => expect(bodies).toHaveLength(1));
    expect(bodies[0]).toMatchObject({ action: "delete_event", args: { id: 3, scope: "one", date: "2026-10-27" } });
    await waitFor(() => expect(onChanged).toHaveBeenCalled());
    expect(onClose).toHaveBeenCalled();
  });

  it("이후 반복 끝내기 and 모두 지우기 ask with the 10장 sentences; 그대로 두기 sends nothing", async () => {
    serveDetail(detailOf());
    const bodies = actions();
    const user = userEvent.setup();
    renderWithProviders(<EventDetailSheet item={meeting} writable onClose={() => {}} onEdit={() => {}} onChanged={() => {}} />);
    await user.click(screen.getByRole("button", { name: S.endFollowing }));
    expect(await screen.findByText(S.askFollowing("팀 회의", "10/27"))).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: S.keep }));
    await user.click(await screen.findByRole("button", { name: S.deleteAll }));
    expect(await screen.findByText(S.askAll("팀 회의"))).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: S.deleteAll }));
    await waitFor(() => expect(bodies).toHaveLength(1));
    expect(bodies[0]).toMatchObject({ action: "delete_event", args: { id: 3, scope: "all" } });
    expect((bodies[0].args as Record<string, unknown>).date).toBeUndefined();
  });

  it("a one-off event: 고치기 and 지우기 only", async () => {
    serveDetail(detailOf({ id: 1, title: "치과", repeat: "none", weekdays: null, date: "2026-10-27", time: "14:00", remind_min: 10, note: "" }));
    const user = userEvent.setup();
    renderWithProviders(<EventDetailSheet item={dentist} writable onClose={() => {}} onEdit={() => {}} onChanged={() => {}} />);
    const sheet = screen.getByRole("dialog", { name: "치과" });
    expect(await within(sheet).findByText("10/27 14:00")).toBeInTheDocument();
    expect(within(sheet).getAllByRole("button").map((b) => b.textContent)).toEqual([S.edit, S.delete]);
    await user.click(within(sheet).getByRole("button", { name: S.delete }));
    expect(await screen.findByText(S.askAll("치과"))).toBeInTheDocument();
  });

  it("고치기 hands the definition to the form", async () => {
    const d = detailOf();
    serveDetail(d);
    const onEdit = vi.fn();
    const user = userEvent.setup();
    renderWithProviders(<EventDetailSheet item={meeting} writable onClose={() => {}} onEdit={onEdit} onChanged={() => {}} />);
    await waitFor(() => expect(screen.getByRole("button", { name: S.edit })).toBeEnabled());
    await user.click(screen.getByRole("button", { name: S.edit }));
    expect(onEdit).toHaveBeenCalledWith(d);
  });

  it("read-only (offline): every button is off", async () => {
    serveDetail(detailOf());
    renderWithProviders(<EventDetailSheet item={meeting} writable={false} onClose={() => {}} onEdit={() => {}} onChanged={() => {}} />);
    await screen.findByText("매주 화 09:30");
    for (const b of within(screen.getByRole("dialog", { name: "팀 회의" })).getAllByRole("button")) expect(b).toBeDisabled();
  });
});
