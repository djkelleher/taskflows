import {
  createContext,
  forwardRef,
  type HTMLAttributes,
  type InputHTMLAttributes,
  type ReactNode,
  useContext,
  useId,
} from "react";

import { cx } from "../lib/cx";
import { useFormFieldContext } from "./FormField";

interface RadioGroupContextValue {
  invalid?: boolean;
  name?: string;
  onValueChange?: (value: string) => void;
  value?: string;
}

const RadioGroupContext = createContext<RadioGroupContextValue | null>(null);

export interface RadioGroupProps extends Omit<HTMLAttributes<HTMLDivElement>, "onChange"> {
  children: ReactNode;
  invalid?: boolean;
  name?: string;
  onValueChange?: (value: string) => void;
  orientation?: "vertical" | "horizontal";
  value?: string;
}

/** Groups Radio controls, sharing name/value and emitting a single onValueChange. */
export function RadioGroup({
  "aria-labelledby": ariaLabelledBy,
  children,
  className,
  invalid,
  name,
  onValueChange,
  orientation = "vertical",
  value,
  ...props
}: RadioGroupProps) {
  const field = useFormFieldContext();
  const generatedName = useId();
  const isInvalid = invalid ?? field?.invalid;

  return (
    <RadioGroupContext.Provider
      value={{ invalid: isInvalid, name: name ?? generatedName, onValueChange, value }}
    >
      <div
        aria-labelledby={ariaLabelledBy}
        className={cx(
          "grid gap-2",
          orientation === "horizontal" && "sm:grid-flow-col sm:auto-cols-max",
          className
        )}
        role="radiogroup"
        {...props}
      >
        {children}
      </div>
    </RadioGroupContext.Provider>
  );
}

export interface RadioProps extends Omit<InputHTMLAttributes<HTMLInputElement>, "type"> {
  description?: ReactNode;
  invalid?: boolean;
  label?: ReactNode;
  value: string;
}

export const Radio = forwardRef<HTMLInputElement, RadioProps>(function Radio(
  { checked, className, description, id, invalid, label, name, onChange, value, ...props },
  ref
) {
  const generatedId = useId();
  const group = useContext(RadioGroupContext);
  const controlId = id ?? `${generatedId}-control`;
  const descriptionId = `${generatedId}-description`;
  const isInvalid = invalid ?? group?.invalid;

  const input = (
    <input
      ref={ref}
      aria-describedby={description ? descriptionId : undefined}
      aria-invalid={isInvalid ? true : undefined}
      checked={group ? group.value === value : checked}
      className={cx(
        "mt-0.5 size-4 border-border text-accent accent-accent",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent",
        "disabled:cursor-not-allowed disabled:opacity-60",
        isInvalid && "border-negative",
        className
      )}
      id={controlId}
      name={group?.name ?? name}
      onChange={(event) => {
        onChange?.(event);
        if (!event.defaultPrevented) {
          group?.onValueChange?.(value);
        }
      }}
      type="radio"
      value={value}
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
