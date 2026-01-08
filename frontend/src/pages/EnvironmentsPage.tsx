import { Link } from "react-router-dom";
import { Header } from "@/components/layout";
import { EnvironmentTable } from "@/components/environments";
import { Button } from "@/components/ui";
import { useEnvironments } from "@/hooks/useEnvironments";
import { Plus } from "lucide-react";

export function EnvironmentsPage() {
  const { data, isLoading } = useEnvironments();
  const environments = data?.environments || [];

  return (
    <>
      <Header
        title="Environments"
        actions={
          <Link to="/environments/create">
            <Button variant="primary">
              <Plus className="w-4 h-4" />
              Create Environment
            </Button>
          </Link>
        }
      />
      <div className="flex-1 p-6 overflow-auto">
        <EnvironmentTable environments={environments} isLoading={isLoading} />
      </div>
    </>
  );
}
