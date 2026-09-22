import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/** Money stays in integer paise everywhere; this is display only. */
export function rupees(paise: number, opts: { compact?: boolean; sign?: boolean } = {}) {
  // The sign goes before the currency symbol (−₹450.00), with a true minus.
  const r = Math.abs(paise) / 100;
  const sign = paise < 0 ? "−" : opts.sign && paise > 0 ? "+" : "";
  if (opts.compact && r >= 1e5) {
    const lakh = r / 1e5;
    return `${sign}₹${lakh.toLocaleString("en-IN", { maximumFractionDigits: lakh >= 100 ? 0 : 2 })}L`;
  }
  return `${sign}₹${r.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

export const pct = (x: number, digits = 1) => `${(x * 100).toFixed(digits)}%`;
export const int = (x: number) => Math.round(x).toLocaleString("en-IN");
export const human = (label: string) => label.replace(/_/g, " ");
