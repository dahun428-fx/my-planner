import Link from "next/link";
import { useRouter } from "next/router";
import { type ReactNode, useCallback, useEffect, useRef, useState } from "react";
import pkg from "../../package.json";
import { failureText } from "../api/actions";
import { apiFetch, apiGet } from "../api/client";
import type { NotifySettings, PushTestResult, VapidPublicKey } from "../api/types.gen";
import { sendCommand } from "../chat/command";
import { BlockError } from "../components/BlockError";
import { Group } from "../components/Group";
import { LargeTitle } from "../components/LargeTitle";
import { Row } from "../components/Row";
import { Segmented } from "../components/Segmented";
import { Sheet } from "../components/Sheet";
import { Skeleton } from "../components/Skeleton";
import { StatusDot } from "../components/StatusDot";
import { useToast } from "../components/Toast";
import { CONN_CHANGED, loadLastHealthOk } from "../lib/connection";
import { useConnection } from "../lib/ConnectionProvider";
import { copy } from "../lib/copy";
import { usePolling } from "../lib/polling";
import { hasLiveSubscription, permission, pushSupport, subscribePush, unsubscribePush } from "../lib/push";
import { clearDeviceData } from "../lib/snapshot";
import { applyTheme, loadTheme, setTheme, type Theme } from "../lib/theme";
import { formatKst, relativeChecked } from "../lib/time";
import page from "../styles/page.module.css";
import { useCatalog } from "../ui/CatalogProvider";
import styles from "./Settings.module.css";

/** SP1 default check-in times (v1 app constants; spec 5.5.7, 12장 request 3 would move them to /health). */
export const SP1_SCHEDULE = { weekdays: ["09:00", "17:30"], weekend: ["10:00", "18:00"] } as const;
const PAUSE_DAYS = [1, 3, 7, 14] as const;

type DeviceState = "loading" | "on" | "off" | "denied" | "needs_home_screen" | "unsupported" | "unavailable";

// What this device can do about push, read fresh (permission can change in iOS Settings meanwhile).
async function readDevice(): Promise<DeviceState> {
  const support = pushSupport();
  if (support !== "ok") return support;
  const key = await apiFetch<VapidPublicKey>("GET", "/push/vapid-public-key", { model: "VapidPublicKey" });
  if (key.kind === "error" && key.status === 404) return "unavailable";
  if (permission() === "denied") return "denied";
  return (await hasLiveSubscription()) ? "on" : "off";
}

