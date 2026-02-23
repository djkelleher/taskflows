import { EnvironmentTable } from "@/components/environments";
import { useEnvironments } from "@/hooks/useEnvironments";

export function EnvironmentsPage() {
  const { data, isLoading } = useEnvironments();
  const environments = data?.environments || [];

  return (
    <div className="flex-1 p-6 overflow-auto">
      <EnvironmentTable environments={environments} isLoading={isLoading} />
    </div>
  );
}
