import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Button, Input, Select, Checkbox, Card, CardHeader, CardContent, CardFooter, useToast } from "@/components/ui";
import { DynamicFieldList, PortMappingField, VolumeMappingField, EnvVarField } from "./DynamicFieldList";
import { useCreateEnvironment, useUpdateEnvironment } from "@/hooks/useEnvironments";
import type { NamedEnvironment, EnvironmentType, NetworkMode, RestartPolicy, PortMapping, VolumeMapping } from "@/types";

interface EnvironmentFormProps {
  initialData?: NamedEnvironment;
  isEdit?: boolean;
}

const NETWORK_MODE_OPTIONS = [
  { value: "bridge", label: "Bridge" },
  { value: "host", label: "Host" },
  { value: "none", label: "None" },
  { value: "overlay", label: "Overlay" },
  { value: "ipvlan", label: "IPvlan" },
  { value: "macvlan", label: "Macvlan" },
];

const RESTART_POLICY_OPTIONS = [
  { value: "no", label: "No" },
  { value: "always", label: "Always" },
  { value: "unless-stopped", label: "Unless Stopped" },
  { value: "on-failure", label: "On Failure" },
];

const TYPE_OPTIONS = [
  { value: "venv", label: "Virtual Environment" },
  { value: "docker", label: "Docker" },
];

interface EnvVar {
  name: string;
  value: string;
}

