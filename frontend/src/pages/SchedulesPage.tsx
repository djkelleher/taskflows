import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CalendarClock, Play, RefreshCw, Trash2, Wrench } from "lucide-react";
import {
  cancelScheduleRun,
  createSchedule,
  deleteSchedule,
  ensureScheduler,
  getScheduleRunLogs,
  getScheduleRuns,
  getSchedulerStatus,
  getSchedules,
  previewSchedule,
  runSchedule,
  setScheduleEnabled,
  updateSchedule,
} from "@/api";
import type {
  CreateScheduleRequest,
  PortableSchedule,
  ScheduleRun,
  UpdateScheduleRequest,
} from "@/types";

type ScheduleKind = "interval" | "cron" | "date";

function formatDate(value: string | null): string {
  return value ? new Date(value).toLocaleString() : "—";
}

function stateClass(state: string): string {
  if (["running", "succeeded"].includes(state)) return "text-emerald-400";
  if (["failed", "timed_out", "unresponsive"].includes(state))
    return "text-red-400";
  if (["degraded", "unmanaged", "missed", "skipped"].includes(state))
    return "text-amber-400";
  return "text-muted";
}

export function SchedulesPage() {
  const queryClient = useQueryClient();
  const [kind, setKind] = useState<ScheduleKind>("interval");
  const [name, setName] = useState("");
  const [command, setCommand] = useState("");
  const [scheduleValue, setScheduleValue] = useState("300");
  const [timezone, setTimezone] = useState(
    Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC",
  );
  const [timeout, setTimeout] = useState("3600");
  const [editing, setEditing] = useState<PortableSchedule | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [preview, setPreview] = useState<string[]>([]);
  const [logs, setLogs] = useState<{
    run: ScheduleRun;
    stdout?: string;
    stderr?: string;
  } | null>(null);

  const schedulesQuery = useQuery({
    queryKey: ["schedules"],
    queryFn: getSchedules,
    refetchInterval: 5000,
  });
  const runsQuery = useQuery({
    queryKey: ["schedule-runs"],
    queryFn: getScheduleRuns,
    refetchInterval: 3000,
  });
  const statusQuery = useQuery({
    queryKey: ["scheduler-status"],
    queryFn: getSchedulerStatus,
    refetchInterval: 5000,
  });

  const refresh = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["schedules"] }),
      queryClient.invalidateQueries({ queryKey: ["schedule-runs"] }),
      queryClient.invalidateQueries({ queryKey: ["scheduler-status"] }),
    ]);
  };

  const mutation = useMutation({
    mutationFn: createSchedule,
    onSuccess: async () => {
      setName("");
      setCommand("");
      setMessage("Schedule created");
      await refresh();
    },
    onError: (error: Error) => setMessage(error.message),
  });

  const updateMutation = useMutation({
    mutationFn: ({
      id,
      request,
    }: {
      id: string;
      request: UpdateScheduleRequest;
    }) => updateSchedule(id, request),
    onSuccess: async () => {
      setEditing(null);
      setName("");
      setCommand("");
      setMessage("Schedule updated");
      await refresh();
    },
    onError: (error: Error) => setMessage(error.message),
  });

  const recentRunsByTask = useMemo(() => {
    const result = new Map<string, ScheduleRun>();
    for (const run of runsQuery.data?.runs || []) {
      if (run.task_id && !result.has(run.task_id)) result.set(run.task_id, run);
    }
    return result;
  }, [runsQuery.data]);

  const submit = () => {
    const args =
      editing && command === editing.command.join("\n")
        ? editing.command
        : command
            .split("\n")
            .map((part) => part.trim())
            .filter(Boolean);
    if (!name.trim() || args.length === 0) {
      setMessage("Enter a name and one command argument per line");
      return;
    }
    const timeoutSeconds = Number(timeout);
    if (
      timeout.trim() &&
      (!Number.isFinite(timeoutSeconds) || timeoutSeconds <= 0)
    ) {
      setMessage("Timeout must be a positive number or blank for no timeout");
      return;
    }
    const request: CreateScheduleRequest = {
      name: name.trim(),
      command: args,
      timezone,
      ...(timeout.trim() ? { timeout: timeoutSeconds } : { no_timeout: true }),
    };
    if (kind === "interval") {
      const seconds = Number(scheduleValue);
      if (!Number.isFinite(seconds) || seconds < 1) {
        setMessage("Interval must be at least one second");
        return;
      }
      request.interval_seconds = seconds;
      if (editing?.schedule.kind === "interval" && editing.schedule.start_at) {
        request.start_at = editing.schedule.start_at;
      }
    }
    if (kind === "cron") request.cron = scheduleValue;
    if (kind === "date") request.run_at = scheduleValue;
    if (editing) {
      updateMutation.mutate({
        id: editing.id,
        request: { ...request, expected_revision: editing.revision },
      });
    } else {
      mutation.mutate(request);
    }
  };

  const edit = (schedule: PortableSchedule) => {
    setEditing(schedule);
    setName(schedule.name);
    setCommand(schedule.command.join("\n"));
    setKind(schedule.schedule.kind);
    setScheduleValue(String(schedule.schedule.value));
    setTimezone(schedule.schedule.timezone);
    setTimeout(schedule.timeout === null ? "" : String(schedule.timeout));
    setPreview([]);
    setMessage(
      `Editing ${schedule.name}; secret environment values will be preserved`,
    );
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  const act = async (action: () => Promise<unknown>, success: string) => {
    try {
      await action();
      setMessage(success);
      await refresh();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error));
    }
  };

  const showPreview = async (schedule: PortableSchedule) => {
    try {
      const result = await previewSchedule(schedule.id);
      setPreview(result.occurrences.map((item) => item.local));
      setMessage(`Next occurrences for ${schedule.name} (${result.timezone})`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error));
    }
  };

  const showLogs = async (run: ScheduleRun) => {
    try {
      const result = await getScheduleRunLogs(run.id);
      setLogs({ run, ...result });
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error));
    }
  };

  const scheduler = statusQuery.data;
  const schedules = schedulesQuery.data?.schedules || [];
  const runs = runsQuery.data?.runs || [];

  return (
    <div className="flex-1 overflow-auto p-6 space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-2xl font-semibold flex items-center gap-2">
            <CalendarClock /> Schedules
          </h2>
          <p className="text-sm text-muted mt-1">
            Portable short-lived jobs with identical timing on Linux, macOS, and
            Windows.
          </p>
        </div>
        <button
          className="px-3 py-2 rounded border border-border hover:bg-border flex gap-2"
          onClick={() => void refresh()}
        >
          <RefreshCw className="w-4" /> Refresh
        </button>
      </div>

      {message && (
        <div
          className="rounded border border-border bg-card px-4 py-3"
          role="status"
        >
          {message}
        </div>
      )}
      {preview.length > 0 && (
        <div className="rounded border border-border bg-card p-4">
          <strong>Preview</strong>
          <ul className="mt-2 text-sm font-mono space-y-1">
            {preview.map((value) => (
              <li key={value}>{value}</li>
            ))}
          </ul>
        </div>
      )}

      <section className="rounded border border-border bg-card p-5">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <h3 className="font-semibold">Scheduler health</h3>
            <div
              className={`text-lg font-medium ${stateClass(scheduler?.state || "unknown")}`}
            >
              {scheduler?.state || "loading"}
            </div>
            {scheduler && (
              <p className="text-xs text-muted">
                {scheduler.supervisor.backend} · {scheduler.enabled_task_count}{" "}
                enabled · {scheduler.running_run_count} running ·{" "}
                {scheduler.queued_occurrence_count}/{scheduler.queue_capacity}{" "}
                queued
              </p>
            )}
          </div>
          {scheduler?.state !== "running" && (
            <button
              className="px-3 py-2 rounded bg-electric-blue text-black flex gap-2"
              onClick={() =>
                void act(ensureScheduler, "Scheduler registration repaired")
              }
            >
              <Wrench className="w-4" /> Ensure scheduler
            </button>
          )}
        </div>
      </section>

      <section className="rounded border border-border bg-card p-5 space-y-4">
        <div className="flex items-center justify-between gap-3">
          <h3 className="font-semibold">
            {editing ? `Edit ${editing.name}` : "Create schedule"}
          </h3>
          {editing && (
            <button
              className="text-sm text-muted hover:text-foreground"
              onClick={() => {
                setEditing(null);
                setName("");
                setCommand("");
                setMessage(null);
              }}
            >
              Cancel edit
            </button>
          )}
        </div>
        <div className="grid md:grid-cols-2 gap-4">
          <label className="text-sm">
            Name
            <input
              className="mt-1 w-full rounded border border-border bg-background px-3 py-2"
              value={name}
              onChange={(event) => setName(event.target.value)}
            />
          </label>
          <label className="text-sm">
            Time zone
            <input
              className="mt-1 w-full rounded border border-border bg-background px-3 py-2"
              value={timezone}
              onChange={(event) => setTimezone(event.target.value)}
            />
          </label>
          <label className="text-sm md:col-span-2">
            Command arguments (one per line)
            <textarea
              className="mt-1 w-full rounded border border-border bg-background px-3 py-2 font-mono"
              rows={4}
              value={command}
              onChange={(event) => setCommand(event.target.value)}
              placeholder={"python\n/path/to/job.py\n--flag"}
            />
          </label>
          <label className="text-sm">
            Schedule type
            <select
              className="mt-1 w-full rounded border border-border bg-background px-3 py-2"
              value={kind}
              onChange={(event) => setKind(event.target.value as ScheduleKind)}
            >
              <option value="interval">Interval seconds</option>
              <option value="cron">Cron (five fields)</option>
              <option value="date">One-off ISO timestamp</option>
            </select>
          </label>
          <label className="text-sm">
            {kind === "interval"
              ? "Seconds"
              : kind === "cron"
                ? "Cron expression"
                : "Timestamp with offset"}
            <input
              className="mt-1 w-full rounded border border-border bg-background px-3 py-2 font-mono"
              value={scheduleValue}
              onChange={(event) => setScheduleValue(event.target.value)}
            />
          </label>
          <label className="text-sm">
            Timeout seconds (blank for none)
            <input
              type="number"
              min="1"
              className="mt-1 w-full rounded border border-border bg-background px-3 py-2"
              value={timeout}
              onChange={(event) => setTimeout(event.target.value)}
            />
          </label>
        </div>
        <button
          disabled={mutation.isPending || updateMutation.isPending}
          className="px-4 py-2 rounded bg-electric-blue text-black disabled:opacity-50"
          onClick={submit}
        >
          {mutation.isPending || updateMutation.isPending
            ? "Saving…"
            : editing
              ? "Save changes"
              : "Create schedule"}
        </button>
      </section>

      <section className="rounded border border-border bg-card overflow-hidden">
        <h3 className="font-semibold p-5 border-b border-border">
          Definitions
        </h3>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-left text-muted">
              <tr>
                <th className="p-3">Name</th>
                <th className="p-3">Schedule</th>
                <th className="p-3">Next run</th>
                <th className="p-3">Last result</th>
                <th className="p-3">Actions</th>
              </tr>
            </thead>
            <tbody>
              {schedules.map((schedule) => {
                const last = recentRunsByTask.get(schedule.id);
                return (
                  <tr key={schedule.id} className="border-t border-border">
                    <td className="p-3">
                      <div className="font-medium">{schedule.name}</div>
                      <code className="text-xs text-muted">
                        {schedule.command.join(" ")}
                      </code>
                    </td>
                    <td className="p-3">
                      {schedule.schedule.description}
                      <div
                        className={
                          schedule.enabled ? "text-emerald-400" : "text-muted"
                        }
                      >
                        {schedule.enabled ? "enabled" : "disabled"}
                      </div>
                    </td>
                    <td className="p-3">{formatDate(schedule.next_run_at)}</td>
                    <td className={`p-3 ${stateClass(last?.status || "")}`}>
                      {last?.status || "never"}
                    </td>
                    <td className="p-3">
                      <div className="flex flex-wrap gap-2">
                        <button
                          title="Run or retry"
                          onClick={() =>
                            void act(
                              () => runSchedule(schedule.id),
                              `Run accepted for ${schedule.name}`,
                            )
                          }
                        >
                          <Play className="w-4" />
                        </button>
                        <button onClick={() => void showPreview(schedule)}>
                          Preview
                        </button>
                        <button onClick={() => edit(schedule)}>Edit</button>
                        <button
                          onClick={() =>
                            void act(
                              () =>
                                setScheduleEnabled(schedule, !schedule.enabled),
                              schedule.enabled
                                ? "Schedule disabled"
                                : "Schedule enabled",
                            )
                          }
                        >
                          {schedule.enabled ? "Disable" : "Enable"}
                        </button>
                        <button
                          title="Delete"
                          onClick={() => {
                            if (window.confirm(`Delete ${schedule.name}?`))
                              void act(
                                () => deleteSchedule(schedule),
                                "Schedule deleted",
                              );
                          }}
                        >
                          <Trash2 className="w-4 text-red-400" />
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })}
              {schedules.length === 0 && (
                <tr>
                  <td colSpan={5} className="p-6 text-center text-muted">
                    No portable schedules yet.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>

      <section className="rounded border border-border bg-card overflow-hidden">
        <h3 className="font-semibold p-5 border-b border-border">
          Recent runs
        </h3>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-left text-muted">
              <tr>
                <th className="p-3">Task</th>
                <th className="p-3">Status</th>
                <th className="p-3">Started</th>
                <th className="p-3">Exit</th>
                <th className="p-3">Actions</th>
              </tr>
            </thead>
            <tbody>
              {runs.map((run) => (
                <tr key={run.id} className="border-t border-border">
                  <td className="p-3">{run.task_name}</td>
                  <td className={`p-3 ${stateClass(run.status)}`}>
                    {run.status}
                  </td>
                  <td className="p-3">
                    {formatDate(run.started_at || run.scheduled_for)}
                  </td>
                  <td className="p-3">{run.exit_code ?? "—"}</td>
                  <td className="p-3 flex gap-3">
                    <button onClick={() => void showLogs(run)}>Logs</button>
                    {["queued", "starting", "running"].includes(run.status) && (
                      <button
                        className="text-red-400"
                        onClick={() =>
                          void act(
                            () => cancelScheduleRun(run.id),
                            "Cancellation requested",
                          )
                        }
                      >
                        Cancel
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {logs && (
        <section className="rounded border border-border bg-card p-5">
          <div className="flex justify-between">
            <h3 className="font-semibold">Logs: {logs.run.task_name}</h3>
            <button onClick={() => setLogs(null)}>Close</button>
          </div>
          {logs.run.error && (
            <p className="text-red-400 mt-2">{logs.run.error}</p>
          )}
          <h4 className="text-sm mt-4">stdout</h4>
          <pre className="mt-1 p-3 bg-background rounded overflow-auto max-h-72 text-xs">
            {logs.stdout || "(empty)"}
          </pre>
          <h4 className="text-sm mt-4">stderr</h4>
          <pre className="mt-1 p-3 bg-background rounded overflow-auto max-h-72 text-xs">
            {logs.stderr || "(empty)"}
          </pre>
        </section>
      )}
    </div>
  );
}
