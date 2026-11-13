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
import AgentWorkbench from "./pages/AgentWorkbench";
import Watchlist from "./pages/Watchlist";
import History from "./pages/History";
import News from "./pages/News";
import { useEffect, useRef, useState } from "react";

const NAV = [
  { to: "/", label: "Agent", icon: BoltIcon, end: true },
  { to: "/portfolio", label: "Portfolio", icon: GridIcon, end: false },
  { to: "/watchlist", label: "Watchlist", icon: CandleIcon, end: false },
  { to: "/history", label: "History", icon: HistoryIcon, end: false },
  { to: "/news", label: "News & calendar", icon: NewsIcon, end: false },
];

const PAGES: Record<string, { title: string; subtitle: string }> = {
  "/": { title: "Agent", subtitle: "Observe, explain and prepare the next safe action" },
  "/portfolio": { title: "Portfolio", subtitle: "Equity, exposure and open risk" },
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
  const [retracted, setRetracted] = useState(false);
  const retractTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const clearRetractTimer = () => {
    if (retractTimeoutRef.current) {
      clearTimeout(retractTimeoutRef.current);
      retractTimeoutRef.current = null;
    }
  };

  const handleMouseEnter = () => {
    clearRetractTimer();
    if (retracted) setRetracted(false);
  };

  const handleMouseLeave = () => {
    clearRetractTimer();
    retractTimeoutRef.current = setTimeout(() => {
      setRetracted(true);
    }, 3000);
  };

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
    <div className="relative">
      {/* Hover zone wrapper - covers both expanded sidebar and retracted icon strip */}
      <div
        className="absolute left-0 top-0 h-screen z-20 transition-all duration-200"
        style={{ width: retracted ? 56 : 236 }}
        onMouseEnter={handleMouseEnter}
        onMouseLeave={handleMouseLeave}
      >
        <aside className={`flex h-screen flex-col border-r border-line/70 bg-ink-900/80 transition-all duration-200 ${retracted ? "w-[56px]" : "w-[236px]"}`}>
          <div className={`flex items-center gap-2.5 px-5 pb-5 pt-5 transition-all duration-200 ${retracted ? "justify-center" : ""}`}>
            <div className="flex h-9 w-9 items-center justify-center rounded-lg border border-gold-500/30 bg-gold-500/10 text-gold-400">
              <BoltIcon className="h-5 w-5" />
            </div>
            {!retracted && (
              <div className="leading-none">
                <div className="text-[15px] font-bold tracking-[0.24em] text-paper">IGNITE</div>
                <div className="mt-1 text-[10px] font-medium uppercase tracking-[0.32em] text-gold-500/80">
                  Desk
                </div>
              </div>
            )}
          </div>

          <nav className={`flex flex-col gap-1 px-3 transition-all duration-200 ${retracted ? "px-2" : ""}`}>
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
                  } ${retracted ? "justify-center px-2" : ""}`
                }
                title={retracted ? label : undefined}
              >
                <Icon className="h-4 w-4 flex-shrink-0" />
                {!retracted && <span>{label}</span>}
              </NavLink>
            ))}
          </nav>

          <div className={`mt-auto space-y-3 pb-4 transition-all duration-200 ${retracted ? "px-2 opacity-0 pointer-events-none h-0 overflow-hidden" : "px-3"}`}>
            <div className="rounded-lg border border-line/70 bg-ink-850/70 p-3">
              <div className="mb-2 flex items-center justify-between">
                <span className={`text-[10px] font-semibold uppercase tracking-[0.16em] text-fog ${retracted ? "hidden" : ""}`}>
                  Systems
                </span>
                <span
                  className={`h-1.5 w-1.5 rounded-full ${
                    health.data?.ok ? "bg-long" : "bg-short"
                  } ${health.data?.ok ? "" : "animate-pulseSoft"}`}
                />
              </div>
              {!retracted && (
                <>
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
                </>
              )}
            </div>

            <button
              onClick={toggle}
              disabled={update.isPending || settings.isLoading}
              className={`flex w-full items-center justify-between rounded-lg border px-3 py-2.5 text-left transition-colors disabled:opacity-60 ${retracted ? "justify-center px-2" : ""} ${
                kill
                  ? "border-short/50 bg-short/10 text-short"
                  : "border-line/70 bg-ink-850/70 text-fog hover:border-short/40 hover:text-short"
              }`}
              title={retracted ? (kill ? "Kill switch: ON" : "Kill switch: OFF") : undefined}
            >
              {!retracted && (
                <span className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.12em]">
                  <PowerIcon className="h-3.5 w-3.5" />
                  Kill switch
                </span>
              )}
              <span
                className={`relative h-4 w-8 rounded-full transition-colors ${retracted ? "ml-0" : ""} ${
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

        {/* Retracted view - icon strip (inside hover zone) */}
        {retracted && (
          <div className="absolute left-0 top-0 h-screen flex flex-col items-center justify-between p-2 bg-ink-900/95 border-r border-line backdrop-blur w-[56px]">
            <nav className="flex flex-col gap-1">
              {NAV.map(({ to, label, icon: Icon, end }) => (
                <NavLink
                  key={to}
                  to={to}
                  end={end}
                  className={({ isActive }) =>
                    `group flex items-center justify-center w-10 h-10 rounded-lg transition-colors ${
                      isActive
                        ? "bg-gold-500/10 text-gold-300"
                        : "text-fog hover:bg-ink-800 hover:text-paper"
                    }`
                  }
                  title={label}
                >
                  <Icon className="h-5 w-5" />
                </NavLink>
              ))}
            </nav>
            <div className="flex flex-col items-center gap-2">
              <div className="relative group">
                <span
                  className={`h-1.5 w-1.5 rounded-full ${
                    health.data?.ok ? "bg-long" : "bg-short"
                  } ${health.data?.ok ? "" : "animate-pulseSoft"}`}
                />
                <span className="absolute left-full top-1/2 -translate-y-1/2 ml-2 whitespace-nowrap rounded px-2 py-1 text-[10px] bg-ink-900 border border-line opacity-0 invisible group-hover:opacity-100 group-hover:visible transition-all">
                  Systems
                </span>
              </div>
              <button
                onClick={toggle}
                disabled={update.isPending || settings.isLoading}
                className={`relative group flex w-10 h-10 items-center justify-center rounded-lg transition-colors disabled:opacity-60 ${
                  kill ? "bg-short/10 text-short" : "text-fog hover:bg-ink-800 hover:text-paper"
                }`}
                title={kill ? "Kill switch: ON (click to release)" : "Kill switch: OFF (click to arm)"}
              >
                <PowerIcon className="h-5 w-5" />
                <span className="absolute left-full top-1/2 -translate-y-1/2 ml-2 whitespace-nowrap rounded px-2 py-1 text-[10px] bg-ink-900 border border-line opacity-0 invisible group-hover:opacity-100 group-hover:visible transition-all">
                  {kill ? "Kill switch: ON" : "Kill switch: OFF"}
                </span>
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
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
      <div className="relative z-10 w-[56px] shrink-0">
        <Sidebar />
      </div>
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
        <Route index element={<AgentWorkbench />} />
        <Route path="agent" element={<AgentWorkbench />} />
        <Route path="portfolio" element={<Portfolio />} />
        <Route path="watchlist" element={<Watchlist />} />
        <Route path="history" element={<History />} />
        <Route path="news" element={<News />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
