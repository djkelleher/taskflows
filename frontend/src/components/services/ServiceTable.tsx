import { useMemo } from "react";
import { useDebounce } from "use-debounce";
import { Input, Checkbox, Card } from "@/components/ui";
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
  const { selectedServices, searchQuery, setSearchQuery, toggleSelection, selectAll, clearSelection } =
    useServiceStore();

  const [debouncedSearch] = useDebounce(searchQuery, 300);

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
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
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
                  <div className="flex items-center justify-center gap-2">
                    <svg
                      className="animate-spin h-5 w-5"
                      xmlns="http://www.w3.org/2000/svg"
                      fill="none"
                      viewBox="0 0 24 24"
                    >
                      <circle
                        className="opacity-25"
                        cx="12"
                        cy="12"
                        r="10"
                        stroke="currentColor"
                        strokeWidth="4"
                      />
                      <path
                        className="opacity-75"
                        fill="currentColor"
                        d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
                      />
                    </svg>
                    Loading services...
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
