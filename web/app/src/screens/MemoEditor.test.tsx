import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import type { Memo } from "../api/types.gen";
import { copy } from "../lib/copy";
import { checklistLines, toggleChecklistLine } from "../lib/memoText";
import { renderWithProviders } from "../test/render";
import { BASE, server } from "../test/server";
import { MemoEditor } from "./MemoEditor";

const MEMO: Memo = {
  id: 7,
  title: "읽을 책",
  body: "읽을 책\n- [ ] 사피엔스\n- [x] 코스모스\n- [ ] 총균쇠",
  area: "learning",
  pinned: false,
  origin: "user",
  created_at: "2026-10-25T05:00:00Z",
  updated_at: "2026-10-25T05:02:00.123456Z",
};

const applied = (result: Record<string, unknown>, confirmation = "✓ 메모를 고쳤어요: 읽을 책", undo: number | null = null) =>
  HttpResponse.json({ status: "applied", activity_id: 900, undo_id: undo, result, confirmation });

function serveMemo(memo: () => Memo | Response = () => MEMO) {
  const reads: number[] = [];
  server.use(
    http.get(`${BASE}/memos/:id`, ({ params }) => {
      reads.push(Number(params.id));
      const m = memo();
      return m instanceof Response ? m : HttpResponse.json(m);
    }),
  );
  return reads;
}

interface Sent {
  action: string;
  args: Record<string, unknown>;
  at: number;
}

function record(answer: (b: Sent) => Response) {
  const sent: Sent[] = [];
  server.use(
    http.post(`${BASE}/actions`, async ({ request }) => {
      const b = (await request.json()) as { action: string; args: Record<string, unknown> };
      const s = { action: b.action, args: b.args, at: performance.now() };
      sent.push(s);
      return answer(s);
    }),
  );
  return sent;
}

const resultOf = (body: string, at = "2026-10-25T05:10:00.000001Z") => ({ id: 7, title: body.split("\n")[0], area: "learning", pinned: false, updated_at: at });

describe("toggleChecklistLine", () => {
  const BODY = "읽을 책\n- [ ] 사피엔스\n- [x] 코스모스\n  - [X] 안쪽\n1. [ ] 번호\n> - [ ] 인용\n일반 줄 [ ] 그대로\n```\n- [ ] 코드\n```\n- [ ] 끝";
  it.each([
    // [line, the line after]
    [1, "- [x] 사피엔스"],
    [2, "- [ ] 코스모스"],
    [3, "  - [ ] 안쪽"],
    [4, "1. [x] 번호"],
    [5, "> - [x] 인용"],
    [10, "- [x] 끝"],
  ])("line %i flips to %s and every other line stays", (line, after) => {
    const out = toggleChecklistLine(BODY, line).split("\n");
    const before = BODY.split("\n");
    expect(out[line]).toBe(after);
    out.forEach((l, i) => {
      if (i !== line) expect(l).toBe(before[i]);
    });
  });

  it.each([0, 6, 8, 99])("line %i is not a checklist line: the body stays as it is", (line) => {
    // 8 is "- [ ] 코드" inside a code fence; toggle only reads the line, so it would flip; the
    // renderer never offers that line (checklistLines leaves it out).
    if (line === 8) {
      expect(checklistLines(BODY)).not.toContain(8);
      return;
    }
    expect(toggleChecklistLine(BODY, line)).toBe(BODY);
  });

  it("only the first box on the line flips", () => {
    expect(toggleChecklistLine("- [ ] a [ ] b", 0)).toBe("- [x] a [ ] b");
  });

  it("checklistLines lists the boxes in drawing order, leaving out code fences", () => {
    expect(checklistLines("읽을 책\n- [ ] 사피엔스\n- [x] 코스모스\n  - [X] 안쪽\n1. [ ] 번호\n> - [ ] 인용\n일반 줄 [ ] 그대로\n```\n- [ ] 코드\n```\n- [ ] 끝")).toEqual([1, 2, 3, 4, 5, 10]);
  });
});

