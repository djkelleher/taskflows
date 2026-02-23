export type ServiceStatus = "running" | "active" | "stopped" | "inactive" | "failed";

export interface Service {
  name: string;
  status: ServiceStatus;
  schedule: string;
  last_run: string;
  description: string;
  service_enabled: string;
  timer_enabled: string;
  load_state: string;
  active_state: string;
  sub_state: string;
  uptime: string;
  last_finish: string;
  next_start: string;
}

export type ColumnId =
  | "name"
  | "status"
  | "schedule"
  | "last_run"
  | "description"
  | "service_enabled"
  | "timer_enabled"
  | "load_state"
  | "active_state"
  | "sub_state"
  | "uptime"
  | "last_finish"
  | "next_start";

export interface ServicesResponse {
  services: Service[];
}

export type BatchOperation = "start" | "stop" | "restart" | "enable" | "disable" | "remove";

export interface BatchRequest {
  service_names: string[];
  operation: BatchOperation;
}

export interface ShowFileEntry {
  name: string;
  path: string;
  content: string;
}

export interface ShowResponse {
  files: Record<string, ShowFileEntry[]>;
}

export interface CreateResponse {
  services: string[];
  dashboards: string[];
}

export interface EnableDisableResponse {
  enabled?: string[];
  disabled?: string[];
}

export interface RemoveResponse {
  removed: string[];
}

export interface Server {
  address: string;
  hostname: string;
}
