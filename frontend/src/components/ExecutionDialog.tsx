import { useEffect, useMemo, useState } from "react";

import {
  useConfirmDraft,
  useDraft,
  useExecuteDraft,
} from "../hooks/useApi";
import { ApiError } from "../lib/api";
import type { Draft, ExecutionResult } from "../lib/types";
import { money, percent, price } from "../lib/format";
import { Badge, Button, Row, Spinner } from "./ui";
import { AlertIcon, CheckIcon, ShieldIcon, XIcon } from "./icons";

type Stage = "review" | "arming" | "done";

function checkLabel(code: string): string {
  return code.replace(/_/g, " ");
}

function describeError(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error) return error.message;
  return String(error);
}

export default function ExecutionDialog({
  draftId,
  onClose,
  onFilled,
}: {
  draftId: string;
  onClose: () => void;
  onFilled?: () => void;
}) {
  const detail = useDraft(draftId, true);
  const confirm = useConfirmDraft();
  const execute = useExecuteDraft();
  const [stage, setStage] = useState<Stage>("review");
  const [ack, setAck] = useState(false);
  const [token, setToken] = useState<string | null>(null);
  const [result, setResult] = useState<ExecutionResult | null>(null);
  const [now, setNow] = useState(() => Date.now());
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !execute.isPending) onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose, execute.isPending]);

  const draft: Draft | undefined = detail.data?.draft;
  const remaining = draft
    ? Math.max(0, Math.floor((new Date(draft.expires_at).getTime() - now) / 1000))
    : 0;

  const failures = useMemo(
    () => (draft?.checks ?? []).filter((check) => !check.ok),
    [draft],
  );

  const canArm =
    Boolean(draft) &&
    draft!.executable &&
    remaining > 0 &&
    !confirm.isPending &&
    stage === "review";

  const arm = () => {
    setError(null);
    confirm.mutate(draftId, {
      onSuccess: (response) => {
        setToken(response.token);
        setStage("arming");
      },
      onError: (mutationError) => setError(describeError(mutationError)),
    });
  };

  const send = () => {
    if (!token) return;
    setError(null);
    execute.mutate(
      { draftId, token },
      {
        onSuccess: (response) => {
          setResult(response);
          setStage("done");
          setToken(null);
          onFilled?.();
        },
        onError: (mutationError) => {
          setError(describeError(mutationError));
          setToken(null);
          setStage("review");
          setAck(false);
          detail.refetch();
        },
      },
    );
  };

  return (
    <div className="fixed inset-0 z-[70] flex items-center justify-center p-4">
      <div
        className="absolute inset-0 animate-fade-in bg-ink-950/80 backdrop-blur-sm"
        onClick={() => {
          if (!execute.isPending) onClose();
        }}
      />
      <div className="relative z-10 w-full max-w-[560px] animate-slide-in rounded-xl border border-line bg-ink-850 shadow-drawer">
        <header className="flex items-start justify-between gap-3 border-b border-line/70 px-5 py-4">
          <div>
            <div className="flex items-center gap-2">
              <ShieldIcon className="h-4 w-4 text-gold-400" />
              <h2 className="text-[14px] font-semibold text-paper">
                {stage === "done" ? "Execution result" : "Confirm execution"}
              </h2>
            </div>
            <p className="mt-1 text-[11.5px] text-fog">
              {stage === "review"
                ? "Live re-validation happens again on the server before the order is sent."
                : stage === "arming"
                  ? "A single-use token is armed. Sending is the irreversible step."
                  : "The order path has completed."}
            </p>
          </div>
          <button
            onClick={onClose}
            disabled={execute.isPending}
            className="rounded-md p-1.5 text-fog transition-colors hover:bg-ink-800 hover:text-paper disabled:opacity-40"
            aria-label="Close"
          >
            <XIcon className="h-4 w-4" />
          </button>
        </header>

        <div className="max-h-[70vh] space-y-4 overflow-y-auto px-5 py-4">
          {stage !== "done" && !draft && detail.isLoading ? (
            <div className="flex items-center gap-2 py-8 text-[12px] text-fog">
              <Spinner className="h-4 w-4" /> Loading live draft…
            </div>
          ) : null}

          {detail.isError ? (
            <div className="rounded-lg border border-short/40 bg-short/10 px-3 py-2.5 text-[12px] text-short">
              {describeError(detail.error)}
            </div>
          ) : null}

          {stage === "done" && result ? (
            <ResultCard result={result} />
          ) : null}

          {stage !== "done" && draft ? (
            <>
              <div className="rounded-lg border border-line/70 bg-ink-900/60 px-4 py-3">
                <div className="mb-2 flex items-center justify-between">
                  <Badge tone={draft.side === "long" ? "long" : "short"}>
                    {draft.side} {draft.lots} lots
                  </Badge>
                  <span
                    className={`font-mono text-[11.5px] ${
                      remaining <= 0 ? "text-short" : remaining < 20 ? "text-warn" : "text-fog"
                    }`}
                  >
                    {remaining > 0 ? `${remaining}s left` : "expired"}
                  </span>
                </div>
                <div className="grid grid-cols-2 gap-x-6">
                  <Row label="Reference" value={price(draft.reference_price)} />
                  <Row label="Stop loss" value={price(draft.sl)} tone="short" />
                  <Row label="Take profit" value={price(draft.tp)} tone="long" />
                  <Row label="Risk" value={money(draft.risk_usd)} />
                  <Row label="Risk %" value={percent(draft.risk_pct)} />
                  <Row label="R:R" value={`${draft.rr.toFixed(2)}`} />
                  <Row
                    label="Worst case"
                    value={money(draft.worst_case_usd)}
                    tone="short"
                  />
                  <Row label="Margin" value={money(draft.margin)} />
                </div>
              </div>

              {draft.live ? (
                <div className="flex items-center justify-between rounded-lg border border-line/60 bg-ink-900/40 px-4 py-2 font-mono text-[11px] text-fog">
                  <span>
                    bid {price(draft.live.bid)} / ask {price(draft.live.ask)}
                  </span>
                  <span>
                    spread {draft.live.spread_points.toFixed(0)} pts · drift{" "}
                    {draft.live.drift_atr.toFixed(2)} ATR
                  </span>
                </div>
              ) : null}

              {draft.blackout ? (
                <div className="flex items-start gap-2 rounded-lg border border-warn/40 bg-warn/10 px-3 py-2.5 text-[12px] text-warn">
                  <AlertIcon className="mt-0.5 h-4 w-4 shrink-0" />
                  <span>
                    Inside a blackout for {draft.blackout.name} ({draft.blackout.currency}).
                    Execution is blocked until it clears.
                  </span>
                </div>
              ) : null}

              <div className="space-y-1.5">
                <div className="text-[10.5px] font-semibold uppercase tracking-[0.14em] text-fog">
                  Live checks
                </div>
                <div className="grid grid-cols-1 gap-1">
                  {(draft.checks ?? []).map((check) => (
                    <div
                      key={check.code}
                      className={`flex items-start gap-2 rounded-md border px-2.5 py-1.5 text-[11.5px] ${
                        check.ok
                          ? "border-line/50 bg-ink-900/30 text-fog"
                          : "border-short/40 bg-short/10 text-short"
                      }`}
                    >
                      {check.ok ? (
                        <CheckIcon className="mt-0.5 h-3 w-3 shrink-0 text-long" />
                      ) : (
                        <AlertIcon className="mt-0.5 h-3 w-3 shrink-0" />
                      )}
                      <span className="shrink-0 font-mono text-[10px] uppercase tracking-wide opacity-70">
                        {checkLabel(check.code)}
                      </span>
                      <span className="text-paper/70">{check.message}</span>
                    </div>
                  ))}
                </div>
              </div>

              {stage === "arming" ? (
                <label className="flex cursor-pointer items-start gap-2.5 rounded-lg border border-gold-500/30 bg-gold-500/[0.07] px-3 py-3">
                  <input
                    type="checkbox"
                    checked={ack}
                    onChange={(event) => setAck(event.target.checked)}
                    className="mt-0.5 h-4 w-4 accent-gold-500"
                  />
                  <span className="text-[12px] leading-snug text-paper/85">
                    I understand this sends a live demo market order for{" "}
                    <b className="font-mono">
                      {draft.side.toUpperCase()} {draft.lots}{" "}
                      {detail.data?.analysis?.symbol ?? "XAUUSD"}
                    </b>{" "}
                    with SL {price(draft.sl)} and TP {price(draft.tp)}.
                  </span>
                </label>
              ) : null}

              {error ? (
                <div className="flex items-start gap-2 rounded-lg border border-short/40 bg-short/10 px-3 py-2.5 text-[12px] text-short">
                  <AlertIcon className="mt-0.5 h-4 w-4 shrink-0" />
                  <div>
                    <div>{error}</div>
                    <div className="mt-1 text-[11px] text-short/70">
                      Any token already issued was burned. Re-check the draft to continue.
                    </div>
                  </div>
                </div>
              ) : null}

              {failures.length > 0 && stage === "review" ? (
                <div className="text-[11.5px] text-short">
                  Execute is disabled: {failures.map((check) => checkLabel(check.code)).join(", ")}.
                </div>
              ) : null}
            </>
          ) : null}
        </div>

        <footer className="flex items-center justify-between gap-3 border-t border-line/70 px-5 py-3.5">
          <div className="text-[10.5px] text-fog">
            {stage === "arming"
              ? "Token is bound to this draft and expires with it."
              : "No order is sent until you confirm twice."}
          </div>
          <div className="flex items-center gap-2">
            <Button variant="ghost" onClick={onClose} disabled={execute.isPending}>
              {stage === "done" ? "Close" : "Cancel"}
            </Button>
            {stage === "review" ? (
              <Button variant="primary" onClick={arm} loading={confirm.isPending} disabled={!canArm}>
                Review & arm
              </Button>
            ) : null}
            {stage === "arming" ? (
              <Button
                variant={draft?.side === "long" ? "long" : "short"}
                onClick={send}
                loading={execute.isPending}
                disabled={!ack || remaining <= 0}
              >
                Send {draft?.side === "long" ? "buy" : "sell"} order
              </Button>
            ) : null}
            {stage === "done" ? (
              <Button variant="primary" onClick={onClose}>
                Done
              </Button>
            ) : null}
          </div>
        </footer>
      </div>
    </div>
  );
}

