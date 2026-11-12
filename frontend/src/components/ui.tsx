import type { ButtonHTMLAttributes, ReactNode } from "react";

type Tone = "neutral" | "long" | "short" | "gold" | "warn" | "info";

const TONE: Record<Tone, { text: string; chip: string; dot: string }> = {
  neutral: { text: "text-paper", chip: "border-line bg-ink-800 text-paper/80", dot: "bg-fog" },
  long: { text: "text-long", chip: "border-long/35 bg-long/10 text-long", dot: "bg-long" },
  short: { text: "text-short", chip: "border-short/35 bg-short/10 text-short", dot: "bg-short" },
  gold: { text: "text-gold-400", chip: "border-gold-500/35 bg-gold-500/10 text-gold-300", dot: "bg-gold-400" },
  warn: { text: "text-warn", chip: "border-warn/35 bg-warn/10 text-warn", dot: "bg-warn" },
  info: { text: "text-info", chip: "border-info/35 bg-info/10 text-info", dot: "bg-info" },
};

export function Panel({
  title,
  subtitle,
  actions,
  children,
  className = "",
  bodyClassName = "p-5",
}: {
  title?: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  bodyClassName?: string;
}) {
  return (
    <section
      className={`rounded-xl border border-line/80 bg-ink-850/70 shadow-panel backdrop-blur-sm ${className}`}
    >
      {title || actions ? (
        <header className="flex items-start justify-between gap-4 border-b border-line/60 px-5 py-3.5">
          <div>
            <h2 className="text-[13px] font-semibold uppercase tracking-[0.14em] text-paper/85">
              {title}
            </h2>
            {subtitle ? (
              <p className="mt-0.5 text-[12px] text-fog">{subtitle}</p>
            ) : null}
          </div>
          {actions ? <div className="flex shrink-0 items-center gap-2">{actions}</div> : null}
        </header>
      ) : null}
      <div className={bodyClassName}>{children}</div>
    </section>
  );
}

export function Metric({
  label,
  value,
  sub,
  tone = "neutral",
  hint,
}: {
  label: string;
  value: ReactNode;
  sub?: ReactNode;
  tone?: Tone;
  hint?: string;
}) {
  return (
    <div
      className="rounded-xl border border-line/80 bg-ink-850/70 px-4 py-3.5 shadow-panel"
      title={hint}
    >
      <div className="text-[11px] font-medium uppercase tracking-[0.16em] text-fog">{label}</div>
      <div className={`mt-1.5 font-mono text-[22px] leading-tight tabular-nums ${TONE[tone].text}`}>
        {value}
      </div>
      {sub ? <div className="mt-1 text-[12px] text-fog">{sub}</div> : null}
    </div>
  );
}

export function Badge({
  tone = "neutral",
  children,
  dot = false,
  className = "",
}: {
  tone?: Tone;
  children: ReactNode;
  dot?: boolean;
  className?: string;
}) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-md border px-2 py-[3px] text-[11px] font-semibold uppercase tracking-[0.1em] ${TONE[tone].chip} ${className}`}
    >
      {dot ? <span className={`h-1.5 w-1.5 rounded-full ${TONE[tone].dot}`} /> : null}
      {children}
    </span>
  );
}

type ButtonVariant = "primary" | "secondary" | "ghost" | "danger" | "long" | "short";

const VARIANTS: Record<ButtonVariant, string> = {
  primary:
    "border-gold-500/70 bg-gold-500 text-ink-950 hover:bg-gold-400 hover:border-gold-400 disabled:bg-gold-600/40 disabled:text-ink-950/50",
  secondary:
    "border-line bg-ink-800 text-paper hover:border-fog/40 hover:bg-ink-700 disabled:text-fog/40",
  ghost:
    "border-transparent bg-transparent text-fog hover:text-paper hover:bg-ink-800 disabled:text-fog/30",
  danger:
    "border-short/60 bg-short/15 text-short hover:bg-short/25 disabled:border-line disabled:bg-transparent disabled:text-fog/40",
  long: "border-long/60 bg-long/15 text-long hover:bg-long/25 disabled:border-line disabled:bg-transparent disabled:text-fog/40",
  short:
    "border-short/60 bg-short/15 text-short hover:bg-short/25 disabled:border-line disabled:bg-transparent disabled:text-fog/40",
};

export function Button({
  variant = "secondary",
  size = "md",
  loading = false,
  className = "",
  children,
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: ButtonVariant;
  size?: "sm" | "md" | "lg";
  loading?: boolean;
}) {
  const sizing =
    size === "sm"
      ? "h-7 px-2.5 text-[11px]"
      : size === "lg"
        ? "h-10 px-5 text-[13px]"
        : "h-8 px-3.5 text-[12px]";
  return (
    <button
      {...rest}
      disabled={rest.disabled || loading}
      className={`inline-flex items-center justify-center gap-2 rounded-md border font-semibold uppercase tracking-[0.08em] transition-colors disabled:cursor-not-allowed ${sizing} ${VARIANTS[variant]} ${className}`}
    >
      {loading ? <Spinner className="h-3.5 w-3.5" /> : null}
      {children}
    </button>
  );
}

export function Spinner({ className = "h-4 w-4" }: { className?: string }) {
  return (
    <svg className={`animate-spin ${className}`} viewBox="0 0 24 24" fill="none" aria-hidden>
      <circle cx="12" cy="12" r="9" stroke="currentColor" strokeOpacity="0.25" strokeWidth="3" />
      <path d="M21 12a9 9 0 0 0-9-9" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
    </svg>
  );
}

export function ProgressBar({ pct, className = "" }: { pct: number; className?: string }) {
  return (
    <div className={`h-1.5 w-full overflow-hidden rounded-full bg-ink-700 ${className}`}>
      <div
        className="h-full rounded-full bg-gold-500 transition-[width] duration-300"
        style={{ width: `${Math.max(0, Math.min(100, pct))}%` }}
      />
    </div>
  );
}

export function EmptyState({
  title,
  message,
  action,
}: {
  title: string;
  message?: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-line/80 px-6 py-10 text-center">
      <div className="text-[13px] font-semibold text-paper/80">{title}</div>
      {message ? <div className="max-w-md text-[12px] leading-relaxed text-fog">{message}</div> : null}
      {action ? <div className="mt-2">{action}</div> : null}
    </div>
  );
}

export function Row({
  label,
  value,
  mono = true,
  tone = "neutral",
}: {
  label: ReactNode;
  value: ReactNode;
  mono?: boolean;
  tone?: Tone;
}) {
  return (
    <div className="flex items-baseline justify-between gap-3 py-1.5">
      <span className="shrink-0 text-[12px] text-fog">{label}</span>
      <span
        className={`min-w-0 truncate text-right ${mono ? "font-mono tabular-nums" : ""} text-[12.5px] ${TONE[tone].text}`}
        title={typeof value === "string" ? value : undefined}
      >
        {value}
      </span>
    </div>
  );
}
