import { useState } from "react";
import { Filter, ChevronDown } from "lucide-react";

import { Button, DropdownMenu, DropdownMenuItem } from "@/components/ui";

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

  const currentLabel = LEVELS.find((l) => l.value === value)?.label ?? "All Levels";

  const handleSelect = (level: string) => {
    onChange(level);
    setIsOpen(false);
  };

  return (
    <DropdownMenu
      onOpenChange={setIsOpen}
      open={isOpen}
      trigger={
        <Button
          leftIcon={<Filter className="w-4 h-4 text-muted" aria-hidden="true" />}
          rightIcon={<ChevronDown className="w-3 h-3 text-muted" aria-hidden="true" />}
        >
          {currentLabel}
        </Button>
      }
    >
      {LEVELS.map((level) => (
        <DropdownMenuItem
          key={level.value}
          className={value === level.value ? "font-medium text-accent" : undefined}
          onSelect={() => handleSelect(level.value)}
        >
          {level.label}
        </DropdownMenuItem>
      ))}
    </DropdownMenu>
  );
}
