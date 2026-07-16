import { forwardRef, type InputHTMLAttributes, type ReactNode, useId } from "react";

import { cx } from "../lib/cx";
import { useFormFieldContext } from "./FormField";

export interface CheckboxProps extends Omit<InputHTMLAttributes<HTMLInputElement>, "type"> {
  description?: ReactNode;
  invalid?: boolean;
  label?: ReactNode;
}

export const Checkbox = forwardRef<HTMLInputElement, CheckboxProps>(function Checkbox(
  {
    "aria-describedby": ariaDescribedBy,
    "aria-errormessage": ariaErrorMessage,
    "aria-invalid": ariaInvalid,
    "aria-required": ariaRequired,
    className,
    description,
    id,
    invalid,
    label,
    ...props
  },
  ref
) {
  const generatedId = useId();
  const field = useFormFieldContext();
  const controlId = id ?? field?.id ?? `${generatedId}-control`;
  const generatedDescriptionId = `${generatedId}-description`;
  const isAriaInvalid =
    ariaInvalid === true ||
    ariaInvalid === "true" ||
    ariaInvalid === "grammar" ||
    ariaInvalid === "spelling";
  const isInvalid = invalid ?? field?.invalid ?? isAriaInvalid;
  const describedBy = [
    ariaDescribedBy,
    description ? generatedDescriptionId : undefined,
    ariaDescribedBy ? undefined : field?.describedBy,
  ]
    .filter(Boolean)
    .join(" ") || undefined;
  const errorMessage = ariaErrorMessage ?? (isInvalid ? field?.errorId : undefined);
  const required = ariaRequired ?? (props.required || field?.required ? true : undefined);

  const input = (
    <input
      ref={ref}
      aria-describedby={describedBy}
      aria-errormessage={errorMessage}
      aria-invalid={isInvalid ? true : undefined}
      aria-required={required}
      className={cx(
        "mt-0.5 size-4 rounded border-border text-accent accent-accent",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent",
        "disabled:cursor-not-allowed disabled:opacity-60",
        isInvalid && "border-negative",
        className
      )}
      id={controlId}
      type="checkbox"
      {...props}
    />
  );

  if (!label && !description) {
    return input;
  }

  return (
    <div className="flex items-start gap-2 text-sm text-foreground">
      {input}
      <div className="grid gap-0.5">
        {label ? (
          <label className="font-medium leading-5" htmlFor={controlId}>
            {label}
            {required ? <span className="ml-1 text-negative" aria-hidden="true">*</span> : null}
          </label>
        ) : null}
        {description ? (
          <div className="text-xs leading-5 text-muted" id={generatedDescriptionId}>
            {description}
          </div>
        ) : null}
      </div>
    </div>
  );
});
