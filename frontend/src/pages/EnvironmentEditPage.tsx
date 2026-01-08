import { useParams } from "react-router-dom";
import { Header } from "@/components/layout";
import { EnvironmentForm } from "@/components/environments";
import { useEnvironment } from "@/hooks/useEnvironments";

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
          <svg
            className="animate-spin h-5 w-5 mr-2"
            xmlns="http://www.w3.org/2000/svg"
            fill="none"
            viewBox="0 0 24 24"
          >
            <circle
              className="opacity-25"
              cx="12"
              cy="12"
              r="10"
              stroke="currentColor"
              strokeWidth="4"
            />
            <path
              className="opacity-75"
              fill="currentColor"
              d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
            />
          </svg>
          Loading environment...
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
