export type EnvironmentType = "venv" | "docker";

export type NetworkMode = "bridge" | "host" | "none" | "overlay" | "ipvlan" | "macvlan";

export type RestartPolicy = "no" | "always" | "unless-stopped" | "on-failure";

export interface VenvConfig {
  name: string;
}

export interface PortMapping {
  host: string;
  container: string;
}

export interface VolumeMapping {
  host: string;
  container: string;
}

export interface DockerConfig {
  image: string;
  network_mode: NetworkMode;
  restart_policy: RestartPolicy;
  shm_size: string | null;
  privileged: boolean;
  ports: PortMapping[];
  volumes: VolumeMapping[];
  environment: Record<string, string>;
}

export interface NamedEnvironment {
  name: string;
  type: EnvironmentType;
  venv?: VenvConfig;
  docker?: DockerConfig;
}

export interface EnvironmentsResponse {
  environments: NamedEnvironment[];
}
