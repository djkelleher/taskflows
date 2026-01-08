import { http, HttpResponse } from "msw";

export const handlers = [
  // Auth endpoints
  http.post("/auth/login", async ({ request }) => {
    const body = (await request.json()) as { username: string; password: string };
    if (body.username === "admin" && body.password === "password") {
      return HttpResponse.json({
        access_token: "mock-access-token",
        refresh_token: "mock-refresh-token",
        expires_in: 3600,
      });
    }
    return new HttpResponse("Invalid credentials", { status: 401 });
  }),

  http.post("/auth/refresh", async ({ request }) => {
    const body = (await request.json()) as { refresh_token: string };
    if (body.refresh_token === "mock-refresh-token") {
      return HttpResponse.json({
        access_token: "new-mock-access-token",
      });
    }
    return new HttpResponse("Invalid refresh token", { status: 401 });
  }),

  http.post("/auth/logout", () => {
    return new HttpResponse(null, { status: 200 });
  }),

  // Services endpoints
  http.get("/api/services", () => {
    return HttpResponse.json({
      services: [
        { name: "service-1", status: "running", schedule: "* * * * *", last_run: "2024-01-01 12:00:00" },
        { name: "service-2", status: "stopped", schedule: null, last_run: null },
        { name: "service-3", status: "failed", schedule: "0 * * * *", last_run: "2024-01-01 11:00:00" },
      ],
    });
  }),

  http.post("/api/start", ({ request }) => {
    const url = new URL(request.url);
    const match = url.searchParams.get("match");
    return HttpResponse.json({ message: `Started ${match}` });
  }),

  http.post("/api/stop", ({ request }) => {
    const url = new URL(request.url);
    const match = url.searchParams.get("match");
    return HttpResponse.json({ message: `Stopped ${match}` });
  }),

  http.post("/api/restart", ({ request }) => {
    const url = new URL(request.url);
    const match = url.searchParams.get("match");
    return HttpResponse.json({ message: `Restarted ${match}` });
  }),

  http.post("/api/batch", async ({ request }) => {
    const body = (await request.json()) as { service_names: string[]; operation: string };
    return HttpResponse.json({
      message: `Batch ${body.operation} for ${body.service_names.length} services`,
    });
  }),

  // Logs endpoints
  http.get("/api/logs", ({ request }) => {
    const url = new URL(request.url);
    const serviceName = url.searchParams.get("service_name");
    const nLines = url.searchParams.get("n_lines") || "1000";
    return HttpResponse.json({
      logs: `[INFO] Service ${serviceName} started\n[INFO] Processing...\n[INFO] Done`,
      service_name: serviceName,
      n_lines: parseInt(nLines),
    });
  }),

  // Environment endpoints
  http.get("/api/environments", () => {
    return HttpResponse.json({
      environments: [
        { name: "dev-env", type: "venv", venv: { name: "dev" } },
        {
          name: "prod-docker",
          type: "docker",
          docker: {
            image: "python:3.11",
            network_mode: "bridge",
            restart_policy: "always",
            shm_size: null,
            privileged: false,
            ports: [],
            volumes: [],
            environment: {},
          },
        },
      ],
    });
  }),

  http.get("/api/environments/:name", ({ params }) => {
    const { name } = params;
    if (name === "dev-env") {
      return HttpResponse.json({ name: "dev-env", type: "venv", venv: { name: "dev" } });
    }
    return new HttpResponse("Not found", { status: 404 });
  }),

  http.post("/api/environments", async ({ request }) => {
    const body = await request.json();
    return HttpResponse.json(body, { status: 201 });
  }),

  http.put("/api/environments/:name", async ({ request }) => {
    const body = await request.json();
    return HttpResponse.json(body);
  }),

  http.delete("/api/environments/:name", () => {
    return new HttpResponse(null, { status: 200 });
  }),
];
