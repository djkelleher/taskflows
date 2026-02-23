import type { ColumnId, Service } from "@/types";

export type BadgeVariant = "success" | "danger" | "warning" | "muted";

export type ColorMap = Record<string, BadgeVariant>;

export interface ColumnDefinition {
  id: ColumnId;
  label: string;
  accessor: (service: Service) => string;
  defaultVisible: boolean;
  colorMap?: ColorMap;
}

// Mirrors CLI COLUMN_COLORS: green→success, yellow→warning, red→danger, orange1→warning
const ENABLED_COLORS: ColorMap = {
  enabled: "success",
  "enabled-runtime": "warning",
  disabled: "danger",
};

const LOAD_STATE_COLORS: ColorMap = {
  loaded: "success",
  merged: "warning",
  stub: "warning",
  error: "danger",
  "not-found": "danger",
  "bad-setting": "danger",
  masked: "danger",
};

const ACTIVE_STATE_COLORS: ColorMap = {
  active: "success",
  activating: "warning",
  deactivating: "warning",
  inactive: "warning",
  failed: "danger",
  reloading: "warning",
};

const SUB_STATE_COLORS: ColorMap = {
  running: "success",
  exited: "success",
  waiting: "warning",
  "start-pre": "success",
  start: "success",
  "start-post": "success",
  reloading: "warning",
  stop: "warning",
  "stop-sigterm": "warning",
  "stop-sigkill": "warning",
  "stop-post": "warning",
  failed: "danger",
  "auto-restart": "warning",
  dead: "warning",
};

export const COLUMN_DEFINITIONS: ColumnDefinition[] = [
  { id: "name", label: "Name", accessor: (s) => s.name, defaultVisible: true },
  { id: "status", label: "Status", accessor: (s) => s.status, defaultVisible: true },
  { id: "schedule", label: "Schedule", accessor: (s) => s.schedule, defaultVisible: true },
  { id: "last_run", label: "Last Run", accessor: (s) => s.last_run, defaultVisible: true },
  { id: "description", label: "Description", accessor: (s) => s.description, defaultVisible: false },
  { id: "service_enabled", label: "Service Enabled", accessor: (s) => s.service_enabled, defaultVisible: false, colorMap: ENABLED_COLORS },
  { id: "timer_enabled", label: "Timer Enabled", accessor: (s) => s.timer_enabled, defaultVisible: false, colorMap: ENABLED_COLORS },
  { id: "load_state", label: "Load State", accessor: (s) => s.load_state, defaultVisible: false, colorMap: LOAD_STATE_COLORS },
  { id: "active_state", label: "Active State", accessor: (s) => s.active_state, defaultVisible: false, colorMap: ACTIVE_STATE_COLORS },
  { id: "sub_state", label: "Sub State", accessor: (s) => s.sub_state, defaultVisible: false, colorMap: SUB_STATE_COLORS },
  { id: "uptime", label: "Uptime", accessor: (s) => s.uptime, defaultVisible: false },
  { id: "last_finish", label: "Last Finish", accessor: (s) => s.last_finish, defaultVisible: false },
  { id: "next_start", label: "Next Start", accessor: (s) => s.next_start, defaultVisible: false },
];

export const DEFAULT_VISIBLE_COLUMNS: ColumnId[] = COLUMN_DEFINITIONS
  .filter((col) => col.defaultVisible)
  .map((col) => col.id);
