import { forwardRef, type SelectHTMLAttributes } from "react";

import { cx } from "../lib/cx";
import { useFormFieldContext } from "./FormField";

export interface SelectOption {
  disabled?: boolean;
  label: string;
  value: string;
}

export interface SelectProps extends SelectHTMLAttributes<HTMLSelectElement> {
  invalid?: boolean;
  options?: SelectOption[];
  placeholder?: string;
}

export const Select = forwardRef<HTMLSelectElement, SelectProps>(function Select(
  {
    "aria-describedby": ariaDescribedBy,
    "aria-errormessage": ariaErrorMessage,
    "aria-invalid": ariaInvalid,
    "aria-required": ariaRequired,
    children,
    className,
    id,
    invalid,
    options,
    placeholder,
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
    <select
      ref={ref}
      aria-describedby={describedBy}
      aria-errormessage={errorMessage}
      aria-invalid={isInvalid ? true : undefined}
      aria-required={required}
      className={cx(
        "h-9 w-full rounded-md border bg-card px-3 text-sm text-foreground outline-none transition-colors",
        "disabled:cursor-not-allowed disabled:opacity-60",
        "focus:border-accent focus:ring-2 focus:ring-accent/20",
        isInvalid ? "border-negative" : "border-border",
        className
      )}
      id={id ?? field?.id}
      {...props}
    >
      {placeholder ? (
        <option value="" disabled={props.required}>
          {placeholder}
        </option>
      ) : null}
      {options?.map((option) => (
        <option key={option.value} disabled={option.disabled} value={option.value}>
          {option.label}
        </option>
      ))}
      {children}
    </select>
  );
});
