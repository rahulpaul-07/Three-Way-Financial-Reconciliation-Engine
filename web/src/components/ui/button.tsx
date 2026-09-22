import { forwardRef, type ButtonHTMLAttributes } from "react";
import { cn } from "@/lib/utils";

type Variant = "ink" | "outline" | "quiet";
type Size = "sm" | "md";

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
}

const variants: Record<Variant, string> = {
  ink: "bg-ink text-paper hover:bg-ink/90 disabled:bg-ink/40",
  outline: "border border-ink/35 text-ink hover:border-ink hover:bg-ink/[0.04] disabled:opacity-50",
  quiet: "text-graphite hover:text-ink hover:bg-ink/[0.05] disabled:opacity-50",
};
const sizes: Record<Size, string> = {
  sm: "h-8 px-3 text-sm gap-1.5",
  md: "h-10 px-4 text-[0.95rem] gap-2",
};

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant = "ink", size = "md", ...props }, ref) => (
    <button
      ref={ref}
      className={cn(
        "inline-flex items-center justify-center rounded font-medium transition-colors disabled:cursor-not-allowed",
        variants[variant], sizes[size], className,
      )}
      {...props}
    />
  ),
);
Button.displayName = "Button";

export function ButtonLink({ className, variant = "outline", size = "md", ...props }:
  React.AnchorHTMLAttributes<HTMLAnchorElement> & { variant?: Variant; size?: Size }) {
  return (
    <a
      className={cn("inline-flex items-center justify-center rounded font-medium transition-colors",
        variants[variant], sizes[size], className)}
      {...props}
    />
  );
}
