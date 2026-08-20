import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  getScheduleRuns,
  getSchedulerStatus,
  getSchedules,
  updateSchedule,
} from "@/api";
import {
  parseCommandArguments,
  parseEnvironmentOverrides,
} from "@/utils/scheduler";
import { SchedulesPage } from "../SchedulesPage";

vi.mock("@/api", () => ({
  cancelScheduleRun: vi.fn(),
  createSchedule: vi.fn(),
  deleteSchedule: vi.fn(),
  ensureScheduler: vi.fn(),
  getScheduleRunLogs: vi.fn(),
  getScheduleRuns: vi.fn(),
  getSchedulerStatus: vi.fn(),
  getSchedules: vi.fn(),
  previewSchedule: vi.fn(),
  runSchedule: vi.fn(),
  setScheduleEnabled: vi.fn(),
  updateSchedule: vi.fn(),
}));

const schedule = {
  id: "schedule-1",
  name: "cleanup",
  command: ["python", "cleanup.py", ""],
  schedule: {
    kind: "interval" as const,
    value: 300,
    timezone: "UTC",
    start_at: "2026-08-19T10:00:00+00:00",
    description: "every 300s",
  },
  enabled: true,
  timeout: 3600,
  cwd: "/tmp",
  environment_names: ["TOKEN"],
  misfire_grace_time: 3600,
  coalesce: true,
  max_instances: 1,
  revision: 4,
  next_run_at: null,
};

describe("SchedulesPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(getSchedules).mockResolvedValue({ schedules: [schedule] });
    vi.mocked(getScheduleRuns).mockResolvedValue({ runs: [] });
    vi.mocked(getSchedulerStatus).mockResolvedValue({
      state: "running",
      supervisor: {
        backend: "systemd",
        installed: true,
        state: "running",
        automatic: true,
        registration_valid: true,
        log_hint: null,
      },
      runtime: { healthy: true, heartbeat_age_seconds: 0 },
      task_count: 1,
      enabled_task_count: 1,
      queued_occurrence_count: 0,
      running_run_count: 0,
      queue_capacity: 10_000,
    });
    vi.mocked(updateSchedule).mockResolvedValue({
      ...schedule,
      name: "cleanup-new",
    });
    vi.stubGlobal("scrollTo", vi.fn());
  });

  it("preserves whitespace and empty command arguments", () => {
    expect(
      parseCommandArguments("python\r\n padded value \r\n\r\n--flag"),
    ).toEqual(["python", " padded value ", "", "--flag"]);
  });

  it("parses environment overrides case-insensitively and preserves values", () => {
    expect(
      parseEnvironmentOverrides("Path=first\nPATH= second value \nEMPTY="),
    ).toEqual({
      PATH: " second value ",
      EMPTY: "",
    });
    expect(() => parseEnvironmentOverrides("MISSING_VALUE")).toThrow(
      "Environment entry must be KEY=VALUE",
    );
  });

  it("edits a definition without resetting its interval anchor or secrets", async () => {
    const user = userEvent.setup();
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    render(
      <QueryClientProvider client={queryClient}>
        <SchedulesPage />
      </QueryClientProvider>,
    );

    await user.click(await screen.findByRole("button", { name: "Edit" }));
    const name = screen.getByLabelText("Name");
    await user.clear(name);
    await user.type(name, "cleanup-new");
    await user.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() => expect(updateSchedule).toHaveBeenCalledOnce());
    expect(updateSchedule).toHaveBeenCalledWith(
      "schedule-1",
      expect.objectContaining({
        expected_revision: 4,
        name: "cleanup-new",
        command: ["python", "cleanup.py", ""],
        interval_seconds: 300,
        start_at: "2026-08-19T10:00:00+00:00",
      }),
    );
    const request = vi.mocked(updateSchedule).mock.calls[0][1];
    expect(request).not.toHaveProperty("environment");
  });

  it("surfaces query failures instead of rendering empty data silently", async () => {
    vi.mocked(getSchedules).mockRejectedValue(new Error("registry unavailable"));
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    render(
      <QueryClientProvider client={queryClient}>
        <SchedulesPage />
      </QueryClientProvider>,
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Definitions: registry unavailable",
    );
  });

  it("shows an accepted cancellation as pending and prevents duplicate requests", async () => {
    vi.mocked(getScheduleRuns).mockResolvedValue({
      runs: [
        {
          id: "run-1",
          task_id: schedule.id,
          task_name: schedule.name,
          task_revision: schedule.revision,
          scheduled_for: "2026-08-20T10:00:00+00:00",
          started_at: "2026-08-20T10:00:01+00:00",
          finished_at: null,
          status: "running",
          exit_code: null,
          error: null,
          cancellation_requested: true,
        },
      ],
    });
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    render(
      <QueryClientProvider client={queryClient}>
        <SchedulesPage />
      </QueryClientProvider>,
    );

    expect(await screen.findByText("cancelling")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Cancel" })).not.toBeInTheDocument();
  });
});
