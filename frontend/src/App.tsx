import { NavLink, Navigate, Outlet, Route, Routes, useLocation } from "react-router-dom";

import { useEventStream, type StreamStatus } from "./hooks/useEventStream";
import { useHealth, useSettings, useUpdateSettings } from "./hooks/useApi";
import { useToast } from "./components/Toast";
import { Badge } from "./components/ui";
import {
  AlertIcon,
  BoltIcon,
  CandleIcon,
  ClockIcon,
  GridIcon,
  HistoryIcon,
  NewsIcon,
  PowerIcon,
} from "./components/icons";
import { time } from "./lib/format";
import Portfolio from "./pages/Portfolio";
import Watchlist from "./pages/Watchlist";
import History from "./pages/History";
import News from "./pages/News";
import { useEffect, useState } from "react";

const NAV = [
  { to: "/", label: "Portfolio", icon: GridIcon, end: true },
  { to: "/watchlist", label: "Watchlist", icon: CandleIcon, end: false },
  { to: "/history", label: "History", icon: HistoryIcon, end: false },
  { to: "/news", label: "News & calendar", icon: NewsIcon, end: false },
];

const PAGES: Record<string, { title: string; subtitle: string }> = {
  "/": { title: "Portfolio", subtitle: "Equity, exposure and open risk" },
  "/watchlist": { title: "Watchlist", subtitle: "Analyse a symbol, then confirm an order" },
  "/history": { title: "History", subtitle: "Closed trades and performance" },
  "/news": { title: "News & calendar", subtitle: "Fundamentals and deterministic blackouts" },
};

function Sidebar() {
  const health = useHealth();
  const settings = useSettings();
  const update = useUpdateSettings();
  const { push } = useToast();
  const kill = settings.data?.kill_switch ?? health.data?.kill_switch ?? false;

  const toggle = () => {
    const next = !kill;
    if (!next) {
      const ok = window.confirm(
        "Release the kill switch? Execution will be allowed again if every other guard passes.",
      );
      if (!ok) return;
    }
    update.mutate(
      { kill_switch: next },
      {
        onError: (error: Error) =>
          push({ tone: "danger", title: "Could not change kill switch", message: error.message }),
      },
    );
  };

  const terminal = health.data?.terminal;
  const kronos = health.data?.kronos;
  const mcp = health.data?.mcp;

  return (
    <aside className="flex w-[236px] shrink-0 flex-col border-r border-line/70 bg-ink-900/80">
      <div className="flex items-center gap-2.5 px-5 pb-5 pt-5">
        <div className="flex h-9 w-9 items-center justify-center rounded-lg border border-gold-500/30 bg-gold-500/10 text-gold-400">
          <BoltIcon className="h-5 w-5" />
        </div>
        <div className="leading-none">
          <div className="text-[15px] font-bold tracking-[0.24em] text-paper">IGNITE</div>
          <div className="mt-1 text-[10px] font-medium uppercase tracking-[0.32em] text-gold-500/80">
            Desk
          </div>
        </div>
      </div>

      <nav className="flex flex-col gap-1 px-3">
        {NAV.map(({ to, label, icon: Icon, end }) => (
          <NavLink
            key={to}
            to={to}
            end={end}
            className={({ isActive }) =>
              `group flex items-center gap-3 rounded-lg px-3 py-2 text-[13px] font-medium transition-colors ${
                isActive
                  ? "bg-gold-500/10 text-gold-300 shadow-[inset_2px_0_0_rgba(217,166,60,0.8)]"
                  : "text-fog hover:bg-ink-800 hover:text-paper"
              }`
            }
          >
            <Icon className="h-4 w-4" />
            {label}
          </NavLink>
        ))}
      </nav>

      <div className="mt-auto space-y-3 px-3 pb-4">
        <div className="rounded-lg border border-line/70 bg-ink-850/70 p-3">
          <div className="mb-2 flex items-center justify-between">
            <span className="text-[10px] font-semibold uppercase tracking-[0.16em] text-fog">
              Systems
            </span>
            <span
              className={`h-1.5 w-1.5 rounded-full ${
                health.data?.ok ? "bg-long" : "bg-short"
              } ${health.data?.ok ? "" : "animate-pulseSoft"}`}
            />
          </div>
          <SystemRow
            label="MT5 terminal"
            value={terminal?.state ?? (health.isError ? "unreachable" : "…")}
            ok={Boolean(terminal?.connected)}
          />
          <SystemRow
            label="MCP tools"
            value={mcp ? `${mcp.tools}` : "…"}
            ok={Boolean(mcp?.reachable)}
          />
          <SystemRow
            label="Kronos"
            value={kronos?.ready ? (kronos.model ?? "ready") : "offline"}
            ok={Boolean(kronos?.ready)}
          />
          <SystemRow
            label="Mode"
            value={health.data?.terminal?.server ?? "demo"}
            ok={true}
            neutral
          />
        </div>

        <button
          onClick={toggle}
          disabled={update.isPending || settings.isLoading}
          className={`flex w-full items-center justify-between rounded-lg border px-3 py-2.5 text-left transition-colors disabled:opacity-60 ${
            kill
              ? "border-short/50 bg-short/10 text-short"
              : "border-line/70 bg-ink-850/70 text-fog hover:border-short/40 hover:text-short"
          }`}
        >
          <span className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.12em]">
            <PowerIcon className="h-3.5 w-3.5" />
            Kill switch
          </span>
          <span
            className={`relative h-4 w-8 rounded-full transition-colors ${
              kill ? "bg-short/70" : "bg-ink-600"
            }`}
          >
            <span
              className={`absolute top-0.5 h-3 w-3 rounded-full bg-paper transition-transform ${
                kill ? "translate-x-[18px]" : "translate-x-0.5"
              }`}
            />
          </span>
        </button>
      </div>
    </aside>
  );
}

