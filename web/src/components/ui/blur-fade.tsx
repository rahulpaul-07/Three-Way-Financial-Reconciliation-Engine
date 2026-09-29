import { useEffect, useRef, useState } from "react";
import { cn } from "@/lib/utils";

/**
 * Fades and un-blurs its children the first time they scroll into view.
 *
 * After Magic UI's Blur Fade (magicui.design/docs/components/blur-fade),
 * rebuilt on CSS rather than a motion component, for one reason: the page is
 * prerendered. A motion component renders its hidden state into the HTML, so
 * the prerendered page would be blank until the bundle ran, which is the
 * delay the prerender exists to remove. Here the hidden state applies only
 * under `html.js` (set by an inline script in index.html), and only when the
 * visitor has not asked for reduced motion; see `.blur-fade` in index.css.
 */
export function BlurFade({ children, className, delay = 0, as: Tag = "div" }: {
  children: React.ReactNode; className?: string; delay?: number;
  as?: "div" | "section" | "li";
}) {
  const ref = useRef<HTMLElement | null>(null);
  const [shown, setShown] = useState(false);

  useEffect(() => {
    const el = ref.current;
    if (!el || typeof IntersectionObserver === "undefined") { setShown(true); return; }
    const io = new IntersectionObserver(([entry]) => {
      if (entry.isIntersecting) { setShown(true); io.disconnect(); }
    }, { rootMargin: "0px 0px -8% 0px" });
    io.observe(el);
    return () => io.disconnect();
  }, []);

  return (
    <Tag ref={ref as never} data-shown={shown ? "" : undefined}
      style={delay ? { transitionDelay: `${delay}s` } : undefined}
      className={cn("blur-fade", className)}>
      {children}
    </Tag>
  );
}
