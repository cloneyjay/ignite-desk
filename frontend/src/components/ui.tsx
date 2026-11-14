import type { ButtonHTMLAttributes, ReactNode } from "react";

type Tone = "neutral" | "long" | "short" | "gold" | "warn" | "info";

const TONE: Record<Tone, { text: string; chip: string; dot: string; rule: string }> = {
  neutral: {
    text: "text-paper",
    chip: "border-line bg-ink-850 text-fog",
    dot: "bg-fog",
    rule: "border-l-line",
  },
  long: {
    text: "text-long",
    chip: "border-long/35 bg-long/[0.08] text-long",
    dot: "bg-long",
    rule: "border-l-long",
  },
  short: {
    text: "text-short",
    chip: "border-short/35 bg-short/[0.08] text-short",
    dot: "bg-short",
    rule: "border-l-short",
  },
  gold: {
    text: "text-gold-300",
    chip: "border-gold-500/35 bg-gold-500/[0.08] text-gold-300",
    dot: "bg-gold-400",
    rule: "border-l-gold-500",
  },
  warn: {
    text: "text-warn",
    chip: "border-warn/30 bg-warn/[0.07] text-warn",
    dot: "bg-warn",
    rule: "border-l-warn",
  },
  info: {
    text: "text-info",
    chip: "border-info/30 bg-info/[0.07] text-info",
    dot: "bg-info",
    rule: "border-l-info",
  },
};

export function Panel({
  title,
  subtitle,
  actions,
  children,
  className = "",
  bodyClassName = "panel-body",
}: {
  title?: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  bodyClassName?: string;
}) {
  return (
    <section className={`panel ${className}`}>
      {title || actions ? (
        <header className="panel-header flex-wrap gap-y-2">
          <div className="min-w-0 flex-1 basis-[190px]">
            <h2 className="panel-title">{title}</h2>
            {subtitle ? <p className="panel-subtitle">{subtitle}</p> : null}
          </div>
          {actions ? <div className="ml-auto flex shrink-0 items-center gap-2">{actions}</div> : null}
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
      className={`border border-line/80 border-l-2 bg-ink-900 px-4 py-3.5 ${TONE[tone].rule}`}
      title={hint}
    >
      <div className="text-[10px] font-semibold uppercase tracking-[0.12em] text-text-muted">
        {label}
      </div>
      <div className={`mt-2 font-mono text-[24px] leading-none tracking-[-0.02em] tabular-nums ${TONE[tone].text}`}>
        {value}
      </div>
      {sub ? <div className="mt-2 truncate text-[11.5px] text-fog">{sub}</div> : null}
    </div>
  );
}

export function Badge({
  tone = "neutral",
  children,
  dot = false,
  size = "md",
  className = "",
}: {
  tone?: Tone;
  children: ReactNode;
  dot?: boolean;
  size?: "sm" | "md" | "lg";
  className?: string;
}) {
  const sizing =
    size === "sm"
      ? "px-1.5 py-[1px] text-[9.5px] gap-1"
      : size === "lg"
        ? "px-2.5 py-[4px] text-[11px] gap-2"
        : "px-2 py-[2px] text-[10px] gap-1.5";
  const dotSize = size === "sm" ? "h-1 w-1" : size === "lg" ? "h-1.5 w-1.5" : "h-1 w-1";

  return (
    <span
      className={`inline-flex items-center ${sizing} rounded-sm border font-semibold uppercase tracking-[0.08em] ${TONE[tone].chip} ${className}`}
    >
      {dot ? <span className={`${dotSize} rounded-full ${TONE[tone].dot}`} /> : null}
      {children}
    </span>
  );
}

type ButtonVariant =
  | "primary"
  | "secondary"
  | "ghost"
  | "danger"
  | "danger-outline"
  | "long"
  | "short";

const VARIANTS: Record<ButtonVariant, string> = {
  primary:
    "border-gold-500 bg-gold-500 text-ink-950 hover:border-gold-400 hover:bg-gold-400 disabled:border-gold-600/40 disabled:bg-gold-600/30 disabled:text-ink-950/50",
  secondary:
    "border-line bg-transparent text-paper hover:border-fog/60 hover:bg-ink-850 disabled:text-fog/40",
  ghost:
    "border-transparent bg-transparent text-fog hover:bg-ink-850 hover:text-paper disabled:text-fog/30",
  danger:
    "border-short/60 bg-short/15 text-short hover:bg-short/25 disabled:border-line disabled:bg-transparent disabled:text-fog/40",
  "danger-outline":
    "border-short/60 bg-transparent text-short hover:bg-short/10 disabled:border-line disabled:bg-transparent disabled:text-fog/40",
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
      ? "h-8 px-2.5 text-[10px]"
      : size === "lg"
        ? "h-10 px-5 text-[11px]"
        : "h-9 px-3.5 text-[10.5px]";
  return (
    <button
      {...rest}
      disabled={rest.disabled || loading}
      className={`inline-flex items-center justify-center gap-2 rounded-sm border font-semibold uppercase tracking-[0.08em] transition-colors disabled:cursor-not-allowed ${sizing} ${VARIANTS[variant]} ${className}`}
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
    <div className={`h-1 w-full overflow-hidden bg-ink-700 ${className}`}>
      <div
        className="h-full bg-gold-500 transition-[width] duration-300"
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
    <div className="flex flex-col items-center justify-center gap-2 border border-dashed border-line/80 px-6 py-12 text-center">
      <div className="text-[12px] font-semibold uppercase tracking-[0.1em] text-paper/80">
        {title}
      </div>
      {message ? (
        <div className="max-w-md text-[12px] leading-relaxed text-fog">{message}</div>
      ) : null}
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
    <div className="flex items-baseline justify-between gap-3 border-b border-line/25 py-1.5 last:border-0">
      <span className="shrink-0 text-[11.5px] text-fog">{label}</span>
      <span
        className={`min-w-0 truncate text-right ${mono ? "font-mono tabular-nums" : ""} text-[12px] ${TONE[tone].text}`}
        title={typeof value === "string" ? value : undefined}
      >
        {value}
      </span>
    </div>
  );
}
