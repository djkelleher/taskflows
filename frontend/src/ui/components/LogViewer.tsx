import { type HTMLAttributes, type ReactNode, useEffect, useRef } from "react";

import { cx } from "../lib/cx";

export type LogLevel = "debug" | "info" | "warning" | "error";

export interface LogViewerProps<T = string> extends HTMLAttributes<HTMLDivElement> {
  follow?: boolean;
  getLineKey?: (line: T, index: number) => string;
  getLineLevel?: (line: T, index: number) => LogLevel | undefined;
  lines: T[];
  renderLine?: (line: T, index: number) => ReactNode;
}

const levelClass: Record<LogLevel, string> = {
  debug: "text-slate-400",
  info: "text-slate-100",
  warning: "text-amber-300",
  error: "text-red-300",
};

export function LogViewer<T = string>({
  className,
  follow = false,
  getLineKey,
  getLineLevel,
  lines,
  renderLine,
  ...props
}: LogViewerProps<T>) {
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (follow) {
      endRef.current?.scrollIntoView({ block: "end" });
    }
  }, [follow, lines.length]);

  return (
    <div
      className={cx(
        "max-h-96 overflow-auto rounded-lg border border-border bg-slate-950 p-3 font-mono text-xs leading-5 text-slate-100",
        className
      )}
      role="log"
      {...props}
    >
      {lines.map((line, index) => {
        const level = getLineLevel?.(line, index);
        return (
          <div
            key={getLineKey?.(line, index) ?? index}
            className={cx("whitespace-pre-wrap break-words", level && levelClass[level])}
          >
            {renderLine?.(line, index) ?? String(line)}
          </div>
        );
      })}
      <div ref={endRef} />
    </div>
  );
}
