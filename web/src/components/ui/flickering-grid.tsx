import { useEffect, useRef } from "react";
import { cn } from "@/lib/utils";

/**
 * A grid of small squares, a few of which brighten and fade at random.
 *
 * After Magic UI's Flickering Grid (magicui.design/docs/components/
 * flickering-grid), drawn on one canvas. It redraws about eight times a
 * second rather than every frame, and stops entirely when it is off screen,
 * when the tab is hidden, or when the visitor asks for reduced motion (one
 * still frame is drawn instead). The colour is read from a CSS variable, so
 * it follows the theme.
 */
export function FlickeringGrid({ className, square = 3, gap = 7, chance = 0.08, maxOpacity = 0.35, color = "--tick" }: {
  className?: string; square?: number; gap?: number; chance?: number; maxOpacity?: number; color?: string;
}) {
  const ref = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = ref.current;
    const ctx = canvas?.getContext("2d");
    if (!canvas || !ctx) return;
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    let cols = 0, rows = 0, cells = new Float32Array(0), rgb = "0 0 0";
    let timer = 0, visible = false;
    const step = square + gap;

    function resize() {
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      const { width, height } = canvas!.getBoundingClientRect();
      canvas!.width = Math.round(width * dpr);
      canvas!.height = Math.round(height * dpr);
      ctx!.setTransform(dpr, 0, 0, dpr, 0, 0);
      cols = Math.ceil(width / step);
      rows = Math.ceil(height / step);
      cells = new Float32Array(cols * rows).map(() => Math.random() * maxOpacity);
      rgb = getComputedStyle(canvas!).getPropertyValue(color).trim() || rgb;
      draw();
    }
    function draw() {
      ctx!.clearRect(0, 0, cols * step, rows * step);
      for (let i = 0; i < cells.length; i++) {
        ctx!.fillStyle = `rgb(${rgb} / ${cells[i]})`;
        ctx!.fillRect((i % cols) * step, Math.floor(i / cols) * step, square, square);
      }
    }
    function tick() {
      for (let i = 0; i < cells.length; i++) if (Math.random() < chance) cells[i] = Math.random() * maxOpacity;
      draw();
    }
    function sync() {
      const run = visible && !reduce && document.visibilityState === "visible";
      if (run && !timer) timer = window.setInterval(tick, 125);
      if (!run && timer) { clearInterval(timer); timer = 0; }
    }

    resize();
    const ro = new ResizeObserver(resize);
    ro.observe(canvas);
    const io = new IntersectionObserver(([e]) => { visible = e.isIntersecting; sync(); });
    io.observe(canvas);
    document.addEventListener("visibilitychange", sync);
    const scheme = window.matchMedia("(prefers-color-scheme: dark)");
    const recolor = () => { rgb = getComputedStyle(canvas).getPropertyValue(color).trim() || rgb; draw(); };
    scheme.addEventListener("change", recolor);
    return () => {
      clearInterval(timer);
      ro.disconnect(); io.disconnect();
      document.removeEventListener("visibilitychange", sync);
      scheme.removeEventListener("change", recolor);
    };
  }, [square, gap, chance, maxOpacity, color]);

  return <canvas ref={ref} aria-hidden className={cn("pointer-events-none h-full w-full", className)} />;
}
