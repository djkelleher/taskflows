import { Link } from "react-router-dom";
import { Button, Badge, Card, useToast, useConfirm } from "@/components/ui";
import { useDeleteEnvironment } from "@/hooks/useEnvironments";
import { Pencil, Trash2 } from "lucide-react";
import type { NamedEnvironment } from "@/types";

interface EnvironmentTableProps {
  environments: NamedEnvironment[];
  isLoading: boolean;
}

export function EnvironmentTable({ environments, isLoading }: EnvironmentTableProps) {
  const { showSuccess, showError } = useToast();
  const confirm = useConfirm();
  const deleteMutation = useDeleteEnvironment();

  const handleDelete = async (name: string) => {
    const confirmed = await confirm({
      message: `Are you sure you want to delete environment "${name}"?`,
      confirmText: "Delete",
      cancelText: "Cancel",
      variant: "danger",
    });

    if (!confirmed) return;

    try {
      await deleteMutation.mutateAsync(name);
      showSuccess(`Environment "${name}" deleted`);
    } catch {
      showError(`Failed to delete environment "${name}". It may be in use by services.`);
    }
  };

  return (
    <Card>
      <div className="overflow-x-auto">
        <table className="w-full">
          <thead className="bg-gray-50 border-b border-border">
            <tr>
              <th className="px-4 py-3 text-left text-xs font-semibold text-muted uppercase tracking-wider">
                Name
              </th>
              <th className="px-4 py-3 text-left text-xs font-semibold text-muted uppercase tracking-wider">
                Type
              </th>
              <th className="px-4 py-3 text-left text-xs font-semibold text-muted uppercase tracking-wider">
                Details
              </th>
              <th className="px-4 py-3 text-left text-xs font-semibold text-muted uppercase tracking-wider">
                Actions
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {isLoading ? (
              <tr>
                <td colSpan={4} className="px-4 py-8 text-center text-muted">
                  <div className="flex items-center justify-center gap-2">
                    <svg
                      className="animate-spin h-5 w-5"
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
                    Loading environments...
                  </div>
                </td>
              </tr>
            ) : environments.length === 0 ? (
              <tr>
                <td colSpan={4} className="px-4 py-8 text-center text-muted">
                  No environments found.{" "}
                  <Link to="/environments/create" className="text-electric-blue hover:underline">
                    Create one
                  </Link>
                </td>
              </tr>
            ) : (
              environments.map((env) => (
                <tr key={env.name} className="hover:bg-gray-50">
                  <td className="px-4 py-3 text-sm font-medium text-foreground">
                    {env.name}
                  </td>
                  <td className="px-4 py-3 text-sm">
                    <Badge variant={env.type === "docker" ? "info" : "muted"}>
                      {env.type === "docker" ? "Docker" : "Venv"}
                    </Badge>
                  </td>
                  <td className="px-4 py-3 text-sm text-muted">
                    {env.type === "venv" && env.venv?.name}
                    {env.type === "docker" && env.docker?.image}
                  </td>
                  <td className="px-4 py-3 text-sm">
                    <div className="flex gap-2">
                      <Link to={`/environments/edit/${env.name}`}>
                        <Button variant="secondary" size="sm">
                          <Pencil className="w-4 h-4" />
                          Edit
                        </Button>
                      </Link>
                      <Button
                        variant="danger"
                        size="sm"
                        onClick={() => handleDelete(env.name)}
                        loading={deleteMutation.isPending}
                      >
                        <Trash2 className="w-4 h-4" />
                        Delete
                      </Button>
                    </div>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </Card>
  );
}
