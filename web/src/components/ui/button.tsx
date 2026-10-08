import { forwardRef, type ButtonHTMLAttributes } from "react";
import { cn } from "@/lib/utils";

type Variant = "ink" | "outline" | "quiet";
type Size = "sm" | "md";

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
}

const variants: Record<Variant, string> = {
  ink: "btn-primary hover:z-10 disabled:opacity-50",
  outline: "btn-secondary disabled:opacity-50",
  quiet: "btn-ghost text-ink disabled:opacity-50",
};
const sizes: Record<Size, string> = {
  sm: "h-10 px-5 text-xs gap-1.5",
  md: "h-14 px-9 text-sm gap-2",
};

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant = "ink", size = "md", ...props }, ref) => (
    <button
      ref={ref}
      className={cn(
        "btn-max inline-flex items-center justify-center disabled:cursor-not-allowed",
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
      className={cn("btn-max inline-flex items-center justify-center",
        variants[variant], sizes[size], className)}
      {...props}
    />
  );
}
