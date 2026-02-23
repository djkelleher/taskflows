import { useState, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { Header } from "@/components/layout";
import { Button, Card, CardHeader, CardContent, Input, Select, useToast } from "@/components/ui";
import { useCreateService, useServers } from "@/hooks/useServices";
import { logger } from "@/utils/logger";
import { getErrorMessage } from "@/utils/error";
import { Upload } from "lucide-react";

export function CreateServicePage() {
  const navigate = useNavigate();
  const { showSuccess, showError } = useToast();
  const createMutation = useCreateService();
  const { data: servers } = useServers();
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [host, setHost] = useState("");
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [include, setInclude] = useState("");
  const [exclude, setExclude] = useState("");

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0] ?? null;
    setSelectedFile(file);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedFile) {
      showError("Please select a YAML file");
      return;
    }

    try {
      await createMutation.mutateAsync({
        file: selectedFile,
        host: host || undefined,
        include: include || undefined,
        exclude: exclude || undefined,
      });
      showSuccess("Services created successfully");
      navigate("/");
    } catch (error) {
      logger.error("Failed to create services:", error);
      showError(`Failed to create services: ${getErrorMessage(error)}`);
    }
  };

  const serverOptions = [
    { value: "", label: "Local (this server)" },
    ...(Array.isArray(servers)
      ? servers.map((s) => ({
          value: s.address,
          label: `${s.hostname} (${s.address})`,
        }))
      : []),
  ];

  return (
    <>
      <Header
        title="Create Services"
        breadcrumbs={[
          { label: "Dashboard", href: "/" },
          { label: "Create Services" },
        ]}
      />
      <div className="flex-1 p-6 overflow-auto">
        <div className="max-w-2xl">
          <Card>
            <CardHeader>
              <h2 className="text-lg font-semibold text-foreground">Upload Service Definition</h2>
            </CardHeader>
            <CardContent>
              <form onSubmit={handleSubmit} className="space-y-4">
                <div>
                  <label className="block text-sm font-medium text-foreground mb-1">
                    Host
                  </label>
                  <Select
                    value={host}
                    onChange={(e) => setHost(e.target.value)}
                    options={serverOptions}
                  />
                </div>

                <div>
                  <label className="block text-sm font-medium text-foreground mb-1">
                    YAML File
                  </label>
                  <div className="flex items-center gap-3">
                    <Button
                      type="button"
                      variant="secondary"
                      onClick={() => fileInputRef.current?.click()}
                    >
                      <Upload className="w-4 h-4" />
                      Choose File
                    </Button>
                    <span className="text-sm text-muted">
                      {selectedFile ? selectedFile.name : "No file selected"}
                    </span>
                    <input
                      ref={fileInputRef}
                      type="file"
                      accept=".yaml,.yml"
                      onChange={handleFileChange}
                      className="hidden"
                    />
                  </div>
                </div>

                <div>
                  <label className="block text-sm font-medium text-foreground mb-1">
                    Include Pattern (optional)
                  </label>
                  <Input
                    value={include}
                    onChange={(e) => setInclude(e.target.value)}
                    placeholder="e.g. my-service-*"
                  />
                </div>

                <div>
                  <label className="block text-sm font-medium text-foreground mb-1">
                    Exclude Pattern (optional)
                  </label>
                  <Input
                    value={exclude}
                    onChange={(e) => setExclude(e.target.value)}
                    placeholder="e.g. test-*"
                  />
                </div>

                <div className="pt-2">
                  <Button
                    type="submit"
                    variant="primary"
                    loading={createMutation.isPending}
                    disabled={!selectedFile || createMutation.isPending}
                  >
                    Create Services
                  </Button>
                </div>
              </form>
            </CardContent>
          </Card>
        </div>
      </div>
    </>
  );
}
