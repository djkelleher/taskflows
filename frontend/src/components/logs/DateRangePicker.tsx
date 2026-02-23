import { useState, useRef, useEffect } from "react";
import { clsx } from "clsx";
import { Calendar, ChevronDown, Clock } from "lucide-react";

export interface TimeRange {
  from: string;
  to: string;
  label: string;
}

interface DateRangePickerProps {
  value: TimeRange;
  onChange: (range: TimeRange) => void;
}

const PRESETS: TimeRange[] = [
  { from: "now-15m", to: "now", label: "Last 15 minutes" },
  { from: "now-1h", to: "now", label: "Last 1 hour" },
  { from: "now-6h", to: "now", label: "Last 6 hours" },
  { from: "now-12h", to: "now", label: "Last 12 hours" },
  { from: "now-24h", to: "now", label: "Last 24 hours" },
  { from: "now-7d", to: "now", label: "Last 7 days" },
];

function toLocalDatetime(date: Date): { date: string; time: string } {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, "0");
  const d = String(date.getDate()).padStart(2, "0");
  const h = String(date.getHours()).padStart(2, "0");
  const min = String(date.getMinutes()).padStart(2, "0");
  return { date: `${y}-${m}-${d}`, time: `${h}:${min}` };
}

export function DateRangePicker({ value, onChange }: DateRangePickerProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [showCustom, setShowCustom] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

  const now = new Date();
  const oneHourAgo = new Date(now.getTime() - 60 * 60 * 1000);
  const [startDate, setStartDate] = useState(toLocalDatetime(oneHourAgo).date);
  const [startTime, setStartTime] = useState(toLocalDatetime(oneHourAgo).time);
  const [endDate, setEndDate] = useState(toLocalDatetime(now).date);
  const [endTime, setEndTime] = useState(toLocalDatetime(now).time);

  // Close dropdown on outside click
  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setIsOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  const handlePreset = (preset: TimeRange) => {
    onChange(preset);
    setShowCustom(false);
    setIsOpen(false);
  };

  const handleCustomApply = () => {
    const fromMs = new Date(`${startDate}T${startTime}`).getTime();
    const toMs = new Date(`${endDate}T${endTime}`).getTime();
    if (fromMs >= toMs) return;
    onChange({
      from: String(fromMs),
      to: String(toMs),
      label: `${startDate} ${startTime} — ${endDate} ${endTime}`,
    });
    setIsOpen(false);
    setShowCustom(false);
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
        <Calendar className="w-4 h-4 text-muted" />
        <span className="max-w-48 truncate">{value.label}</span>
        <ChevronDown className="w-3 h-3 text-muted" />
      </button>

      {isOpen && (
        <div className="absolute top-full left-0 mt-1 z-50 min-w-64 bg-card border border-border rounded-lg shadow-lg">
          {/* Preset ranges */}
          <div className="p-2">
            <div className="text-xs font-medium text-muted px-2 py-1 uppercase tracking-wide">
              Quick ranges
            </div>
            {PRESETS.map((preset) => (
              <button
                key={preset.from}
                type="button"
                onClick={() => handlePreset(preset)}
                className={clsx(
                  "w-full text-left px-3 py-1.5 text-sm rounded-md",
                  "hover:bg-border/50 transition-colors",
                  value.label === preset.label
                    ? "text-accent font-medium"
                    : "text-foreground",
                )}
              >
                {preset.label}
              </button>
            ))}
          </div>

          <div className="border-t border-border" />

          {/* Custom range toggle */}
          <div className="p-2">
            <button
              type="button"
              onClick={() => setShowCustom(!showCustom)}
              className="w-full text-left px-3 py-1.5 text-sm rounded-md hover:bg-border/50 transition-colors text-foreground inline-flex items-center gap-2"
            >
              <Clock className="w-3.5 h-3.5 text-muted" />
              Custom range...
            </button>

            {showCustom && (
              <div className="mt-2 px-2 space-y-3">
                <div>
                  <label className="block text-xs text-muted mb-1">From</label>
                  <div className="flex gap-2">
                    <input
                      type="date"
                      value={startDate}
                      onChange={(e) => setStartDate(e.target.value)}
                      className="flex-1 px-2 py-1.5 text-sm bg-background border border-border rounded-md text-foreground"
                    />
                    <input
                      type="time"
                      value={startTime}
                      onChange={(e) => setStartTime(e.target.value)}
                      className="w-28 px-2 py-1.5 text-sm bg-background border border-border rounded-md text-foreground"
                    />
                  </div>
                </div>
                <div>
                  <label className="block text-xs text-muted mb-1">To</label>
                  <div className="flex gap-2">
                    <input
                      type="date"
                      value={endDate}
                      onChange={(e) => setEndDate(e.target.value)}
                      className="flex-1 px-2 py-1.5 text-sm bg-background border border-border rounded-md text-foreground"
                    />
                    <input
                      type="time"
                      value={endTime}
                      onChange={(e) => setEndTime(e.target.value)}
                      className="w-28 px-2 py-1.5 text-sm bg-background border border-border rounded-md text-foreground"
                    />
                  </div>
                </div>
                <div className="flex gap-2 justify-end pb-1">
                  <button
                    type="button"
                    onClick={() => setShowCustom(false)}
                    className="px-3 py-1.5 text-xs rounded-md border border-border text-muted hover:text-foreground transition-colors"
                  >
                    Cancel
                  </button>
                  <button
                    type="button"
                    onClick={handleCustomApply}
                    className="px-3 py-1.5 text-xs rounded-md bg-accent text-background font-medium hover:opacity-90 transition-opacity"
                  >
                    Apply
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
