import { useCallback, useEffect, useRef, useState } from "react";
import { type ActionOutcome, useAction } from "../api/actions";
import type { Todo } from "../api/types.gen";
import { ConfirmSheet } from "../components/ConfirmSheet";
import { useToast } from "../components/Toast";
import { copy } from "../lib/copy";

// Row actions shared by Today and Todos. useAction toasts applied / rejected / failed; the
// callers here own `conflict` and `needs_confirm`.

/** A card or row that changed under us (conflict), or a confirm question nobody expected: the failure sentence, then read again. */
export function useNotAllowed(refresh: () => Promise<void>) {
  const toast = useToast();
  return useCallback(
    async (out: ActionOutcome | null) => {
      if (out?.kind !== "conflict" && out?.kind !== "needs_confirm") return;
      toast.show({ text: copy.actions.failed });
      await refresh();
    },
    [toast, refresh],
  );
}

/**
 * Optimistic check (spec 4.6): todo id -> the done state the person asked for, until the answer is in.
 * `todos` is every row the screen shows right now (null when the screen is not live).
 */
export function useOptimisticCheck(todos: readonly Todo[] | null, refresh: () => Promise<void>) {
  const { run } = useAction();
  const toast = useToast();
  const [flip, setFlip] = useState<Readonly<Record<number, boolean>>>({});
  const busy = useRef(new Set<number>());

  const unflip = useCallback((id: number) => {
    setFlip((f) => {
      const { [id]: _gone, ...rest } = f;
      return rest;
    });
  }, []);

  // A flip ends once the live list shows the state it asked for (or no longer has the row).
  useEffect(() => {
    if (todos === null) return;
    setFlip((f) => {
      const ids = Object.keys(f).map(Number);
      const keep = ids.filter((id) => {
        const row = todos.find((t) => t.id === id);
        return row !== undefined && (row.status === "done") !== f[id];
      });
      if (keep.length === ids.length) return f;
      return Object.fromEntries(keep.map((id) => [id, f[id]]));
    });
  }, [todos]);

  const show = useCallback(
    (todo: Todo): Todo => {
      const want = flip[todo.id];
      if (want === undefined || want === (todo.status === "done")) return todo;
      return { ...todo, status: want ? "done" : "open", completed_at: want ? new Date().toISOString() : null };
    },
    [flip],
  );

  const toggle = async (todo: Todo) => {
    const id = todo.id;
    if (busy.current.has(id)) return; // the answer to the first press has not come yet
    busy.current.add(id);
    const wasDone = flip[id] ?? todo.status === "done";
    setFlip((f) => ({ ...f, [id]: !wasDone }));
    let applied = false;
    try {
      const out = await run(wasDone ? "reopen_task" : "complete_task", { id });
      applied = out?.kind === "applied";
      if (out?.kind === "conflict" || out?.kind === "needs_confirm") toast.show({ text: copy.actions.failed });
      if (applied) await refresh();
    } finally {
      busy.current.delete(id);
      // After an applied write the flip stays until an answer that shows the change arrives
      // (the effect above), so a failed refresh does not make the row look unchecked again.
      if (!applied) unflip(id);
    }
  };

  return { show, toggle };
}

interface PendingConfirm {
  id: number;
  token: string;
  summary: string;
}

/** `drop_task` with the BE's `needs_confirm` sheet: "바꾸기" sends again with the token and a NEW client_msg_id. */
export function useConfirmedDrop(refresh: () => Promise<void>) {
  const { run } = useAction();
  const toast = useToast();
  const notAllowed = useNotAllowed(refresh);
  const [confirm, setConfirm] = useState<PendingConfirm | null>(null);
  const [busy, setBusy] = useState(false);
  const lock = useRef(false);

  const drop = async (id: number) => {
    const out = await run("drop_task", { id });
    if (out?.kind === "applied") await refresh();
    else if (out?.kind === "needs_confirm") setConfirm({ id, token: out.confirmToken, summary: out.summary });
    else await notAllowed(out);
  };

  const confirmDrop = async () => {
    if (!confirm || lock.current) return;
    lock.current = true;
    setBusy(true);
    try {
      const out = await run("drop_task", { id: confirm.id }, { confirmToken: confirm.token });
      if (out === null) return;
      if (out.kind === "needs_confirm") {
        setConfirm({ id: confirm.id, token: out.confirmToken, summary: out.summary });
        return;
      }
      if (out.kind === "conflict") toast.show({ text: copy.todos.confirmExpired });
      setConfirm(null);
      if (out.kind === "applied") await refresh();
    } finally {
      lock.current = false;
      setBusy(false);
    }
  };

  const sheet = confirm ? (
    <ConfirmSheet summary={confirm.summary} busy={busy} onKeep={() => setConfirm(null)} onChange={() => void confirmDrop()} />
  ) : null;
  return { drop, sheet };
}