export function EnvironmentForm({ initialData, isEdit = false }: EnvironmentFormProps) {
  const navigate = useNavigate();
  const { showSuccess, showError } = useToast();
  const createMutation = useCreateEnvironment();
  const updateMutation = useUpdateEnvironment();

  const [name, setName] = useState(initialData?.name || "");
  const [type, setType] = useState<EnvironmentType>(initialData?.type || "venv");

  // Venv fields
  const [venvName, setVenvName] = useState(initialData?.venv?.name || "");

  // Docker fields
  const [image, setImage] = useState(initialData?.docker?.image || "");
  const [networkMode, setNetworkMode] = useState<NetworkMode>(initialData?.docker?.network_mode || "bridge");
  const [restartPolicy, setRestartPolicy] = useState<RestartPolicy>(initialData?.docker?.restart_policy || "no");
  const [shmSize, setShmSize] = useState(initialData?.docker?.shm_size || "");
  const [privileged, setPrivileged] = useState(initialData?.docker?.privileged || false);
  const [ports, setPorts] = useState<PortMapping[]>(initialData?.docker?.ports || []);
  const [volumes, setVolumes] = useState<VolumeMapping[]>(initialData?.docker?.volumes || []);
  const [envVars, setEnvVars] = useState<EnvVar[]>(
    initialData?.docker?.environment
      ? Object.entries(initialData.docker.environment).map(([name, value]) => ({ name, value }))
      : []
  );

  const isSubmitting = createMutation.isPending || updateMutation.isPending;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    const environment: NamedEnvironment = {
      name,
      type,
      ...(type === "venv" && {
        venv: { name: venvName },
      }),
      ...(type === "docker" && {
        docker: {
          image,
          network_mode: networkMode,
          restart_policy: restartPolicy,
          shm_size: shmSize || null,
          privileged,
          ports,
          volumes,
          environment: Object.fromEntries(envVars.map((ev) => [ev.name, ev.value])),
        },
      }),
    };

    try {
      if (isEdit && initialData) {
        await updateMutation.mutateAsync({ name: initialData.name, environment });
        showSuccess(`Environment "${name}" updated`);
      } else {
        await createMutation.mutateAsync(environment);
        showSuccess(`Environment "${name}" created`);
      }
      navigate("/environments");
    } catch {
      showError(isEdit ? "Failed to update environment" : "Failed to create environment");
    }
  };

  return (
    <form onSubmit={handleSubmit}>
      <Card>
        <CardHeader>
          <h2 className="text-lg font-semibold">
            {isEdit ? "Edit Environment" : "Create Environment"}
          </h2>
        </CardHeader>
        <CardContent className="space-y-4">
          <Input
            label="Name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            required
            disabled={isEdit}
          />

          <Select
            label="Type"
            options={TYPE_OPTIONS}
            value={type}
            onChange={(e) => setType(e.target.value as EnvironmentType)}
            disabled={isEdit}
          />

          {type === "venv" && (
            <Input
              label="Environment Name"
              value={venvName}
              onChange={(e) => setVenvName(e.target.value)}
              placeholder="e.g., myenv"
              required
            />
          )}

          {type === "docker" && (
            <>
              <Input
                label="Image"
                value={image}
                onChange={(e) => setImage(e.target.value)}
                placeholder="e.g., python:3.11"
                required
              />

              <div className="grid grid-cols-2 gap-4">
                <Select
                  label="Network Mode"
                  options={NETWORK_MODE_OPTIONS}
                  value={networkMode}
                  onChange={(e) => setNetworkMode(e.target.value as NetworkMode)}
                />

                <Select
                  label="Restart Policy"
                  options={RESTART_POLICY_OPTIONS}
                  value={restartPolicy}
                  onChange={(e) => setRestartPolicy(e.target.value as RestartPolicy)}
                />
              </div>

              <Input
                label="Shared Memory Size"
                value={shmSize}
                onChange={(e) => setShmSize(e.target.value)}
                placeholder="e.g., 2g"
              />

              <Checkbox
                label="Privileged Mode"
                checked={privileged}
                onChange={(e) => setPrivileged(e.target.checked)}
              />

              <DynamicFieldList
                label="Port Mappings"
                items={ports}
                onAdd={() => setPorts([...ports, { host: "", container: "" }])}
                onRemove={(index) => setPorts(ports.filter((_, i) => i !== index))}
                onUpdate={(index, item) => {
                  const newPorts = [...ports];
                  newPorts[index] = item;
                  setPorts(newPorts);
                }}
                renderItem={(item, _index, onUpdate) => (
                  <PortMappingField
                    host={item.host}
                    container={item.container}
                    onUpdate={onUpdate}
                  />
                )}
                addLabel="Add Port"
              />

              <DynamicFieldList
                label="Volume Mappings"
                items={volumes}
                onAdd={() => setVolumes([...volumes, { host: "", container: "" }])}
                onRemove={(index) => setVolumes(volumes.filter((_, i) => i !== index))}
                onUpdate={(index, item) => {
                  const newVolumes = [...volumes];
                  newVolumes[index] = item;
                  setVolumes(newVolumes);
                }}
                renderItem={(item, _index, onUpdate) => (
                  <VolumeMappingField
                    host={item.host}
                    container={item.container}
                    onUpdate={onUpdate}
                  />
                )}
                addLabel="Add Volume"
              />

              <DynamicFieldList
                label="Environment Variables"
                items={envVars}
                onAdd={() => setEnvVars([...envVars, { name: "", value: "" }])}
                onRemove={(index) => setEnvVars(envVars.filter((_, i) => i !== index))}
                onUpdate={(index, item) => {
                  const newEnvVars = [...envVars];
                  newEnvVars[index] = item;
                  setEnvVars(newEnvVars);
                }}
                renderItem={(item, _index, onUpdate) => (
                  <EnvVarField
                    name={item.name}
                    value={item.value}
                    onUpdate={onUpdate}
                  />
                )}
                addLabel="Add Variable"
              />
            </>
          )}
        </CardContent>
        <CardFooter className="flex justify-end gap-2">
          <Button
            type="button"
            variant="secondary"
            onClick={() => navigate("/environments")}
          >
            Cancel
          </Button>
          <Button type="submit" variant="primary" loading={isSubmitting}>
            {isEdit ? "Update" : "Create"}
          </Button>
        </CardFooter>
      </Card>
    </form>
  );
}
