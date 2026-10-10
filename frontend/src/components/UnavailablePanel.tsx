import type { ReactNode } from "react";

export function UnavailablePanel({
  title,
  children
}: {
  title: string;
  children: ReactNode;
}) {
  return (
    <section className="unavailable">
      <p className="eyebrow">Not available yet</p>
      <h3>{title}</h3>
      <p>{children}</p>
    </section>
  );
}
