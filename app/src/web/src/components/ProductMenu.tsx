/**
 * Products group in the top bar: one trigger ("Products ▾", or the active
 * product's name) that opens a menu of every product book. Keeps the top bar
 * to four items so it fits at 1280px beside the brand, Fabric capacity, bank
 * picker and user chip.
 *
 * Keyboard: ArrowDown / Enter / Space open on the active item, ArrowUp opens
 * on the last; inside the menu ArrowUp/Down wrap, Home/End jump, a letter jumps
 * to the next product starting with it, Escape closes and returns focus, Tab
 * closes.
 */
import { useEffect, useId, useRef, useState, type KeyboardEvent } from "react";

export type ProductMode = "dashboard" | "cards" | "banking" | "borrowing" | "investing" | "newcomers" | "insurance" | "security";

export const PRODUCTS: { id: ProductMode; label: string; hint: string }[] = [
  { id: "dashboard", label: "Mortgage", hint: "Renewal book, customers and wellness" },
  { id: "cards", label: "Cards", hint: "Card portfolio, spend and fit" },
  { id: "banking", label: "Everyday banking", hint: "Packages, fees and deposit flows" },
  { id: "borrowing", label: "Borrowing", hint: "Lines, loans and consolidation" },
  { id: "investing", label: "Investing", hint: "Registered plans, GICs and KYC" },
  { id: "newcomers", label: "Newcomers & transfers", hint: "Packages, credit building, remittances" },
  { id: "insurance", label: "Insurance", hint: "Creditor, home and travel cover" },
  { id: "security", label: "Security & fraud", hint: "Cross-book alerts and scam protection" },
];

export const isProductMode = (m: string): m is ProductMode => PRODUCTS.some((p) => p.id === m);

export function ProductMenu({ mode, onSelect }: { mode: string; onSelect: (m: ProductMode) => void }) {
  const [open, setOpen] = useState(false);
  const wrap = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const items = useRef<(HTMLButtonElement | null)[]>([]);
  const menuId = `product-menu-${useId().replace(/[^a-zA-Z0-9]/g, "")}`;
  const current = PRODUCTS.find((p) => p.id === mode);
  const activeIdx = Math.max(0, PRODUCTS.findIndex((p) => p.id === mode));
  const pending = useRef<number | null>(null);

  useEffect(() => {
    if (!open) return;
    if (pending.current !== null) {
      items.current[pending.current]?.focus();
      pending.current = null;
    }
    const onDown = (e: MouseEvent) => { if (!wrap.current?.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [open]);

  const openAt = (i: number) => { pending.current = i; setOpen(true); };
  const close = (refocus: boolean) => { setOpen(false); if (refocus) trigger.current?.focus(); };
  const focusItem = (i: number) => items.current[(i + PRODUCTS.length) % PRODUCTS.length]?.focus();
  const focusedIdx = () => items.current.findIndex((el) => el === document.activeElement);

  const onTriggerKey = (e: KeyboardEvent<HTMLButtonElement>) => {
    if (e.key === "ArrowDown" || e.key === "Enter" || e.key === " ") { e.preventDefault(); openAt(activeIdx); }
    else if (e.key === "ArrowUp") { e.preventDefault(); openAt(PRODUCTS.length - 1); }
    else if (e.key === "Escape" && open) { e.preventDefault(); close(true); }
  };

  const onMenuKey = (e: KeyboardEvent<HTMLDivElement>) => {
    const i = focusedIdx();
    if (e.key === "ArrowDown") { e.preventDefault(); focusItem(i + 1); }
    else if (e.key === "ArrowUp") { e.preventDefault(); focusItem(i - 1); }
    else if (e.key === "Home") { e.preventDefault(); focusItem(0); }
    else if (e.key === "End") { e.preventDefault(); focusItem(PRODUCTS.length - 1); }
    else if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); close(true); }
    else if (e.key === "Tab") { setOpen(false); }
    else if (/^[a-z]$/i.test(e.key)) {
      const k = e.key.toLowerCase();
      for (let s = 1; s <= PRODUCTS.length; s++) {
        const j = (i + s) % PRODUCTS.length;
        if (PRODUCTS[j].label.toLowerCase().startsWith(k)) { focusItem(j); break; }
      }
    }
  };

  const choose = (m: ProductMode) => { onSelect(m); close(true); };

  return (
    <div className="mode-products" ref={wrap}>
      <button
        ref={trigger}
        type="button"
        className={`mode-products-trigger${current ? " on" : ""}`}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={menuId}
        aria-current={current ? "page" : undefined}
        title={current ? `${current.label} - switch product` : "Choose a product book"}
        onClick={() => (open ? close(false) : openAt(activeIdx))}
        onKeyDown={onTriggerKey}
      >
        <span className="mode-products-label">{current?.label ?? "Products"}</span>
        <svg className="mode-products-caret" viewBox="0 0 12 12" width="10" height="10" aria-hidden>
          <path d="M2.5 4.5 6 8l3.5-3.5" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>
      {open && (
        <div className="mode-menu" id={menuId} role="menu" aria-label="Product books" onKeyDown={onMenuKey}>
          <div className="mode-menu-head" aria-hidden>Product books</div>
          {PRODUCTS.map((p, i) => (
            <button
              key={p.id}
              ref={(el) => { items.current[i] = el; }}
              type="button"
              role="menuitemradio"
              aria-checked={p.id === mode}
              tabIndex={-1}
              className={`mode-menu-item${p.id === mode ? " on" : ""}`}
              onClick={() => choose(p.id)}
            >
              <span className="mode-menu-check" aria-hidden>{p.id === mode ? "✓" : ""}</span>
              <span className="mode-menu-text"><b>{p.label}</b><small>{p.hint}</small></span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
