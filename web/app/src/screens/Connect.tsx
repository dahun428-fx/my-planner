import { useRouter } from "next/router";
import { type FormEvent, useEffect, useRef, useState } from "react";
import { getHealth } from "../api/client";
import { LargeTitle } from "../components/LargeTitle";
import { type Conn, normalizeBeUrl, normalizeToken, saveConn, saveLastHealthOk } from "../lib/connection";
import { copy } from "../lib/copy";
import { isIos, isStandalone } from "../lib/platform";
import { askPermission, pushSupport, subscribePush } from "../lib/push";
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
        saveConn(conn);
        saveLastHealthOk(new Date().toISOString());
        // Subscribe when asked; whatever the answer (denied, no push on this BE, a failure), go on:
        // settings shows this device's push state and can try again.
        if (permission) await subscribePush(permission);
        await router.push("/");
      }
    } finally {
      running.current = false;
      setBusy(false);
    }
  }

  function go(withPush: boolean) {
    // Asked here, before any await, so the prompt still counts as an answer to this tap (iOS).
    if (withPush && !asked.current) asked.current = askPermission();
    void run(true);
  }

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    go(offerPush);
  }

  return (
    <main className={styles.main}>
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
          <button type="submit" className={styles.start} disabled={busy}>
            {offerPush ? copy.connect.startWithPush : copy.connect.start}
          </button>
          {offerPush && (
            <button type="button" className={styles.later} disabled={busy} onClick={() => go(false)}>
              {copy.connect.pushLater}
            </button>
          )}
        </form>
      )}
    </main>
  );
}
