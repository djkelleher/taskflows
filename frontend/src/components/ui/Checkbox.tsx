import { forwardRef } from "react";
import { clsx } from "clsx";

interface CheckboxProps extends React.InputHTMLAttributes<HTMLInputElement> {
  label?: string;
  indeterminate?: boolean;
}

export const Checkbox = forwardRef<HTMLInputElement, CheckboxProps>(
  ({ label, indeterminate, className, id, ...props }, ref) => {
    const checkboxId = id || label?.toLowerCase().replace(/\s+/g, "-");

    return (
      <div className="flex items-center gap-2">
        <input
          ref={(el) => {
            if (typeof ref === "function") {
              ref(el);
            } else if (ref) {
              ref.current = el;
            }
            if (el) {
              el.indeterminate = indeterminate ?? false;
            }
          }}
          type="checkbox"
          id={checkboxId}
          className={clsx(
            "h-4 w-4 rounded border-border text-electric-blue",
            "focus:ring-2 focus:ring-electric-blue focus:ring-offset-0",
            className
          )}
          {...props}
        />
        {label && (
          <label htmlFor={checkboxId} className="text-sm text-foreground">
            {label}
          </label>
        )}
      </div>
    );
  }
);

Checkbox.displayName = "Checkbox";
