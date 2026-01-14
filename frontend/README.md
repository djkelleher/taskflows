# Taskflows React Frontend

A modern React SPA for managing taskflows services, environments, and logs.

## Quick Start

```bash
# Install dependencies
npm install

# Start development server (proxies API to localhost:7777)
npm run dev

# Build for production
npm run build

# Run tests
npm test
```

## Development

### Prerequisites

- Node.js 18+
- The taskflows API server running on port 7777:
  ```bash
  tf api start
  ```

### Running

```bash
npm run dev
```

This starts the Vite dev server on **http://localhost:3000** with:
- Hot module replacement
- API proxy to `http://localhost:7777`
- Source maps for debugging

### Authentication

1. Set up UI credentials (if not already done):
   ```bash
   tf api setup-ui --username admin
   ```

2. Login at http://localhost:3000/login

## Using the UI

The Taskflows UI provides a comprehensive interface for managing services, viewing logs, and configuring environments.

### 🏠 Dashboard (Service Management)

The main dashboard displays all your taskflows services with real-time status updates (polls every 5 seconds).

**Features:**

- **Service Status**: View running/stopped/failed status with color-coded badges
  - 🟢 **Running/Active** - Service is currently running
  - 🔴 **Stopped/Inactive** - Service is not running
  - 🟠 **Failed** - Service encountered an error

- **Service Actions**: Use the action buttons on each row
  - **Start** - Start a stopped service
  - **Stop** - Stop a running service
  - **Restart** - Restart a service (stop + start)
  - **Logs** - View service logs in real-time

- **Search & Filter**: Use the search bar to filter services by name

- **Batch Operations**: Select multiple services and perform bulk actions
  1. Use checkboxes to select services
  2. Click "Start Selected", "Stop Selected", or "Restart Selected"
  3. Confirm the batch operation in the dialog

- **Service Information**:
  - **Schedule**: Displays cron schedule if service is scheduled
  - **Last Run**: Shows when the service last executed

### 📊 Logs Page

View and analyze service logs with powerful filtering options.

**Accessing Logs:**
- Click the "Logs" button next to any service on the dashboard
- Or navigate to `/logs/:serviceName` directly

**Features:**

- **Real-time Updates**: Logs refresh automatically every 3 seconds when viewing recent logs
- **Line Limit**: Control how many log lines to display (50, 100, 200, 500, or All)
- **Search**: Filter logs by text search (case-sensitive)
- **Log Level Filter**: Show only specific log levels
  - All Levels
  - ERROR
  - WARNING
  - INFO
  - DEBUG
- **Auto-scroll**: Automatically scrolls to latest logs (disables when you manually scroll up)
- **Download**: Download complete logs as a `.txt` file
- **Syntax Highlighting**: Log levels are color-coded for easy scanning

**Tips:**
- Increase line limit if you need to see more history
- Use search to find specific error messages or patterns
- Disable auto-scroll to review historical logs without interruption

### ⚙️ Environments Page

Manage Python virtual environments and Docker containers for your services.

**Viewing Environments:**
- Navigate to `/environments` from the sidebar
- See all configured environments with their type (venv/docker)

**Creating a New Environment:**

1. Click "Create Environment" button
2. Choose environment type:

   **Virtual Environment (venv):**
   - **Name**: Unique identifier for the environment
   - **Venv Name**: Name of the Python virtual environment

   **Docker Container:**
   - **Name**: Unique identifier for the environment
   - **Image**: Docker image (e.g., `python:3.11`, `ubuntu:22.04`)
   - **Network Mode**: bridge, host, none, overlay, ipvlan, or macvlan
   - **Restart Policy**: no, always, unless-stopped, or on-failure
   - **Privileged**: Run container in privileged mode
   - **Shared Memory Size**: Optional (e.g., `512m`, `1g`)
   - **Port Mappings**: Map host ports to container ports
     - Example: Host `8080` → Container `80`
   - **Volume Mappings**: Mount host directories into container
     - Example: Host `/data` → Container `/app/data`
   - **Environment Variables**: Set env vars for the container
     - Example: `DATABASE_URL=postgresql://...`

3. Click "Create" to save

**Editing an Environment:**
- Click "Edit" button next to any environment
- Modify configuration as needed
- Click "Save Changes"

**Deleting an Environment:**
- Click "Delete" button next to any environment
- Confirm the deletion in the dialog
- ⚠️ **Warning**: Cannot delete environments currently in use by services

**Dynamic Fields:**
- Use "+ Add Port", "+ Add Volume", "+ Add Variable" to add multiple mappings
- Click "Remove" to delete individual entries
- Fields are automatically validated

### 🎨 Theme & Colors

The UI uses a custom color palette:

