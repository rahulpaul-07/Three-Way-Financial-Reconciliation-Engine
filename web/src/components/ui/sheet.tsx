import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { X } from "lucide-react";
import { useEffect, useRef } from "react";

/** A side panel over the page. Closes on Escape and on the backdrop. */
export function Sheet({ open, onClose, title, children }: {
  open: boolean; onClose: () => void; title: React.ReactNode; children: React.ReactNode;
}) {
  const reduce = useReducedMotion();
  const closeRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;
    const prev = document.activeElement as HTMLElement | null;
    closeRef.current?.focus();
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = "";
      prev?.focus();
    };
  }, [open, onClose]);

  return (
    <AnimatePresence>
      {open && (
        <div className="fixed inset-0 z-50" role="dialog" aria-modal="true">
          <motion.div className="absolute inset-0 bg-paper/70 backdrop-blur-sm" onClick={onClose}
            initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} />
          <motion.aside
            className="absolute right-0 top-0 flex h-full w-full max-w-[34rem] flex-col border-l-8 border-dashed border-magenta bg-sheet shadow-[-12px_0_0_rgb(var(--pencil))]"
            style={{ paddingTop: "env(safe-area-inset-top, 0px)" }}
            initial={reduce ? { opacity: 0 } : { x: "100%" }}
            animate={reduce ? { opacity: 1 } : { x: 0 }}
            exit={reduce ? { opacity: 0 } : { x: "100%" }}
            transition={{ type: "tween", duration: 0.22, ease: "easeOut" }}>
            <header className="flex items-start justify-between gap-4 border-b-4 border-dashed border-tick px-6 py-4">
              <div className="min-w-0">{title}</div>
              <button ref={closeRef} onClick={onClose} aria-label="Close"
                className="rounded-full border-2 border-pencil p-1.5 text-pencil transition-transform hover:rotate-90 hover:bg-pencil hover:text-paper">
                <X size={18} />
              </button>
            </header>
            <div className="flex-1 overflow-y-auto px-6 py-5">{children}</div>
          </motion.aside>
        </div>
      )}
    </AnimatePresence>
  );
}
