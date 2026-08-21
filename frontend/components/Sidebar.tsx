"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/cn";
import {
  ChevronLeftIcon,
  ChevronRightIcon,
  CloseIcon,
  FolderIcon,
  GearIcon,
  GridIcon,
  HomeIcon,
  MenuIcon,
  PackageIcon,
  PlayListIcon,
} from "@/components/icons";

const NAV_ITEMS = [
  { href: "/", label: "Home", icon: HomeIcon, exact: true },
  { href: "/dashboard", label: "Dashboard", icon: GridIcon },
  { href: "/projects", label: "Projects", icon: FolderIcon },
  { href: "/executions", label: "Executions", icon: PlayListIcon },
  { href: "/artifacts", label: "Artifacts", icon: PackageIcon },
  { href: "/settings", label: "Settings", icon: GearIcon },
];

function isActiveHref(pathname: string, href: string, exact?: boolean) {
  if (exact) return pathname === href;
  return pathname === href || pathname.startsWith(`${href}/`);
}

export function Sidebar() {
  const pathname = usePathname();
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);

  useEffect(() => {
    if (!mobileOpen) return;
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") setMobileOpen(false);
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [mobileOpen]);

  return (
    <>
      <button
        type="button"
        onClick={() => setMobileOpen(true)}
        aria-label="Open navigation"
        className="fixed left-4 top-[4.5rem] z-30 flex h-9 w-9 items-center justify-center rounded-full border border-line-strong bg-ground/90 text-ivory-dim backdrop-blur-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-gold/50 md:hidden"
      >
        <MenuIcon />
      </button>

      {mobileOpen ? (
        <div className="fixed inset-0 z-40 md:hidden">
          <button
            type="button"
            aria-label="Close navigation"
            onClick={() => setMobileOpen(false)}
            className="absolute inset-0 bg-black/60"
          />
          <nav
            aria-label="Primary"
            className="relative flex h-full w-64 flex-col gap-1 border-r border-line bg-ground p-4 pt-6"
          >
            <div className="mb-4 flex items-center justify-between">
              <span className="text-xs uppercase tracking-widest2 text-ivory-faint">Navigate</span>
              <button
                type="button"
                onClick={() => setMobileOpen(false)}
                aria-label="Close navigation"
                className="flex h-8 w-8 items-center justify-center rounded-full text-ivory-faint hover:text-ivory focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-gold/50"
              >
                <CloseIcon />
              </button>
            </div>
            {NAV_ITEMS.map((item) => (
              <SidebarLink
                key={item.href}
                item={item}
                active={isActiveHref(pathname, item.href, item.exact)}
                onNavigate={() => setMobileOpen(false)}
              />
            ))}
          </nav>
        </div>
      ) : null}

      <aside
        className={cn(
          "sticky top-[73px] hidden h-[calc(100vh-73px)] flex-shrink-0 flex-col border-r border-line bg-ground-raised/20 py-5 transition-all duration-200 md:flex",
          collapsed ? "w-[68px] px-2" : "w-56 px-3"
        )}
      >
        <nav aria-label="Primary" className="flex flex-1 flex-col gap-1">
          {NAV_ITEMS.map((item) => (
            <SidebarLink
              key={item.href}
              item={item}
              active={isActiveHref(pathname, item.href, item.exact)}
              collapsed={collapsed}
            />
          ))}
        </nav>

        <button
          type="button"
          onClick={() => setCollapsed((v) => !v)}
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          className="mt-2 flex items-center justify-center gap-2 rounded-md border border-line-strong px-3 py-2 text-ivory-faint transition-colors hover:text-ivory-dim focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-gold/50"
        >
          {collapsed ? <ChevronRightIcon /> : <ChevronLeftIcon />}
          {!collapsed ? <span className="text-xs uppercase tracking-widest2">Collapse</span> : null}
        </button>
      </aside>
    </>
  );
}

function SidebarLink({
  item,
  active,
  collapsed,
  onNavigate,
}: {
  item: (typeof NAV_ITEMS)[number];
  active: boolean;
  collapsed?: boolean;
  onNavigate?: () => void;
}) {
  const Icon = item.icon;
  return (
    <Link
      href={item.href}
      title={collapsed ? item.label : undefined}
      onClick={onNavigate}
      className={cn(
        "flex items-center gap-3 rounded-md px-3 py-2.5 text-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-gold/50",
        collapsed ? "justify-center" : "",
        active ? "bg-gold/10 text-gold" : "text-ivory-faint hover:bg-white/[0.03] hover:text-ivory-dim"
      )}
    >
      <Icon className="flex-shrink-0" />
      {!collapsed ? <span>{item.label}</span> : null}
    </Link>
  );
}