- **Electric Blue** (#0062FF) - Primary actions, active navigation
- **Neon Green** (#00FF66) - Success states, running services
- **Neon Red** (#FF3300) - Error states, danger actions, stopped services

### 🔔 Notifications

Toast notifications appear in the top-right corner to confirm actions:

- ✅ **Success** (green) - Action completed successfully
- ❌ **Error** (red) - Action failed with error message
- ⚠️ **Warning** (yellow) - Important information
- ℹ️ **Info** (blue) - General information

Notifications auto-dismiss after 5 seconds or can be manually closed.

### 🔒 Session Management

- **Auto-refresh**: Access tokens automatically refresh when expired
- **Logout**: Click your username in the header to logout
- **Session Expiry**: You'll be redirected to login if refresh token expires

### ⌨️ Navigation

**Sidebar Menu:**
- **Dashboard** - Service management (main page)
- **Environments** - Environment configuration
- **Logs** - Quick access to view logs (requires service selection)

**Header:**
- Displays current page title
- Shows logged-in username
- Provides logout option

**Breadcrumbs & Back Navigation:**
- Use browser back button or click "Back to..." links
- Service name is shown in page titles for context

## Project Structure

```
src/
├── api/
│   └── client.ts          # API functions with auth middleware
├── components/
│   ├── ui/                # Reusable UI components
│   │   ├── Button.tsx
│   │   ├── Badge.tsx
│   │   ├── Card.tsx
│   │   ├── Input.tsx
│   │   ├── Select.tsx
│   │   ├── Checkbox.tsx
│   │   ├── Toast.tsx
│   │   └── ConfirmDialog.tsx
│   ├── layout/            # Layout components
│   │   ├── Sidebar.tsx
│   │   ├── Header.tsx
│   │   └── MainLayout.tsx
│   ├── services/          # Service management
│   │   ├── ServiceTable.tsx
│   │   ├── ServiceRow.tsx
│   │   ├── StatusBadge.tsx
│   │   └── BatchActions.tsx
│   ├── logs/              # Log viewer
│   │   └── LogViewer.tsx
│   └── environments/      # Environment CRUD
│       ├── EnvironmentTable.tsx
│       ├── EnvironmentForm.tsx
│       └── DynamicFieldList.tsx
├── hooks/
│   ├── useServices.ts     # Service list with 5s polling
│   ├── useLogs.ts         # Log fetching with 3s polling
│   └── useEnvironments.ts # Environment CRUD
├── stores/
│   ├── authStore.ts       # JWT tokens (localStorage)
│   └── serviceStore.ts    # Selection state, search query
├── types/
│   ├── service.ts
│   ├── environment.ts
│   └── auth.ts
├── pages/
│   ├── LoginPage.tsx
│   ├── DashboardPage.tsx
│   ├── LogsPage.tsx
│   ├── EnvironmentsPage.tsx
│   ├── EnvironmentCreatePage.tsx
│   └── EnvironmentEditPage.tsx
├── test/
│   ├── setup.ts           # Vitest setup
│   └── mocks/
│       ├── handlers.ts    # MSW API handlers
│       └── server.ts      # MSW server
├── App.tsx                # Router with protected routes
├── main.tsx               # Entry point
└── index.css              # Tailwind with theme
```

## Pages

| Route | Page | Description |
|-------|------|-------------|
| `/login` | LoginPage | JWT authentication |
| `/` | DashboardPage | Service table with actions |
| `/logs/:serviceName` | LogsPage | Log viewer for a service |
| `/environments` | EnvironmentsPage | Environment list |
| `/environments/create` | EnvironmentCreatePage | Create new environment |
| `/environments/edit/:name` | EnvironmentEditPage | Edit existing environment |

## API Endpoints

The frontend communicates with the taskflows API:

| Hook | Endpoint | Method |
|------|----------|--------|
| login | `/auth/login` | POST |
| refresh | `/auth/refresh` | POST |
| useServices | `/api/services?as_json=true` | GET |
| serviceAction | `/api/{start\|stop\|restart}?match=NAME` | POST |
| batchAction | `/api/batch` | POST |
| useLogs | `/api/logs?service_name=NAME&n_lines=N` | GET |
| useEnvironments | `/api/environments` | GET/POST |
| getEnvironment | `/api/environments/{name}` | GET |
| updateEnvironment | `/api/environments/{name}` | PUT |
| deleteEnvironment | `/api/environments/{name}` | DELETE |

## Tech Stack

- **React 19** - UI framework
- **TypeScript** - Type safety
- **Vite** - Build tool with HMR
- **React Router v7** - Client-side routing with protected routes
- **Zustand** - Lightweight state management
- **React Query** - Server state with automatic polling
- **TailwindCSS 4** - Utility-first CSS
- **Lucide React** - Icons
- **Vitest + MSW** - Testing with API mocking

## Theme

Custom colors (defined in `src/index.css`):

| Name | Hex | Usage |
|------|-----|-------|
| electric-blue | #0062FF | Primary actions, active nav |
| neon-green | #00FF66 | Success states, running status |
| neon-red | #FF3300 | Error states, danger actions |

## Scripts

| Command | Description |
|---------|-------------|
| `npm run dev` | Start dev server on port 3000 |
| `npm run build` | Build for production to `dist/` |
| `npm run preview` | Preview production build |
| `npm test` | Run tests in watch mode |
| `npm run test:run` | Run tests once |
| `npm run test:coverage` | Run tests with coverage report |
| `npm run lint` | Run ESLint |

## Testing

The frontend has comprehensive test coverage using **Vitest**, **React Testing Library**, and **MSW** (Mock Service Worker) for API mocking.

### Test Coverage

- **91 passing tests** covering core functionality
- **~37% code coverage** with thresholds enforced:
  - Lines: 35%
  - Branches: 28%
  - Functions: 30%
  - Statements: 35%

### Test Structure

```
src/
├── api/__tests__/
│   └── client.test.ts          # API client + auth middleware (16 tests)
├── stores/__tests__/
│   └── authStore.test.ts       # Auth store + token management (13 tests)
├── hooks/__tests__/
│   ├── useServices.test.tsx    # Service hooks (10 tests)
│   └── useEnvironments.test.tsx # Environment hooks (11 tests)
├── pages/__tests__/
│   └── LoginPage.test.tsx      # Login page integration (7 tests)
└── components/
    ├── ui/__tests__/
    │   ├── Badge.test.tsx      # Badge component (7 tests)
    │   ├── Checkbox.test.tsx   # Checkbox component (9 tests)
    │   └── Select.test.tsx     # Select component (11 tests)
    └── services/__tests__/
        └── StatusBadge.test.tsx # Status badge (7 tests)
```

### Running Tests

```bash
# Run tests in watch mode (default)
npm test

# Run tests once (useful for CI)
npm run test:run

# Generate coverage report (HTML + console)
npm run test:coverage
```

### Test Infrastructure

**Vitest Configuration** (`vitest.config.ts`)
- Environment: happy-dom (lightweight JSDOM)
- Global test utilities
- Coverage thresholds enforced
- Path aliases (`@/` → `src/`)

**MSW Mock Handlers** (`src/test/mocks/handlers.ts`)
- Complete API mocking for all endpoints
- Realistic response data
- Error scenario testing
- Token refresh flow mocking

**Test Setup** (`src/test/setup.ts`)
- MSW server lifecycle (beforeAll, afterEach, afterAll)
- Custom matchers from @testing-library/jest-dom
- Global test utilities

### Writing Tests

**Example: Testing a Component**
```typescript
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MyComponent } from "../MyComponent";

describe("MyComponent", () => {
  it("should render with default props", () => {
    render(<MyComponent />);
    expect(screen.getByText("Hello")).toBeInTheDocument();
  });

  it("should handle user interaction", async () => {
    const user = userEvent.setup();
    render(<MyComponent />);

    await user.click(screen.getByRole("button"));

    expect(screen.getByText("Clicked")).toBeInTheDocument();
  });
});
```

**Example: Testing React Query Hooks**
```typescript
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });

  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>
      {children}
    </QueryClientProvider>
  );
}

it("should fetch data", async () => {
  const { result } = renderHook(() => useMyHook(), {
    wrapper: createWrapper()
  });

  await waitFor(() => expect(result.current.isSuccess).toBe(true));
  expect(result.current.data).toBeDefined();
});
```

**Example: Mocking API Responses**
```typescript
import { server } from "@/test/mocks/server";
import { http, HttpResponse } from "msw";

it("should handle API errors", async () => {
  // Override default handler for this test
  server.use(
    http.get("/api/services", () => {
      return HttpResponse.json({ error: "Server error" }, { status: 500 });
    })
  );

  // Test error handling...
});
```

### Code Quality

The project enforces strict code quality standards:

**TypeScript**
- Strict mode enabled
- No unused variables/parameters
- Explicit return types for exported functions

**ESLint**
- React Hooks rules
- React Refresh validation
- No console.log in production

**Testing Best Practices**
- No implementation details tested
- Focus on user behavior
- Avoid brittle selectors (use roles, labels, text)
- Mock external dependencies (API, timers)

## Production Deployment

1. Build the frontend:
   ```bash
   npm run build
   ```

2. Copy to FastAPI static directory:
   ```bash
   cp -r dist/* ../taskflows/ui/static/
   ```

3. Start the API with UI enabled:
   ```bash
   tf api start --enable-ui
   ```

The frontend will be served at **http://localhost:7777**.
