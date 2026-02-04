export type ServiceStatus = "running" | "active" | "stopped" | "inactive" | "failed";

export interface Service {
  name: string;
  status: ServiceStatus;
  schedule: string | null;
  last_run: string | null;
}

export interface ServicesResponse {
  services: Service[];
}

export type BatchOperation = "start" | "stop" | "restart";

export interface BatchRequest {
  service_names: string[];
  operation: BatchOperation;
}
