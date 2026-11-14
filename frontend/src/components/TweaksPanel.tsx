import { useEffect, useState, createContext, useContext, type ReactNode } from "react";
import { PaletteIcon, XIcon } from "./icons";

interface TweaksState {
  density: number;
  radiusScale: number;
  fontScale: number;
  theme: "dark" | "light" | "auto";
  reducedMotion: boolean;
  showGrid: boolean;
  compactMode: boolean;
}

const defaultTweaks: TweaksState = {
  density: 1,
  radiusScale: 1,
  fontScale: 1,
  theme: "dark",
  reducedMotion: false,
  showGrid: false,
  compactMode: false,
};

const STORAGE_KEY = "ignite-tweaks";

function loadTweaks(): TweaksState {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored) {
      return { ...defaultTweaks, ...JSON.parse(stored) };
    }
  } catch {
    // Ignore malformed storage.
  }
  return defaultTweaks;
}

function saveTweaks(tweaks: TweaksState) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(tweaks));
  } catch {
    // Ignore quota errors.
  }
}

function applyTweaks(tweaks: TweaksState) {
  const root = document.documentElement;
  const density = tweaks.compactMode ? tweaks.density * 0.72 : tweaks.density;

  root.style.setProperty("--density", String(density));
  root.style.setProperty("--radius-scale", String(tweaks.radiusScale));
  root.style.setProperty("--font-scale", String(tweaks.fontScale));

  const autoLight =
    typeof window !== "undefined" &&
    window.matchMedia?.("(prefers-color-scheme: light)").matches;
  const theme = tweaks.theme === "auto" ? (autoLight ? "light" : "dark") : tweaks.theme;
  root.setAttribute("data-theme", theme);

  document.body.classList.toggle("reduce-motion", tweaks.reducedMotion);
  document.body.classList.toggle("show-grid", tweaks.showGrid);
  document.body.classList.toggle("compact-mode", tweaks.compactMode);
}

interface TweaksContextValue {
  tweaks: TweaksState;
  setTweaks: (tweaks: Partial<TweaksState>) => void;
  resetTweaks: () => void;
  togglePanel: () => void;
  isOpen: boolean;
}

const TweaksContext = createContext<TweaksContextValue | null>(null);

export function TweaksProvider({ children }: { children: ReactNode }) {
  const [tweaks, setTweaksState] = useState<TweaksState>(() => loadTweaks());
  const [isOpen, setIsOpen] = useState(false);

  useEffect(() => {
    applyTweaks(tweaks);
    saveTweaks(tweaks);
  }, [tweaks]);

  const setTweaks = (partial: Partial<TweaksState>) => {
    setTweaksState((previous) => ({ ...previous, ...partial }));
  };

  const resetTweaks = () => setTweaksState(defaultTweaks);
  const togglePanel = () => setIsOpen((previous) => !previous);

  return (
    <TweaksContext.Provider value={{ tweaks, setTweaks, resetTweaks, togglePanel, isOpen }}>
      {children}
      <TweaksPanel isOpen={isOpen} onClose={() => setIsOpen(false)} />
    </TweaksContext.Provider>
  );
}

export function useTweaks() {
  const context = useContext(TweaksContext);
  if (!context) {
    throw new Error("useTweaks must be used within a TweaksProvider");
  }
  return context;
}

function Section({
  title,
  value,
  children,
}: {
  title: string;
  value?: string;
  children: ReactNode;
}) {
  return (
    <section className="tweaks-section">
      <div className="flex items-baseline justify-between">
        <h4 className="tweaks-section-title">{title}</h4>
        {value ? <span className="tweaks-value">{value}</span> : null}
      </div>
      {children}
    </section>
  );
}

