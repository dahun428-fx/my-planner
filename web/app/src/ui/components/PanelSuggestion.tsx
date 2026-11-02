import { type MouseEvent, useEffect, useRef, useState } from "react";
import { getPanelSuggestions } from "../../api/panel";
import type { PanelEvidenceOut, PanelSuggestionOut } from "../../api/types.gen";
import { Sheet } from "../../components/Sheet";
import { copy } from "../../lib/copy";
import {
  copyPanel,
  type DismissReason,
  type ExpertKey,
} from "../../lib/copyPanel";
import type { PartContext, PartProps } from "../types";
import { usePartAction } from "../usePartAction";
import { Part } from "./Part";
import parts from "./parts.module.css";
import styles from "./PanelSuggestion.module.css";

export type PanelSuggestionProps = { suggestion_id: number };

const GROUPS = ["record", "statement", "external"] as const;
const REASONS = Object.keys(copyPanel.reasons) as DismissReason[];

// Review Focus 2: a card restored after a reload is read-only, unless the BE still has its
// suggestion proposed. One GET /panel/suggestions?state=proposed per history read, shared by every
// restored card (ChatSheet forgets it when it reads a conversation again). Null: not known (offline,
// refused): the cards stay read-only.
let proposed: Promise<ReadonlySet<number> | null> | null = null;
function proposedIds(): Promise<ReadonlySet<number> | null> {
  proposed ??= getPanelSuggestions("proposed").then((r) =>
    r.kind === "ok" ? new Set(r.data.items.map((s) => s.id)) : null,
  );
  return proposed;
}
/** The next restored card asks the BE again (a new history read, a new test). */
export function forgetProposed(): void {
  proposed = null;
}

const nameOf = (key: string): string | null =>
  key in copyPanel.experts ? copyPanel.experts[key as ExpertKey] : null;

function metaLine(s: PanelSuggestionOut): string {
  const bits: string[] = [
    copy.areas[s.area],
    copyPanel.card.minutes(s.size_min),
  ];
  if (s.kind === "habit" && s.per_week !== null)
    bits.push(copyPanel.card.perWeek(s.per_week));
  const experts = s.experts.map(nameOf).filter((n): n is string => n !== null);
  if (experts.length > 0) bits.push(experts.join(", "));
  return bits.join(" · ");
}

// A row with an app address is a link (the chat sheet moves there and closes); a bench row, or one
// whose record has no screen, is text. A link to a record gone since stays as it is (the screen says so).
function EvidenceRow({ e, ctx }: { e: PanelEvidenceOut; ctx: PartContext }) {
  if (e.href === null) return <li>{e.note}</li>;
  const href = e.href;
  const open = (ev: MouseEvent<HTMLAnchorElement>) => {
    if (!ctx.onOpenPath) return;
    ev.preventDefault();
    ctx.onOpenPath(href);
  };
  return (
    <li>
      <a href={href} onClick={open}>
        {e.note}
      </a>
    </li>
  );
}

// ui_panel_suggestion (SP15 7장, 11장): a suggestion of the life manager's panel. Title, the area's
// dot, how long it takes (and how often, for a habit), the experts; "받기" makes it a to-do or a
// habit, "버리기" asks why (five reason chips). After either the card says so and its buttons go;
// the undo is the activity toast's. "근거 보기" opens the evidence in three groups.
export function PanelSuggestion({
  props,
  data,
  ctx,
}: PartProps<PanelSuggestionProps>) {
  const act = usePartAction();
  const s = data?.suggestion;
  const restored = ctx.restored === true;
  const [stillProposed, setStillProposed] = useState<boolean | null>(
    restored ? null : true,
  );
  const [done, setDone] = useState<"accepted" | "dismissed" | null>(null);
  const [asking, setAsking] = useState(false);
  const [busy, setBusy] = useState(false);
  const inFlight = useRef(false);
  const dismissButton = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!restored) return;
    let live = true;
    void proposedIds().then((ids) => {
      if (live) setStillProposed(ids?.has(props.suggestion_id) ?? false);
    });
    return () => {
      live = false;
    };
  }, [restored, props.suggestion_id]);

  if (!s) return null;
  const canAct =
    done === null && s.state === "proposed" && stillProposed === true;
  const off = ctx.readOnly || busy;

  const run = async (
    action: "accept_suggestion" | "dismiss_suggestion",
    args: object,
    after: "accepted" | "dismissed",
  ) => {
    if (off || inFlight.current) return;
    inFlight.current = true;
    setBusy(true);
    try {
      const out = await act(action, args);
      if (out?.kind === "applied") {
        setDone(after);
        ctx.onAfterAction();
      }
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  };
  const dismiss = (reason: DismissReason) => {
    setAsking(false);
    void run(
      "dismiss_suggestion",
      { id: props.suggestion_id, reason },
      "dismissed",
    );
  };
  const groups = GROUPS.map((g) => ({
    g,
    rows: s.evidence.filter((e) => e.type === g),
  })).filter((x) => x.rows.length > 0);

  return (
    <Part
      title={s.title}
      readOnly={ctx.readOnly && canAct}
      restored={restored && !canAct}
    >
      <div className={styles.panel}>
        <p data-meta="">
          <span className="area-dot" data-area={s.area} aria-hidden="true" />
          <span>{metaLine(s)}</span>
        </p>
        {done !== null && <p data-state="">{copyPanel.card[done]}</p>}
        {canAct && (
          <div className={parts.buttons}>
            <button
              type="button"
              className={`${parts.button} ${parts.primary} pressable`}
              disabled={off}
              onClick={() =>
                void run(
                  "accept_suggestion",
                  { id: props.suggestion_id },
                  "accepted",
                )
              }
            >
              {copyPanel.card.accept}
            </button>
            <button
              ref={dismissButton}
              type="button"
              className={`${parts.button} pressable`}
              disabled={off}
              onClick={() => setAsking(true)}
            >
              {copyPanel.card.dismiss}
            </button>
          </div>
        )}
        {groups.length > 0 && (
          <details>
            <summary>{copyPanel.card.evidence}</summary>
            {groups.map(({ g, rows }) => (
              <section key={g}>
                <h4>{copyPanel.card.groups[g]}</h4>
                <ul>
                  {rows.map((e, i) => (
                    <EvidenceRow key={`${e.ref}-${i}`} e={e} ctx={ctx} />
                  ))}
                </ul>
              </section>
            ))}
          </details>
        )}
      </div>
      <Sheet
        open={asking}
        onClose={() => setAsking(false)}
        title={copyPanel.reasonTitle}
        returnFocusTo={dismissButton}
      >
        <div className={styles.reasons}>
          {REASONS.map((r) => (
            <button
              key={r}
              type="button"
              className="pressable"
              disabled={off}
              onClick={() => dismiss(r)}
            >
              {copyPanel.reasons[r]}
            </button>
          ))}
        </div>
      </Sheet>
    </Part>
  );
}