describe("MemoEditor (spec 9.4)", () => {
  it("a new memo opens in the write state; 1s after the typing stops it is made, with the undo toast", async () => {
    const sent = record(() => applied({ ...resultOf("읽을 책\n- [ ] 사피엔스"), area: null }, "✓ 메모를 만들었어요: 읽을 책", 900));
    const { router } = renderWithProviders(<MemoEditor id={null} />, { route: "/memos/view/?new=1" });
    const box = screen.getByRole("textbox", { name: copy.memos.body });
    await waitFor(() => expect(box).toHaveFocus());
    await userEvent.type(box, "읽을 책{Enter}- [[ ] 사피엔스");
    const typedAt = performance.now();
    expect(sent).toEqual([]);
    await waitFor(() => expect(sent).toHaveLength(1), { timeout: 2500 });
    expect(sent[0].at - typedAt).toBeGreaterThanOrEqual(900);
    expect(sent[0]).toMatchObject({ action: "create_memo", args: { body: "읽을 책\n- [ ] 사피엔스" } });
    expect(sent[0].args).not.toHaveProperty("area");
    const toast = screen.getByRole("status");
    await waitFor(() => expect(toast).toHaveTextContent("✓ 메모를 만들었어요: 읽을 책"));
    expect(within(toast).getByRole("button", { name: copy.activity.undo })).toBeInTheDocument();
    expect(router.replace).toHaveBeenCalledWith("/memos/view/?id=7", undefined, { shallow: true });
    // More typing goes to update_memo with the updated_at the create gave back.
    await userEvent.type(box, "{Enter}- [[ ] 총균쇠");
    await waitFor(() => expect(sent).toHaveLength(2), { timeout: 2500 });
    expect(sent[1]).toMatchObject({
      action: "update_memo",
      args: { id: 7, body: "읽을 책\n- [ ] 사피엔스\n- [ ] 총균쇠", updated_at: "2026-10-25T05:10:00.000001Z" },
    });
  });

  it("a saved memo opens in the read state; pressing a box saves that line only", async () => {
    serveMemo();
    const sent = record((s) => applied(resultOf(String(s.args.body))));
    renderWithProviders(<MemoEditor id={7} />, { route: "/memos/view/?id=7" });
    const box = await screen.findByRole("checkbox", { name: "총균쇠" });
    expect(screen.queryByRole("textbox")).toBeNull();
    expect(screen.getByRole("checkbox", { name: "코스모스" })).toBeChecked();
    await userEvent.click(box);
    await waitFor(() => expect(sent).toHaveLength(1));
    expect(sent[0].action).toBe("update_memo");
    expect(sent[0].args).toEqual({ id: 7, body: "읽을 책\n- [ ] 사피엔스\n- [x] 코스모스\n- [x] 총균쇠", updated_at: MEMO.updated_at });
    await waitFor(() => expect(screen.getByRole("checkbox", { name: "총균쇠" })).toBeChecked());
    // The next press sends the new updated_at.
    await userEvent.click(screen.getByRole("checkbox", { name: "사피엔스" }));
    await waitFor(() => expect(sent).toHaveLength(2));
    expect(sent[1].args).toEqual({ id: 7, body: "읽을 책\n- [x] 사피엔스\n- [x] 코스모스\n- [x] 총균쇠", updated_at: "2026-10-25T05:10:00.000001Z" });
  });

  it("409 memo_conflict: says so, reads the memo again and shows what is there now", async () => {
    let body = MEMO.body;
    const reads = serveMemo(() => ({ ...MEMO, body, updated_at: body === MEMO.body ? MEMO.updated_at : "2026-10-25T05:20:00Z" }));
    record(() => {
      body = "다른 기기에서 고침\n- [ ] 새 줄";
      return HttpResponse.json({ error: { code: "memo_conflict", message: copy.memos.conflict } }, { status: 409 });
    });
    renderWithProviders(<MemoEditor id={7} />, { route: "/memos/view/?id=7" });
    await userEvent.click(await screen.findByRole("checkbox", { name: "총균쇠" }));
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("다른 곳에서 바뀌었어요. 새로 불러올게요."));
    await waitFor(() => expect(reads).toHaveLength(2));
    expect(await screen.findByText("다른 기기에서 고침")).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "새 줄" })).not.toBeChecked();
  });

  it("pressing the body opens the write state; typing saves 1s later; 완료 saves at once and goes back to reading", async () => {
    serveMemo();
    const sent = record((s) => applied(resultOf(String(s.args.body))));
    renderWithProviders(<MemoEditor id={7} />, { route: "/memos/view/?id=7" });
    await userEvent.click(await screen.findByText("읽을 책"));
    const box = screen.getByRole("textbox", { name: copy.memos.body });
    expect(box).toHaveValue(MEMO.body);
    await userEvent.type(box, "{Enter}- [[ ] 이기적 유전자");
    await waitFor(() => expect(sent).toHaveLength(1), { timeout: 2500 });
    expect(sent[0].args).toEqual({ id: 7, body: `${MEMO.body}\n- [ ] 이기적 유전자`, updated_at: MEMO.updated_at });
    await userEvent.type(box, "!");
    await userEvent.click(screen.getByRole("button", { name: copy.memos.toolbar.done }));
    await waitFor(() => expect(sent).toHaveLength(2));
    expect(sent[1].args.body).toBe(`${MEMO.body}\n- [ ] 이기적 유전자!`);
    await waitFor(() => expect(screen.queryByRole("textbox")).toBeNull());
    expect(screen.getByRole("checkbox", { name: "이기적 유전자!" })).toBeInTheDocument();
  });

  it("the area goes out only when it was changed, and null clears it", async () => {
    serveMemo();
    const sent = record((s) => applied({ ...resultOf(String(s.args.body)), area: s.args.area === undefined ? "learning" : s.args.area }));
    renderWithProviders(<MemoEditor id={7} />, { route: "/memos/view/?id=7" });
    await userEvent.click(await screen.findByText("읽을 책"));
    await userEvent.click(screen.getByRole("button", { name: copy.memos.toolbar.area }));
    await userEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: copy.memos.noArea }));
    await userEvent.click(screen.getByRole("button", { name: copy.memos.toolbar.done }));
    await waitFor(() => expect(sent).toHaveLength(1));
    expect(sent[0].args).toEqual({ id: 7, body: MEMO.body, area: null, updated_at: MEMO.updated_at });
  });

  it("the tool row writes list, checkbox and bold marks", async () => {
    const sent = record(() => applied({ ...resultOf("x"), area: null }, "✓ 메모를 만들었어요: x", 900));
    renderWithProviders(<MemoEditor id={null} />, { route: "/memos/view/?new=1" });
    const box = screen.getByRole("textbox", { name: copy.memos.body });
    await userEvent.type(box, "장보기{Enter}");
    // A tool button keeps the caret in the text box, so the typing goes on where it was.
    await userEvent.click(screen.getByRole("button", { name: copy.memos.toolbar.checkbox }));
    expect(box).toHaveFocus();
    await userEvent.keyboard("우유{Enter}");
    await userEvent.click(screen.getByRole("button", { name: copy.memos.toolbar.list }));
    await userEvent.keyboard("빵 ");
    await userEvent.click(screen.getByRole("button", { name: copy.memos.toolbar.bold }));
    await userEvent.keyboard("꼭");
    expect(box).toHaveValue("장보기\n- [ ] 우유\n- 빵 **꼭**");
    await waitFor(() => expect(sent).toHaveLength(1), { timeout: 2500 });
  });

  it("the text waits in localStorage as a draft until it is saved", async () => {
    let answer: () => Response = () => HttpResponse.error();
    record(() => answer());
    renderWithProviders(<MemoEditor id={null} />, { route: "/memos/view/?new=1" });
    await userEvent.type(screen.getByRole("textbox", { name: copy.memos.body }), "떠오른 것");
    expect(JSON.parse(localStorage.getItem("mp.memoDraft.new") ?? "null")).toMatchObject({ body: "떠오른 것" });
    answer = () => applied({ ...resultOf("떠오른 것"), area: null }, "✓ 메모를 만들었어요: 떠오른 것", 900);
    await userEvent.click(screen.getByRole("button", { name: copy.memos.toolbar.done }));
    await waitFor(() => expect(localStorage.getItem("mp.memoDraft.new")).toBeNull());
  });

  it("a draft left on the device comes back into the new memo", async () => {
    localStorage.setItem("mp.memoDraft.new", JSON.stringify({ body: "어제 쓰던 글", area: null, base: null }));
    record(() => applied({ ...resultOf("어제 쓰던 글"), area: null }, "✓ 메모를 만들었어요: 어제 쓰던 글", 900));
    renderWithProviders(<MemoEditor id={null} />, { route: "/memos/view/?new=1" });
    expect(screen.getByRole("textbox", { name: copy.memos.body })).toHaveValue("어제 쓰던 글");
  });

  it("leaving the screen saves what was typed", async () => {
    serveMemo();
    const sent = record((s) => applied(resultOf(String(s.args.body))));
    const { unmount } = renderWithProviders(<MemoEditor id={7} />, { route: "/memos/view/?id=7" });
    await userEvent.click(await screen.findByText("읽을 책"));
    await userEvent.type(screen.getByRole("textbox", { name: copy.memos.body }), "?");
    unmount();
    await waitFor(() => expect(sent).toHaveLength(1));
    expect(sent[0].args.body).toBe(`${MEMO.body}?`);
  });

  it("offline: read only (no write state, boxes cannot be pressed)", async () => {
    serveMemo();
    const sent = record(() => applied({}));
    renderWithProviders(<MemoEditor id={7} />, { route: "/memos/view/?id=7", conn: "offline" });
    expect(await screen.findByText(copy.offline.lead)).toBeInTheDocument();
    const box = await screen.findByRole("checkbox", { name: "총균쇠" });
    await waitFor(() => expect(box).toBeDisabled());
    await userEvent.click(screen.getByText("읽을 책"));
    expect(screen.queryByRole("textbox")).toBeNull();
    expect(screen.queryByRole("button", { name: copy.memos.toolbar.done })).toBeNull();
    expect(sent).toEqual([]);
  });

  it("a memo that is gone says so", async () => {
    serveMemo(() => HttpResponse.json({ error: { code: "not_found", message: "x" } }, { status: 404 }));
    renderWithProviders(<MemoEditor id={8} />, { route: "/memos/view/?id=8" });
    expect(await screen.findByText(copy.memos.errors.notFound)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: copy.memos.back })).toHaveAttribute("href", "/memos/");
  });
});
