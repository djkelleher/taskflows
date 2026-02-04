import { useParams, Link } from "react-router-dom";
import { Header } from "@/components/layout";
import { LogViewer } from "@/components/logs";
import { ArrowLeft } from "lucide-react";

export function LogsPage() {
  const { serviceName } = useParams<{ serviceName: string }>();

  if (!serviceName) {
    return (
      <>
        <Header title="Logs" />
        <div className="flex-1 p-6 flex items-center justify-center text-muted">
          No service specified
        </div>
      </>
    );
  }

  return (
    <>
      <Header
        title={`Logs: ${serviceName}`}
        breadcrumbs={[
          { label: "Dashboard", href: "/" },
          { label: "Logs" },
        ]}
        actions={
          <Link
            to="/"
            className="flex items-center gap-2 text-sm text-muted hover:text-foreground"
          >
            <ArrowLeft className="w-4 h-4" />
            Back to Dashboard
          </Link>
        }
      />
      <div className="flex-1 p-6 overflow-hidden flex flex-col">
        <LogViewer serviceName={serviceName} />
      </div>
    </>
  );
}
