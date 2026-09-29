import { motion, useReducedMotion } from "framer-motion";
import { useEffect, useId, useState, type RefObject } from "react";
import { cn } from "@/lib/utils";

/**
 * A curved line between two elements, with a pulse travelling along it.
 *
 * Ported from Magic UI's Animated Beam (magicui.design/docs/components/
 * animated-beam) to framer-motion and this site's colour tokens. Used for
 * one purpose: to show a record's direction of travel, from the source files
 * into the engine and out to an outcome. With reduced motion the line is
 * drawn and the pulse is left out.
 */
export function AnimatedBeam({
  containerRef, fromRef, toRef, className, curvature = 0, reverse = false,
  duration = 4, delay = 0, color = "rgb(var(--tick))", pathOpacity = 0.25, pathWidth = 1.5, active = true,
}: {
  containerRef: RefObject<HTMLElement | null>;
  fromRef: RefObject<HTMLElement | null>;
  toRef: RefObject<HTMLElement | null>;
  className?: string; curvature?: number; reverse?: boolean;
  duration?: number; delay?: number; color?: string; pathOpacity?: number; pathWidth?: number;
  /** Off-screen beams draw their line but run no pulse: each pulse costs a
   *  style and paint pass every frame, whether anyone can see it or not. */
  active?: boolean;
}) {
  // useId returns colons, which are not valid in a url(#...) reference.
  const id = useId().replace(/:/g, "");
  const reduce = useReducedMotion();
  const [d, setD] = useState("");
  const [size, setSize] = useState({ width: 0, height: 0 });

  useEffect(() => {
    const update = () => {
      const c = containerRef.current, a = fromRef.current, b = toRef.current;
      if (!c || !a || !b) return;
      const cr = c.getBoundingClientRect(), ra = a.getBoundingClientRect(), rb = b.getBoundingClientRect();
      setSize({ width: cr.width, height: cr.height });
      // Leave from the edge of the source that faces the target and arrive at
      // the facing edge of the target, so the line reads as a flow. Side by
      // side (wide screens) that is right to left; stacked (phones) it is
      // bottom to top.
      if (rb.left >= ra.right - 1) {
        const sx = ra.right - cr.left, sy = ra.top - cr.top + ra.height / 2;
        const ex = rb.left - cr.left, ey = rb.top - cr.top + rb.height / 2;
        const mx = (sx + ex) / 2;
        setD(`M ${sx},${sy} C ${mx},${sy - curvature} ${mx},${ey - curvature} ${ex},${ey}`);
      } else {
        const sx = ra.left - cr.left + ra.width / 2, sy = ra.bottom - cr.top;
        const ex = rb.left - cr.left + rb.width / 2, ey = rb.top - cr.top;
        const my = (sy + ey) / 2;
        setD(`M ${sx},${sy} C ${sx},${my} ${ex},${my} ${ex},${ey}`);
      }
    };
    const ro = new ResizeObserver(update);
    if (containerRef.current) ro.observe(containerRef.current);
    update();
    return () => ro.disconnect();
  }, [containerRef, fromRef, toRef, curvature]);

  // Nothing to draw until the ends have been measured, which happens only in
  // the browser. Rendering nothing until then also keeps the prerendered HTML
  // and the first client render identical.
  if (!d) return null;

  const x = reverse ?{ x1: ["90%", "-10%"], x2: ["100%", "0%"] } : { x1: ["10%", "110%"], x2: ["0%", "100%"] };

  return (
    <svg aria-hidden fill="none" width={size.width} height={size.height}
      viewBox={`0 0 ${size.width} ${size.height}`}
      className={cn("pointer-events-none absolute left-0 top-0", className)}>
      <path d={d} stroke={color} strokeWidth={pathWidth} strokeOpacity={pathOpacity} strokeLinecap="round" />
      {!reduce && active && (
        <>
          <path d={d} stroke={`url(#${id})`} strokeWidth={pathWidth + 0.5} strokeLinecap="round" />
          <defs>
            <motion.linearGradient id={id} gradientUnits="userSpaceOnUse"
              initial={{ x1: "0%", x2: "0%", y1: "0%", y2: "0%" }}
              animate={{ ...x, y1: ["0%", "0%"], y2: ["0%", "0%"] }}
              transition={{ delay, duration, ease: [0.16, 1, 0.3, 1], repeat: Infinity, repeatDelay: 1.2 }}>
              <stop stopColor={color} stopOpacity="0" />
              <stop stopColor={color} />
              <stop offset="32.5%" stopColor={color} />
              <stop offset="100%" stopColor={color} stopOpacity="0" />
            </motion.linearGradient>
          </defs>
        </>
      )}
    </svg>
  );
}
