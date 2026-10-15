import { useEffect, useState } from "react";
import { currentBrand, getBrand, type Brand, type BrandId } from "./brand";

/** Re-render on bank switch, for components that draw brand assets themselves. */
export function useBrand(): Brand {
  const [id, setId] = useState<BrandId>(currentBrand);
  useEffect(() => {
    const on = (e: Event) => setId((e as CustomEvent<BrandId>).detail);
    window.addEventListener("brandchange", on);
    return () => window.removeEventListener("brandchange", on);
  }, []);
  return getBrand(id);
}
