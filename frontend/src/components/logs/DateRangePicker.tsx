import { useState } from "react";
import { Calendar, ChevronDown, Clock } from "lucide-react";

import { Button, Input, Popover } from "@/components/ui";

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

  const now = new Date();
  const oneHourAgo = new Date(now.getTime() - 60 * 60 * 1000);
  const [startDate, setStartDate] = useState(toLocalDatetime(oneHourAgo).date);
  const [startTime, setStartTime] = useState(toLocalDatetime(oneHourAgo).time);
  const [endDate, setEndDate] = useState(toLocalDatetime(now).date);
  const [endTime, setEndTime] = useState(toLocalDatetime(now).time);

  const fromMs = new Date(`${startDate}T${startTime}`).getTime();
  const toMs = new Date(`${endDate}T${endTime}`).getTime();
  const customRangeIsValid = Number.isFinite(fromMs) && Number.isFinite(toMs) && fromMs < toMs;

  const handlePreset = (preset: TimeRange) => {
    onChange(preset);
    setShowCustom(false);
    setIsOpen(false);
  };

  const handleCustomApply = () => {
    if (!customRangeIsValid) return;
    onChange({
      from: String(fromMs),
      to: String(toMs),
      label: `${startDate} ${startTime} — ${endDate} ${endTime}`,
    });
    setIsOpen(false);
    setShowCustom(false);
  };

  return (
    <Popover
      className="min-w-64 p-0"
      onOpenChange={setIsOpen}
      open={isOpen}
      trigger={
        <Button
          leftIcon={<Calendar className="w-4 h-4 text-muted" aria-hidden="true" />}
          rightIcon={<ChevronDown className="w-3 h-3 text-muted" aria-hidden="true" />}
        >
          <span className="max-w-48 truncate">{value.label}</span>
        </Button>
      }
    >
          {/* Preset ranges */}
          <div className="p-2">
            <div className="text-xs font-medium text-muted px-2 py-1 uppercase tracking-wide">
              Quick ranges
            </div>
            {PRESETS.map((preset) => (
              <Button
                key={preset.from}
                onClick={() => handlePreset(preset)}
                className={value.label === preset.label ? "justify-start text-accent" : "justify-start"}
                fullWidth
                size="sm"
                variant="ghost"
              >
                {preset.label}
              </Button>
            ))}
          </div>

          <div className="border-t border-border" />

          {/* Custom range toggle */}
          <div className="p-2">
            <Button
              onClick={() => setShowCustom(!showCustom)}
              className="justify-start"
              fullWidth
              leftIcon={<Clock className="w-3.5 h-3.5 text-muted" aria-hidden="true" />}
              size="sm"
              variant="ghost"
            >
              Custom range...
            </Button>

            {showCustom && (
              <div className="mt-2 px-2 space-y-3">
                <div>
                  <span className="block text-xs text-muted mb-1">From</span>
                  <div className="flex gap-2">
                    <Input
                      aria-label="Start date"
                      type="date"
                      value={startDate}
                      onChange={(e) => setStartDate(e.target.value)}
                      className="flex-1 px-2 py-1.5 text-sm bg-background border border-border rounded-md text-foreground"
                    />
                    <Input
                      aria-label="Start time"
                      type="time"
                      value={startTime}
                      onChange={(e) => setStartTime(e.target.value)}
                      className="w-28 px-2 py-1.5 text-sm bg-background border border-border rounded-md text-foreground"
                    />
                  </div>
                </div>
                <div>
                  <span className="block text-xs text-muted mb-1">To</span>
                  <div className="flex gap-2">
                    <Input
                      aria-label="End date"
                      type="date"
                      value={endDate}
                      onChange={(e) => setEndDate(e.target.value)}
                      className="flex-1 px-2 py-1.5 text-sm bg-background border border-border rounded-md text-foreground"
                    />
                    <Input
                      aria-label="End time"
                      type="time"
                      value={endTime}
                      onChange={(e) => setEndTime(e.target.value)}
                      className="w-28 px-2 py-1.5 text-sm bg-background border border-border rounded-md text-foreground"
                    />
                  </div>
                </div>
                {!customRangeIsValid ? (
                  <p className="text-xs text-negative" role="alert">
                    The end of the range must be after the start.
                  </p>
                ) : null}
                <div className="flex gap-2 justify-end pb-1">
                  <Button
                    onClick={() => setShowCustom(false)}
                    size="sm"
                    variant="outline"
                  >
                    Cancel
                  </Button>
                  <Button
                    disabled={!customRangeIsValid}
                    onClick={handleCustomApply}
                    size="sm"
                    variant="primary"
                  >
                    Apply
                  </Button>
                </div>
              </div>
            )}
          </div>
    </Popover>
  );
}
