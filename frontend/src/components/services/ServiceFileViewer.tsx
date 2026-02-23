import { useEffect, useCallback, useRef } from "react";
import { useShowService } from "@/hooks/useServices";
import { LoadingSpinner } from "@/components/ui";
import { X } from "lucide-react";

interface ServiceFileViewerProps {
  serviceName: string;
  onClose: () => void;
}

export function ServiceFileViewer({ serviceName, onClose }: ServiceFileViewerProps) {
  const { data, isLoading } = useShowService(serviceName);
  const dialogRef = useRef<HTMLDivElement>(null);

  const handleKeyDown = useCallback(
    (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    },
    [onClose]
  );

  useEffect(() => {
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [handleKeyDown]);

  useEffect(() => {
    dialogRef.current?.focus();
  }, []);

  return (
    <div
      className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center"
      onClick={onClose}
    >
      <div
        ref={dialogRef}
        className="bg-card rounded-lg shadow-xl max-w-4xl w-full mx-4 max-h-[80vh] flex flex-col"
        onClick={(e) => e.stopPropagation()}
        tabIndex={-1}
      >
        <div className="flex items-center justify-between p-4 border-b border-border">
          <h2 className="text-lg font-semibold text-foreground">
            Service Files: {serviceName}
          </h2>
          <button
            onClick={onClose}
            className="text-muted hover:text-foreground p-1 rounded"
          >
            <X className="w-5 h-5" />
          </button>
        </div>
        <div className="p-4 overflow-auto flex-1">
          {isLoading ? (
            <div className="flex justify-center py-8">
              <LoadingSpinner />
            </div>
          ) : data?.files ? (
            Object.entries(data.files).map(([svcName, files]) => (
              <div key={svcName} className="mb-6">
                {files.map((file) => (
                  <div key={file.path} className="mb-4">
                    <div className="text-sm font-medium text-foreground mb-1">
                      {file.name}
                      <span className="text-muted ml-2 font-normal text-xs">{file.path}</span>
                    </div>
                    <pre className="bg-background rounded p-3 text-sm text-foreground overflow-x-auto font-mono border border-border">
                      {file.content}
                    </pre>
                  </div>
                ))}
              </div>
            ))
          ) : (
            <p className="text-muted">No files found.</p>
          )}
        </div>
      </div>
    </div>
  );
}