// "https://gp76.tail1234.ts.net" -> host, cut in the middle when long (spec 5.5.7).
function shortHost(beUrl: string): string {
  const host = beUrl.replace(/^https:\/\//, "");
  return host.length > 28 ? `${host.slice(0, 14)}…${host.slice(-12)}` : host;
}

// Spec 5.5.7, F7: connection, check-in notifications, schedule, pause, this device, about. No chat launcher.
export function Settings() {
  const router = useRouter();
  const toast = useToast();
  const { state, conn, recheck } = useConnection();
  const { catalog } = useCatalog();
  const online = state?.kind === "online";
  const health = state?.kind === "online" ? state.health : null;

  // ---- check-in notifications ----
  const notifyPoll = usePolling<NotifySettings>(() => apiGet<NotifySettings>("/settings/notify", "NotifySettings"));
  const [notify, setNotify] = useState<NotifySettings | null>(null);
  useEffect(() => {
    if (notifyPoll.result?.kind === "ok") setNotify(notifyPoll.result.data);
  }, [notifyPoll.result]);
  const [notifyBusy, setNotifyBusy] = useState(false);
  const notifyLock = useRef(false);

  const changePrimary = async (primary: NotifySettings["primary"]) => {
    if (notifyLock.current || !notify || primary === notify.primary) return;
    notifyLock.current = true;
    setNotifyBusy(true);
    try {
      const r = await apiFetch<NotifySettings>("PUT", "/settings/notify", { body: { primary }, model: "NotifySettings" });
      if (r.kind === "ok") setNotify(r.data);
      else toast.show({ text: failureText(r) });
    } finally {
      notifyLock.current = false;
      setNotifyBusy(false);
    }
  };

  // ---- this device's push ----
  const [device, setDevice] = useState<DeviceState>("loading");
  const beUrl = conn?.beUrl;
  const deviceSeq = useRef(0);
  const readDeviceNow = useCallback(() => {
    const mine = ++deviceSeq.current;
    void readDevice().then((d) => {
      if (mine === deviceSeq.current) setDevice(d);
    });
  }, []);
  useEffect(() => {
    if (!beUrl) return;
    readDeviceNow();
    // Back from iOS Settings (notifications turned on there): read again.
    const onVisible = () => document.visibilityState === "visible" && readDeviceNow();
    document.addEventListener("visibilitychange", onVisible);
    return () => document.removeEventListener("visibilitychange", onVisible);
  }, [beUrl, readDeviceNow]);

  const [allowing, setAllowing] = useState(false);
  const allowLock = useRef(false);
  const allow = async () => {
    if (allowLock.current) return;
    allowLock.current = true;
    setAllowing(true);
    deviceSeq.current += 1; // a slower read started before this tap does not overwrite its answer
    try {
      const r = await subscribePush();
      switch (r.kind) {
        case "subscribed":
          setDevice("on");
          void notifyPoll.refresh(); // `effective` may now be the app
          break;
        case "denied":
          if (permission() === "denied") setDevice("denied");
          else toast.show({ text: copy.settings.pushTurnOnFailed });
          break;
        case "unsupported":
          setDevice(pushSupport() === "needs_home_screen" ? "needs_home_screen" : "unsupported");
          break;
        case "unavailable":
          setDevice("unavailable");
          break;
        case "failed":
          toast.show({ text: copy.settings.pushTurnOnFailed });
          break;
      }
    } finally {
      allowLock.current = false;
      setAllowing(false);
    }
  };

  const [testing, setTesting] = useState(false);
  const testLock = useRef(false);
  const testPush = async () => {
    if (testLock.current) return;
    testLock.current = true;
    setTesting(true);
    try {
      const r = await apiFetch<PushTestResult>("POST", "/push/test", { model: "PushTestResult" });
      if (r.kind === "ok") toast.show({ text: copy.settings.testResult(r.data.ok, r.data.failed) });
      else if (r.kind === "error" && r.status === 404) {
        setDevice("unavailable");
        toast.show({ text: copy.settings.pushUnavailable });
      } else toast.show({ text: failureText(r) });
    } finally {
      testLock.current = false;
      setTesting(false);
    }
  };

  // ---- pause ----
  const pausedUntil = health?.paused_until && Date.parse(health.paused_until) > Date.parse(health.now) ? health.paused_until : null;
  const [pauseOpen, setPauseOpen] = useState(false);
  const [commandBusy, setCommandBusy] = useState(false);
  const commandLock = useRef(false);
  const command = async (text: string): Promise<boolean> => {
    if (commandLock.current) return false;
    commandLock.current = true;
    setCommandBusy(true);
    try {
      const r = await sendCommand(text);
      if (!r.ok) {
        toast.show({ text: copy.actions.failed });
        return false;
      }
      await recheck();
      return true;
    } finally {
      commandLock.current = false;
      setCommandBusy(false);
    }
  };
  const pause = async (days: number) => {
    if (await command(`/pause ${days}`)) setPauseOpen(false);
  };

  // ---- this device ----
  const [theme, setThemeState] = useState<Theme>("system");
  useEffect(() => setThemeState(loadTheme()), []);
  const chooseTheme = (t: Theme) => {
    setTheme(t);
    setThemeState(t);
  };

  const [disconnectOpen, setDisconnectOpen] = useState(false);
  const [disconnecting, setDisconnecting] = useState(false);
  const disconnectLock = useRef(false);
  const disconnect = async () => {
    if (disconnectLock.current) return;
    disconnectLock.current = true;
    setDisconnecting(true);
    try {
      try {
        await unsubscribePush();
      } catch {
        // spec 5.5.7: the device is cleared even when the BE or the browser cannot drop the subscription
      }
      await clearDeviceData();
      applyTheme("system");
      window.dispatchEvent(new Event(CONN_CHANGED));
      await router.replace("/connect/");
    } finally {
      disconnectLock.current = false;
      setDisconnecting(false);
    }
  };

  // ---- rows ----
  const lastOk = loadLastHealthOk();
  let status: ReactNode = <Skeleton size="short" />;
  if (state) {
    status =
      state.kind === "online" ? (
        <StatusDot state={state} label={copy.settings.connectedChecked(lastOk ? relativeChecked(lastOk, Date.now()) : copy.settings.checkedJustNow)} />
      ) : (
        <StatusDot state={state} />
      );
  }

  let deviceTrailing: ReactNode = null;
  let deviceNote: string | undefined;
  switch (device) {
    case "loading":
      deviceTrailing = <Skeleton size="pill" />;
      break;
    case "on":
      deviceTrailing = copy.settings.pushOn;
      break;
    case "off":
      deviceTrailing = (
        <button type="button" className={styles.pill} onClick={() => void allow()} disabled={allowing || !online}>
          {copy.settings.pushAllow}
        </button>
      );
      break;
    case "denied":
      deviceTrailing = copy.settings.pushOff;
      deviceNote = copy.settings.pushDenied;
      break;
    case "needs_home_screen":
      deviceTrailing = copy.settings.pushOff;
      deviceNote = copy.settings.needsHomeScreen;
      break;
    case "unsupported":
      deviceTrailing = copy.settings.pushOff;
      deviceNote = copy.settings.pushUnsupported;
      break;
    case "unavailable":
      deviceTrailing = copy.settings.pushOff;
      deviceNote = copy.settings.pushUnavailable;
      break;
  }

  let notifyBody: ReactNode;
  if (notify) {
    notifyBody = (
      <>
        <div className={styles.control}>
          <span className={styles.controlLabel} aria-hidden="true">
            {copy.settings.notifyWhere}
          </span>
          <Segmented
            ariaLabel={copy.settings.notifyWhere}
            options={[
              { value: "app", label: copy.settings.primaryApp },
              { value: "telegram", label: copy.settings.primaryTelegram },
            ]}
            value={notify.primary}
            onChange={(v) => void changePrimary(v)}
            disabled={notifyBusy || !online}
          />
        </div>
        {notify.effective !== notify.primary && <Row title={<span className={styles.note}>{copy.settings.effectiveTelegram}</span>} />}
      </>
    );
  } else if (notifyPoll.result && notifyPoll.result.kind !== "ok" && notifyPoll.result.kind !== "offline") {
    notifyBody = (
      <div className={styles.control}>
        <BlockError code={notifyPoll.result.kind === "error" ? notifyPoll.result.code : notifyPoll.result.kind} onRetry={() => void notifyPoll.refresh()} />
      </div>
    );
  } else if (notifyPoll.result?.kind === "offline" || state?.kind === "offline") {
    notifyBody = <Row title={<span className={styles.note}>{copy.offline.later}</span>} />;
  } else {
    notifyBody = (
      <div className={styles.control}>
        <Skeleton size="row" />
      </div>
    );
  }

  return (
    <main className={page.main}>
      <LargeTitle title={copy.settings.title} />

      <Group heading={copy.settings.connection}>
        <Row title={status} />
        {health?.polling === "down" && <Row title={<span className={styles.note}>{copy.status.telegramDown}</span>} />}
        {state?.kind === "online" && state.degraded && <Row title={<span className={styles.note}>{state.degraded}</span>} />}
        <Row title={copy.settings.address} trailing={conn ? <span className={styles.value}>{shortHost(conn.beUrl)}</span> : undefined} />
        <Row
          title={copy.settings.token}
          trailing={
            <Link href="/connect/" className={styles.link}>
              {copy.settings.reenter}
            </Link>
          }
        />
      </Group>

      <Group heading={copy.settings.notify} footer={copy.settings.notifyHelp}>
        {notifyBody}
        <div className={styles.wrap} data-testid="device-push">
          <Row title={copy.settings.devicePush} meta={deviceNote} trailing={deviceTrailing} />
        </div>
        {device !== "unavailable" && (
          <button type="button" className={styles.action} onClick={() => void testPush()} disabled={testing || !online}>
            {copy.settings.testPush}
          </button>
        )}
      </Group>

      <Group heading={copy.settings.schedule} footer={copy.settings.scheduleNote}>
        <Row title={copy.settings.weekdays} trailing={<span className={styles.value}>{SP1_SCHEDULE.weekdays.join(" · ")}</span>} />
        <Row title={copy.settings.weekend} trailing={<span className={styles.value}>{SP1_SCHEDULE.weekend.join(" · ")}</span>} />
      </Group>

      <Group heading={copy.settings.pause}>
        {pausedUntil ? (
          <Row
            title={copy.settings.pausedUntil(formatKst(pausedUntil, copy.dateStyle.monthDayTime))}
            trailing={
              <button type="button" className={styles.pill} onClick={() => void command("/unpause")} disabled={commandBusy || !online}>
                {copy.settings.resume}
              </button>
            }
          />
        ) : (
          <button type="button" className={styles.action} onClick={() => setPauseOpen(true)} disabled={!online}>
            {copy.settings.pauseRow}
          </button>
        )}
      </Group>

      <Group heading={copy.settings.device}>
        <div className={styles.control}>
          <span className={styles.controlLabel} aria-hidden="true">
            {copy.settings.theme}
          </span>
          <Segmented
            ariaLabel={copy.settings.theme}
            options={[
              { value: "system", label: copy.settings.themeSystem },
              { value: "light", label: copy.settings.themeLight },
              { value: "dark", label: copy.settings.themeDark },
            ]}
            value={theme}
            onChange={chooseTheme}
          />
        </div>
        <button type="button" className={`${styles.action} ${styles.danger}`} onClick={() => setDisconnectOpen(true)}>
          {copy.settings.disconnect}
        </button>
      </Group>

      <Group heading={copy.settings.about}>
        <Row title={copy.settings.appVersion} trailing={<span className={styles.value}>{pkg.version}</span>} />
        <Row title={copy.settings.beVersion} trailing={<span className={styles.value}>{health?.version.app ?? copy.settings.unknown}</span>} />
        <Row
          title={copy.settings.catalogVersion}
          trailing={<span className={styles.value}>{catalog?.version ?? health?.version.ui_catalog ?? copy.settings.unknown}</span>}
        />
      </Group>

      <Sheet open={pauseOpen} onClose={() => !commandBusy && setPauseOpen(false)} title={copy.settings.pauseSheet}>
        <div className={styles.choices}>
          {PAUSE_DAYS.map((n) => (
            <button key={n} type="button" className={styles.choice} onClick={() => void pause(n)} disabled={commandBusy}>
              {copy.settings.pauseDays(n)}
            </button>
          ))}
        </div>
      </Sheet>

      <Sheet open={disconnectOpen} onClose={() => !disconnecting && setDisconnectOpen(false)} ariaLabel={copy.settings.disconnectSummary}>
        <p className={styles.summary}>{copy.settings.disconnectSummary}</p>
        <div className={styles.buttons}>
          <button type="button" className={styles.keep} onClick={() => setDisconnectOpen(false)} disabled={disconnecting}>
            {copy.settings.cancel}
          </button>
          <button type="button" className={styles.confirmDanger} onClick={() => void disconnect()} disabled={disconnecting}>
            {copy.settings.disconnectConfirm}
          </button>
        </div>
      </Sheet>
    </main>
  );
}
