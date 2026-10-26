import { useRouter } from "next/router";
import { type ClipboardEvent, type FormEvent, type KeyboardEvent, useEffect, useRef, useState } from "react";
import { StateNotice } from "../components/StateNotice";
import { type ApiResult, getHealth } from "../lib/api";
import { useConnection } from "../lib/ConnectionProvider";
import { type Conn, defaultBeUrl, normalizeBeUrl } from "../lib/connection";
import { SETTINGS_TEXT as T } from "../lib/labels";
import { deviceName, type PairHash, postPair, readPairHash } from "../lib/pairing";

// `saved`: the check ran after the connection was kept, so a failed answer says "저장했어요" above it.
type Outcome = { kind: "error"; text: string } | { kind: "result"; result: ApiResult<unknown>; saved: boolean } | { kind: "cleared" } | null;
type Mode = "code" | "token";

const EMPTY = ["", "", "", "", "", ""];

// An API token is `secrets.token_urlsafe(32)`: visible ASCII only. A header cannot carry anything else.
const TOKEN = /^[\x21-\x7e]+$/;

/** DU-04: where the BE address and the token come from. The address is a pattern, never a real name. */
function Help() {
  const H = T.help;
  return (
    <details className="panel help">
      <summary>{H.summary}</summary>
      <div className="help-body">
        <h2 className="help-title">{H.urlTitle}</h2>
        <p>{H.urlBody}</p>
        <pre className="help-code">
          <code>{H.urlCommand}</code>
        </pre>
        <p>
          <code className="help-shape">{H.urlShape}</code>
        </p>
        <p className="meta">{H.urlShapeNote}</p>
        <h2 className="help-title">{H.tokenTitle}</h2>
        <p>{H.tokenBody}</p>
        <pre className="help-code">
          <code>{H.tokenCommand}</code>
        </pre>
        <p className="meta">{H.tokenEnv}</p>
      </div>
    </details>
  );
}

/**
 * How this browser reaches the BE (spec 13.1, device pairing spec 6). The default is the six digit code made
 * on a connected device: the sixth digit sends `POST /pair` and the token it returns is checked with GET
 * /health like a typed one. The address and API token form stays one link away. A good answer goes straight
 * to the home screen (DU-04).
 */
