import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";
import type { Habit } from "../../api/types.gen";
import { copy } from "../../lib/copy";
import { useToast } from "../../components/Toast";
import { makeCtx, makeHabit, serveActions } from "../../test/parts";
import { renderWithProviders } from "../../test/render";
import { BASE, server } from "../../test/server";
import { HabitCheck, HabitList } from "./HabitList";

const DATE = "2026-10-24";

const daily = makeHabit(1, "물 마시기", { week_count: 4 });
const weekly = makeHabit(2, "운동", { kind: "weekly", target_per_week: 3, week_count: 2 });
const met = makeHabit(3, "독서", { kind: "weekly", target_per_week: 3, week_count: 3, checked: true });

// The BE's answer to check_habit / uncheck_habit: {habit, date, already} (SP7 5.4).
function answerWith(habit: (body: Record<string, unknown>) => Habit) {
  return (body: Record<string, unknown>) =>
    HttpResponse.json({
      status: "applied",
      activity_id: 910,
      undo_id: 910,
      result: { habit: habit(body), date: DATE, already: false },
      confirmation: "✓ 습관: 운동", // taste-skill-ignore: BE confirmation (appendix A), not UI
    });
}

const box = (title: string) => screen.getByRole("checkbox", { name: copy.parts.checkLabel(title) });

const list = (items: Habit[]) => ({ date: DATE, week: "2026-W43", items });

function serveUndo() {
  const undos: string[] = [];
  server.use(
    http.post(`${BASE}/activity/:id/undo`, ({ params }) => {
      undos.push(String(params.id));
      return HttpResponse.json({ status: "undone", confirmation: "↩ 되돌림" });
    }),
  );
  return undos;
}

/** GET /habits; returns the query string of every read. */
function serveHabits(answer: () => Response) {
  const reads: string[] = [];
  server.use(
    http.get(`${BASE}/habits`, ({ request }) => {
      reads.push(new URL(request.url).searchParams.toString());
      return answer();
    }),
  );
  return reads;
}

// Another write in the same app (a to-do in the same chat): its toast replaces the habit's.
function OtherWrite() {
  const toast = useToast();
  return (
    <button type="button" onClick={() => toast.show({ text: "✓ 다른 일", undoId: 777 })}>
      other
    </button>
  );
}

