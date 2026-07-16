import { forwardRef, type InputHTMLAttributes, type ReactNode, useId } from "react";

import { cx } from "../lib/cx";
import { useFormFieldContext } from "./FormField";

export interface SwitchProps extends Omit<InputHTMLAttributes<HTMLInputElement>, "type" | "size"> {
  description?: ReactNode;
  invalid?: boolean;
  label?: ReactNode;
  size?: "sm" | "md";
}

const trackSize = {
  sm: "h-4 w-7",
  md: "h-5 w-9",
};

const thumbSize = {
  sm: "size-3 peer-checked:translate-x-3",
  md: "size-4 peer-checked:translate-x-4",
};

/**
 * Accessible on/off toggle built on a native checkbox (role switch) so it works
 * inside forms and with FormField. Keyboard and label semantics come for free.
 */
export const Switch = forwardRef<HTMLInputElement, SwitchProps>(function Switch(
  {
    "aria-describedby": ariaDescribedBy,
    "aria-invalid": ariaInvalid,
    className,
    description,
    id,
    invalid,
    label,
    size = "md",
    ...props
  },
  ref
) {
  const generatedId = useId();
  const field = useFormFieldContext();
  const controlId = id ?? field?.id ?? `${generatedId}-control`;
  const descriptionId = `${generatedId}-description`;
  const isInvalid = invalid ?? field?.invalid ?? (ariaInvalid === true || ariaInvalid === "true");
  const describedBy =
    [ariaDescribedBy, description ? descriptionId : undefined, field?.describedBy]
      .filter(Boolean)
      .join(" ") || undefined;

  const control = (
    <span className={cx("relative inline-flex shrink-0 items-center", trackSize[size])}>
      <input
        ref={ref}
        aria-describedby={describedBy}
        aria-invalid={isInvalid ? true : undefined}
        className="peer absolute inset-0 z-10 cursor-pointer opacity-0 disabled:cursor-not-allowed"
        id={controlId}
        role="switch"
        type="checkbox"
        {...props}
      />
      <span
        aria-hidden="true"
        className={cx(
          "absolute inset-0 rounded-full border border-border bg-surface-muted transition-colors",
          "peer-checked:border-accent peer-checked:bg-accent",
          "peer-focus-visible:ring-2 peer-focus-visible:ring-accent peer-focus-visible:ring-offset-2",
          "peer-disabled:opacity-60",
          isInvalid && "border-negative",
          className
        )}
      />
      <span
        aria-hidden="true"
        className={cx(
          "pointer-events-none absolute left-0.5 rounded-full bg-card shadow-sm transition-transform",
          thumbSize[size]
        )}
      />
    </span>
  );

  if (!label && !description) {
    return control;
  }

  return (
    <div className="flex items-start gap-2 text-sm text-foreground">
      {control}
      <div className="grid gap-0.5">
        {label ? (
          <label className="font-medium leading-5" htmlFor={controlId}>
            {label}
          </label>
        ) : null}
        {description ? (
          <div className="text-xs leading-5 text-muted" id={descriptionId}>
            {description}
          </div>
        ) : null}
      </div>
    </div>
  );
});
