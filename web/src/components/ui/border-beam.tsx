import { motion, useReducedMotion } from "framer-motion";

/**
 * A short highlight travelling round the border of its parent.
 *
 * Ported from Magic UI's Border Beam (magicui.design/docs/components/
 * border-beam) to Tailwind 3 and framer-motion. It means one thing on this
 * site: the engine is working on the thing it surrounds. It is mounted only
 * while a request is in flight, never as decoration. The parent needs
 * `position: relative` and a border radius.
 */
export function BorderBeam({ size = 120, duration = 3, color = "rgb(var(--tick))", width = 1.5 }: {
  size?: number; duration?: number; color?: string; width?: number;
}) {
  const reduce = useReducedMotion();
  return (
    <div aria-hidden className="pointer-events-none absolute inset-0 rounded-[inherit]"
      style={{
        border: `${width}px solid transparent`,
        // Show only the border box: the padding box is masked out.
        mask: "linear-gradient(transparent, transparent) padding-box, linear-gradient(#000, #000) border-box",
        maskComposite: "intersect",
        WebkitMask: "linear-gradient(transparent, transparent) padding-box, linear-gradient(#000, #000) border-box",
        WebkitMaskComposite: "source-in",
      }}>
      {reduce ? (
        <div className="absolute inset-0" style={{ boxShadow: `inset 0 0 0 ${width}px ${color}` }} />
      ) : (
        <motion.div className="absolute aspect-square"
          style={{
            width: size,
            offsetPath: `rect(0 auto auto 0 round ${size}px)`,
            background: `linear-gradient(to left, ${color}, transparent)`,
          }}
          initial={{ offsetDistance: "0%" }}
          animate={{ offsetDistance: ["0%", "100%"] }}
          transition={{ repeat: Infinity, ease: "linear", duration }} />
      )}
    </div>
  );
}
