import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from "react";

import { cx } from "../lib/cx";

export type ButtonVariant = "primary" | "secondary" | "outline" | "ghost" | "danger" | "success";
export type ButtonSize = "sm" | "md" | "lg";

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  fullWidth?: boolean;
  leftIcon?: ReactNode;
  loading?: boolean;
  rightIcon?: ReactNode;
  size?: ButtonSize;
  variant?: ButtonVariant;
}

const spinnerSizeClass: Record<ButtonSize, string> = {
  sm: "size-3",
  md: "size-4",
  lg: "size-5",
};

function ButtonSpinner({ size }: { size: ButtonSize }) {
  return (
    <span
      aria-hidden="true"
      className={cx(
        "animate-spin rounded-full border-2 border-current/30 border-t-current",
        spinnerSizeClass[size]
      )}
    />
  );
}

const variantClass: Record<ButtonVariant, string> = {
  primary: "border-accent bg-accent text-white hover:bg-accent/90",
  secondary:
    "border-border bg-card text-foreground hover:border-accent hover:text-accent",
  outline: "border-accent bg-transparent text-accent hover:bg-accent/10",
  ghost: "border-transparent bg-transparent text-foreground hover:bg-background",
  danger: "border-negative/20 bg-negative/10 text-negative hover:border-negative",
  success: "border-positive bg-positive text-white hover:bg-positive/90",
};

const sizeClass: Record<ButtonSize, string> = {
  sm: "min-h-8 px-2 text-xs",
  md: "min-h-9 px-3 text-sm",
  lg: "min-h-10 px-4 text-base",
};

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  {
    children,
    className,
    disabled,
    fullWidth,
    leftIcon,
    loading = false,
    rightIcon,
    size = "md",
    type = "button",
    variant = "secondary",
    ...props
  },
  ref
) {
  return (
    <button
      ref={ref}
      aria-busy={loading || undefined}
      className={cx(
        "inline-flex items-center justify-center gap-2 rounded-md border font-semibold transition-colors",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2",
        "disabled:cursor-not-allowed disabled:opacity-[0.55]",
        fullWidth && "w-full",
        sizeClass[size],
        variantClass[variant],
        className
      )}
      disabled={disabled || loading}
      type={type}
      {...props}
    >
      {loading ? <ButtonSpinner size={size} /> : leftIcon}
      {children}
      {loading ? null : rightIcon}
    </button>
  );
});

export interface IconButtonProps extends Omit<ButtonProps, "children" | "leftIcon" | "rightIcon"> {
  "aria-label": string;
  icon: ReactNode;
}

export const IconButton = forwardRef<HTMLButtonElement, IconButtonProps>(function IconButton(
  { className, icon, size = "md", title, variant = "secondary", ...props },
  ref
) {
  return (
    <Button
      ref={ref}
      className={cx("aspect-square px-0", className)}
      size={size}
      title={title ?? props["aria-label"]}
      variant={variant}
      {...props}
    >
      {icon}
    </Button>
  );
});
