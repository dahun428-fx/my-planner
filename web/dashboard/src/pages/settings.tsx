import Link from "next/link";
import { type FormEvent, useEffect, useState } from "react";
import { StateNotice } from "../components/StateNotice";
import { type ApiResult, getHealth } from "../lib/api";
import { useConnection } from "../lib/ConnectionProvider";
import { normalizeBeUrl } from "../lib/connection";
import { SETTINGS_TEXT as T } from "../lib/labels";

type Outcome = { kind: "error"; text: string } | { kind: "result"; result: ApiResult<unknown> } | null;

// An API token is `secrets.token_urlsafe(32)`: visible ASCII only. A header cannot carry anything else.
const TOKEN = /^[\x21-\x7e]+$/;

/** BE URL and API token for this browser (spec 13.1). "연결 확인" saves them and calls GET /health. */
export default function Settings() {
  const { ready, conn, connect } = useConnection();
  const [url, setUrl] = useState("");
  const [token, setToken] = useState("");
  const [busy, setBusy] = useState(false);
  const [outcome, setOutcome] = useState<Outcome>(null);

  useEffect(() => {
    if (ready && conn) {
      setUrl(`${conn.beUrl}/api/v1`);
      setToken(conn.token);
    }
  }, [ready, conn]);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    const n = normalizeBeUrl(url);
    if (!n.ok) return setOutcome({ kind: "error", text: T.urlErrors[n.reason] });
    const t = token.trim();
    if (!t) return setOutcome({ kind: "error", text: T.tokenMissing });
    if (!TOKEN.test(t)) return setOutcome({ kind: "error", text: T.tokenInvalid });
    const next = { beUrl: n.url, token: t };
    setBusy(true);
    setOutcome(null);
    try {
      const result = await getHealth(next);
      connect(next);
      setOutcome({ kind: "result", result });
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <h1>{T.title}</h1>
      <p className="lead">{T.intro}</p>
      <form className="panel form" onSubmit={onSubmit} noValidate>
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
      {outcome?.kind === "error" && (
        <p className="field-error" role="alert">
          {outcome.text}
        </p>
      )}
      {outcome?.kind === "result" &&
        (outcome.result.kind === "ok" ? (
          <div className="notice" data-kind="ok" role="status">
            <p>{T.ok}</p>
            <p>
              <Link href="/">{T.home}</Link>
            </p>
          </div>
        ) : (
          <>
            <p className="meta">{T.saved}</p>
            <StateNotice result={outcome.result} settingsLink={false} />
          </>
        ))}
    </>
  );
}
