import { Sparkles, Star, Zap, Circle, Square, Triangle, Hexagon, Plus } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";

/** The five accents, in rotation order. A section or a grid item takes
    `ACCENTS[i % ACCENTS.length]`; the CSS reads it from `data-accent`. */
export const ACCENT_COUNT = 5;
export const accentOf = (i: number) => i % ACCENT_COUNT;

const ICONS: LucideIcon[] = [Star, Sparkles, Zap, Circle, Square, Triangle, Hexagon, Plus];
const COLORS = ["text-magenta", "text-tick", "text-pencil", "text-orange", "text-violet"];
const MOTION = ["animate-float", "animate-float-reverse", "animate-wiggle", "animate-bounce-subtle", "animate-spin-slow"];

/** Fixed spots so server and client render the same markup. */
const SPOTS = [
  { top: "6%", left: "4%", size: 40 }, { top: "12%", right: "6%", size: 64 },
  { top: "34%", left: "1.5%", size: 28 }, { top: "46%", right: "2.5%", size: 48 },
  { top: "64%", left: "6%", size: 56 }, { top: "78%", right: "9%", size: 32 },
  { top: "90%", left: "42%", size: 44 }, { top: "24%", left: "46%", size: 24 },
  { top: "58%", right: "34%", size: 36 }, { top: "4%", left: "58%", size: 30 },
];

/** Scattered SVG shapes. Decorative, so hidden from assistive tech; only the
    first six show on small screens to keep the page readable on a phone. */
export function FloatingShapes({ seed = 0, count = 8 }: { seed?: number; count?: number }) {
  return (
    <div aria-hidden className="pointer-events-none absolute inset-0 overflow-hidden">
      {SPOTS.slice(0, count).map((s, i) => {
        const k = i + seed;
        const Icon = ICONS[k % ICONS.length];
        const { size, ...pos } = s;
        return (
          <Icon key={i} size={size} strokeWidth={2.5}
            className={cn("shape fill-current", COLORS[k % COLORS.length], MOTION[k % MOTION.length], i >= 6 && "hidden md:block")}
            style={{ ...pos, opacity: 0.85, animationDelay: `${(i % 4) * -1.1}s` }} />
        );
      })}
    </div>
  );
}

/** A page section with its own accent, two layered patterns, oversized
    background type and floating shapes. Children sit above all of it. */
export function Section({ id, accent, word, patterns = ["dots", "stripes"], wordClass, children, className }: {
  id?: string; accent: number; word: string;
  patterns?: ("dots" | "stripes" | "checker" | "mesh")[]; wordClass?: string;
  children: React.ReactNode; className?: string;
}) {
  return (
    <section id={id} data-accent={accentOf(accent)}
      className={cn("relative overflow-hidden border-b-8 border-double border-[rgb(var(--a))]", className)}>
      {patterns.map((p) => <div key={p} aria-hidden className={cn("pattern-layer", `pattern-${p}`, p === "dots" && "opacity-25")} />)}
      <span aria-hidden className={cn("bg-word right-[-2rem] top-6 font-display", wordClass)}>{word}</span>
      <FloatingShapes seed={accent * 2} />
      <div className="relative z-10">{children}</div>
    </section>
  );
}
