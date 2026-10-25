import Link from "next/link";
import { useRouter } from "next/router";
import { type FormEvent, useEffect, useRef, useState } from "react";
import { getHealth } from "../api/client";
import { LargeTitle } from "../components/LargeTitle";
import { useToast } from "../components/Toast";
import { useConnection } from "../lib/ConnectionProvider";
import { type Conn, normalizeBeUrl, normalizeToken, saveConn, saveLastHealthOk } from "../lib/connection";
import { copy } from "../lib/copy";
import { isIos, isStandalone } from "../lib/platform";
import { askPermission, forgetPushForOtherBe, pushSupport, subscribePush } from "../lib/push";
import styles from "./Connect.module.css";

type Line = { tone: "ok" | "bad"; text: string } | null;

const URL_REASON = {
  not_https: copy.connect.notHttps,
  out_of_range: copy.connect.outOfRange,
  invalid: copy.connect.invalidUrl,
} as const;

// Spec 5.5.8 / F1: address and key, checked against /health; saved only when the secretary answers.
export function Connect() {
  const router = useRouter();
  const toast = useToast();
  // SP9 9.1: reached from the more screen once connected; the first connect has nowhere to go back to.
  const connected = useConnection().conn !== null;
  const [guideOnly, setGuideOnly] = useState<boolean | null>(null);
  // The iPhone home screen app offers "알림 허용하고 시작하기"; a computer browser just "시작하기".
  const [offerPush, setOfferPush] = useState(false);
  const [url, setUrl] = useState("");
  const [token, setToken] = useState("");
  const [line, setLine] = useState<Line>(null);
  const [busy, setBusy] = useState(false);
  const running = useRef(false);
  const goWhenChecked = useRef(false);
  // A permission request started by the tap that also asked to go (F1 step 2).
  const asked = useRef<Promise<NotificationPermission> | null>(null);

  // Device checks need the browser, so they run after mount (the page is prerendered).
  useEffect(() => {
    setGuideOnly(isIos() && !isStandalone());
    setOfferPush(isIos() && isStandalone() && pushSupport() === "ok");
  }, []);

  // Returns the connection to save when /health accepted it, otherwise null (and says why).
  async function check(): Promise<Conn | null> {
    const key = normalizeToken(token);
    if (!url.trim() || !key) {
      setLine(null);
      return null;
    }
    const norm = normalizeBeUrl(url);
    if (!norm.ok) {
      setLine({ tone: "bad", text: URL_REASON[norm.reason] });
      return null;
    }
    const conn = { beUrl: norm.url, token: key };
    setLine({ tone: "ok", text: copy.connect.checking });
    const r = await getHealth(conn);
    switch (r.kind) {
      case "ok":
        setLine({ tone: "ok", text: copy.connect.ok });
        return conn;
      case "unauthorized":
        setLine({ tone: "bad", text: copy.connect.badToken });
        return null;
      case "offline":
        setLine({ tone: "bad", text: copy.connect.unreachable });
        return null;
      case "rate_limited":
        setLine({ tone: "bad", text: copy.status.tooMany });
        return null;
      case "safe_mode":
        setLine({ tone: "bad", text: copy.status.safeMode });
        return null;
      case "error":
        setLine({ tone: "bad", text: copy.errors.block(r.code) });
        return null;
    }
  }

  async function run(go: boolean) {
    if (running.current) {
      // Pressing the button blurs a field first, so a check is often already running: join it.
      if (go) {
        goWhenChecked.current = true;
        setBusy(true);
      }
      return;
    }
    running.current = true;
    if (go) setBusy(true); // a check on leaving a field must not disable the button under the finger
    try {
      const conn = await check();
      const proceed = go || goWhenChecked.current;
      goWhenChecked.current = false;
      const permission = asked.current;
      if (proceed) asked.current = null;
      if (proceed && conn) {
        await forgetPushForOtherBe(conn.beUrl);
        saveConn(conn);
        saveLastHealthOk(new Date().toISOString());
        // Subscribe when asked; whatever the answer (denied, no push on this BE, a failure), go on:
        // settings shows this device's push state and can try again.
        if (permission) {
          const r = await subscribePush(permission);
          if (r.kind === "unavailable") toast.show({ text: copy.settings.pushUnavailable });
          else if (r.kind === "failed" || r.kind === "unsupported") toast.show({ text: copy.settings.pushTurnOnFailed });
        }
        await router.push("/");
      }
    } finally {
      running.current = false;
      setBusy(false);
    }
  }

  function go(withPush: boolean) {
    // Asked here, before any await, so the prompt still counts as an answer to this tap (iOS).
    // Only for an address and key that can be checked at all; the check itself still decides.
    const usable = normalizeBeUrl(url).ok && normalizeToken(token) !== "";
    if (withPush && usable && !asked.current) asked.current = askPermission();
    void run(true);
  }

  // Nothing to check until both fields hold something besides spaces.
  const filled = url.trim() !== "" && token.trim() !== "";

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    if (filled) go(offerPush);
  }

  return (
    <main className={styles.main}>
      {connected && (
        <nav className={styles.bar}>
          <Link href="/more/" className={styles.back}>
            {copy.connect.back}
          </Link>
        </nav>
      )}
      <LargeTitle title={copy.connect.title} />
      <p className={styles.intro}>{copy.connect.intro}</p>
      {guideOnly === true && <p className={styles.guide}>{copy.connect.homeScreenGuide}</p>}
      {guideOnly === false && (
        <form className={styles.form} onSubmit={onSubmit} noValidate>
          <div className={styles.field}>
            <label className={styles.label} htmlFor="be-url">
              {copy.connect.urlLabel}
            </label>
            <input
              id="be-url"
              aria-describedby="be-url-help"
              className={styles.input}
              type="url"
              inputMode="url"
              autoCapitalize="off"
              autoCorrect="off"
              autoComplete="off"
              spellCheck={false}
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              onBlur={() => void run(false)}
            />
            <span id="be-url-help" className={styles.help}>
              {copy.connect.urlHelp}
            </span>
          </div>
          <div className={styles.field}>
            <label className={styles.label} htmlFor="be-token">
              {copy.connect.tokenLabel}
            </label>
            <input
              id="be-token"
              aria-describedby="be-token-help"
              className={styles.input}
              type="password"
              autoCapitalize="off"
              autoCorrect="off"
              autoComplete="off"
              spellCheck={false}
              value={token}
              onChange={(e) => setToken(e.target.value)}
              onBlur={() => void run(false)}
            />
            <span id="be-token-help" className={styles.help}>
              {copy.connect.tokenHelp}
            </span>
          </div>
          <p className={line?.tone === "bad" ? styles.bad : styles.ok} role="status">
            {line?.text}
          </p>
          <button type="submit" className={styles.start} disabled={busy || !filled}>
            {offerPush ? copy.connect.startWithPush : copy.connect.start}
          </button>
          {offerPush && (
            <button type="button" className={styles.later} disabled={busy || !filled} onClick={() => go(false)}>
              {copy.connect.pushLater}
            </button>
          )}
        </form>
      )}
    </main>
  );
}
