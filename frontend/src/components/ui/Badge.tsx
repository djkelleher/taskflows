import { clsx } from "clsx";

type BadgeVariant = "success" | "danger" | "warning" | "info" | "muted";

interface BadgeProps {
  variant?: BadgeVariant;
  children: React.ReactNode;
  className?: string;
}

const variantStyles: Record<BadgeVariant, string> = {
  success: "bg-neon-green text-gray-900",
  danger: "bg-neon-red text-white",
  warning: "bg-yellow-500 text-gray-900",
  info: "bg-electric-blue text-white",
  muted: "bg-gray-300 text-gray-700",
};

export function Badge({ variant = "muted", children, className }: BadgeProps) {
  return (
    <span
      className={clsx(
        "px-2 py-1 rounded-full text-xs font-semibold inline-flex items-center",
        variantStyles[variant],
        className
      )}
    >
      {children}
    </span>
  );
}
