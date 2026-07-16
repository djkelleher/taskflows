import { forwardRef, type HTMLAttributes } from "react";

import { cx } from "../lib/cx";

export interface CardProps extends HTMLAttributes<HTMLDivElement> {
  padded?: boolean;
}

export const Card = forwardRef<HTMLDivElement, CardProps>(function Card(
  { className, padded = true, ...props },
  ref
) {
  return (
    <div
      ref={ref}
      className={cx(
        "rounded-lg border border-border bg-card shadow-[var(--shadow-card)]",
        padded && "p-4",
        className
      )}
      {...props}
    />
  );
});

export interface CardSectionProps extends HTMLAttributes<HTMLDivElement> {}

export const CardHeader = forwardRef<HTMLDivElement, CardSectionProps>(function CardHeader(
  { className, ...props },
  ref
) {
  return <div ref={ref} className={cx("flex items-start justify-between gap-3", className)} {...props} />;
});

export const CardContent = forwardRef<HTMLDivElement, CardSectionProps>(function CardContent(
  { className, ...props },
  ref
) {
  return <div ref={ref} className={cx("mt-4 min-w-0", className)} {...props} />;
});

export const CardFooter = forwardRef<HTMLDivElement, CardSectionProps>(function CardFooter(
  { className, ...props },
  ref
) {
  return <div ref={ref} className={cx("mt-4 border-t border-border pt-4", className)} {...props} />;
});
