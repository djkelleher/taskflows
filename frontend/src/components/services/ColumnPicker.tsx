import { useState, useRef, useEffect } from "react";
import { Settings } from "lucide-react";
import { Checkbox, Select } from "@/components/ui";
import { COLUMN_DEFINITIONS } from "./columns";
import { useServiceStore } from "@/stores/serviceStore";

const TIMEZONES = [
  // UTC
  { value: "UTC", label: "UTC" },

  // Americas
  { value: "America/New_York", label: "New York (EST/EDT)" },
  { value: "America/Chicago", label: "Chicago (CST/CDT)" },
  { value: "America/Denver", label: "Denver (MST/MDT)" },
  { value: "America/Phoenix", label: "Phoenix (MST)" },
  { value: "America/Los_Angeles", label: "Los Angeles (PST/PDT)" },
  { value: "America/Anchorage", label: "Anchorage (AKST/AKDT)" },
  { value: "America/Honolulu", label: "Honolulu (HST)" },
  { value: "America/Toronto", label: "Toronto (EST/EDT)" },
  { value: "America/Vancouver", label: "Vancouver (PST/PDT)" },
  { value: "America/Mexico_City", label: "Mexico City (CST/CDT)" },
  { value: "America/Sao_Paulo", label: "São Paulo (BRT)" },
  { value: "America/Buenos_Aires", label: "Buenos Aires (ART)" },
  { value: "America/Santiago", label: "Santiago (CLT/CLST)" },

  // Europe
  { value: "Europe/London", label: "London (GMT/BST)" },
  { value: "Europe/Dublin", label: "Dublin (GMT/IST)" },
  { value: "Europe/Paris", label: "Paris (CET/CEST)" },
  { value: "Europe/Berlin", label: "Berlin (CET/CEST)" },
  { value: "Europe/Amsterdam", label: "Amsterdam (CET/CEST)" },
  { value: "Europe/Brussels", label: "Brussels (CET/CEST)" },
  { value: "Europe/Madrid", label: "Madrid (CET/CEST)" },
  { value: "Europe/Rome", label: "Rome (CET/CEST)" },
  { value: "Europe/Zurich", label: "Zurich (CET/CEST)" },
  { value: "Europe/Stockholm", label: "Stockholm (CET/CEST)" },
  { value: "Europe/Oslo", label: "Oslo (CET/CEST)" },
  { value: "Europe/Copenhagen", label: "Copenhagen (CET/CEST)" },
  { value: "Europe/Helsinki", label: "Helsinki (EET/EEST)" },
  { value: "Europe/Warsaw", label: "Warsaw (CET/CEST)" },
  { value: "Europe/Prague", label: "Prague (CET/CEST)" },
  { value: "Europe/Vienna", label: "Vienna (CET/CEST)" },
  { value: "Europe/Athens", label: "Athens (EET/EEST)" },
  { value: "Europe/Moscow", label: "Moscow (MSK)" },
  { value: "Europe/Istanbul", label: "Istanbul (TRT)" },

  // Africa & Middle East
  { value: "Africa/Cairo", label: "Cairo (EET)" },
  { value: "Africa/Johannesburg", label: "Johannesburg (SAST)" },
  { value: "Africa/Lagos", label: "Lagos (WAT)" },
  { value: "Asia/Dubai", label: "Dubai (GST)" },
  { value: "Asia/Riyadh", label: "Riyadh (AST)" },
  { value: "Asia/Jerusalem", label: "Jerusalem (IST/IDT)" },

  // Asia
  { value: "Asia/Kolkata", label: "India (IST)" },
  { value: "Asia/Karachi", label: "Karachi (PKT)" },
  { value: "Asia/Dhaka", label: "Dhaka (BST)" },
  { value: "Asia/Bangkok", label: "Bangkok (ICT)" },
  { value: "Asia/Jakarta", label: "Jakarta (WIB)" },
  { value: "Asia/Singapore", label: "Singapore (SGT)" },
  { value: "Asia/Kuala_Lumpur", label: "Kuala Lumpur (MYT)" },
  { value: "Asia/Hong_Kong", label: "Hong Kong (HKT)" },
  { value: "Asia/Shanghai", label: "Shanghai (CST)" },
  { value: "Asia/Taipei", label: "Taipei (CST)" },
  { value: "Asia/Seoul", label: "Seoul (KST)" },
  { value: "Asia/Tokyo", label: "Tokyo (JST)" },

  // Oceania
  { value: "Australia/Perth", label: "Perth (AWST)" },
  { value: "Australia/Adelaide", label: "Adelaide (ACST/ACDT)" },
  { value: "Australia/Brisbane", label: "Brisbane (AEST)" },
  { value: "Australia/Sydney", label: "Sydney (AEST/AEDT)" },
  { value: "Australia/Melbourne", label: "Melbourne (AEST/AEDT)" },
  { value: "Pacific/Auckland", label: "Auckland (NZST/NZDT)" },
  { value: "Pacific/Fiji", label: "Fiji (FJT)" },
];

export function ColumnPicker() {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const visibleColumns = useServiceStore((state) => state.visibleColumns);
  const toggleColumn = useServiceStore((state) => state.toggleColumn);
  const timezone = useServiceStore((state) => state.timezone);
  const setTimezone = useServiceStore((state) => state.setTimezone);

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    if (open) {
      document.addEventListener("mousedown", handleClickOutside);
      return () => document.removeEventListener("mousedown", handleClickOutside);
    }
  }, [open]);

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen((prev) => !prev)}
        className="p-2 rounded-md hover:bg-muted/50 text-muted hover:text-foreground transition-colors"
        title="Configure columns"
      >
        <Settings className="w-4 h-4" />
      </button>
      {open && (
        <div className="absolute right-0 top-full mt-1 z-50 bg-card border border-border rounded-md shadow-lg py-1 min-w-56 max-h-96 overflow-y-auto">
          <div className="px-3 py-1.5 text-xs font-semibold text-muted uppercase tracking-wider border-b border-border">
            Timezone
          </div>
          <div className="px-3 py-2 border-b border-border">
            <Select
              value={timezone}
              onChange={(e) => setTimezone(e.target.value)}
              options={TIMEZONES}
              className="w-full text-sm"
            />
          </div>
          <div className="px-3 py-1.5 text-xs font-semibold text-muted uppercase tracking-wider border-b border-border">
            Columns
          </div>
          {COLUMN_DEFINITIONS.map((col) => (
            <label
              key={col.id}
              className="flex items-center gap-2 px-3 py-1.5 hover:bg-muted/30 cursor-pointer text-sm"
            >
              <Checkbox
                checked={visibleColumns.includes(col.id)}
                onChange={() => toggleColumn(col.id)}
              />
              {col.label}
            </label>
          ))}
        </div>
      )}
    </div>
  );
}
