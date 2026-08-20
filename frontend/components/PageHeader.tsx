import type { ReactNode } from "react";

export function PageHeader({
  eyebrow,
  title,
  description,
  action,
}: {
  eyebrow?: string;
  title: string;
  description?: string;
  action?: ReactNode;
}) {
  return (
    <div className="mb-10 flex flex-col gap-6 sm:flex-row sm:items-end sm:justify-between">
      <div>
        {eyebrow ? <p className="mb-3 text-xs uppercase tracking-widest2 text-gold/80">{eyebrow}</p> : null}
        <h1 className="font-display text-4xl tracking-tightest text-ivory sm:text-5xl">{title}</h1>
        {description ? (
          <p className="mt-3 max-w-xl text-base leading-relaxed text-ivory-faint">{description}</p>
        ) : null}
      </div>
      {action ? <div className="flex-shrink-0">{action}</div> : null}
    </div>
  );
}
