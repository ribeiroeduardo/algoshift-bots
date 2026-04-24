import { Home, Menu, PanelLeftClose, Waypoints } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { Link, NavLink, useLocation } from "react-router-dom";
import { cn } from "@/lib/utils";
import { isSupabaseEnabled } from "@/lib/supabaseClient";

const SIDEBAR_KEY = "algoshift-sidebar-collapsed";

type DashboardLayoutProps = {
  title: string;
  children: ReactNode;
};

export const DashboardLayout = ({ title, children }: DashboardLayoutProps) => {
  const { pathname } = useLocation();
  const [collapsed, setCollapsed] = useState(() => {
    if (typeof globalThis.localStorage === "undefined") {
      return false;
    }
    return globalThis.localStorage.getItem(SIDEBAR_KEY) === "1";
  });
  const supa = isSupabaseEnabled();

  useEffect(() => {
    globalThis.localStorage.setItem(SIDEBAR_KEY, collapsed ? "1" : "0");
  }, [collapsed]);

  return (
    <div className="flex h-svh w-full bg-[#111] text-[13px] text-[#ededed]">
      <aside
        data-sidebar
        className={cn(
          "flex h-full flex-col border-r border-white/[0.06] bg-[#0e0e0e]",
          "transition-[width] duration-200 ease-out",
          collapsed ? "w-12" : "w-[220px]",
        )}
      >
        <div className="flex h-12 items-center border-b border-white/[0.06] px-2">
          <button
            type="button"
            className={cn(
              "inline-flex h-8 w-8 items-center justify-center rounded-md",
              "text-[#919191] hover:bg-white/[0.05] hover:text-[#ededed]",
            )}
            onClick={() => setCollapsed((c) => !c)}
            title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
            aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          >
            {collapsed ? <Menu className="h-4 w-4" /> : <PanelLeftClose className="h-4 w-4" />}
          </button>
        </div>
        <nav className="flex flex-1 flex-col gap-0.5 p-2" aria-label="Main">
          <Link
            to="/"
            className={cn(
              "nav-dash flex h-8 items-center gap-2 rounded-md px-2.5 text-[13px] font-medium",
              pathname === "/"
                ? "bg-white/[0.08] text-white"
                : "text-[#919191] hover:bg-white/[0.05] hover:text-[#ededed]",
            )}
            title="Home"
          >
            <Home className="h-4 w-4 shrink-0" />
            {!collapsed ? <span>Home</span> : null}
          </Link>
          <NavLink
            to="/strategies"
            className={({ isActive }) =>
              cn(
                "nav-dash flex h-8 items-center gap-2 rounded-md px-2.5 text-[13px] font-medium",
                isActive
                  ? "bg-white/[0.08] font-semibold text-white"
                  : "text-[#919191] hover:bg-white/[0.05] hover:text-[#ededed]",
              )
            }
            title="Strategies"
          >
            <Waypoints className="h-4 w-4 shrink-0" />
            {!collapsed ? <span>Strategies</span> : null}
          </NavLink>
        </nav>
      </aside>
      <div className="flex min-h-0 min-w-0 flex-1 flex-col">
        <header className="flex h-12 shrink-0 items-center justify-between border-b border-white/[0.06] px-4">
          <div className="flex min-w-0 items-center gap-1.5 text-[14px] text-[#919191]">
            <span>AlgoShift</span>
            <span className="text-[#444]">/</span>
            <span className="truncate text-[#ededed]">{title}</span>
          </div>
          <div className="flex items-center gap-1">
            {!supa ? (
              <span className="text-[12px] text-amber-400/90">Demo mode (no Supabase env)</span>
            ) : null}
          </div>
        </header>
        <main className="min-h-0 flex-1 overflow-auto p-4 md:px-6">{children}</main>
      </div>
    </div>
  );
};
