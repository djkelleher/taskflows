import { useMemo, useState, useEffect } from "react";
import { Link } from "react-router-dom";
import { useDebounce } from "use-debounce";
import { Input, Checkbox, Card, LoadingSpinner, Button } from "@/components/ui";
import { ServiceRow } from "./ServiceRow";
import { BatchActions } from "./BatchActions";
import { ColumnPicker } from "./ColumnPicker";
import { COLUMN_DEFINITIONS } from "./columns";
import { useServiceStore } from "@/stores/serviceStore";
import { Search, Plus } from "lucide-react";
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
  const visibleColumns = useServiceStore((state) => state.visibleColumns);

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

  const visibleColumnDefs = useMemo(
    () => COLUMN_DEFINITIONS.filter((col) => visibleColumns.includes(col.id)),
    [visibleColumns]
  );

  // +1 for checkbox column
  const totalColSpan = visibleColumnDefs.length + 1;

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
        <div className="flex items-center gap-2">
          <BatchActions />
          <Link to="/services/create">
            <Button variant="primary">
              <Plus className="w-4 h-4" />
              Create Service
            </Button>
          </Link>
          <ColumnPicker />
        </div>
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
              {visibleColumnDefs.map((col) => (
                <th
                  key={col.id}
                  className="px-4 py-3 text-left text-xs font-semibold text-muted uppercase tracking-wider"
                >
                  {col.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {isLoading && filteredServices.length === 0 ? (
              <tr>
                <td colSpan={totalColSpan} className="px-4 py-8 text-center text-muted">
                  <div className="flex items-center justify-center">
                    <LoadingSpinner label="Loading services..." />
                  </div>
                </td>
              </tr>
            ) : filteredServices.length === 0 ? (
              <tr>
                <td colSpan={totalColSpan} className="px-4 py-8 text-center text-muted">
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
                  columns={visibleColumnDefs}
                />
              ))
            )}
          </tbody>
        </table>
      </div>
    </Card>
  );
}
