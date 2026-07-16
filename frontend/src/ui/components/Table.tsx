import { type KeyboardEvent, type ReactNode } from "react";

import { cx } from "../lib/cx";
import { LoadingSpinner } from "./LoadingSpinner";

export type TableColumnAlign = "left" | "center" | "right";
export type TableDensity = "compact" | "normal" | "spacious";
export type TableSortDirection = "ascending" | "descending";

export interface TableColumn<T> {
  align?: TableColumnAlign;
  className?: string;
  header: ReactNode;
  headerClassName?: string;
  id: string;
  render?: (row: T, rowIndex: number) => ReactNode;
  sortable?: boolean;
  width?: string | number;
}

export interface TableProps<T> {
  caption?: ReactNode;
  className?: string;
  columns: TableColumn<T>[];
  density?: TableDensity;
  emptyLabel?: ReactNode;
  emptyState?: ReactNode;
  getRowClassName?: (row: T, rowIndex: number) => string | undefined;
  loading?: boolean;
  loadingLabel?: string;
  loadingState?: ReactNode;
  onRowClick?: (row: T, rowIndex: number) => void;
  onSort?: (columnId: string, direction: TableSortDirection) => void;
  renderCellFallback?: (row: T, column: TableColumn<T>, rowIndex: number) => ReactNode;
  rowKey: (row: T, rowIndex: number) => string;
  rows: T[];
  sortColumnId?: string;
  sortDirection?: TableSortDirection;
  stickyHeader?: boolean;
}

const alignClass: Record<TableColumnAlign, string> = {
  left: "text-left",
  center: "text-center",
  right: "text-right",
};

const sortButtonAlignClass: Record<TableColumnAlign, string> = {
  left: "justify-start",
  center: "justify-center",
  right: "justify-end",
};

const cellPaddingClass: Record<TableDensity, string> = {
  compact: "px-3 py-2",
  normal: "px-4 py-3",
  spacious: "px-5 py-4",
};

function getNextSortDirection(isSorted: boolean, direction: TableSortDirection): TableSortDirection {
  if (!isSorted) {
    return "ascending";
  }
  return direction === "ascending" ? "descending" : "ascending";
}

function getSortIndicator(isSorted: boolean, direction: TableSortDirection) {
  if (!isSorted) {
    return "↕";
  }
  return direction === "ascending" ? "↑" : "↓";
}

function getSortLabel(header: ReactNode, isSorted: boolean, direction: TableSortDirection) {
  const label = typeof header === "string" ? header : "column";
  if (!isSorted) {
    return `Sort by ${label} ascending`;
  }
  return `Sort by ${label} ${direction === "ascending" ? "descending" : "ascending"}`;
}

export function Table<T>({
  caption,
  className,
  columns,
  density = "normal",
  emptyLabel = "No results",
  emptyState,
  getRowClassName,
  loading = false,
  loadingLabel = "Loading",
  loadingState,
  onRowClick,
  onSort,
  renderCellFallback,
  rowKey,
  rows,
  sortColumnId,
  sortDirection = "ascending",
  stickyHeader = false,
}: TableProps<T>) {
  const colSpan = Math.max(columns.length, 1);
  const interactive = Boolean(onRowClick);

  const handleRowKeyDown = (event: KeyboardEvent<HTMLTableRowElement>, row: T, rowIndex: number) => {
    if (!onRowClick) {
      return;
    }
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      onRowClick(row, rowIndex);
    }
  };

  return (
    <div className={cx("overflow-x-auto rounded-lg border border-border bg-card", className)}>
      <table aria-busy={loading ? true : undefined} className="min-w-full divide-y divide-border text-sm">
        {caption ? <caption className="sr-only">{caption}</caption> : null}
        <thead className={cx("bg-background", stickyHeader && "sticky top-0 z-10")}>
          <tr>
            {columns.map((column) => {
              const isSorted = sortColumnId === column.id;
              const sortable = Boolean(column.sortable && onSort);
              const nextDirection = getNextSortDirection(isSorted, sortDirection);
              return (
                <th
                  key={column.id}
                  aria-sort={isSorted ? sortDirection : sortable ? "none" : undefined}
                  className={cx(
                    cellPaddingClass[density],
                    "text-xs font-semibold uppercase tracking-wide text-muted",
                    alignClass[column.align ?? "left"],
                    column.headerClassName ?? column.className
                  )}
                  scope="col"
                  style={column.width ? { width: column.width } : undefined}
                >
                  {sortable ? (
                    <button
                      aria-label={getSortLabel(column.header, isSorted, sortDirection)}
                      className={cx(
                        "inline-flex min-h-8 w-full items-center gap-1 rounded-sm text-inherit outline-none transition-colors",
                        "hover:text-foreground focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-card",
                        sortButtonAlignClass[column.align ?? "left"]
                      )}
                      onClick={() => onSort?.(column.id, nextDirection)}
                      type="button"
                    >
                      <span>{column.header}</span>
                      <span aria-hidden="true" className="text-[0.6875rem] leading-none">
                        {getSortIndicator(isSorted, sortDirection)}
                      </span>
                    </button>
                  ) : (
                    column.header
                  )}
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody className="divide-y divide-border/60">
          {loading ? (
            <tr>
              <td className="px-4 py-8 text-center" colSpan={colSpan}>
                {loadingState ?? <LoadingSpinner className="justify-center" label={loadingLabel} />}
              </td>
            </tr>
          ) : rows.length === 0 ? (
            <tr>
              <td className="px-4 py-8 text-center text-muted" colSpan={colSpan}>
                {emptyState ?? emptyLabel}
              </td>
            </tr>
          ) : (
            rows.map((row, rowIndex) => (
              <tr
                key={rowKey(row, rowIndex)}
                className={cx(
                  "transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-accent",
                  interactive && "cursor-pointer hover:bg-background",
                  getRowClassName?.(row, rowIndex)
                )}
                onClick={() => onRowClick?.(row, rowIndex)}
                onKeyDown={(event) => handleRowKeyDown(event, row, rowIndex)}
                tabIndex={interactive ? 0 : undefined}
              >
                {columns.map((column) => (
                  <td
                    key={column.id}
                    className={cx(
                      cellPaddingClass[density],
                      "align-top text-foreground",
                      alignClass[column.align ?? "left"],
                      column.className
                    )}
                  >
                    {column.render?.(row, rowIndex) ?? renderCellFallback?.(row, column, rowIndex)}
                  </td>
                ))}
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}
