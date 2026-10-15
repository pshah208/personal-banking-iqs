/**
 * Fabric capacity control - pause / resume the F-SKU behind Fabric IQ from the
 * top bar, so the capacity is not billing while the demo is idle.
 *
 * Resume is one click. Pause takes Fabric IQ offline for every user, so it is a
 * two-step "Pause → Confirm" rather than a browser dialog. While the capacity is
 * changing state the control polls every few seconds; otherwise once a minute.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { apiGet, apiPost } from "../api";
import type { FabricCapacity } from "../types";

const LABEL: Record<FabricCapacity["state"], string> = {
  active: "Active · Fabric IQ online",
  paused: "Paused · Fabric IQ offline",
  resuming: "Resuming…",
  pausing: "Pausing…",
  unknown: "Status unavailable",
};

const Icon = {
  db: (
    <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="1.75"
         strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <ellipse cx="12" cy="5.5" rx="7.5" ry="2.75" />
      <path d="M4.5 5.5v6.5c0 1.5 3.4 2.75 7.5 2.75s7.5-1.25 7.5-2.75V5.5" />
      <path d="M4.5 12v6.5c0 1.5 3.4 2.75 7.5 2.75s7.5-1.25 7.5-2.75V12" />
    </svg>
  ),
  play: (
    <svg viewBox="0 0 24 24" width="12" height="12" fill="currentColor" aria-hidden>
      <path d="M7 4.5v15l12-7.5z" />
    </svg>
  ),
  pause: (
    <svg viewBox="0 0 24 24" width="12" height="12" fill="currentColor" aria-hidden>
      <rect x="6" y="4.5" width="4" height="15" rx="1" /><rect x="14" y="4.5" width="4" height="15" rx="1" />
    </svg>
  ),
  refresh: (
    <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2"
         strokeLinecap="round" strokeLinejoin="round" aria-hidden>
      <path d="M20 11a8 8 0 0 0-14.3-4.9L4 8" /><path d="M4 3v5h5" />
      <path d="M4 13a8 8 0 0 0 14.3 4.9L20 16" /><path d="M20 21v-5h-5" />
    </svg>
  ),
};

export function FabricCapacityControl() {
  const [cap, setCap] = useState<FabricCapacity | null>(null);
  const [busy, setBusy] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [error, setError] = useState("");
  const confirmTimer = useRef<number | undefined>(undefined);

  const refresh = useCallback(async () => {
    try {
      setCap(await apiGet<FabricCapacity>("/api/fabric-capacity"));
      setError("");
    } catch {
      setCap((c) => c ?? { configured: false, state: "unknown", canOperate: false });
    }
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);

  const transient = cap?.state === "resuming" || cap?.state === "pausing";
  useEffect(() => {
    if (!cap?.configured) return;
    const id = window.setInterval(() => { void refresh(); }, transient ? 5000 : 60000);
    return () => window.clearInterval(id);
  }, [cap?.configured, transient, refresh]);

  useEffect(() => () => window.clearTimeout(confirmTimer.current), []);

  if (!cap?.configured) return null;

  const act = async (action: "resume" | "suspend") => {
    setBusy(true);
    setConfirming(false);
    try {
      setCap(await apiPost<FabricCapacity>(`/api/fabric-capacity/${action}`, {}));
      setError("");
    } catch (e) {
      setError(String(e).includes("403") ? "Not permitted" : "Request failed");
    } finally {
      setBusy(false);
    }
  };

  const askPause = () => {
    setConfirming(true);
    window.clearTimeout(confirmTimer.current);
    confirmTimer.current = window.setTimeout(() => setConfirming(false), 5000);
  };

  const state = cap.state;
  const title = [
    `Fabric capacity ${cap.name ?? ""}`,
    cap.sku && `SKU ${cap.sku}`,
    cap.region,
    cap.rawState && `ARM state: ${cap.rawState}`,
  ].filter(Boolean).join(" · ");

  return (
    <div className={`fabcap state-${state}`} role="group" aria-label="Fabric capacity" title={title}>
      <span className="fabcap-icon">{Icon.db}</span>
      <span className="fabcap-text">
        <span className="fabcap-name">
          Fabric capacity <span className="fabcap-id">{cap.name}{cap.sku ? ` · ${cap.sku}` : ""}</span>
        </span>
        <span className="fabcap-status" aria-live="polite">
          <span className="fabcap-dot" aria-hidden />
          {error || LABEL[state]}
        </span>
      </span>

      {cap.canOperate && state === "paused" && (
        <button className="fabcap-btn resume" disabled={busy} onClick={() => act("resume")}>
          {Icon.play}<span>Resume</span>
        </button>
      )}
      {cap.canOperate && state === "active" && !confirming && (
        <button className="fabcap-btn pause" disabled={busy} onClick={askPause}>
          {Icon.pause}<span>Pause</span>
        </button>
      )}
      {cap.canOperate && state === "active" && confirming && (
        <button className="fabcap-btn confirm" disabled={busy} onClick={() => act("suspend")}
                aria-label="Confirm pause - takes Fabric IQ offline for all users">
          {Icon.pause}<span>Confirm pause</span>
        </button>
      )}
      {transient && <span className="fabcap-spinner" aria-hidden />}

      <button className="fabcap-refresh" onClick={() => void refresh()} aria-label="Refresh capacity status"
              disabled={busy}>
        {Icon.refresh}
      </button>
    </div>
  );
}
