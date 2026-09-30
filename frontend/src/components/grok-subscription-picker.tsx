import { useEffect, useRef, useState } from "react";
import { Check, Copy, ExternalLink, Loader2 } from "lucide-react";
import { useT } from "@/lib/i18n";
import {
  useCredentials,
  usePollGrokDeviceLogin,
  useStartGrokDeviceLogin,
  type DeviceLoginPoll,
} from "@/lib/hooks";

/** The Grok credential type whose creation is a login, not a form. */
const CREDENTIAL_TYPE = "xai_grok_subscription";

interface PendingLogin {
  deviceAuthId: string;
  userCode: string;
  verificationUri: string;
  /** ISO deadline, computed here from `expiresIn` -- the poll endpoint is
   * stateless and cannot work it out for itself. */
  expiresAt: string;
  intervalSeconds: number;
}

interface Failure {
  kind: "expired" | "error" | "start";
  message?: string;
}

/** Same controlled `value`/`onChange` contract as `CredentialPicker` and
 * `ChatGptSubscriptionPicker`, for `xai_grok_subscription`. Creation is a
 * device-code login, not a form -- the type declares ZERO fields, so the
 * generic picker would write an unusable credential. */
export function GrokSubscriptionPicker({
  value,
  onChange,
}: {
  value: string;
  onChange: (credentialId: string) => void;
}) {
  const t = useT();
  const { data: credentials = [], refetch } = useCredentials(CREDENTIAL_TYPE);
  const startLogin = useStartGrokDeviceLogin();
  const pollLogin = usePollGrokDeviceLogin();
  const [pending, setPending] = useState<PendingLogin | null>(null);
  const [failure, setFailure] = useState<Failure | null>(null);
  const [copied, setCopied] = useState(false);
  const [secondsLeft, setSecondsLeft] = useState(0);

  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Every attempt gets a generation number. A poll request already in flight
  // when the user cancels, retries, or navigates away belongs to an older
  // generation and throws its own result away -- otherwise a stale "complete"
  // could fire `onChange` for an attempt nobody is waiting on any more, or a
  // stale "expired" could stamp an error over a freshly started attempt.
  const attemptRef = useRef(0);

  const stopPolling = () => {
    attemptRef.current += 1;
    if (timerRef.current) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  };

  useEffect(
    () => () => {
      // Unmount: kill the timer AND invalidate the generation, so nothing
      // sets state on a component that is already gone.
      attemptRef.current += 1;
      if (timerRef.current) clearTimeout(timerRef.current);
    },
    [],
  );

  // Countdown, purely informational. Keyed on `pending` so it starts, stops,
  // and cleans itself up with the attempt it belongs to.
  useEffect(() => {
    if (!pending) return;
    const tick = () =>
      setSecondsLeft(Math.max(0, Math.round((Date.parse(pending.expiresAt) - Date.now()) / 1000)));
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, [pending]);

  // Called from inside the poll timer's own callback, so there is no pending
  // timeout left to clear -- only the generation guard matters here.
  const finish = async (result: DeviceLoginPoll, generation: number) => {
    timerRef.current = null;
    if (result.status === "complete" && result.credentialId) {
      setPending(null);
      // Pull the new account into the dropdown BEFORE handing its id up, so
      // the select never renders a value with no matching option.
      try {
        await refetch();
      } catch {
        /* the list refreshes on its own soon enough; the id is what matters */
      }
      if (attemptRef.current !== generation) return;
      onChange(result.credentialId);
      return;
    }
    // "expired" and "error" both end the attempt; the user starts a new one
    // (a new device code -- the old one cannot be resumed).
    setPending(null);
    setFailure({
      kind: result.status === "expired" ? "expired" : "error",
      message: result.error ?? undefined,
    });
  };

  const schedulePoll = (login: PendingLogin, generation: number) => {
    timerRef.current = setTimeout(() => {
      void (async () => {
        const body = {
          deviceAuthId: login.deviceAuthId,
          userCode: login.userCode,
          expiresAt: login.expiresAt,
        };
        let result: DeviceLoginPoll;
        try {
          result = await pollLogin.mutateAsync(body);
        } catch (err) {
          if (attemptRef.current !== generation) return;
          // A poll that fails at the transport/HTTP level ends the attempt
          // rather than retrying blind: the alternative is a spinner that
          // never stops while every request 500s.
          timerRef.current = null;
          setPending(null);
          setFailure({ kind: "error", message: err instanceof Error ? err.message : String(err) });
          return;
        }
        if (attemptRef.current !== generation) return;
        if (result.status === "pending") {
          schedulePoll(login, generation);
          return;
        }
        await finish(result, generation);
      })();
    }, login.intervalSeconds * 1000);
  };

  const start = async () => {
    stopPolling();
    setFailure(null);
    setCopied(false);
    const generation = attemptRef.current;
    let started;
    try {
      started = await startLogin.mutateAsync();
    } catch (err) {
      if (attemptRef.current !== generation) return;
      setFailure({ kind: "start", message: err instanceof Error ? err.message : String(err) });
      return;
    }
    if (attemptRef.current !== generation) return;
    const login: PendingLogin = {
      deviceAuthId: started.deviceAuthId,
      userCode: started.userCode,
      verificationUri: started.verificationUri,
      expiresAt: new Date(Date.now() + started.expiresIn * 1000).toISOString(),
      intervalSeconds: Math.max(1, started.interval),
    };
    setPending(login);
    schedulePoll(login, generation);
  };

  const cancel = () => {
    stopPolling();
    setPending(null);
  };

  const copyCode = () => {
    if (!pending) return;
    void navigator.clipboard?.writeText(pending.userCode).then(
      () => setCopied(true),
      () => setCopied(false),
    );
  };

  const mmss = `${Math.floor(secondsLeft / 60)}:${String(secondsLeft % 60).padStart(2, "0")}`;

  return (
    <div className="flex w-full min-w-0 flex-col gap-2">
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full min-w-0 rounded-md border border-border bg-background/40 px-3 py-2 text-sm text-foreground outline-none focus:border-primary/50"
      >
        <option value="">{t("Select a Grok account…", "Grok-Konto auswählen …")}</option>
        {credentials.map((c) => (
          <option key={c.id} value={c.id}>
            {c.name}
          </option>
        ))}
      </select>

      {pending ? (
        <div className="space-y-2.5 rounded-md border border-dashed border-border bg-background/20 p-3">
          <ol className="space-y-2.5">
            <li className="flex items-start gap-2 text-sm">
              <span className="mt-0.5 grid h-4 w-4 shrink-0 place-items-center rounded-full border border-primary/50 text-[10px] font-semibold text-primary">
                1
              </span>
              <span className="min-w-0">
                {t("Open", "Öffne")}{" "}
                <a
                  href={pending.verificationUri}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex items-center gap-1 break-all text-primary underline underline-offset-2"
                >
                  {pending.verificationUri.replace(/^https?:\/\//, "")}
                  <ExternalLink className="h-3 w-3 shrink-0" />
                </a>
              </span>
            </li>
            <li className="flex items-start gap-2 text-sm">
              <span className="mt-0.5 grid h-4 w-4 shrink-0 place-items-center rounded-full border border-primary/50 text-[10px] font-semibold text-primary">
                2
              </span>
              <div className="min-w-0">
                <div>
                  {t("Enter this code on that page:", "Diesen Code auf der Seite eingeben:")}
                </div>
                <div className="mt-1 flex items-center gap-2">
                  <span className="select-all rounded-md border border-border bg-background/50 px-2 py-1 font-mono text-base tracking-[0.2em]">
                    {pending.userCode}
                  </span>
                  <button
                    type="button"
                    onClick={copyCode}
                    className="inline-flex items-center gap-1 rounded-md border border-border px-2 py-1 text-[11px] text-muted-foreground hover:text-foreground"
                  >
                    {copied ? <Check className="h-3 w-3" /> : <Copy className="h-3 w-3" />}
                    {copied ? t("Copied", "Kopiert") : t("Copy", "Kopieren")}
                  </button>
                </div>
                {/* The one thing people get wrong on this flow: the link does
                    not carry the code, so the page will sit there waiting. */}
                <p className="mt-1 text-[11px] text-muted-foreground">
                  {t(
                    "If the page still asks for a code, type or paste it yourself.",
                    "Wenn die Seite noch nach einem Code fragt, selbst eintippen oder einfügen.",
                  )}
                </p>
              </div>
            </li>
          </ol>
          <div className="flex flex-wrap items-center justify-between gap-2 border-t border-border/60 pt-2">
            <span className="inline-flex items-center gap-1.5 text-[11px] text-muted-foreground">
              <Loader2 className="h-3 w-3 animate-spin" />
              {t("Waiting for confirmation…", "Warte auf Bestätigung …")}
              {secondsLeft > 0 && (
                <span className="font-mono">
                  {t(`code expires in ${mmss}`, `Code läuft ab in ${mmss}`)}
                </span>
              )}
            </span>
            <button
              type="button"
              onClick={cancel}
              className="rounded-md border border-border px-2 py-1 text-[11px] text-muted-foreground hover:text-foreground"
            >
              {t("Cancel", "Abbrechen")}
            </button>
          </div>
        </div>
      ) : (
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={start}
            disabled={startLogin.isPending}
            className="inline-flex items-center gap-1.5 rounded-md border border-border px-3 py-2 text-xs text-muted-foreground hover:text-foreground disabled:cursor-not-allowed disabled:opacity-50"
          >
            {startLogin.isPending && <Loader2 className="h-3 w-3 animate-spin" />}
            {t("Sign in with Grok", "Mit Grok anmelden")}
          </button>
          <span className="text-[11px] text-muted-foreground">
            {t(
              "Uses your personal subscription — agents on it can only be started manually.",
              "Nutzt dein persönliches Abo — Agenten damit lassen sich nur manuell starten.",
            )}
          </span>
        </div>
      )}

      {failure && (
        <p className="text-[11px] text-[color:var(--status-warning)]">
          {failure.kind === "expired"
            ? t(
                "The code expired before it was confirmed. Start again to get a new one.",
                "Der Code ist abgelaufen, bevor er bestätigt wurde. Starte erneut für einen neuen Code.",
              )
            : failure.kind === "start"
              ? t("Could not start the sign-in.", "Anmeldung konnte nicht gestartet werden.")
              : t(
                  "Sign-in failed. Try again.",
                  "Anmeldung fehlgeschlagen. Bitte erneut versuchen.",
                )}
          {failure.message ? ` ${failure.message}` : ""}
        </p>
      )}
    </div>
  );
}