function ResultCard({ result }: { result: ExecutionResult }) {
  const filled = result.state === "filled" && result.confirmed;
  return (
    <div className="space-y-3">
      <div
        className={`flex items-start gap-3 rounded-lg border px-4 py-3 ${
          filled ? "border-long/40 bg-long/10" : "border-warn/40 bg-warn/10"
        }`}
      >
        {filled ? (
          <CheckIcon className="mt-0.5 h-4 w-4 shrink-0 text-long" />
        ) : (
          <AlertIcon className="mt-0.5 h-4 w-4 shrink-0 text-warn" />
        )}
        <div>
          <div className={`text-[13px] font-semibold ${filled ? "text-long" : "text-warn"}`}>
            {filled ? "Order filled" : "Order sent but unconfirmed"}
          </div>
          <div className="mt-0.5 text-[11.5px] text-paper/70">
            {filled
              ? `Position ${result.position?.ticket} is open.`
              : "No position appeared within 10 s. Check the terminal before retrying."}
          </div>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-x-6 rounded-lg border border-line/70 bg-ink-900/60 px-4 py-3">
        <Row label="Symbol" value={result.position?.symbol ?? result.order?.symbol ?? "—"} />
        <Row
          label="Filled price"
          value={price(result.position?.price_open ?? result.order?.filled_price ?? null)}
        />
        <Row label="Lots" value={result.position?.lots ?? result.draft.lots} />
        <Row label="Stop loss" value={price(result.position?.sl ?? result.draft.sl)} tone="short" />
        <Row label="Take profit" value={price(result.position?.tp ?? result.draft.tp)} tone="long" />
        <Row label="Ticket" value={result.position?.ticket ?? result.order?.ticket ?? "—"} />
      </div>
      <div className="text-[11px] text-fog">
        State <span className="font-mono text-paper/80">{result.state}</span> · draft{" "}
        <span className="font-mono text-paper/80">{result.draft.state}</span>
      </div>
    </div>
  );
}
