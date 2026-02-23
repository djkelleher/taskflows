import { useState, useRef, useEffect } from "react";
import { clsx } from "clsx";
import { Filter, ChevronDown } from "lucide-react";

interface LogLevelFilterProps {
  value: string;
  onChange: (level: string) => void;
}

const LEVELS = [
  { label: "All Levels", value: ".*" },
  { label: "Debug", value: "debug" },
  { label: "Info", value: "info" },
  { label: "Warning", value: "warning" },
  { label: "Error", value: "error" },
  { label: "Critical", value: "critical" },
];

export function LogLevelFilter({ value, onChange }: LogLevelFilterProps) {
  const [isOpen, setIsOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

  const currentLabel = LEVELS.find((l) => l.value === value)?.label ?? "All Levels";

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setIsOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  const handleSelect = (level: string) => {
    onChange(level);
    setIsOpen(false);
  };

  return (
    <div className="relative" ref={dropdownRef}>
      <button
        type="button"
        onClick={() => setIsOpen(!isOpen)}
        className={clsx(
          "inline-flex items-center gap-2 px-3 py-2 text-sm rounded-lg border border-border",
          "bg-card text-foreground hover:bg-border/50 transition-colors",
        )}
      >
        <Filter className="w-4 h-4 text-muted" />
        <span>{currentLabel}</span>
        <ChevronDown className="w-3 h-3 text-muted" />
      </button>

      {isOpen && (
        <div className="absolute top-full left-0 mt-1 z-50 min-w-44 bg-card border border-border rounded-lg shadow-lg p-2">
          {LEVELS.map((level) => (
            <button
              key={level.value}
              type="button"
              onClick={() => handleSelect(level.value)}
              className={clsx(
                "w-full text-left px-3 py-1.5 text-sm rounded-md",
                "hover:bg-border/50 transition-colors",
                value === level.value
                  ? "text-accent font-medium"
                  : "text-foreground",
              )}
            >
              {level.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
