import { create } from "zustand";
import { devtools } from "zustand/middleware";
import type { ColumnId } from "@/types";
import { DEFAULT_VISIBLE_COLUMNS } from "@/components/services/columns";

const VISIBLE_COLUMNS_KEY = "taskflows_visible_columns";
const TIMEZONE_KEY = "taskflows_timezone";

function loadVisibleColumns(): ColumnId[] {
  try {
    const stored = localStorage.getItem(VISIBLE_COLUMNS_KEY);
    if (stored) {
      return JSON.parse(stored) as ColumnId[];
    }
  } catch {
    // ignore
  }
  return DEFAULT_VISIBLE_COLUMNS;
}

function loadTimezone(): string {
  try {
    const stored = localStorage.getItem(TIMEZONE_KEY);
    if (stored) {
      return stored;
    }
  } catch {
    // ignore
  }
  return Intl.DateTimeFormat().resolvedOptions().timeZone;
}

interface ServiceState {
  selectedServices: Set<string>;
  searchQuery: string;
  visibleColumns: ColumnId[];
  timezone: string;
}

interface ServiceActions {
  toggleSelection: (serviceName: string) => void;
  selectAll: (serviceNames: string[]) => void;
  clearSelection: () => void;
  setSearchQuery: (query: string) => void;
  toggleColumn: (columnId: ColumnId) => void;
  setTimezone: (timezone: string) => void;
}

export const useServiceStore = create<ServiceState & ServiceActions>()(
  devtools(
    (set) => ({
      selectedServices: new Set<string>(),
      searchQuery: "",
      visibleColumns: loadVisibleColumns(),
      timezone: loadTimezone(),

      toggleSelection: (serviceName: string) => {
        set((state) => {
          const newSelected = new Set(state.selectedServices);
          if (newSelected.has(serviceName)) {
            newSelected.delete(serviceName);
          } else {
            newSelected.add(serviceName);
          }
          return { selectedServices: newSelected };
        });
      },

      selectAll: (serviceNames: string[]) => {
        set({ selectedServices: new Set(serviceNames) });
      },

      clearSelection: () => {
        set({ selectedServices: new Set() });
      },

      setSearchQuery: (query: string) => {
        set({ searchQuery: query });
      },

      toggleColumn: (columnId: ColumnId) => {
        set((state) => {
          const newColumns = state.visibleColumns.includes(columnId)
            ? state.visibleColumns.filter((id) => id !== columnId)
            : [...state.visibleColumns, columnId];
          localStorage.setItem(VISIBLE_COLUMNS_KEY, JSON.stringify(newColumns));
          return { visibleColumns: newColumns };
        });
      },

      setTimezone: (timezone: string) => {
        localStorage.setItem(TIMEZONE_KEY, timezone);
        set({ timezone });
      },
    }),
    { name: "ServiceStore", enabled: import.meta.env.DEV }
  )
);
