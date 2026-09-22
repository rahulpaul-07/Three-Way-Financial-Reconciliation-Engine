import type { Severity } from "@/lib/types";
import { cn, human } from "@/lib/utils";

// One meaning per colour, everywhere: blue pencil for matched, green for an
// explained movement, amber for "a person should look", red ink for a break.
export const SEVERITY_TEXT: Record<Severity, string> = {
  ok: "text-tick", expected: "text-settled", review: "text-pencil", break: "text-redink",
};
export const SEVERITY_BG: Record<Severity, string> = {
  ok: "bg-tick", expected: "bg-settled", review: "bg-pencil", break: "bg-redink",
};
export const SEVERITY_VAR: Record<Severity, string> = {
  ok: "rgb(var(--tick))", expected: "rgb(var(--settled))",
  review: "rgb(var(--pencil))", break: "rgb(var(--redink))",
};
export const SEVERITY_NAME: Record<Severity, string> = {
  ok: "Matched", expected: "Explained", review: "Needs review", break: "Break",
};

export function ClassBadge({ label, severity, className }:
  { label: string; severity: Severity; className?: string }) {
  return (
    <span className={cn("inline-flex items-center gap-1.5 whitespace-nowrap text-sm", SEVERITY_TEXT[severity], className)}>
      <span aria-hidden className={cn("h-2 w-2 shrink-0 rounded-full", SEVERITY_BG[severity])} />
      {human(label)}
    </span>
  );
}
