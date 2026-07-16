import { forwardRef, type TextareaHTMLAttributes } from "react";

import { cx } from "../lib/cx";
import { useFormFieldContext } from "./FormField";

export interface TextareaProps extends TextareaHTMLAttributes<HTMLTextAreaElement> {
  invalid?: boolean;
}

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaProps>(function Textarea(
  {
    "aria-describedby": ariaDescribedBy,
    "aria-errormessage": ariaErrorMessage,
    "aria-invalid": ariaInvalid,
    "aria-required": ariaRequired,
    className,
    id,
    invalid,
    rows = 3,
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
    <textarea
      ref={ref}
      aria-describedby={describedBy}
      aria-errormessage={errorMessage}
      aria-invalid={isInvalid ? true : undefined}
      aria-required={required}
      className={cx(
        "w-full rounded-md border bg-card px-3 py-2 text-sm text-foreground outline-none transition-colors",
        "placeholder:text-muted disabled:cursor-not-allowed disabled:opacity-60",
        "focus:border-accent focus:ring-2 focus:ring-accent/20",
        isInvalid ? "border-negative" : "border-border",
        className
      )}
      id={id ?? field?.id}
      rows={rows}
      {...props}
    />
  );
});
