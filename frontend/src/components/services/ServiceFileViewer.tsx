import { useShowService } from "@/hooks/useServices";
import { CodeBlock, LoadingSpinner, Modal } from "@/components/ui";

interface ServiceFileViewerProps {
  serviceName: string;
  onClose: () => void;
}

export function ServiceFileViewer({ serviceName, onClose }: ServiceFileViewerProps) {
  const { data, isLoading } = useShowService(serviceName);
  const filesByService = data?.files ? Object.entries(data.files) : [];

  return (
    <Modal onClose={onClose} open size="2xl" title={`Service Files: ${serviceName}`}>
      {isLoading ? (
        <div className="flex justify-center py-8">
          <LoadingSpinner label="Loading service files" />
        </div>
      ) : filesByService.length > 0 ? (
        filesByService.map(([svcName, files]) => (
          <section key={svcName} className="mb-6 last:mb-0">
            {files.map((file) => (
              <div key={file.path} className="mb-4 last:mb-0">
                <div className="mb-1 text-sm font-medium text-foreground">
                  {file.name}
                  <span className="ml-2 text-xs font-normal text-muted">{file.path}</span>
                </div>
                <CodeBlock language="yaml" value={file.content} />
              </div>
            ))}
          </section>
        ))
      ) : (
        <p className="text-muted">No files found.</p>
      )}
    </Modal>
  );
}
