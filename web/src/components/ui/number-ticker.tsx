import { animate, useReducedMotion } from "framer-motion";
import { useEffect, useRef, useState } from "react";

/**
 * Shows a number, and when it changes -- a different batch was reconciled --
 * counts from the old value to the new one so the change is visible. The
 * first render shows the real value at once: a figure that starts at zero
 * misreports the data to anyone who screenshots or scrolls past too fast.
 */
export function NumberTicker({ value, format, duration = 0.8 }: {
  value: number; format: (n: number) => string; duration?: number;
}) {
  const reduce = useReducedMotion();
  const [shown, setShown] = useState(value);
  const prev = useRef(value);

  useEffect(() => {
    const from = prev.current;
    prev.current = value;
    if (reduce || from === value) { setShown(value); return; }
    const controls = animate(from, value, { duration, ease: [0.16, 1, 0.3, 1], onUpdate: setShown });
    return () => controls.stop();
  }, [value, reduce, duration]);

  return <span className="num">{format(shown)}</span>;
}
