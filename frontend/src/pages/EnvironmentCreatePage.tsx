import { Header } from "@/components/layout";
import { EnvironmentForm } from "@/components/environments";

export function EnvironmentCreatePage() {
  return (
    <>
      <Header
        title="Create Environment"
        breadcrumbs={[
          { label: "Environments", href: "/environments" },
          { label: "Create" },
        ]}
      />
      <div className="flex-1 p-6 overflow-auto">
        <div className="max-w-2xl">
          <EnvironmentForm />
        </div>
      </div>
    </>
  );
}