describe("HabitList", () => {
  it("renders_meta_copy_for_daily_weekly_met", () => {
    renderWithProviders(<HabitList habits={[daily, weekly, met]} date={DATE} readOnly={false} onChanged={vi.fn()} />);
    expect(screen.getByText("이번 주 4번")).toBeInTheDocument();
    expect(screen.getByText("이번 주 2번 · 목표 3번")).toBeInTheDocument();
    expect(screen.getByText("이번 주 목표만큼 했어요")).toBeInTheDocument();
    expect(box("물 마시기")).not.toBeChecked();
    expect(box("독서")).toBeChecked();
  });

  it("press_calls_check_then_uncheck", async () => {
    const bodies = serveActions(
      answerWith((b) => ({ ...weekly, checked: b.action === "check_habit", week_count: b.action === "check_habit" ? 3 : 2 })),
    );
    const onChanged = vi.fn();
    renderWithProviders(<HabitList habits={[weekly]} date={DATE} readOnly={false} onChanged={onChanged} />);
    await userEvent.click(box("운동"));
    await waitFor(() => expect(bodies).toHaveLength(1));
    expect(bodies[0]).toMatchObject({ action: "check_habit", args: { id: 2, date: DATE } });
    await waitFor(() => expect(box("운동")).toBeChecked());
    expect(screen.getByText("이번 주 목표만큼 했어요")).toBeInTheDocument();
    expect(onChanged).toHaveBeenCalledTimes(1);
    // Applied right away, with "되돌리기" on the toast (9장: no confirm for a light, undoable write).
    expect(await screen.findByRole("button", { name: copy.activity.undo })).toBeInTheDocument();

    await userEvent.click(box("운동"));
    await waitFor(() => expect(bodies).toHaveLength(2));
    expect(bodies[1]).toMatchObject({ action: "uncheck_habit", args: { id: 2, date: DATE } });
    await waitFor(() => expect(box("운동")).not.toBeChecked());
    expect(screen.getByText("이번 주 2번 · 목표 3번")).toBeInTheDocument();
    expect(onChanged).toHaveBeenCalledTimes(2);
  });

  it("chat card: press A, press B, undo B reads the habits again (A stays checked)", async () => {
    const a = makeHabit(1, "물 마시기");
    const b = makeHabit(2, "운동");
    let n = 0;
    const bodies = serveActions((body) => {
      n += 1;
      const id = (body.args as { id: number }).id;
      return HttpResponse.json({
        status: "applied",
        activity_id: 930 + n,
        undo_id: 930 + n,
        result: { habit: { ...(id === 1 ? a : b), checked: true, week_count: 1 }, date: DATE, already: false },
        confirmation: "✓ 습관", // taste-skill-ignore: BE confirmation (appendix A), not UI
      });
    });
    const undos = serveUndo();
    const reads = serveHabits(() => HttpResponse.json(list([{ ...a, checked: true, week_count: 1 }, b])));
    renderWithProviders(<HabitCheck props={{ date: DATE }} data={{ habits: [a, b] }} ctx={makeCtx({ where: "chat" })} />);
    await userEvent.click(box("물 마시기"));
    await waitFor(() => expect(box("물 마시기")).toBeChecked());
    await userEvent.click(box("운동"));
    await waitFor(() => expect(box("운동")).toBeChecked());
    expect(bodies).toHaveLength(2);
    await userEvent.click(await screen.findByRole("button", { name: copy.activity.undo }));
    await waitFor(() => expect(undos).toEqual(["932"]));
    await waitFor(() => expect(reads).toEqual([`date=${DATE}&status=active`]));
    await waitFor(() => expect(box("운동")).not.toBeChecked());
    expect(box("물 마시기")).toBeChecked();
    expect(screen.getByText("이번 주 1번")).toBeInTheDocument();
  });

  it("chat card: undo of an unrelated write does not flip a pressed row", async () => {
    const a = makeHabit(1, "물 마시기");
    serveActions(answerWith(() => ({ ...a, checked: true, week_count: 1 })));
    serveUndo();
    serveHabits(() => HttpResponse.json(list([{ ...a, checked: true, week_count: 1 }])));
    renderWithProviders(
      <>
        <HabitCheck props={{ date: DATE }} data={{ habits: [a] }} ctx={makeCtx({ where: "chat" })} />
        <OtherWrite />
      </>,
    );
    await userEvent.click(box("물 마시기"));
    await waitFor(() => expect(box("물 마시기")).toBeChecked());
    await userEvent.click(screen.getByRole("button", { name: "other" }));
    await userEvent.click(await screen.findByRole("button", { name: copy.activity.undo }));
    await screen.findByText("↩ 되돌림");
    expect(box("물 마시기")).toBeChecked();
  });

  it("chat card: a failed read after undo keeps the rows as they are", async () => {
    const a = makeHabit(1, "물 마시기");
    serveActions(answerWith(() => ({ ...a, checked: true, week_count: 1 })));
    serveUndo();
    const reads = serveHabits(() => HttpResponse.error());
    renderWithProviders(<HabitCheck props={{ date: DATE }} data={{ habits: [a] }} ctx={makeCtx({ where: "chat" })} />);
    await userEvent.click(box("물 마시기"));
    await waitFor(() => expect(box("물 마시기")).toBeChecked());
    await userEvent.click(await screen.findByRole("button", { name: copy.activity.undo }));
    await waitFor(() => expect(reads.length).toBeGreaterThan(0));
    expect(box("물 마시기")).toBeChecked();
  });

  it("a list whose caller reads again (Today) does not read the habits itself", async () => {
    serveActions(answerWith(() => ({ ...weekly, checked: true, week_count: 3 })));
    serveUndo();
    const reads = serveHabits(() => HttpResponse.json(list([weekly])));
    const onChanged = vi.fn();
    renderWithProviders(<HabitList habits={[weekly]} date={DATE} readOnly={false} onChanged={onChanged} />);
    await userEvent.click(box("운동"));
    await waitFor(() => expect(onChanged).toHaveBeenCalledTimes(1));
    await userEvent.click(await screen.findByRole("button", { name: copy.activity.undo }));
    await screen.findByText("↩ 되돌림");
    expect(reads).toEqual([]);
    expect(onChanged).toHaveBeenCalledTimes(1);
  });

  it("a refused check leaves the row as it was", async () => {
    const bodies = serveActions(() =>
      HttpResponse.json({ error: { code: "rejected", message: "쉬는 중인 습관이에요. 다시 시작하면 체크할 수 있어요." } }, { status: 422 }),
    );
    const onChanged = vi.fn();
    renderWithProviders(<HabitList habits={[daily]} date={DATE} readOnly={false} onChanged={onChanged} />);
    await userEvent.click(box("물 마시기"));
    await waitFor(() => expect(bodies).toHaveLength(1));
    expect(await screen.findByText("쉬는 중인 습관이에요. 다시 시작하면 체크할 수 있어요.")).toBeInTheDocument();
    expect(box("물 마시기")).not.toBeChecked();
    expect(onChanged).not.toHaveBeenCalled();
  });

  it("read_only_disables_press", async () => {
    const bodies = serveActions();
    renderWithProviders(<HabitList habits={[daily, met]} date={DATE} readOnly onChanged={vi.fn()} />);
    expect(screen.getByText("물 마시기")).toBeInTheDocument();
    for (const c of screen.getAllByRole("checkbox")) expect(c).toBeDisabled();
    await userEvent.click(box("물 마시기"));
    expect(bodies).toHaveLength(0);
    // The checked one still reads as checked: the drawn circle keeps its state.
    expect(box("독서")).toBeChecked();
  });

  it("no_strikethrough_when_checked", () => {
    renderWithProviders(<HabitList habits={[met]} date={DATE} readOnly={false} onChanged={vi.fn()} />);
    expect(box("독서")).toBeChecked();
    expect(screen.getByText("독서")).not.toHaveClass("done");
  });

  it("no_ratio_or_remaining_text", () => {
    const many = [
      daily,
      weekly,
      met,
      makeHabit(4, "산책", { kind: "weekly", target_per_week: 6, week_count: 1 }),
      makeHabit(5, "명상", { kind: "weekly", target_per_week: 2, week_count: 5 }),
      makeHabit(6, "일기", { week_count: 0 }),
    ];
    const { container } = renderWithProviders(<HabitList habits={many} date={DATE} readOnly={false} onChanged={vi.fn()} />);
    const text = container.textContent ?? "";
    expect(text).not.toMatch(/%/);
    expect(text).not.toMatch(/남음|남은/);
    expect(text).not.toMatch(/\d+\s*\/\s*\d+/);
    expect(container.querySelector("progress, [role='progressbar']")).toBeNull();
  });

  it("rows carry the 52px row class and the 44px check class", () => {
    const { container } = renderWithProviders(<HabitList habits={[daily]} date={DATE} readOnly={false} onChanged={vi.fn()} />);
    expect(container.querySelector("ul")).toHaveClass("habitRows");
    expect(box("물 마시기")).toHaveClass("check");
  });

  it("no habits shows the add row to the habits screen", () => {
    renderWithProviders(<HabitList habits={[]} date={DATE} readOnly={false} onChanged={vi.fn()} />);
    expect(screen.getByRole("link", { name: "습관 추가하기" })).toHaveAttribute("href", "/habits/");
    expect(screen.queryByRole("checkbox")).toBeNull();
  });
});
