import Link from "next/link";
import { Fragment } from "react";

export interface BreadcrumbItem {
  label: string;
  href?: string;
}

export function Breadcrumb({ items }: { items: BreadcrumbItem[] }) {
  return (
    <nav aria-label="Breadcrumb" className="mb-4 flex flex-wrap items-center gap-2">
      {items.map((item, i) => (
        <Fragment key={`${item.label}-${i}`}>
          {i > 0 ? (
            <span aria-hidden className="text-xs text-ivory-faint/60">
              /
            </span>
          ) : null}
          {item.href ? (
            <Link
              href={item.href}
              className="text-xs uppercase tracking-widest2 text-ivory-faint transition-colors hover:text-gold"
            >
              {item.label}
            </Link>
          ) : (
            <span aria-current="page" className="text-xs uppercase tracking-widest2 text-ivory-dim">
              {item.label}
            </span>
          )}
        </Fragment>
      ))}
    </nav>
  );
}
