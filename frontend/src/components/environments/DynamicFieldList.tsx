import { Button, Input } from "@/components/ui";
import { Plus, Trash2 } from "lucide-react";

interface DynamicFieldListProps<T> {
  label: string;
  items: T[];
  onAdd: () => void;
  onRemove: (index: number) => void;
  onUpdate: (index: number, item: T) => void;
  renderItem: (item: T, index: number, onUpdate: (item: T) => void) => React.ReactNode;
  addLabel?: string;
}

export function DynamicFieldList<T>({
  label,
  items,
  onAdd,
  onRemove,
  onUpdate,
  renderItem,
  addLabel = "Add",
}: DynamicFieldListProps<T>) {
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <label className="text-sm font-medium text-foreground">{label}</label>
        <Button type="button" variant="secondary" size="sm" onClick={onAdd}>
          <Plus className="w-4 h-4" />
          {addLabel}
        </Button>
      </div>
      {items.length === 0 ? (
        <p className="text-sm text-muted">No items added</p>
      ) : (
        <div className="space-y-2">
          {items.map((item, index) => (
            <div key={index} className="flex items-start gap-2">
              <div className="flex-1">
                {renderItem(item, index, (newItem) => onUpdate(index, newItem))}
              </div>
              <Button
                type="button"
                variant="danger"
                size="sm"
                onClick={() => onRemove(index)}
              >
                <Trash2 className="w-4 h-4" />
              </Button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// Helper components for common field types

interface PortMappingFieldProps {
  host: string;
  container: string;
  onUpdate: (mapping: { host: string; container: string }) => void;
}

export function PortMappingField({ host, container, onUpdate }: PortMappingFieldProps) {
  return (
    <div className="flex gap-2">
      <Input
        placeholder="Host port"
        value={host}
        onChange={(e) => onUpdate({ host: e.target.value, container })}
        className="flex-1"
      />
      <span className="flex items-center text-muted">:</span>
      <Input
        placeholder="Container port"
        value={container}
        onChange={(e) => onUpdate({ host, container: e.target.value })}
        className="flex-1"
      />
    </div>
  );
}

interface VolumeMappingFieldProps {
  host: string;
  container: string;
  onUpdate: (mapping: { host: string; container: string }) => void;
}

export function VolumeMappingField({ host, container, onUpdate }: VolumeMappingFieldProps) {
  return (
    <div className="flex gap-2">
      <Input
        placeholder="Host path"
        value={host}
        onChange={(e) => onUpdate({ host: e.target.value, container })}
        className="flex-1"
      />
      <span className="flex items-center text-muted">:</span>
      <Input
        placeholder="Container path"
        value={container}
        onChange={(e) => onUpdate({ host, container: e.target.value })}
        className="flex-1"
      />
    </div>
  );
}

interface EnvVarFieldProps {
  name: string;
  value: string;
  onUpdate: (envVar: { name: string; value: string }) => void;
}

export function EnvVarField({ name, value, onUpdate }: EnvVarFieldProps) {
  return (
    <div className="flex gap-2">
      <Input
        placeholder="Variable name"
        value={name}
        onChange={(e) => onUpdate({ name: e.target.value, value })}
        className="flex-1"
      />
      <span className="flex items-center text-muted">=</span>
      <Input
        placeholder="Value"
        value={value}
        onChange={(e) => onUpdate({ name, value: e.target.value })}
        className="flex-1"
      />
    </div>
  );
}
