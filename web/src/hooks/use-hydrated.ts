import { useEffect, useState } from "react";

/**
 * False while prerendering and during hydration, true once mounted.
 *
 * renderToString cannot wait for a lazy component: it writes the Suspense
 * fallback with a marker, and the client then abandons that boundary and
 * re-renders it, logging React error #419. Rendering the placeholder
 * directly until hydration has finished keeps server and client output
 * identical, and only then brings in the lazy chunk.
 */
export function useHydrated(): boolean {
  const [hydrated, setHydrated] = useState(false);
  useEffect(() => setHydrated(true), []);
  return hydrated;
}

/** True while `ref` is within `margin` of the viewport. */
export function useInViewport(ref: React.RefObject<Element | null>, margin = "200px"): boolean {
  const [inView, setInView] = useState(false);
  useEffect(() => {
    const el = ref.current;
    if (!el || typeof IntersectionObserver === "undefined") { setInView(true); return; }
    const io = new IntersectionObserver(([e]) => setInView(e.isIntersecting), { rootMargin: margin });
    io.observe(el);
    return () => io.disconnect();
  }, [ref, margin]);
  return inView;
}
