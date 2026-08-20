export type SchedulerState =
  | "running"
  | "degraded"
  | "unmanaged"
  | "starting"
  | "stopped"
  | "failed"
  | "unresponsive"
  | "not-installed"
  | "unknown";

export interface PortableSchedule {
  id: string;
  name: string;
  command: string[];
  schedule: {
    kind: "date" | "interval" | "cron";
    value: string | number;
    timezone: string;
    start_at: string | null;
    description: string;
  };
  enabled: boolean;
  timeout: number | null;
  cwd: string | null;
  environment_names: string[];
  misfire_grace_time: number | null;
  coalesce: boolean;
  max_instances: number;
  revision: number;
  next_run_at: string | null;
}

export interface ScheduleRun {
  id: string;
  task_id: string | null;
  task_name: string;
  task_revision: number | null;
  scheduled_for: string | null;
  status: string;
  started_at: string | null;
  finished_at: string | null;
  exit_code: number | null;
  error: string | null;
  cancellation_requested: boolean;
}

export interface SchedulerStatus {
  state: SchedulerState;
  supervisor: {
    backend: string;
    installed: boolean;
    state: string;
    automatic: boolean | null;
    registration_valid: boolean | null;
    log_hint: string | null;
  };
  runtime: {
    healthy: boolean;
    heartbeat_age_seconds: number | null;
  };
  task_count: number;
  enabled_task_count: number;
  queued_occurrence_count: number;
  running_run_count: number;
  queue_capacity: number;
}

export interface SchedulerDiagnosticCheck {
  name: string;
  level: "ok" | "warning" | "error";
  message: string;
  remedy: string | null;
}

export interface SchedulerDiagnostics {
  status: SchedulerStatus;
  checks: SchedulerDiagnosticCheck[];
}

export interface CreateScheduleRequest {
  name: string;
  command: string[];
  run_at?: string;
  interval_seconds?: number;
  start_at?: string;
  cron?: string;
  timezone: string;
  timeout?: number;
  no_timeout?: boolean;
  enabled?: boolean;
  cwd?: string;
  environment?: Record<string, string>;
  misfire_grace_time?: number | null;
  coalesce?: boolean;
  max_instances?: number;
}

export interface UpdateScheduleRequest {
  expected_revision: number;
  name?: string;
  command?: string[];
  run_at?: string;
  interval_seconds?: number;
  start_at?: string;
  cron?: string;
  timezone?: string;
  timeout?: number;
  no_timeout?: boolean;
  enabled?: boolean;
  cwd?: string;
  environment?: Record<string, string>;
  remove_environment?: string[];
  misfire_grace_time?: number | null;
  coalesce?: boolean;
  max_instances?: number;
}
