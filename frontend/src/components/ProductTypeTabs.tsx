import { PRODUCT_CATEGORIES } from "../app/category";

export function ProductTypeTabs({
  active,
  counts,
  onChange
}: {
  active: string;
  counts: Record<string, number>;
  onChange: (category: string) => void;
}) {
  return (
    <div className="tabs" role="tablist" aria-label="Product categories">
      {PRODUCT_CATEGORIES.map((category) => (
        <button
          key={category.key}
          type="button"
          role="tab"
          aria-selected={active === category.key}
          className={active === category.key ? "active" : ""}
          onClick={() => onChange(category.key)}
        >
          {category.label}
          <span>{counts[category.key] ?? 0}</span>
        </button>
      ))}
    </div>
  );
}
