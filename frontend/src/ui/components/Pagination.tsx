import { ChevronLeft, ChevronRight } from "lucide-react";
import { type HTMLAttributes } from "react";

import { cx } from "../lib/cx";

export interface PaginationProps extends Omit<HTMLAttributes<HTMLElement>, "onChange"> {
  /** 1-based current page. */
  page: number;
  onPageChange: (page: number) => void;
  /** Total number of pages (>= 1). */
  pageCount: number;
  /** How many page buttons to show around the current page. Defaults to 1. */
  siblingCount?: number;
}

const ELLIPSIS = "ellipsis";

function buildRange(page: number, pageCount: number, siblingCount: number): (number | typeof ELLIPSIS)[] {
  const totalNumbers = siblingCount * 2 + 5; // first, last, current, 2 ellipses
  if (pageCount <= totalNumbers) {
    return Array.from({ length: pageCount }, (_, index) => index + 1);
  }

  const left = Math.max(page - siblingCount, 1);
  const right = Math.min(page + siblingCount, pageCount);
  const showLeftEllipsis = left > 2;
  const showRightEllipsis = right < pageCount - 1;

  const pages: (number | typeof ELLIPSIS)[] = [1];
  if (showLeftEllipsis) {
    pages.push(ELLIPSIS);
  }
  for (let value = showLeftEllipsis ? left : 2; value <= (showRightEllipsis ? right : pageCount - 1); value += 1) {
    pages.push(value);
  }
  if (showRightEllipsis) {
    pages.push(ELLIPSIS);
  }
  pages.push(pageCount);
  return pages;
}

const itemClass =
  "inline-flex min-h-8 min-w-8 items-center justify-center rounded-md border px-2 text-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent disabled:cursor-not-allowed disabled:opacity-50";

/** Accessible page navigation with first/last anchoring and ellipsis truncation. */
export function Pagination({
  "aria-label": ariaLabel = "Pagination",
  className,
  onPageChange,
  page,
  pageCount,
  siblingCount = 1,
  ...props
}: PaginationProps) {
  const safeCount = Math.max(1, pageCount);
  const current = Math.min(Math.max(1, page), safeCount);
  const items = buildRange(current, safeCount, siblingCount);

  return (
    <nav aria-label={ariaLabel} className={cx("flex items-center gap-1", className)} {...props}>
      <button
        aria-label="Previous page"
        className={cx(itemClass, "border-border bg-card text-foreground hover:border-accent")}
        disabled={current <= 1}
        onClick={() => onPageChange(current - 1)}
        type="button"
      >
        <ChevronLeft className="size-4" aria-hidden="true" />
      </button>
      {items.map((item, index) =>
        item === ELLIPSIS ? (
          <span key={`ellipsis-${index}`} aria-hidden="true" className="px-1 text-muted">
            &hellip;
          </span>
        ) : (
          <button
            key={item}
            aria-current={item === current ? "page" : undefined}
            aria-label={`Page ${item}`}
            className={cx(
              itemClass,
              item === current
                ? "border-accent bg-accent text-white"
                : "border-border bg-card text-foreground hover:border-accent"
            )}
            onClick={() => onPageChange(item)}
            type="button"
          >
            {item}
          </button>
        )
      )}
      <button
        aria-label="Next page"
        className={cx(itemClass, "border-border bg-card text-foreground hover:border-accent")}
        disabled={current >= safeCount}
        onClick={() => onPageChange(current + 1)}
        type="button"
      >
        <ChevronRight className="size-4" aria-hidden="true" />
      </button>
    </nav>
  );
}
