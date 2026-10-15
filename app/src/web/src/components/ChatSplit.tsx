/**
 * One resizable, collapsible chat column used by every view (Guided, Explore,
 * Dashboard, client workspace, Scenarios), so drag-to-resize, keyboard resize,
 * double-click reset and collapse/expand behave the same everywhere.
 *
 * Width is a percentage of the split container (not the viewport) and both the
 * width and the open state persist per view in localStorage.
 */
import { useCallback, useEffect, useState } from "react";
import type { RefObject } from "react";

export interface ChatSplit {
  width: number;
  open: boolean;
  min: number;
  max: number;
  setWidth: (w: number) => void;
  setOpen: (open: boolean) => void;
  toggle: () => void;
  reset: () => void;
}

function read(key: string): string | null {
  try { return window.localStorage.getItem(key); } catch { return null; }
}
function write(key: string, value: string) {
  try { window.localStorage.setItem(key, value); } catch { /* private mode: not persisted */ }
}

export function useChatSplit(key: string, def: number, min = 20, max = 70): ChatSplit {
  const clamp = useCallback((w: number) => Math.min(max, Math.max(min, w)), [min, max]);
  const [width, setW] = useState(() => {
    const n = Number(read(`${key}.width`));
    return Number.isFinite(n) && n > 0 ? clamp(n) : def;
  });
  const [open, setOpen] = useState(() => read(`${key}.open`) !== "0");
  useEffect(() => write(`${key}.width`, String(Math.round(width * 10) / 10)), [key, width]);
  useEffect(() => write(`${key}.open`, open ? "1" : "0"), [key, open]);
  return {
    width, open, min, max,
    setWidth: (w) => setW(clamp(w)),
    setOpen,
    toggle: () => setOpen((o) => !o),
    reset: () => setW(def),
  };
}

const Chevron = ({ dir }: { dir: "left" | "right" }) => (
  <svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="1.8"
       strokeLinecap="round" strokeLinejoin="round" aria-hidden>
    <path d={dir === "right" ? "M6 3.5 10.5 8 6 12.5" : "M10 3.5 5.5 8 10 12.5"} />
  </svg>
);

/** Drag handle between the content and the chat column, with a collapse button. */
export function SplitHandle({ split, container, controls, label = "chat" }: {
  split: ChatSplit;
  container: RefObject<HTMLElement | null>;
  controls?: string;
  label?: string;
}) {
  const end = (el: HTMLElement, id: number) => {
    if (el.hasPointerCapture(id)) el.releasePointerCapture(id);
    container.current?.classList.remove("split-resizing");
  };
  return (
    <div
      className="split-handle"
      role="separator"
      aria-orientation="vertical"
      aria-label={`Resize ${label}. Arrow keys resize, Enter resets, Escape collapses.`}
      aria-valuemin={split.min}
      aria-valuemax={split.max}
      aria-valuenow={Math.round(split.width)}
      aria-controls={controls}
      tabIndex={0}
      onPointerDown={(e) => {
        if ((e.target as HTMLElement).closest("button")) return;
        e.preventDefault();
        e.currentTarget.setPointerCapture(e.pointerId);
        container.current?.classList.add("split-resizing");
      }}
      onPointerMove={(e) => {
        if (!e.currentTarget.hasPointerCapture(e.pointerId) || !container.current) return;
        const r = container.current.getBoundingClientRect();
        split.setWidth(((r.right - e.clientX) / r.width) * 100);
      }}
      onPointerUp={(e) => end(e.currentTarget, e.pointerId)}
      onPointerCancel={(e) => end(e.currentTarget, e.pointerId)}
      onDoubleClick={split.reset}
      onKeyDown={(e) => {
        const k = e.key;
        if (k === "ArrowLeft") split.setWidth(split.width + 2);
        else if (k === "ArrowRight") split.setWidth(split.width - 2);
        else if (k === "Home") split.setWidth(split.min);
        else if (k === "End") split.setWidth(split.max);
        else if (k === "Enter") split.reset();
        else if (k === "Escape") split.setOpen(false);
        else return;
        e.preventDefault();
      }}
    >
      <button type="button" className="split-collapse" onClick={() => split.setOpen(false)}
              aria-label={`Collapse ${label}`} title={`Collapse ${label}`}>
        <Chevron dir="right" />
      </button>
      <span className="split-grip" aria-hidden />
    </div>
  );
}

/** Slim rail shown in place of a collapsed chat column. */
export function SplitRail({ split, controls, label = "Chat" }: {
  split: ChatSplit;
  controls?: string;
  label?: string;
}) {
  return (
    <button type="button" className="split-rail" onClick={() => split.setOpen(true)}
            aria-expanded={false} aria-controls={controls} title={`Expand ${label.toLowerCase()}`}>
      <Chevron dir="left" />
      <span>{label}</span>
    </button>
  );
}

/** Header button: the same toggle, labelled for whichever state the column is in. */
export function SplitToggle({ split, controls, className = "" }: {
  split: ChatSplit;
  controls?: string;
  className?: string;
}) {
  return (
    <button type="button" className={`split-toggle ${className}`.trim()} aria-expanded={split.open}
            aria-controls={controls} onClick={split.toggle}>
      <Chevron dir={split.open ? "right" : "left"} />
      {split.open ? "Collapse chat" : "Expand chat"}
    </button>
  );
}
