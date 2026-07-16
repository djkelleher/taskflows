import { forwardRef, type InputHTMLAttributes } from "react";

import { cx } from "../lib/cx";
import { useFormFieldContext } from "./FormField";

export interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  invalid?: boolean;
}

export const Input = forwardRef<HTMLInputElement, InputProps>(function Input(
  {
    "aria-describedby": ariaDescribedBy,
    "aria-errormessage": ariaErrorMessage,
    "aria-invalid": ariaInvalid,
    "aria-required": ariaRequired,
    className,
    id,
    invalid,
    type = "text",
    ...props
  },
  ref
) {
  const field = useFormFieldContext();
  const isAriaInvalid =
    ariaInvalid === true ||
    ariaInvalid === "true" ||
    ariaInvalid === "grammar" ||
    ariaInvalid === "spelling";
  const isInvalid = invalid ?? field?.invalid ?? isAriaInvalid;
  const describedBy = ariaDescribedBy ?? field?.describedBy;
  const errorMessage = ariaErrorMessage ?? (isInvalid ? field?.errorId : undefined);
  const required = ariaRequired ?? (props.required || field?.required ? true : undefined);

  return (
    <input
      ref={ref}
      aria-describedby={describedBy}
      aria-errormessage={errorMessage}
      aria-invalid={isInvalid ? true : undefined}
      aria-required={required}
      className={cx(
        "h-9 w-full rounded-md border bg-card px-3 text-sm text-foreground outline-none transition-colors",
        "placeholder:text-muted disabled:cursor-not-allowed disabled:opacity-60",
        "focus:border-accent focus:ring-2 focus:ring-accent/20",
        isInvalid ? "border-negative" : "border-border",
        className
      )}
      id={id ?? field?.id}
      type={type}
      {...props}
    />
  );
});
