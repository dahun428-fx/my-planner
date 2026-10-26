import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { type ApiResult, deleteDevice, getDevices } from "../api/client";
import type { DeviceItem, DeviceList } from "../api/types.gen";
import { BlockError } from "../components/BlockError";
import { ConfirmSheet } from "../components/ConfirmSheet";
import { Group } from "../components/Group";
import { LargeTitle } from "../components/LargeTitle";
import { Row } from "../components/Row";
import { Skeleton } from "../components/Skeleton";
import { useToast } from "../components/Toast";
import { useConnection } from "../lib/ConnectionProvider";
import { copy } from "../lib/copy";
import { disconnectThisDevice } from "../lib/disconnect";
import { formatKst } from "../lib/time";
import page from "../styles/page.module.css";
import styles from "./Devices.module.css";
import { PairSheet } from "./PairSheet";

// "마지막 사용 10월 26일", "마지막 사용 오늘", or "연결 10월 26일" for a device that has not been used yet.
function usedLine(d: DeviceItem, now: number): string {
  if (!d.last_used_at) return copy.devices.connectedOn(formatKst(d.created_at, copy.dateStyle.monthDay));
  const today = formatKst(new Date(now).toISOString(), "date") === formatKst(d.last_used_at, "date");
  return copy.devices.lastUsed(today ? copy.devices.today : formatKst(d.last_used_at, copy.dateStyle.monthDay));
}

type Confirm = { kind: "one"; device: DeviceItem } | { kind: "others" } | null;

// Device pairing spec 5.1 (`/devices/`, "‹ 더보기" back): the devices that connected with a pairing
// code, each one cut with one confirmation; "다른 기기 모두 끊기"; "새 기기 연결" opens the code sheet.
// Cutting this device clears the saved connection and goes to /connect/.
export function Devices({ pollMs }: { pollMs?: number }) {
  const toast = useToast();
  const { conn } = useConnection();
  const [list, setList] = useState<ApiResult<DeviceList> | null>(null);
  const [confirm, setConfirm] = useState<Confirm>(null);
  const [busy, setBusy] = useState(false);
  const [pairOpen, setPairOpen] = useState(false);

  const load = useCallback(async () => {
    setList(await getDevices());
  }, []);
  useEffect(() => {
    void load();
  }, [load]);

  const devices = list?.kind === "ok" ? list.data.devices : [];
  const others = devices.filter((d) => !d.this_device);

  const revoke = async () => {
    if (!confirm || busy) return;
    setBusy(true);
    try {
      if (confirm.kind === "one" && confirm.device.this_device) {
        // The whole "이 기기 연결 해제": the BE revoke is part of it. The page goes away.
        await disconnectThisDevice({ deviceId: confirm.device.id });
        return;
      }
      const targets = confirm.kind === "one" ? [confirm.device] : others;
      const results = await Promise.all(targets.map((d) => deleteDevice(d.id)));
      // 404: already cut elsewhere, which is what was asked.
      if (results.some((r) => r.kind !== "ok" && !(r.kind === "error" && r.status === 404))) toast.show({ text: copy.devices.revokeFailed });
      setConfirm(null);
      await load();
    } finally {
      setBusy(false);
    }
  };

  let body;
  if (list === null) {
    body = (
      <div className={styles.pad}>
        <Skeleton size="row" />
      </div>
    );
  } else if (list.kind === "ok") {
    const now = Date.now();
    body =
      devices.length === 0 ? (
        <Row title={<span className={styles.note}>{copy.devices.empty}</span>} />
      ) : (
        devices.map((d) => (
          <Row
            key={d.id}
            title={d.label}
            meta={usedLine(d, now)}
            trailing={d.this_device ? <span className={styles.mark}>{copy.devices.thisDevice}</span> : undefined}
            onPress={() => setConfirm({ kind: "one", device: d })}
          />
        ))
      );
  } else if (list.kind === "offline") {
    body = <Row title={<span className={styles.note}>{copy.offline.later}</span>} />;
  } else {
    body = (
      <div className={styles.pad}>
        <BlockError code={list.kind === "error" ? list.code : list.kind} onRetry={() => void load()} />
      </div>
    );
  }

  return (
    <main className={page.main}>
      <nav className={styles.bar}>
        <Link href="/more/" className={styles.back}>
          {copy.devices.back}
        </Link>
      </nav>
      <LargeTitle
        title={copy.devices.title}
        trailing={
          <button type="button" className={styles.add} onClick={() => setPairOpen(true)} disabled={!conn}>
            {copy.devices.add}
          </button>
        }
      />
      <Group footer={<span className={styles.note}>{copy.devices.keyNote}</span>}>
        {body}
        {others.length > 0 && (
          <button type="button" className={styles.danger} onClick={() => setConfirm({ kind: "others" })}>
            {copy.devices.revokeOthers}
          </button>
        )}
      </Group>

      {confirm && (
        <ConfirmSheet
          summary={confirm.kind === "one" ? copy.devices.revokeSummary : copy.devices.revokeOthersSummary}
          keepLabel={copy.devices.cancel}
          changeLabel={confirm.kind === "one" ? copy.devices.revoke : copy.devices.revokeOthers}
          busy={busy}
          onKeep={() => setConfirm(null)}
          onChange={() => void revoke()}
        />
      )}
      <PairSheet open={pairOpen} onClose={() => setPairOpen(false)} beUrl={conn?.beUrl ?? ""} onUsed={() => void load()} pollMs={pollMs} />
    </main>
  );
}
