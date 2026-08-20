"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/cn";

const LINKS = [
  { href: "/dashboard", label: "Dashboard" },
  { href: "/projects", label: "Projects" },
  { href: "/executions", label: "Executions" },
  { href: "/artifacts", label: "Artifacts" },
  { href: "/settings", label: "Settings" },
];

export function TopNav() {
  const pathname = usePathname();

  return (
    <header className="sticky top-0 z-40 border-b border-line bg-ground/85 backdrop-blur-md">
      <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-5 sm:px-8">
        <Link href="/" className="group flex items-baseline gap-2.5">
          <span className="font-display text-2xl font-medium tracking-tight text-ivory sm:text-[1.75rem]">Loco</span>
          <span className="font-display text-2xl italic tracking-tight text-gold sm:text-[1.75rem]">Pilot</span>
        </Link>

        <nav className="hidden items-center gap-1 md:flex">
          {LINKS.map((link) => {
            const isActive = pathname === link.href || pathname.startsWith(`${link.href}/`);
            return (
              <Link
                key={link.href}
                href={link.href}
                className={cn(
                  "rounded-full px-3.5 py-1.5 text-sm tracking-wide transition-colors duration-200",
                  isActive ? "text-ivory" : "text-ivory-faint hover:text-ivory-dim"
                )}
              >
                {link.label}
              </Link>
            );
          })}
        </nav>

        <MobileNav pathname={pathname} />
      </div>
    </header>
  );
}

function MobileNav({ pathname }: { pathname: string }) {
  return (
    <nav className="flex items-center gap-3 md:hidden">
      {LINKS.map((link) => {
        const isActive = pathname === link.href || pathname.startsWith(`${link.href}/`);
        return (
          <Link
            key={link.href}
            href={link.href}
            className={cn(
              "text-xs uppercase tracking-widest2 transition-colors",
              isActive ? "text-gold" : "text-ivory-faint"
            )}
          >
            {link.label}
          </Link>
        );
      })}
    </nav>
  );
}
