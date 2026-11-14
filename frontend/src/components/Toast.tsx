import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";

export type ToastTone = "info" | "ok" | "warn" | "danger";

export interface Toast {
  id: number;
  tone: ToastTone;
  title: string;
  message?: string;
}

interface ToastApi {
  push: (toast: Omit<Toast, "id">) => void;
}

const ToastContext = createContext<ToastApi>({ push: () => undefined });

const TONE_STYLE: Record<ToastTone, string> = {
  info: "border-info/30 border-l-info bg-info/[0.07] text-info",
  ok: "border-long/30 border-l-long bg-long/[0.07] text-long",
  warn: "border-warn/30 border-l-warn bg-warn/[0.07] text-warn",
  danger: "border-short/30 border-l-short bg-short/[0.07] text-short",
};

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const nextId = useRef(1);
  const timers = useRef<number[]>([]);

  const dismiss = useCallback((id: number) => {
    setToasts((current) => current.filter((toast) => toast.id !== id));
  }, []);

  const push = useCallback(
    (toast: Omit<Toast, "id">) => {
      const id = nextId.current++;
      setToasts((current) => [...current.slice(-4), { ...toast, id }]);
      const timer = window.setTimeout(() => dismiss(id), 6000);
      timers.current.push(timer);
    },
    [dismiss],
  );

  useEffect(() => () => timers.current.forEach((timer) => window.clearTimeout(timer)), []);

  return (
    <ToastContext.Provider value={{ push }}>
      {children}
      <div className="pointer-events-none fixed bottom-20 right-5 z-[80] flex w-[340px] flex-col gap-2">
        {toasts.map((toast) => (
          <button
            key={toast.id}
            onClick={() => dismiss(toast.id)}
            className={`pointer-events-auto animate-slide-in border border-l-2 px-4 py-3 text-left shadow-panel backdrop-blur ${TONE_STYLE[toast.tone]}`}
          >
            <div className="text-[11px] font-semibold uppercase tracking-[0.08em]">{toast.title}</div>
            {toast.message ? (
              <div className="mt-1 text-[11px] leading-snug text-paper/65">
                {toast.message}
              </div>
            ) : null}
          </button>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast(): ToastApi {
  return useContext(ToastContext);
}
