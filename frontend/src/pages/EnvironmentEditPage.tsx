import { useParams } from "react-router-dom";
import { Header } from "@/components/layout";
import { EnvironmentForm } from "@/components/environments";
import { useEnvironment } from "@/hooks/useEnvironments";
import { LoadingSpinner } from "@/components/ui";

export function EnvironmentEditPage() {
  const { name } = useParams<{ name: string }>();
  const { data: environment, isLoading } = useEnvironment(name || "");

  if (!name) {
    return (
      <>
        <Header title="Edit Environment" />
        <div className="flex-1 p-6 flex items-center justify-center text-muted">
          No environment specified
        </div>
      </>
    );
  }

  if (isLoading) {
    return (
      <>
        <Header
          title="Edit Environment"
          breadcrumbs={[
            { label: "Environments", href: "/environments" },
            { label: "Edit" },
          ]}
        />
        <div className="flex-1 p-6 flex items-center justify-center text-muted">
          <LoadingSpinner label="Loading environment..." />
        </div>
      </>
    );
  }

  if (!environment) {
    return (
      <>
        <Header
          title="Edit Environment"
          breadcrumbs={[
            { label: "Environments", href: "/environments" },
            { label: "Edit" },
          ]}
        />
        <div className="flex-1 p-6 flex items-center justify-center text-muted">
          Environment not found
        </div>
      </>
    );
  }

  return (
    <>
      <Header
        title={`Edit: ${name}`}
        breadcrumbs={[
          { label: "Environments", href: "/environments" },
          { label: "Edit" },
        ]}
      />
      <div className="flex-1 p-6 overflow-auto">
        <div className="max-w-2xl">
          <EnvironmentForm initialData={environment} isEdit />
        </div>
      </div>
    </>
  );
}