export default function Settings() {
  const { ready, conn, connect, disconnect } = useConnection();
  const router = useRouter();
  const [mode, setMode] = useState<Mode>("code");
  const [url, setUrl] = useState("");
  // Code mode folds a prefilled address that passes the check (spec 6.1); "주소 바꾸기" opens it.
  const [urlOpen, setUrlOpen] = useState(true);
  const [token, setToken] = useState("");
  const [digits, setDigits] = useState(EMPTY);
  const [busy, setBusy] = useState(false);
  const [clearing, setClearing] = useState(false);
  const [outcome, setOutcome] = useState<Outcome>(null);
  const boxes = useRef<(HTMLInputElement | null)[]>([]);
  const inFlight = useRef(false);
  const hash = useRef<PairHash | null | undefined>(undefined);
  const started = useRef(false);

  // Spec 3.3: `#be=…&code=…` is read once and taken off the address at once. Read in every browser, iPhone
  // Safari too: the app skips it in a Safari tab (its home screen app keeps other storage), but a dashboard
  // tab is the dashboard itself.
  useEffect(() => {
    if (hash.current !== undefined) return;
    hash.current = readPairHash(window.location.hash);
    if (hash.current) window.history.replaceState(window.history.state, "", window.location.pathname + window.location.search);
  }, []);

  // Once the saved connection is known: the hash address beats the saved one, which beats the build default.
  useEffect(() => {
    if (!ready || started.current) return;
    started.current = true;
    const h = hash.current ?? null;
    const address = h?.be ?? (conn ? (conn.kind === "api" ? `${conn.beUrl}/api/v1` : conn.beUrl) : (defaultBeUrl() ?? ""));
    setUrl(address);
    setUrlOpen(!normalizeBeUrl(address).ok);
    if (conn?.kind === "api") setToken(conn.token);
    setMode(!h && conn?.kind === "api" ? "token" : "code");
    if (h?.code) {
      setDigits(h.code.split(""));
      void submitCode(h.code, address);
    }
    // runs once (started): later changes of conn are this screen's own connect and disconnect
  }, [ready, conn]);

  async function onTokenSubmit(e: FormEvent) {
    e.preventDefault();
    const n = normalizeBeUrl(url);
    if (!n.ok) return setOutcome({ kind: "error", text: T.urlErrors[n.reason] });
    const t = token.trim();
    if (!t) return setOutcome({ kind: "error", text: T.tokenMissing });
    if (!TOKEN.test(t)) return setOutcome({ kind: "error", text: T.tokenInvalid });
    await check({ beUrl: n.url, token: t, kind: "api" });
  }

  // Saves first and checks after, so a BE that is off keeps the address (spec 13.1).
  async function check(next: Conn) {
    setBusy(true);
    setOutcome(null);
    try {
      const result = await getHealth(next);
      connect(next);
      setOutcome({ kind: "result", result, saved: true });
      if (result.kind === "ok") void router.push("/");
    } finally {
      setBusy(false);
    }
  }

  // Device pairing spec 5.3: `/pair` errors are read by their code, not folded into "token is wrong".
  async function submitCode(code: string, address: string = url) {
    if (inFlight.current) return;
    const n = normalizeBeUrl(address);
    if (!n.ok) {
      setUrlOpen(true);
      return setOutcome({ kind: "error", text: T.urlErrors[n.reason] });
    }
    inFlight.current = true;
    setBusy(true);
    setOutcome(null);
    try {
      const label = T.deviceLabel(deviceName(navigator.userAgent, navigator.maxTouchPoints));
      const r = await postPair(n.url, { code, client: "dashboard", label });
      if (r.kind === "bad_code") {
        setDigits(EMPTY);
        boxes.current[0]?.focus();
        return setOutcome({ kind: "error", text: T.badCode });
      }
      if (r.kind === "old_be") {
        setMode("token");
        return setOutcome({ kind: "error", text: T.oldBe });
      }
      // off, 429, safe mode: the same notices as a typed token's check, with nothing saved
      if (r.kind !== "ok") return setOutcome({ kind: "result", result: r, saved: false });
      setDigits(EMPTY);
      await check({ beUrl: n.url, token: r.data.token, kind: "device", deviceId: r.data.device.id });
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  }

  // Typed, pasted or filled by the browser's one-time-code: digits spread from box `at` (a whole code from
  // the first box). The sixth digit sends it.
  function putDigits(at: number, raw: string) {
    const ds = raw.replace(/\D/g, "");
    const next = [...digits];
    if (ds === "") {
      next[at] = "";
      return setDigits(next);
    }
    let i = ds.length >= EMPTY.length ? 0 : at;
    for (const d of ds) {
      if (i >= EMPTY.length) break;
      next[i++] = d;
    }
    setDigits(next);
    boxes.current[Math.min(i, EMPTY.length - 1)]?.focus();
    if (next.every((d) => d !== "")) void submitCode(next.join(""));
  }

  function onDigit(at: number, value: string) {
    const prev = digits[at];
    // typed over a filled box: keep the new digit only
    const v = prev && value.length === 2 ? (value.startsWith(prev) ? value.slice(1) : value.slice(0, 1)) : value;
    putDigits(at, v);
  }

  function onPaste(at: number, e: ClipboardEvent<HTMLInputElement>) {
    e.preventDefault();
    putDigits(at, e.clipboardData.getData("text"));
  }

  function onKey(at: number, e: KeyboardEvent<HTMLInputElement>) {
    if (e.key !== "Backspace" || digits[at] !== "" || at === 0) return;
    e.preventDefault();
    const next = [...digits];
    next[at - 1] = "";
    setDigits(next);
    boxes.current[at - 1]?.focus();
  }

  function onCodeSubmit(e: FormEvent) {
    e.preventDefault();
    if (digits.every((d) => d !== "")) void submitCode(digits.join(""));
  }

  function switchMode(to: Mode) {
    setMode(to);
    setOutcome(null);
    if (to === "code") setUrlOpen(!normalizeBeUrl(url).ok);
  }

  async function onClear() {
    setClearing(true);
    try {
      await disconnect();
    } finally {
      setClearing(false);
    }
    const fallback = defaultBeUrl();
    setUrl(fallback ?? "");
    setUrlOpen(!fallback);
    setToken("");
    setDigits(EMPTY);
    setMode("code");
    setOutcome({ kind: "cleared" });
  }

  const shown = normalizeBeUrl(url);
  const urlField = (
    <label className="field">
      <span>{T.url}</span>
      <input
        name="url"
        type="url"
        inputMode="url"
        autoComplete="off"
        autoCapitalize="off"
        spellCheck={false}
        placeholder={T.urlHint}
        value={url}
        onChange={(e) => setUrl(e.target.value)}
      />
    </label>
  );

  return (
    <>
      <h1>{T.title}</h1>
      <p className="lead">{T.intro}</p>
      {mode === "code" ? (
        <form className="panel form" onSubmit={onCodeSubmit} noValidate>
          {urlOpen || !shown.ok ? (
            urlField
          ) : (
            <div className="field">
              <span>{T.url}</span>
              <p className="url-fixed">
                <code>{shown.url}</code>
                <button type="button" className="text-button" onClick={() => setUrlOpen(true)}>
                  {T.changeUrl}
                </button>
              </p>
            </div>
          )}
          <div className="field" role="group" aria-labelledby="code-label">
            <span id="code-label">{T.code}</span>
            <p className="meta">{T.codeLead}</p>
            <div className="code-boxes">
              {digits.map((d, i) => (
                <input
                  key={i}
                  ref={(el) => {
                    boxes.current[i] = el;
                  }}
                  className="code-box"
                  name={`code-${i + 1}`}
                  inputMode="numeric"
                  pattern="[0-9]*"
                  autoComplete={i === 0 ? "one-time-code" : "off"}
                  aria-label={T.codeDigit(i + 1)}
                  value={d}
                  readOnly={busy}
                  onChange={(e) => onDigit(i, e.target.value)}
                  onPaste={(e) => onPaste(i, e)}
                  onKeyDown={(e) => onKey(i, e)}
                />
              ))}
            </div>
          </div>
          <button type="submit" className="button" disabled={busy || digits.some((d) => d === "")}>
            {busy ? T.connecting : T.check}
          </button>
        </form>
      ) : (
        <form className="panel form" onSubmit={onTokenSubmit} noValidate>
          {urlField}
          <label className="field">
            <span>{T.token}</span>
            <input
              name="token"
              type="password"
              autoComplete="off"
              spellCheck={false}
              value={token}
              onChange={(e) => setToken(e.target.value)}
            />
          </label>
          <button type="submit" className="button" disabled={busy}>
            {busy ? T.checking : T.check}
          </button>
        </form>
      )}
      <p className="mode-switch">
        <button type="button" className="text-button" onClick={() => switchMode(mode === "code" ? "token" : "code")}>
          {mode === "code" ? T.useToken : T.useCode}
        </button>
      </p>
      {outcome?.kind === "error" && (
        <p className="field-error" role="alert">
          {outcome.text}
        </p>
      )}
      {/* A good answer goes home at once (the band there says it is on); only a failed check stays. */}
      {outcome?.kind === "result" && outcome.result.kind !== "ok" && (
        <>
          {outcome.saved && <p className="meta">{T.saved}</p>}
          <StateNotice result={outcome.result} settingsLink={false} />
        </>
      )}
      {outcome?.kind === "cleared" && (
        <p className="meta" role="status">
          {T.cleared}
        </p>
      )}
      {ready && conn && (
        <p className="mode-switch">
          <button type="button" className="text-button" onClick={() => void onClear()} disabled={clearing}>
            {clearing ? T.clearing : T.clear}
          </button>
        </p>
      )}
      <Help />
    </>
  );
}
