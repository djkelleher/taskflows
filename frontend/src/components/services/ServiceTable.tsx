import { useMemo, useState, useEffect } from "react";
import { useDebounce } from "use-debounce";
import { Input, Checkbox, Card, LoadingSpinner } from "@/components/ui";
import { ServiceRow } from "./ServiceRow";
import { BatchActions } from "./BatchActions";
import { useServiceStore } from "@/stores/serviceStore";
import { Search } from "lucide-react";
import type { Service } from "@/types";

interface ServiceTableProps {
  services: Service[];
  isLoading: boolean;
}

export function ServiceTable({ services, isLoading }: ServiceTableProps) {
  // Use local state for search input to avoid re-rendering on every keystroke
  const [localSearchQuery, setLocalSearchQuery] = useState("");
  const [debouncedSearch] = useDebounce(localSearchQuery, 300);

  // Only subscribe to selection-related state from store
  const selectedServices = useServiceStore((state) => state.selectedServices);
  const toggleSelection = useServiceStore((state) => state.toggleSelection);
  const selectAll = useServiceStore((state) => state.selectAll);
  const clearSelection = useServiceStore((state) => state.clearSelection);

  // Sync debounced search to store for other components (e.g., URL state)
  const setSearchQuery = useServiceStore((state) => state.setSearchQuery);
  useEffect(() => {
    setSearchQuery(debouncedSearch);
  }, [debouncedSearch, setSearchQuery]);

  const filteredServices = useMemo(() => {
    if (!debouncedSearch) return services;
    return services.filter((s) =>
      s.name.toLowerCase().includes(debouncedSearch.toLowerCase())
    );
  }, [services, debouncedSearch]);

  const allSelected = filteredServices.length > 0 && filteredServices.every((s) => selectedServices.has(s.name));
  const someSelected = filteredServices.some((s) => selectedServices.has(s.name)) && !allSelected;

  const handleSelectAll = () => {
    if (allSelected) {
      clearSelection();
    } else {
      selectAll(filteredServices.map((s) => s.name));
    }
  };

  return (
    <Card>
      <div className="px-4 py-3 border-b border-border flex items-center justify-between">
        <div className="relative">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted" />
          <Input
            type="text"
            placeholder="Search services..."
            value={localSearchQuery}
            onChange={(e) => setLocalSearchQuery(e.target.value)}
            className="pl-9 w-64"
          />
        </div>
        <BatchActions />
      </div>

      <div className="overflow-x-auto">
        <table className="w-full">
          <thead className="bg-muted/30 border-b border-border">
            <tr>
              <th className="px-4 py-3 text-left">
                <Checkbox
                  checked={allSelected}
                  indeterminate={someSelected}
                  onChange={handleSelectAll}
                />
              </th>
              <th className="px-4 py-3 text-left text-xs font-semibold text-muted uppercase tracking-wider">
                Name
              </th>
              <th className="px-4 py-3 text-left text-xs font-semibold text-muted uppercase tracking-wider">
                Status
              </th>
              <th className="px-4 py-3 text-left text-xs font-semibold text-muted uppercase tracking-wider">
                Schedule
              </th>
              <th className="px-4 py-3 text-left text-xs font-semibold text-muted uppercase tracking-wider">
                Last Run
              </th>
              <th className="px-4 py-3 text-left text-xs font-semibold text-muted uppercase tracking-wider">
                Actions
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {isLoading && filteredServices.length === 0 ? (
              <tr>
                <td colSpan={6} className="px-4 py-8 text-center text-muted">
                  <div className="flex items-center justify-center">
                    <LoadingSpinner label="Loading services..." />
                  </div>
                </td>
              </tr>
            ) : filteredServices.length === 0 ? (
              <tr>
                <td colSpan={6} className="px-4 py-8 text-center text-muted">
                  No services found
                </td>
              </tr>
            ) : (
              filteredServices.map((service) => (
                <ServiceRow
                  key={service.name}
                  service={service}
                  isSelected={selectedServices.has(service.name)}
                  onToggleSelect={toggleSelection}
                />
              ))
            )}
          </tbody>
        </table>
      </div>
    </Card>
  );
}
