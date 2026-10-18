import type { ReactNode } from "react";

export function Panel({
  title,
  tag,
  className = "",
  children,
}: {
  title: string;
  tag?: string;
  className?: string;
  children: ReactNode;
}) {
  return (
    <section className={`panel ${className}`} aria-label={title}>
      <header className="panel-head">
        <h2>{title}</h2>
        {tag && <span className="tag">{tag}</span>}
      </header>
      <div className="panel-body">{children}</div>
    </section>
  );
}

/** Estado vazio honesto para módulos ainda não implementados. */
export function NotYet({ phase, children }: { phase: string; children: ReactNode }) {
  return (
    <div className="empty">
      <span className="tag tag-planned">{phase}</span>
      <p>{children}</p>
    </div>
  );
}
