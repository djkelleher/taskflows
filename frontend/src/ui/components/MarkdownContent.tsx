import { type HTMLAttributes } from "react";

import { cx } from "../lib/cx";

export interface MarkdownContentProps extends HTMLAttributes<HTMLDivElement> {}

export function MarkdownContent({ className, ...props }: MarkdownContentProps) {
  return <div className={cx("doc-content", className)} {...props} />;
}
