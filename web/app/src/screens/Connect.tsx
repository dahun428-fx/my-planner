import Link from "next/link";
import { useRouter } from "next/router";
import { type ClipboardEvent, type FormEvent, type KeyboardEvent, useEffect, useRef, useState } from "react";
import { type ApiResult, deleteDevice, getHealth, postPair } from "../api/client";
import { LargeTitle } from "../components/LargeTitle";
import { useToast } from "../components/Toast";
import { useConnection } from "../lib/ConnectionProvider";
import {
  type Conn,
  defaultBeUrl,
  deviceLabel,
  loadConn,
  loadDeviceId,
  normalizeBeUrl,
  normalizeToken,
  parsePairHash,
  saveConn,
  saveLastHealthOk,
} from "../lib/connection";
import { copy } from "../lib/copy";
import { isIos, isStandalone } from "../lib/platform";
import { askPermission, forgetPushForOtherBe, pushSupport, reRegisterPush, subscribePush } from "../lib/push";
import styles from "./Connect.module.css";

type Line = { tone: "ok" | "bad"; text: string } | null;

const URL_REASON = {
  not_https: copy.connect.notHttps,
  out_of_range: copy.connect.outOfRange,
  invalid: copy.connect.invalidUrl,
} as const;

const CODE_LEN = 6;
const EMPTY_DIGITS: readonly string[] = Array.from({ length: CODE_LEN }, () => "");

// What the connect screen says when a call did not get through (both modes).
function trouble(r: ApiResult<unknown>): string {
  switch (r.kind) {
    case "offline":
      return copy.connect.unreachable;
    case "rate_limited":
      return copy.status.tooMany;
    case "safe_mode":
      return copy.status.safeMode;
    case "unauthorized":
      return copy.connect.badToken;
    case "error":
      return copy.errors.block(r.code);
    case "ok":
      return "";
  }
}

