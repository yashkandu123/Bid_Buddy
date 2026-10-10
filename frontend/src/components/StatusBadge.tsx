const STATUS_LABELS: Record<string, string> = {
  calculated: "Calculated",
  supplier_quote_required: "Supplier quote required",
  review_required: "Review required",
  insufficient_information: "Insufficient information",
  non_priceable: "Non-priceable",
  completed: "Completed",
  processing: "Processing",
  queued: "Queued",
  failed: "Failed"
};

export function StatusBadge({ status }: { status: string }) {
  return <span className={`status-badge status-${status}`}>{STATUS_LABELS[status] ?? status}</span>;
}
