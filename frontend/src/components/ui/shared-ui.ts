/**
 * Adapter barrel for the vendored shared-ui library (src/ui).
 *
 * Single import surface for shared design-system primitives that Taskflows does
 * NOT already implement locally. Components that already exist in this directory
 * (Button, Card, Input, Select, Checkbox, Badge, ConfirmDialog, Toast, ThemeToggle,
 * LoadingSpinner) are intentionally NOT re-exported so the local implementations
 * remain the source of truth until a deliberate migration. New feature code should
 * import net-new primitives (Modal, Alert, Tooltip, Table, providers, ...) from here.
 *
 * Note: Taskflows' local Button already exposes `loading`/`fullWidth`; the shared-ui
 * Button now matches that API (plus icon slots and extra variants), so a future
 * migration is a drop-in once the `.btn-*` CSS classes are retired.
 *
 * Theming: these components consume Taskflows' own Tailwind tokens (see
 * `src/index.css`, which adds the semantic tokens they require and `@source`s the
 * library's dist). Do NOT import the library styles.css.
 */

// Overlays / feedback
export { Modal } from "../../ui";
export type { ModalProps, ModalSize } from "../../ui";

export { Alert } from "../../ui";
export type { AlertProps, AlertTone } from "../../ui";

export { Tooltip } from "../../ui";
export type { TooltipProps, TooltipSide } from "../../ui";

export { Popover } from "../../ui";
export type { PopoverProps } from "../../ui";

export { DropdownMenu, DropdownMenuItem, DropdownMenuSeparator } from "../../ui";
export type {
  DropdownMenuItemProps,
  DropdownMenuProps,
  DropdownMenuSeparatorProps,
} from "../../ui";

export { ContextMenu } from "../../ui";

// Data display
export { Table } from "../../ui";
export type {
  TableColumn,
  TableColumnAlign,
  TableDensity,
  TableProps,
  TableSortDirection,
} from "../../ui";

export { Tab, TabList, TabPanel, Tabs } from "../../ui";
export type { TabListProps, TabPanelProps, TabProps, TabsProps } from "../../ui";

export { MetricCard, BigNumber } from "../../ui";
export type { BigNumberProps, MetricCardProps, MetricTone } from "../../ui";

export { StatusBadge } from "../../ui";
export type { StatusBadgeProps, StatusTone } from "../../ui";

export { CodeBlock } from "../../ui";
export { LogViewer } from "../../ui";
export { MarkdownContent } from "../../ui";

// Form controls not present locally
export { FormField } from "../../ui";
export type { FormFieldProps } from "../../ui";

export { Switch } from "../../ui";
export type { SwitchProps } from "../../ui";

export { Radio, RadioGroup } from "../../ui";
export type { RadioGroupProps, RadioProps } from "../../ui";

export { Textarea } from "../../ui";
export type { TextareaProps } from "../../ui";

// Loading / layout helpers
export { Skeleton, SkeletonText } from "../../ui";
export type { SkeletonProps, SkeletonTextProps } from "../../ui";

export { Pagination } from "../../ui";
export type { PaginationProps } from "../../ui";

export { EmptyState, ErrorState, LoadingState } from "../../ui";
export type { EmptyStateProps, ErrorStateProps, LoadingStateProps } from "../../ui";

export { PageHeader } from "../../ui";
export type { PageHeaderProps } from "../../ui";

export { Toolbar, ToolbarSpacer } from "../../ui";
export type { ToolbarProps } from "../../ui";

// Providers (the orchestration layer Taskflows otherwise rebuilds per-app)
export { ToastProvider, useToast } from "../../ui";
export type { ToastContextValue, ToastOptions, ToastProviderProps } from "../../ui";

export { ConfirmProvider, useConfirm } from "../../ui";
export type { ConfirmFn, ConfirmOptions, ConfirmProviderProps } from "../../ui";

export { ThemeProvider, useTheme } from "../../ui";
export type {
  ResolvedTheme,
  Theme,
  ThemeContextValue,
  ThemeProviderProps,
} from "../../ui";
