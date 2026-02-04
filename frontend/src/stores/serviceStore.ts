import { create } from "zustand";
import { devtools } from "zustand/middleware";

interface ServiceState {
  selectedServices: Set<string>;
  searchQuery: string;
}

interface ServiceActions {
  toggleSelection: (serviceName: string) => void;
  selectAll: (serviceNames: string[]) => void;
  clearSelection: () => void;
  setSearchQuery: (query: string) => void;
}

export const useServiceStore = create<ServiceState & ServiceActions>()(
  devtools(
    (set) => ({
      selectedServices: new Set<string>(),
      searchQuery: "",

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
    }),
    { name: "ServiceStore", enabled: import.meta.env.DEV }
  )
);
