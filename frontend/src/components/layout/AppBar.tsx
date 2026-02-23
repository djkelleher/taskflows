import { NavLink, useNavigate } from "react-router-dom";
import { LayoutDashboard, Box, LogOut } from "lucide-react";
import { clsx } from "clsx";
import { logout } from "@/api";
import { ThemeToggle } from "@/components/ui";

interface TabItemProps {
  to: string;
  icon: React.ReactNode;
  label: string;
  end?: boolean;
}

function TabItem({ to, icon, label, end }: TabItemProps) {
  return (
    <NavLink
      to={to}
      end={end}
      className={({ isActive }) =>
        clsx(
          "flex items-center gap-2 px-4 h-full border-b-2 text-sm font-medium transition-colors",
          isActive
            ? "border-electric-blue text-electric-blue"
            : "border-transparent text-muted hover:text-foreground hover:border-muted"
        )
      }
    >
      {icon}
      {label}
    </NavLink>
  );
}

export function AppBar() {
  const navigate = useNavigate();

  const handleLogout = async () => {
    await logout();
    navigate("/login");
  };

  return (
    <header className="bg-card border-b border-border px-6 py-3 flex items-center relative">
      <h1 className="text-xl font-bold text-electric-blue">Taskflows</h1>

      <nav className="absolute left-1/2 -translate-x-1/2 top-0 bottom-[-1px] flex gap-4">
        <TabItem
          to="/"
          end
          icon={<LayoutDashboard className="w-5 h-5" />}
          label="Dashboard"
        />
        <TabItem
          to="/environments"
          icon={<Box className="w-5 h-5" />}
          label="Environments"
        />
      </nav>

      <div className="ml-auto flex items-center gap-2">
        <ThemeToggle />
        <button
          onClick={handleLogout}
          className="flex items-center gap-2 px-3 py-2 rounded-md text-sm font-medium text-electric-blue hover:bg-border transition-colors"
        >
          <LogOut className="w-4 h-4" />
          Logout
        </button>
      </div>
    </header>
  );
}
