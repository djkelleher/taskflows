import { type ReactElement, type ReactNode } from "react";

import {
  ContextMenu,
  ContextMenuItem,
  ContextMenuRoot,
  ContextMenuSeparator,
  type ContextMenuItemProps,
  type ContextMenuSeparatorProps,
} from "./ContextMenu";
import { ContextMenuTrigger } from "./ContextMenu";

export interface DropdownMenuProps {
  align?: "start" | "end";
  children: ReactNode;
  defaultOpen?: boolean;
  onOpenChange?: (open: boolean) => void;
  open?: boolean;
  /** Render the trigger element; menu props/ref are merged onto it. */
  trigger: ReactElement;
}

/**
 * Click/keyboard-triggered menu of actions. Built on the accessible menu
 * primitives (roving focus, arrow/Home/End, Escape, outside-close) and exposed
 * as an ergonomic single component. For right-click menus, use ContextMenu*.
 */
export function DropdownMenu({
  align = "start",
  children,
  defaultOpen,
  onOpenChange,
  open,
  trigger,
}: DropdownMenuProps) {
  return (
    <ContextMenuRoot defaultOpen={defaultOpen} onOpenChange={onOpenChange} open={open}>
      <ContextMenuTrigger asChild>{trigger}</ContextMenuTrigger>
      <ContextMenu align={align}>{children}</ContextMenu>
    </ContextMenuRoot>
  );
}

export type DropdownMenuItemProps = ContextMenuItemProps;
export const DropdownMenuItem = ContextMenuItem;

export type DropdownMenuSeparatorProps = ContextMenuSeparatorProps;
export const DropdownMenuSeparator = ContextMenuSeparator;