// Spec 5.5.8 / F1 and device pairing spec 5.3: a 6-digit pairing code by default (the BE address
// filled from NEXT_PUBLIC_DEFAULT_BE_URL or the QR's `#be=`), the address and key form behind
// "열쇠로 연결". Either way the connection is checked against /health and saved only when the
// secretary answers.
export function Connect() {
  const router = useRouter();
  const toast = useToast();
  // SP9 9.1: reached from the more screen once connected; the first connect has nowhere to go back to.
  const connected = useConnection().conn !== null;
  const [guideOnly, setGuideOnly] = useState<boolean | null>(null);
  // The iPhone home screen app offers "알림 허용하고 시작하기"; a computer browser just "시작하기".
  const [offerPush, setOfferPush] = useState(false);
  // The iPhone home screen app: no auto-submit, so the permission prompt stays on a tap (5.3).
  const [homeApp, setHomeApp] = useState(false);
  const [mode, setMode] = useState<"code" | "key">("code");
  // Filled from the build's default or the QR and shown as text until "주소 바꾸기".
  const [urlFixed, setUrlFixed] = useState(false);
  const [digits, setDigits] = useState<readonly string[]>(EMPTY_DIGITS);
  const boxes = useRef<(HTMLInputElement | null)[]>([]);
  const [url, setUrl] = useState("");
  const [token, setToken] = useState("");
  const [line, setLine] = useState<Line>(null);
  const [busy, setBusy] = useState(false);
  const running = useRef(false);
  const goWhenChecked = useRef(false);
  // A permission request started by the tap that also asked to go (F1 step 2).
  const asked = useRef<Promise<NotificationPermission> | null>(null);

  // Device checks need the browser, so they run after mount (the page is prerendered).
  // Then the address: the QR's `#be=` beats the build's default (it is the address a connected device
  // really uses). The hash goes from the address bar at once; an iPhone/iPad Safari tab never uses it
  // (3.3: the code would be spent on a tab whose storage the home screen app cannot see).
  useEffect(() => {
    const ios = isIos();
    const standalone = isStandalone();
    setGuideOnly(ios && !standalone);
    setOfferPush(ios && standalone && pushSupport() === "ok");
    setHomeApp(ios && standalone);
    const hash = parsePairHash(window.location.hash);
    if (hash) {
      // Cleared in a Safari tab too, unread there: tab sync (iCloud) would carry the code on.
      try {
        window.history.replaceState(window.history.state, "", window.location.pathname + window.location.search);
      } catch {
        // no history API: the hash stays, nothing else changes
      }
    }
    if (ios && !standalone) return;
    const be = hash?.be ?? defaultBeUrl();
    if (be) {
      setUrl(be);
      setUrlFixed(normalizeBeUrl(be).ok);
    }
    if (hash?.code) {
      setDigits(hash.code.split(""));
      if (!(ios && standalone) && be) void pair(be, hash.code, null);
    }
    // Once, on arrival.
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
    if (r.kind === "ok") {
      setLine({ tone: "ok", text: copy.connect.ok });
      return conn;
    }
    setLine({ tone: "bad", text: trouble(r) });
    return null;
  }

  // Saves a connection /health accepted, subscribes when asked, and goes today.
  async function finish(conn: Conn, permission: Promise<NotificationPermission> | null, device?: { id: number }) {
    await forgetPushForOtherBe(conn.beUrl);
    // A device token this connection replaces is revoked at its BE first (spec 5.4), best effort.
    const old = loadConn();
    const oldId = loadDeviceId();
    if (old && oldId !== null && old.token !== conn.token) {
      try {
        await deleteDevice(oldId, old);
      } catch {
        // any answer: the new connection is saved anyway
      }
    }
    saveConn(conn, device);
    saveLastHealthOk(new Date().toISOString());
    // Same BE: the subscription this browser already has goes to the BE again under the new token.
    if (!permission) await reRegisterPush();
    // Subscribe when asked; whatever the answer (denied, no push on this BE, a failure), go on:
    // settings shows this device's push state and can try again.
    if (permission) {
      const r = await subscribePush(permission);
      if (r.kind === "unavailable") toast.show({ text: copy.settings.pushUnavailable });
      else if (r.kind === "failed" || r.kind === "unsupported") toast.show({ text: copy.settings.pushTurnOnFailed });
    }
    await router.push("/");
  }

  function clearDigits() {
    setDigits(EMPTY_DIGITS);
    boxes.current[0]?.focus();
  }

  // Device pairing spec 5.3: POST /pair (no key), then /health with the device token it gave.
  // A 401 is read by its code here: `bad_code` is a wrong or spent code, `unauthorized` a BE without /pair.
  async function pair(beInput: string, code: string, permission: Promise<NotificationPermission> | null) {
    if (running.current) return;
    const norm = normalizeBeUrl(beInput);
    if (!norm.ok) {
      setUrlFixed(false);
      setLine({ tone: "bad", text: URL_REASON[norm.reason] });
      return;
    }
    running.current = true;
    setBusy(true);
    try {
      setLine({ tone: "ok", text: copy.connect.checking });
      const label = deviceLabel(navigator.userAgent, copy.devices.whereApp);
      const r = await postPair(norm.url, { code, client: "app", label });
      if (r.kind === "error" && r.status === 401) {
        if (r.code === "bad_code") {
          setLine({ tone: "bad", text: copy.connect.badCode });
          clearDigits();
        } else {
          setLine({ tone: "bad", text: copy.connect.oldBe });
          setMode("key");
        }
        return;
      }
      if (r.kind !== "ok") {
        setLine({ tone: "bad", text: trouble(r) });
        return;
      }
      const conn = { beUrl: norm.url, token: r.data.token };
      const h = await getHealth(conn);
      if (h.kind !== "ok") {
        // Not saved, so the new device would stay on the list with nobody holding its token.
        void deleteDevice(r.data.device.id, conn).catch(() => undefined);
        setLine({ tone: "bad", text: trouble(h) });
        return;
      }
      setLine({ tone: "ok", text: copy.connect.ok });
      await finish(conn, permission, { id: r.data.device.id });
    } finally {
      running.current = false;
      setBusy(false);
    }
  }

  const code = digits.join("");
  const codeDone = code.length === CODE_LEN;

  function goCode(withPush: boolean) {
    // As in `go`: asked before any await, only for an address and code that can be tried at all.
    const usable = normalizeBeUrl(url).ok && codeDone;
    const permission = withPush && usable ? askPermission() : null;
    void pair(url, code, permission);
  }

  // Typing, pasting or the one-time-code autofill put text into box `at`: its digits go into the
  // boxes from there on. The sixth digit sends the code, except in the home screen app (a tap does).
  function fillFrom(at: number, text: string) {
    const got = text.replace(/\D/g, "");
    const next = [...digits];
    if (got === "") {
      next[at] = "";
      setDigits(next);
      return;
    }
    let i = at;
    for (const ch of got) {
      if (i >= CODE_LEN) break;
      next[i++] = ch;
    }
    setDigits(next);
    boxes.current[Math.min(i, CODE_LEN - 1)]?.focus();
    const full = next.join("");
    if (full.length === CODE_LEN && !homeApp) void pair(url, full, null);
  }

  function onBoxKey(at: number, e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Backspace" && digits[at] === "" && at > 0) {
      e.preventDefault();
      const next = [...digits];
      next[at - 1] = "";
      setDigits(next);
      boxes.current[at - 1]?.focus();
    }
  }

  function onBoxPaste(at: number, e: ClipboardEvent<HTMLInputElement>) {
    e.preventDefault();
    fillFrom(at, e.clipboardData.getData("text"));
  }

  function onCodeSubmit(e: FormEvent) {
    e.preventDefault();
    if (codeDone && url.trim() !== "") goCode(offerPush);
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
      if (proceed && conn) await finish(conn, permission);
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
      <p className={styles.intro}>{mode === "code" && guideOnly === false ? copy.connect.codeIntro : copy.connect.intro}</p>
      {guideOnly === true && <p className={styles.guide}>{copy.connect.homeScreenGuide}</p>}
      {guideOnly === false && mode === "code" && (
        <form className={styles.form} onSubmit={onCodeSubmit} noValidate>
          <div className={styles.field}>
            {urlFixed ? (
              <div className={styles.fixed}>
                <span className={styles.label}>{copy.connect.urlLabel}</span>
                <span className={styles.address}>{url.replace(/^https:\/\//, "")}</span>
                <button type="button" className={styles.link} onClick={() => setUrlFixed(false)}>
                  {copy.connect.changeUrl}
                </button>
              </div>
            ) : (
              <>
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
                />
                <span id="be-url-help" className={styles.help}>
                  {copy.connect.urlHelp}
                </span>
              </>
            )}
          </div>
          <fieldset className={styles.codeField}>
            <legend className={styles.label}>{copy.connect.codeLabel}</legend>
            <div className={styles.boxes}>
              {digits.map((d, i) => (
                <input
                  key={i}
                  ref={(el) => {
                    boxes.current[i] = el;
                  }}
                  className={`${styles.box} ${i === 3 ? styles.split : ""}`}
                  aria-label={copy.connect.digitLabel(i + 1)}
                  type="text"
                  inputMode="numeric"
                  pattern="[0-9]*"
                  autoComplete={i === 0 ? "one-time-code" : "off"}
                  value={d}
                  readOnly={busy}
                  onChange={(e) => fillFrom(i, e.target.value.replace(d, "") || e.target.value)}
                  onKeyDown={(e) => onBoxKey(i, e)}
                  onPaste={(e) => onBoxPaste(i, e)}
                  onFocus={(e) => e.target.select()}
                />
              ))}
            </div>
          </fieldset>
          <p className={line?.tone === "bad" ? styles.bad : styles.ok} role="status">
            {line?.text}
          </p>
          <button type="submit" className={styles.start} disabled={busy || !codeDone || url.trim() === ""}>
            {offerPush ? copy.connect.startWithPush : copy.connect.start}
          </button>
          {offerPush && (
            <button type="button" className={styles.later} disabled={busy || !codeDone || url.trim() === ""} onClick={() => goCode(false)}>
              {copy.connect.pushLater}
            </button>
          )}
          <button
            type="button"
            className={styles.switch}
            onClick={() => {
              setLine(null);
              setMode("key");
            }}
          >
            {copy.connect.useKey}
          </button>
        </form>
      )}
      {guideOnly === false && mode === "key" && (
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
          <button
            type="button"
            className={styles.switch}
            onClick={() => {
              setLine(null);
              setMode("code");
            }}
          >
            {copy.connect.useCode}
          </button>
        </form>
      )}
    </main>
  );
}
