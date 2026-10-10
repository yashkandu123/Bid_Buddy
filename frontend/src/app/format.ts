export function chf(value: number | undefined): string {
  if (value === undefined || Number.isNaN(value)) return "—";
  return new Intl.NumberFormat("de-CH", {
    style: "currency",
    currency: "CHF",
    maximumFractionDigits: 2
  }).format(value);
}

export function pct(value: number | undefined): string {
  if (value === undefined || Number.isNaN(value)) return "—";
  return `${Math.round(value * 100)}%`;
}
