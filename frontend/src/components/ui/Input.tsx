import { forwardRef } from "react";
import { clsx } from "clsx";

interface InputProps extends React.InputHTMLAttributes<HTMLInputElement> {
  label?: string;
  error?: string;
}

export const Input = forwardRef<HTMLInputElement, InputProps>(
  ({ label, error, className, id, ...props }, ref) => {
    const inputId = id || label?.toLowerCase().replace(/\s+/g, "-");

    return (
      <div className="flex flex-col gap-1">
        {label && (
          <label htmlFor={inputId} className="text-sm font-medium text-foreground">
            {label}
          </label>
        )}
        <input
          ref={ref}
          id={inputId}
          className={clsx(
            "px-3 py-2 rounded-md border border-border bg-card text-foreground",
            "focus:outline-none focus:ring-2 focus:ring-electric-blue focus:border-transparent",
            "placeholder:text-muted",
            error && "border-neon-red focus:ring-neon-red",
            className
          )}
          {...props}
        />
        {error && <p className="text-xs text-neon-red">{error}</p>}
      </div>
    );
  }
);

Input.displayName = "Input";
