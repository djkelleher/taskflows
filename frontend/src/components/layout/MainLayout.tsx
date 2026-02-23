import { Outlet } from "react-router-dom";
import { AppBar } from "./AppBar";

export function MainLayout() {
  return (
    <div className="flex flex-col min-h-screen">
      <AppBar />
      <main className="flex-1 flex flex-col overflow-hidden">
        <Outlet />
      </main>
    </div>
  );
}
