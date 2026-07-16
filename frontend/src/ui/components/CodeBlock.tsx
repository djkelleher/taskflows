import { Check, Copy } from "lucide-react";
import { type HTMLAttributes, useState } from "react";

import { cx } from "../lib/cx";
import { IconButton } from "./Button";

export interface CodeBlockProps extends HTMLAttributes<HTMLPreElement> {
  copyable?: boolean;
  language?: string;
  value: string;
}

export function CodeBlock({ className, copyable = false, language, value, ...props }: CodeBlockProps) {
  const [copied, setCopied] = useState(false);

  const copy = async () => {
    await navigator.clipboard?.writeText(value);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1200);
  };

  return (
    <div className="relative min-w-0">
      {copyable ? (
        <IconButton
          aria-label={copied ? "Copied" : "Copy code"}
          className="absolute right-2 top-2 z-10 border-slate-700 bg-slate-900/80 text-slate-100 hover:bg-slate-800"
          icon={copied ? <Check className="size-4" aria-hidden="true" /> : <Copy className="size-4" aria-hidden="true" />}
          onClick={copy}
          size="sm"
          variant="ghost"
        />
      ) : null}
      <pre
        className={cx(
          "overflow-auto rounded-lg border border-border bg-slate-950 p-4 text-sm leading-6 text-slate-100",
          copyable && "pr-12",
          className
        )}
        {...props}
      >
        <code className={language ? `language-${language}` : undefined}>{value}</code>
      </pre>
    </div>
  );
}
