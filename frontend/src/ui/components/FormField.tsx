import {
  createContext,
  type HTMLAttributes,
  type ReactNode,
  useContext,
  useId,
  useMemo,
} from "react";

import { cx } from "../lib/cx";

export interface FormFieldContextValue {
  describedBy?: string;
  errorId?: string;
  id: string;
  invalid: boolean;
  required: boolean;
}

const FormFieldContext = createContext<FormFieldContextValue | null>(null);

export function useFormFieldContext() {
  return useContext(FormFieldContext);
}

export interface FormFieldProps extends HTMLAttributes<HTMLDivElement> {
  children: ReactNode;
  description?: ReactNode;
  descriptionId?: string;
  error?: ReactNode;
  errorId?: string;
  htmlFor?: string;
  label?: ReactNode;
  orientation?: "vertical" | "horizontal";
  required?: boolean;
}

export function FormField({
  children,
  className,
  description,
  descriptionId,
  error,
  errorId,
  htmlFor,
  label,
  orientation = "vertical",
  required = false,
  ...props
}: FormFieldProps) {
  const generatedId = useId();
  const controlId = htmlFor ?? `${generatedId}-control`;
  const generatedDescriptionId = descriptionId ?? `${generatedId}-description`;
  const generatedErrorId = errorId ?? `${generatedId}-error`;
  const describedBy = [
    description ? generatedDescriptionId : undefined,
    error ? generatedErrorId : undefined,
  ]
    .filter(Boolean)
    .join(" ") || undefined;

  const context = useMemo<FormFieldContextValue>(
    () => ({
      describedBy,
      errorId: error ? generatedErrorId : undefined,
      id: controlId,
      invalid: Boolean(error),
      required: Boolean(required),
    }),
    [controlId, describedBy, error, generatedErrorId, required]
  );

  return (
    <FormFieldContext.Provider value={context}>
      <div
        className={cx(
          orientation === "horizontal"
            ? "grid gap-2 sm:grid-cols-[minmax(10rem,14rem)_minmax(0,1fr)] sm:items-start"
            : "grid gap-1.5",
          className
        )}
        {...props}
      >
        {label ? (
          <label className="text-sm font-medium text-foreground" htmlFor={controlId}>
            {label}
            {required ? <span className="ml-1 text-negative" aria-hidden="true">*</span> : null}
          </label>
        ) : null}
        <div className="grid min-w-0 gap-1.5">
          {children}
          {description ? (
            <p className="text-xs leading-5 text-muted" id={generatedDescriptionId}>
              {description}
            </p>
          ) : null}
          {error ? (
            <p className="text-xs leading-5 text-negative" id={generatedErrorId} role="alert">
              {error}
            </p>
          ) : null}
        </div>
      </div>
    </FormFieldContext.Provider>
  );
}