function TweaksPanel({ isOpen, onClose }: { isOpen: boolean; onClose: () => void }) {
  const { tweaks, setTweaks, resetTweaks } = useTweaks();

  if (!isOpen) return null;

  const densities = [0.8, 0.9, 1, 1.1, 1.2, 1.3];
  const radii = [0, 0.5, 0.75, 1, 1.25, 1.5];
  const fonts = [0.9, 0.95, 1, 1.05, 1.1, 1.15];

  return (
    <>
      <div
        className="fixed inset-0 z-[900] animate-fade bg-black/40 backdrop-blur-[2px]"
        onClick={onClose}
        aria-hidden="true"
      />
      <aside className="tweaks-panel" role="dialog" aria-label="Design tweaks">
        <div className="tweaks-header">
          <div className="flex items-center gap-2">
            <PaletteIcon className="h-3.5 w-3.5 text-gold-500" />
            <span className="tweaks-title">Design tweaks</span>
          </div>
          <button className="tweaks-close" onClick={onClose} aria-label="Close design tweaks">
            <XIcon className="h-3.5 w-3.5" />
          </button>
        </div>

        <div className="tweaks-body">
          <Section title="Theme">
            <div className="tweaks-presets" role="radiogroup" aria-label="Theme">
              {(["dark", "light", "auto"] as const).map((theme) => (
                <button
                  key={theme}
                  onClick={() => setTweaks({ theme })}
                  className={`tweaks-preset flex-1 ${tweaks.theme === theme ? "active" : ""}`}
                  role="radio"
                  aria-checked={tweaks.theme === theme}
                >
                  {theme}
                </button>
              ))}
            </div>
          </Section>

          <Section title="Density" value={`${tweaks.density.toFixed(2)}×`}>
            <input
              type="range"
              min="0.8"
              max="1.3"
              step="0.05"
              value={tweaks.density}
              onChange={(event) => setTweaks({ density: parseFloat(event.target.value) })}
              className="tweaks-slider"
              aria-label="Density"
            />
            <div className="tweaks-presets mt-2" role="group" aria-label="Density presets">
              {densities.map((density) => (
                <button
                  key={density}
                  onClick={() => setTweaks({ density })}
                  className={`tweaks-preset flex-1 ${
                    Math.abs(tweaks.density - density) < 0.03 ? "active" : ""
                  }`}
                >
                  {density}
                </button>
              ))}
            </div>
          </Section>

          <Section title="Border radius" value={`${tweaks.radiusScale.toFixed(2)}×`}>
            <input
              type="range"
              min="0"
              max="1.5"
              step="0.05"
              value={tweaks.radiusScale}
              onChange={(event) => setTweaks({ radiusScale: parseFloat(event.target.value) })}
              className="tweaks-slider"
              aria-label="Border radius scale"
            />
            <div className="tweaks-presets mt-2" role="group" aria-label="Radius presets">
              {radii.map((radius) => (
                <button
                  key={radius}
                  onClick={() => setTweaks({ radiusScale: radius })}
                  title={radius === 0 ? "Sharp" : radius === 1 ? "Default" : `${radius}×`}
                  className={`tweaks-preset flex-1 ${
                    Math.abs(tweaks.radiusScale - radius) < 0.03 ? "active" : ""
                  }`}
                >
                  {radius === 0 ? "0" : radius}
                </button>
              ))}
            </div>
          </Section>

          <Section title="Font scale" value={`${tweaks.fontScale.toFixed(2)}×`}>
            <input
              type="range"
              min="0.9"
              max="1.15"
              step="0.01"
              value={tweaks.fontScale}
              onChange={(event) => setTweaks({ fontScale: parseFloat(event.target.value) })}
              className="tweaks-slider"
              aria-label="Font scale"
            />
            <div className="tweaks-presets mt-2" role="group" aria-label="Font scale presets">
              {fonts.map((font) => (
                <button
                  key={font}
                  onClick={() => setTweaks({ fontScale: font })}
                  className={`tweaks-preset flex-1 ${
                    Math.abs(tweaks.fontScale - font) < 0.015 ? "active" : ""
                  }`}
                >
                  {font.toFixed(2)}
                </button>
              ))}
            </div>
          </Section>

          <Section title="Options">
            <div className="space-y-2.5">
              <label className="tweaks-toggle-row !mb-0 cursor-pointer">
                <span className="tweaks-toggle-label">Reduced motion</span>
                <input
                  type="checkbox"
                  checked={tweaks.reducedMotion}
                  onChange={(event) => setTweaks({ reducedMotion: event.target.checked })}
                  className="tweaks-toggle-input"
                />
              </label>
              <label className="tweaks-toggle-row !mb-0 cursor-pointer">
                <span className="tweaks-toggle-label">Grid overlay</span>
                <input
                  type="checkbox"
                  checked={tweaks.showGrid}
                  onChange={(event) => setTweaks({ showGrid: event.target.checked })}
                  className="tweaks-toggle-input"
                />
              </label>
              <label className="tweaks-toggle-row !mb-0 cursor-pointer">
                <span className="tweaks-toggle-label">Compact mode</span>
                <input
                  type="checkbox"
                  checked={tweaks.compactMode}
                  onChange={(event) => setTweaks({ compactMode: event.target.checked })}
                  className="tweaks-toggle-input"
                />
              </label>
            </div>
          </Section>

          <div className="tweaks-actions">
            <button className="tweaks-action" onClick={resetTweaks}>
              Reset
            </button>
            <button className="tweaks-action tweaks-action-primary" onClick={onClose}>
              Done
            </button>
          </div>
        </div>
      </aside>
    </>
  );
}

export function TweaksToggle() {
  const { togglePanel, isOpen } = useTweaks();

  return (
    <button
      onClick={togglePanel}
      className="tweaks-toggle"
      aria-label={isOpen ? "Close design tweaks" : "Open design tweaks"}
      aria-expanded={isOpen}
    >
      <PaletteIcon className="h-4 w-4" />
    </button>
  );
}
