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
  info: "border-info/40 bg-info/10 text-info",
  ok: "border-long/40 bg-long/10 text-long",
  warn: "border-warn/40 bg-warn/10 text-warn",
  danger: "border-short/40 bg-short/10 text-short",
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
      <div className="pointer-events-none fixed bottom-5 right-5 z-[80] flex w-[340px] flex-col gap-2">
        {toasts.map((toast) => (
          <button
            key={toast.id}
            onClick={() => dismiss(toast.id)}
            className={`pointer-events-auto animate-slide-in rounded-lg border px-4 py-3 text-left shadow-panel backdrop-blur ${TONE_STYLE[toast.tone]}`}
          >
            <div className="text-[13px] font-semibold tracking-wide">{toast.title}</div>
            {toast.message ? (
              <div className="mt-0.5 text-[12px] leading-snug text-paper/70">
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
