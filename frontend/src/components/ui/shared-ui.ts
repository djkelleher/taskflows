/**
 * Adapter barrel for @danklab/shared-ui.
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
 * library's dist). Do NOT import "@danklab/shared-ui/styles.css".
 */

// Overlays / feedback
export { Modal } from "@danklab/shared-ui";
export type { ModalProps, ModalSize } from "@danklab/shared-ui";

export { Alert } from "@danklab/shared-ui";
export type { AlertProps, AlertTone } from "@danklab/shared-ui";

export { Tooltip } from "@danklab/shared-ui";
export type { TooltipProps, TooltipSide } from "@danklab/shared-ui";

export { Popover } from "@danklab/shared-ui";
export type { PopoverProps } from "@danklab/shared-ui";

export { DropdownMenu, DropdownMenuItem, DropdownMenuSeparator } from "@danklab/shared-ui";
export type {
  DropdownMenuItemProps,
  DropdownMenuProps,
  DropdownMenuSeparatorProps,
} from "@danklab/shared-ui";

export { ContextMenu } from "@danklab/shared-ui";

// Data display
export { Table } from "@danklab/shared-ui";
export type {
  TableColumn,
  TableColumnAlign,
  TableDensity,
  TableProps,
  TableSortDirection,
} from "@danklab/shared-ui";

export { Tab, TabList, TabPanel, Tabs } from "@danklab/shared-ui";
export type { TabListProps, TabPanelProps, TabProps, TabsProps } from "@danklab/shared-ui";

export { MetricCard, BigNumber } from "@danklab/shared-ui";
export type { BigNumberProps, MetricCardProps, MetricTone } from "@danklab/shared-ui";

export { StatusBadge } from "@danklab/shared-ui";
export type { StatusBadgeProps, StatusTone } from "@danklab/shared-ui";

export { CodeBlock } from "@danklab/shared-ui";
export { LogViewer } from "@danklab/shared-ui";
export { MarkdownContent } from "@danklab/shared-ui";

// Form controls not present locally
export { FormField } from "@danklab/shared-ui";
export type { FormFieldProps } from "@danklab/shared-ui";

export { Switch } from "@danklab/shared-ui";
export type { SwitchProps } from "@danklab/shared-ui";

export { Radio, RadioGroup } from "@danklab/shared-ui";
export type { RadioGroupProps, RadioProps } from "@danklab/shared-ui";

export { Textarea } from "@danklab/shared-ui";
export type { TextareaProps } from "@danklab/shared-ui";

// Loading / layout helpers
export { Skeleton, SkeletonText } from "@danklab/shared-ui";
export type { SkeletonProps, SkeletonTextProps } from "@danklab/shared-ui";

export { Pagination } from "@danklab/shared-ui";
export type { PaginationProps } from "@danklab/shared-ui";

export { EmptyState, ErrorState, LoadingState } from "@danklab/shared-ui";
export type { EmptyStateProps, ErrorStateProps, LoadingStateProps } from "@danklab/shared-ui";

export { PageHeader } from "@danklab/shared-ui";
export type { PageHeaderProps } from "@danklab/shared-ui";

export { Toolbar, ToolbarSpacer } from "@danklab/shared-ui";
export type { ToolbarProps } from "@danklab/shared-ui";

// Providers (the orchestration layer Taskflows otherwise rebuilds per-app)
export { ToastProvider, useToast } from "@danklab/shared-ui";
export type { ToastContextValue, ToastOptions, ToastProviderProps } from "@danklab/shared-ui";

export { ConfirmProvider, useConfirm } from "@danklab/shared-ui";
export type { ConfirmFn, ConfirmOptions, ConfirmProviderProps } from "@danklab/shared-ui";

export { ThemeProvider, useTheme } from "@danklab/shared-ui";
export type {
  ResolvedTheme,
  Theme,
  ThemeContextValue,
  ThemeProviderProps,
} from "@danklab/shared-ui";
