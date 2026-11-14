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
import { getApiBase } from "./lib/api";
import Portfolio from "./pages/Portfolio";
import AgentWorkbench from "./pages/AgentWorkbench";
import Watchlist from "./pages/Watchlist";
import History from "./pages/History";
import News from "./pages/News";
import { useConnectionStatus } from "./hooks/useConnectionStatus";
import { useEffect, useRef, useState } from "react";

const NAV = [
  { to: "/", label: "Agent", index: "01", icon: BoltIcon, end: true },
  { to: "/portfolio", label: "Portfolio", index: "02", icon: GridIcon, end: false },
  { to: "/watchlist", label: "Watchlist", index: "03", icon: CandleIcon, end: false },
  { to: "/history", label: "History", index: "04", icon: HistoryIcon, end: false },
  { to: "/news", label: "News & calendar", index: "05", icon: NewsIcon, end: false },
];

const PAGES: Record<string, { section: string; title: string; subtitle: string }> = {
  "/": {
    section: "Workbench",
    title: "Agent",
    subtitle: "Observe, explain and prepare the next safe action",
  },
  "/portfolio": {
    section: "Book",
    title: "Portfolio",
    subtitle: "Equity, exposure and open risk",
  },
  "/watchlist": {
    section: "Research",
    title: "Watchlist",
    subtitle: "Analyse a symbol, then confirm an order",
  },
  "/history": {
    section: "Book",
    title: "History",
    subtitle: "Closed trades and realised performance",
  },
  "/news": {
    section: "Context",
    title: "News & calendar",
    subtitle: "Fundamentals and deterministic blackout windows",
  },
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
    <aside className="sidebar">
      <div className="sidebar-brand flex h-[var(--header-h)] shrink-0 items-center gap-3 border-b border-line/60 px-5">
        <div className="flex h-8 w-8 items-center justify-center border border-gold-500/40 bg-gold-500/10 text-gold-400">
          <BoltIcon className="h-4 w-4" />
        </div>
        <div className="sidebar-brand-text leading-none">
          <div className="font-display text-[15px] font-bold tracking-[0.24em] text-paper">
            IGNITE
          </div>
          <div className="mt-1 text-micro font-medium uppercase tracking-[0.34em] text-gold-500/80">
            Desk
          </div>
        </div>
      </div>

      <nav className="sidebar-nav flex-1 overflow-y-auto px-3 py-5">
        <div className="sidebar-label eyebrow mb-2 px-2">Workspace</div>
        <div className="space-y-0.5">
          {NAV.map(({ to, label, index, icon: Icon, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              className={({ isActive }) =>
                `group flex h-9 items-center gap-3 border-l-2 px-2.5 text-[12.5px] font-medium transition-colors ${
                  isActive
                    ? "border-gold-500 bg-gold-500/[0.07] text-gold-300"
                    : "border-transparent text-fog hover:bg-ink-850 hover:text-paper"
                }`
              }
              title={label}
            >
              <Icon className="h-4 w-4 shrink-0" />
              <span className="sidebar-label flex-1 truncate">{label}</span>
              <span className="sidebar-label font-mono text-[9px] tracking-[0.12em] text-text-faint group-hover:text-fog">
                {index}
              </span>
            </NavLink>
          ))}
        </div>
      </nav>

      <div className="sidebar-system shrink-0 border-t border-line/60 px-4 py-4">
        <div className="mb-2 flex items-center justify-between">
          <span className="eyebrow text-[9.5px]">Systems</span>
          <span className="flex items-center gap-1.5 font-mono text-[9px] uppercase tracking-[0.1em] text-fog">
            <span
              className={`h-1.5 w-1.5 ${health.data?.ok ? "bg-long" : "bg-short"} ${
                health.data?.ok ? "" : "animate-pulse"
              }`}
            />
            {health.data?.ok ? "nominal" : "degraded"}
          </span>
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
        <SystemRow label="Mode" value={terminal?.server ?? "demo"} ok neutral />

        <button
          onClick={toggle}
          disabled={update.isPending || settings.isLoading}
          className={`mt-3 flex w-full items-center justify-between gap-2 border px-2.5 py-2 text-left transition-colors disabled:opacity-50 ${
            kill
              ? "border-short/50 bg-short/10 text-short"
              : "border-line/80 text-fog hover:border-short/40 hover:text-short"
          }`}
          title={kill ? "Kill switch: ON (click to release)" : "Kill switch: OFF (click to arm)"}
        >
          <span className="sidebar-footer-text flex items-center gap-2 text-[10px] font-semibold uppercase tracking-[0.12em]">
            <PowerIcon className="h-3.5 w-3.5" />
            Kill switch
          </span>
          <span
            className={`relative h-4 w-7 shrink-0 transition-colors ${
              kill ? "bg-short/70" : "bg-ink-600"
            }`}
          >
            <span
              className={`absolute top-0.5 h-3 w-3 bg-paper transition-transform ${
                kill ? "translate-x-[14px]" : "translate-x-0.5"
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
    <div className="flex items-center justify-between gap-3 border-b border-line/30 py-1.5 last:border-0">
      <span className="sidebar-footer-text text-[11px] text-fog">{label}</span>
      <span
        className={`flex min-w-0 items-center gap-1.5 font-mono text-[10px] uppercase tracking-[0.04em] ${
          neutral ? "text-fog" : ok ? "text-long" : "text-short"
        }`}
      >
        {!neutral ? <span className={`h-1 w-1 shrink-0 ${ok ? "bg-long" : "bg-short"}`} /> : null}
        <span className="truncate">{value}</span>
      </span>
    </div>
  );
}

function Header({ streamStatus }: { streamStatus: StreamStatus }) {
  const location = useLocation();
  const health = useHealth();
  const connection = useConnectionStatus();
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
    <header className="header">
      <div className="flex min-w-0 flex-1 items-center gap-4">
        <div className="min-w-0">
          <div className="hidden items-center gap-2 sm:flex">
            <span className="eyebrow text-[9.5px] text-text-faint">Ignite Desk</span>
            <span className="text-text-faint">/</span>
            <span className="eyebrow truncate text-[9.5px] text-gold-500">{page.section}</span>
          </div>
          <div className="flex min-w-0 items-baseline gap-3 sm:mt-1">
            <h1 className="truncate text-[15px] font-semibold leading-none tracking-[-0.01em] text-paper">
              {page.title}
            </h1>
            <p className="hidden truncate text-[11.5px] leading-none text-fog md:block">
              {page.subtitle}
            </p>
          </div>
        </div>
      </div>

      <div className="flex shrink-0 items-center gap-2">
        <Badge tone={streamTone} dot>
          <span className="hidden sm:inline">stream&nbsp;</span>
          {streamLabel}
        </Badge>
        {!connection.data?.connected ? (
          <Badge tone="short" dot>
            API unreachable
          </Badge>
        ) : (
          <span className="hidden 2xl:inline-flex">
            <Badge tone={health.data?.terminal.connected ? "long" : "short"} dot>
              {health.data?.terminal.connected ? "terminal synced" : "terminal offline"}
            </Badge>
          </span>
        )}
        <div className="flex items-center gap-2 border-l border-line/70 pl-3">
          <ClockIcon className="h-3.5 w-3.5 text-text-faint" />
          <div className="leading-none">
            <div className="w-[68px] text-right font-mono text-[12.5px] tabular-nums text-paper">
              {time(now.toISOString())}
            </div>
            <div className="mt-1 hidden text-right text-[9px] uppercase tracking-[0.14em] text-text-faint sm:block">
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
      <div className="flex items-start gap-3 border border-short/35 border-l-2 border-l-short bg-short/[0.07] px-4 py-3 text-short">
        <AlertIcon className="mt-0.5 h-4 w-4 shrink-0" />
        <div>
          <div className="text-[12px] font-semibold uppercase tracking-[0.08em]">
            Backend unreachable
          </div>
          <div className="mt-0.5 text-[12px] text-short/80">
            Start the API with{" "}
            <code className="border border-line/60 bg-ink-900 px-1 py-0.5 font-mono text-[11px] text-paper">
              python -m backend.ignite.api
            </code>{" "}
            and reload.
          </div>
        </div>
      </div>
    );
  }

  const problems: string[] = [];
  if (health.data && !health.data.mcp.reachable) problems.push("MT5 MCP unreachable — read-only mode");
  if (health.data && !health.data.kronos.ready) problems.push("Kronos worker offline — Analyse disabled");
  if (health.data && health.data.kill_switch) problems.push("Kill switch engaged — execution blocked");

  if (!problems.length) return null;
  return (
    <div className="flex flex-wrap gap-2">
      {problems.map((problem) => (
        <div
          key={problem}
          className="flex items-center gap-2 border border-warn/30 border-l-2 border-l-warn bg-warn/[0.06] px-3 py-1.5 text-[11px] font-medium text-warn"
        >
          <AlertIcon className="h-3 w-3" />
          {problem}
        </div>
      ))}
    </div>
  );
}

function Layout({ streamStatus }: { streamStatus: StreamStatus }) {
  const connection = useConnectionStatus();
  const { push } = useToast();
  const prevConnected = useRef(connection.data?.connected ?? null);

  useEffect(() => {
    const current = connection.data?.connected;
    const previous = prevConnected.current;
    if (previous === null) {
      prevConnected.current = current ?? false;
      return;
    }
    if (current === false && previous === true) {
      push({
        tone: "danger",
        title: "API unreachable",
        message: "The backend API is not reachable. Check that the API server is running on " +
          getApiBase(),
      });
    }
    if (current === true && previous === false) {
      push({
        tone: "ok",
        title: "API restored",
        message: "Connection to the backend API has been restored.",
      });
    }
    prevConnected.current = current ?? false;
  }, [connection.data?.connected, push]);

  return (
    <div className="app-shell">
      <Sidebar />
      <Header streamStatus={streamStatus} />
      <main className="main">
        <div className="space-y-4">
          <Banners />
          <Outlet />
        </div>
      </main>
    </div>
  );
}

export default function App() {
  const streamStatus = useEventStream();

  return (
    <Routes>
      <Route element={<Layout streamStatus={streamStatus} />}>
        <Route index element={<AgentWorkbench streamStatus={streamStatus} />} />
        <Route path="agent" element={<AgentWorkbench streamStatus={streamStatus} />} />
        <Route path="portfolio" element={<Portfolio />} />
        <Route path="watchlist" element={<Watchlist />} />
        <Route path="history" element={<History />} />
        <Route path="news" element={<News />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
