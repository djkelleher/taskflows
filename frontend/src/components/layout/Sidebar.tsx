import { NavLink } from "react-router-dom";
import { LayoutDashboard, Box, LogOut } from "lucide-react";
import { clsx } from "clsx";
import { logout } from "@/api";
import { useNavigate } from "react-router-dom";

interface NavItemProps {
  to: string;
  icon: React.ReactNode;
  label: string;
}

function NavItem({ to, icon, label }: NavItemProps) {
  return (
    <NavLink
      to={to}
      className={({ isActive }) =>
        clsx(
          "flex items-center gap-3 px-4 py-2 rounded-md text-sm font-medium transition-colors",
          isActive
            ? "bg-electric-blue text-white"
            : "text-foreground hover:bg-gray-200"
        )
      }
    >
      {icon}
      {label}
    </NavLink>
  );
}

export function Sidebar() {
  const navigate = useNavigate();

  const handleLogout = async () => {
    await logout();
    navigate("/login");
  };

  return (
    <aside className="w-64 bg-card border-r border-border h-screen flex flex-col">
      <div className="p-4 border-b border-border">
        <h1 className="text-xl font-bold text-electric-blue">Taskflows</h1>
      </div>

      <nav className="flex-1 p-4 space-y-1">
        <NavItem
          to="/"
          icon={<LayoutDashboard className="w-5 h-5" />}
          label="Dashboard"
        />
        <NavItem
          to="/environments"
          icon={<Box className="w-5 h-5" />}
          label="Environments"
        />
      </nav>

      <div className="p-4 border-t border-border">
        <button
          onClick={handleLogout}
          className="flex items-center gap-3 px-4 py-2 rounded-md text-sm font-medium text-foreground hover:bg-gray-200 w-full transition-colors"
        >
          <LogOut className="w-5 h-5" />
          Logout
        </button>
      </div>
    </aside>
  );
}