function SystemRow({
  label,
  value,
  ok,
  neutral = false,
}: {
  label: string;
  value: string;
  ok: boolean;
  neutral?: boolean;
}) {
  return (
    <div className="flex items-center justify-between py-[3px]">
      <span className="text-[11px] text-fog">{label}</span>
      <span
        className={`flex items-center gap-1.5 font-mono text-[10.5px] ${
          neutral ? "text-fog" : ok ? "text-long" : "text-short"
        }`}
      >
        {!neutral ? (
          <span className={`h-1 w-1 rounded-full ${ok ? "bg-long" : "bg-short"}`} />
        ) : null}
        {value}
      </span>
    </div>
  );
}

function Header({ streamStatus }: { streamStatus: StreamStatus }) {
  const location = useLocation();
  const health = useHealth();
  const page = PAGES[location.pathname] ?? PAGES["/"];
  const [now, setNow] = useState(() => new Date());

  useEffect(() => {
    const timer = window.setInterval(() => setNow(new Date()), 1000);
    return () => window.clearInterval(timer);
  }, []);

  const streamLabel =
    streamStatus === "live" ? "live" : streamStatus === "connecting" ? "linking" : "offline";
  const streamTone =
    streamStatus === "live" ? "long" : streamStatus === "connecting" ? "warn" : "short";

  return (
    <header className="flex h-[58px] shrink-0 items-center justify-between gap-4 border-b border-line/70 bg-ink-900/50 px-6 backdrop-blur">
      <div className="min-w-0">
        <h1 className="truncate text-[16px] font-semibold text-paper">{page.title}</h1>
        <p className="truncate text-[11.5px] text-fog">{page.subtitle}</p>
      </div>

      <div className="flex items-center gap-3">
        <Badge tone={streamTone} dot>
          stream {streamLabel}
        </Badge>
        {health.data ? (
          <Badge tone={health.data.terminal.connected ? "long" : "short"} dot>
            {health.data.terminal.connected ? "terminal synced" : "terminal offline"}
          </Badge>
        ) : null}
        <div className="flex items-center gap-2 rounded-md border border-line/70 bg-ink-850/60 px-3 py-1.5">
          <ClockIcon className="h-3.5 w-3.5 text-fog" />
          <div className="leading-none">
            <div className="font-mono text-[12.5px] tabular-nums text-paper">
              {time(now.toISOString())}
            </div>
            <div className="mt-0.5 text-[9.5px] uppercase tracking-[0.14em] text-fog">
              {health.data?.timezone ?? "local"}
            </div>
          </div>
        </div>
      </div>
    </header>
  );
}

function Banners() {
  const health = useHealth();
  if (health.isError) {
    return (
      <div className="mb-4 flex items-start gap-3 rounded-lg border border-short/40 bg-short/10 px-4 py-3 text-short">
        <AlertIcon className="mt-0.5 h-4 w-4 shrink-0" />
        <div>
          <div className="text-[12.5px] font-semibold">Backend unreachable</div>
          <div className="text-[11.5px] text-short/80">
            Start the API with{" "}
            <code className="rounded bg-ink-900 px-1 py-0.5 font-mono text-[11px]">
              python -m backend.ignite.api
            </code>{" "}
            and reload.
          </div>
        </div>
      </div>
    );
  }

  const problems: string[] = [];
  if (health.data && !health.data.mcp.reachable) problems.push("MT5 MCP is unreachable — read-only mode");
  if (health.data && !health.data.kronos.ready) problems.push("Kronos worker is offline — Analyse is disabled");
  if (health.data && health.data.kill_switch) problems.push("Kill switch is engaged — execution is blocked");

  if (!problems.length) return null;
  return (
    <div className="mb-4 flex flex-wrap gap-2">
      {problems.map((problem) => (
        <div
          key={problem}
          className="flex items-center gap-2 rounded-md border border-warn/35 bg-warn/10 px-3 py-2 text-[11.5px] font-medium text-warn"
        >
          <AlertIcon className="h-3.5 w-3.5" />
          {problem}
        </div>
      ))}
    </div>
  );
}

function Layout({ streamStatus }: { streamStatus: StreamStatus }) {
  return (
    <div className="flex h-screen overflow-hidden">
      <Sidebar />
      <div className="flex min-w-0 flex-1 flex-col">
        <Header streamStatus={streamStatus} />
        <main className="min-h-0 flex-1 overflow-y-auto px-6 py-5">
          <Banners />
          <Outlet />
        </main>
      </div>
    </div>
  );
}

export default function App() {
  const streamStatus = useEventStream();

  return (
    <Routes>
      <Route element={<Layout streamStatus={streamStatus} />}>
        <Route index element={<Portfolio />} />
        <Route path="watchlist" element={<Watchlist />} />
        <Route path="history" element={<History />} />
        <Route path="news" element={<News />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
