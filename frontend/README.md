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
| `npm test` | Run tests with Vitest |
| `npm run lint` | Run ESLint |

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
