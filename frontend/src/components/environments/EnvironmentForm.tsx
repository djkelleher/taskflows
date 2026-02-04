import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Button, Input, Select, Checkbox, Card, CardHeader, CardContent, CardFooter, useToast } from "@/components/ui";
import { DynamicFieldList, PortMappingField, VolumeMappingField, EnvVarField } from "./DynamicFieldList";
import { useCreateEnvironment, useUpdateEnvironment } from "@/hooks/useEnvironments";
import { logger } from "@/utils/logger";
import { getErrorMessage } from "@/utils/error";
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

// Validation functions
function validatePort(port: string | number): string | null {
  const portNum = typeof port === "string" ? parseInt(port, 10) : port;
  if (isNaN(portNum) || portNum < 1 || portNum > 65535) {
    return "Port must be between 1 and 65535";
  }
  return null;
}

function validateVolumePath(path: string): string | null {
  if (!path) {
    return "Path cannot be empty";
  }
  if (!path.startsWith("/")) {
    return "Path must be absolute (start with /)";
  }
  return null;
}

function validateEnvVarName(name: string): string | null {
  if (!name) {
    return "Name cannot be empty";
  }
  if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(name)) {
    return "Name must start with letter or underscore, followed by letters, numbers, or underscores";
  }
  return null;
}

export function EnvironmentForm({ initialData, isEdit = false }: EnvironmentFormProps) {
  const navigate = useNavigate();
  const { showSuccess, showError } = useToast();
  const createMutation = useCreateEnvironment();
  const updateMutation = useUpdateEnvironment();

  const [name, setName] = useState(initialData?.name || "");
  const [type, setType] = useState<EnvironmentType>(initialData?.type || "venv");

  // Validation error states
  const [portErrors, setPortErrors] = useState<Record<number, { host?: string; container?: string }>>({});
  const [volumeErrors, setVolumeErrors] = useState<Record<number, { host?: string; container?: string }>>({});
  const [envVarErrors, setEnvVarErrors] = useState<Record<number, { name?: string }>>({});

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

  // Handle type change and clear form fields for inactive type
  const handleTypeChange = (newType: EnvironmentType) => {
    setType(newType);

    // Only clear if not in edit mode (to preserve initialData)
    if (!isEdit) {
      if (newType === "venv") {
        // Clear docker fields
        setImage("");
        setNetworkMode("bridge");
        setRestartPolicy("no");
        setShmSize("");
        setPrivileged(false);
        setPorts([]);
        setVolumes([]);
        setEnvVars([]);
      } else if (newType === "docker") {
        // Clear venv fields
        setVenvName("");
      }
    }
  };

  // Validation handlers
  const validateAllFields = (): boolean => {
    if (type !== "docker") return true;

    let hasErrors = false;
    const newPortErrors: Record<number, { host?: string; container?: string }> = {};
    const newVolumeErrors: Record<number, { host?: string; container?: string }> = {};
    const newEnvVarErrors: Record<number, { name?: string }> = {};

    // Validate ports
    ports.forEach((port, index) => {
      const hostError = validatePort(port.host);
      const containerError = validatePort(port.container);
      if (hostError || containerError) {
        newPortErrors[index] = {};
        if (hostError) newPortErrors[index].host = hostError;
        if (containerError) newPortErrors[index].container = containerError;
        hasErrors = true;
      }
    });

    // Validate volumes
    volumes.forEach((volume, index) => {
      const hostError = validateVolumePath(volume.host);
      const containerError = validateVolumePath(volume.container);
      if (hostError || containerError) {
        newVolumeErrors[index] = {};
        if (hostError) newVolumeErrors[index].host = hostError;
        if (containerError) newVolumeErrors[index].container = containerError;
        hasErrors = true;
      }
    });

    // Validate environment variables
    envVars.forEach((envVar, index) => {
      const nameError = validateEnvVarName(envVar.name);
      if (nameError) {
        newEnvVarErrors[index] = { name: nameError };
        hasErrors = true;
      }
    });

    setPortErrors(newPortErrors);
    setVolumeErrors(newVolumeErrors);
    setEnvVarErrors(newEnvVarErrors);

    return !hasErrors;
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    // Validate all fields before submission
    if (!validateAllFields()) {
      showError("Please fix validation errors before submitting");
      return;
    }

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
    } catch (error) {
      logger.error("Failed to save environment:", error);
      showError(
        isEdit
          ? `Failed to update environment: ${getErrorMessage(error)}`
          : `Failed to create environment: ${getErrorMessage(error)}`
      );
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
            onChange={(e) => handleTypeChange(e.target.value as EnvironmentType)}
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
                onRemove={(index) => {
                  setPorts(ports.filter((_, i) => i !== index));
                  // Clear errors for removed item
                  const newErrors = { ...portErrors };
                  delete newErrors[index];
                  setPortErrors(newErrors);
                }}
                onUpdate={(index, item) => {
                  const newPorts = [...ports];
                  newPorts[index] = item;
                  setPorts(newPorts);
                }}
                renderItem={(item, index, onUpdate) => (
                  <PortMappingField
                    host={item.host}
                    container={item.container}
                    onUpdate={onUpdate}
                    errors={portErrors[index]}
                  />
                )}
                addLabel="Add Port"
              />

              <DynamicFieldList
                label="Volume Mappings"
                items={volumes}
                onAdd={() => setVolumes([...volumes, { host: "", container: "" }])}
                onRemove={(index) => {
                  setVolumes(volumes.filter((_, i) => i !== index));
                  // Clear errors for removed item
                  const newErrors = { ...volumeErrors };
                  delete newErrors[index];
                  setVolumeErrors(newErrors);
                }}
                onUpdate={(index, item) => {
                  const newVolumes = [...volumes];
                  newVolumes[index] = item;
                  setVolumes(newVolumes);
                }}
                renderItem={(item, index, onUpdate) => (
                  <VolumeMappingField
                    host={item.host}
                    container={item.container}
                    onUpdate={onUpdate}
                    errors={volumeErrors[index]}
                  />
                )}
                addLabel="Add Volume"
              />

              <DynamicFieldList
                label="Environment Variables"
                items={envVars}
                onAdd={() => setEnvVars([...envVars, { name: "", value: "" }])}
                onRemove={(index) => {
                  setEnvVars(envVars.filter((_, i) => i !== index));
                  // Clear errors for removed item
                  const newErrors = { ...envVarErrors };
                  delete newErrors[index];
                  setEnvVarErrors(newErrors);
                }}
                onUpdate={(index, item) => {
                  const newEnvVars = [...envVars];
                  newEnvVars[index] = item;
                  setEnvVars(newEnvVars);
                }}
                renderItem={(item, index, onUpdate) => (
                  <EnvVarField
                    name={item.name}
                    value={item.value}
                    onUpdate={onUpdate}
                    errors={envVarErrors[index]}
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
