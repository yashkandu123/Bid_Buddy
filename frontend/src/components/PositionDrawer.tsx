import { Save, X } from "lucide-react";
import { FormEvent, useEffect, useMemo, useState } from "react";
import { chf } from "../app/format";
import { updatePositionReview } from "../app/apiClient";
import type { CatalogItem, TenderPosition, TenderResult } from "../app/types";
import { StatusBadge } from "./StatusBadge";

export function PositionDrawer({
  position,
  onClose,
  catalog,
  jobId,
  onSaved
}: {
  position: TenderPosition | null;
  catalog: CatalogItem[];
  jobId?: string;
  onClose: () => void;
  onSaved: (result: TenderResult) => void;
}) {
  const [quantity, setQuantity] = useState("");
  const [unit, setUnit] = useState("pc");
  const [productId, setProductId] = useState("");
  const [notes, setNotes] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isSaving, setSaving] = useState(false);

  useEffect(() => {
    if (!position) return;
    setQuantity(String(position.quantity));
    setUnit(position.unit);
    setProductId(position.matched_product_id ?? "");
    setNotes(position.review_state?.estimator_notes ?? "");
    setError(null);
  }, [position]);

  const productOptions = useMemo(
    () => catalog.filter((item) => !unit || item.unit === unit),
    [catalog, unit]
  );

  if (!position) return null;
  const canEdit = Boolean(jobId);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!jobId || !position) return;
    setSaving(true);
    setError(null);
    try {
      const updated = await updatePositionReview(jobId, position.lv_id, {
        quantity: Number(quantity),
        unit,
        matched_product_id: productId || null,
        estimator_notes: notes
      });
      onSaved(updated);
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : "Could not save review changes.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <aside className="drawer" aria-label="Position traceability">
      <button className="icon-button drawer-close" type="button" onClick={onClose} aria-label="Close details">
        <X size={20} />
      </button>
      <p className="eyebrow">Source page {position.source_page}</p>
      <h3>{position.lv_id}</h3>
      <StatusBadge status={position.status} />

      <section>
        <h4>Original German text</h4>
        <p>{position.original_description}</p>
      </section>

      <section>
        <h4>Parsed quantity</h4>
        <p>
          {position.quantity} {position.unit} · source unit {position.original_unit}
        </p>
        {position.machine_values?.quantity !== undefined && position.review_state?.has_overrides ? (
          <p>
            Machine value: {String(position.machine_values.quantity)} {String(position.machine_values.unit)}
          </p>
        ) : null}
      </section>

      <section>
        <h4>Traceability</h4>
        <dl>
          <dt>Product</dt>
          <dd>{position.catalogue_traceability?.product_id ?? "No confirmed product"}</dd>
          <dt>Catalogue</dt>
          <dd>{position.catalogue_traceability?.description ?? "Not available"}</dd>
          <dt>Productivity</dt>
          <dd>{position.productivity_traceability?.work_type ?? "Not available"}</dd>
          <dt>Direct cost</dt>
          <dd>{chf(position.accepted_direct_position_cost_chf ?? undefined)}</dd>
          <dt>Preview cost</dt>
          <dd>{chf(position.override_cost_preview?.direct_position_cost_chf)}</dd>
          <dt>Reason</dt>
          <dd>{position.insufficient_reason ?? position.classification_reason ?? position.match_reason}</dd>
        </dl>
      </section>

      <section>
        <h4>Cost breakdown</h4>
        <dl>
          <dt>Material</dt>
          <dd>{chf(position.accepted_material_cost_chf ?? position.override_cost_preview?.material_cost_chf)}</dd>
          <dt>Labour</dt>
          <dd>{chf(position.accepted_labour_cost_chf ?? position.override_cost_preview?.labour_cost_chf)}</dd>
          <dt>Basis</dt>
          <dd>{position.cost_confirmation_status ?? "Not priced"}</dd>
        </dl>
      </section>

      <form className="review-form" onSubmit={handleSubmit}>
        <h4>Estimator override</h4>
        {!canEdit ? <p>Edits are available only for uploaded jobs, not the fixed Phase 2 reference output.</p> : null}
        <label>
          Quantity
          <input
            type="number"
            min="0.0001"
            step="0.0001"
            value={quantity}
            disabled={!canEdit}
            onChange={(event) => setQuantity(event.target.value)}
          />
        </label>
        <label>
          Unit
          <select value={unit} disabled={!canEdit} onChange={(event) => setUnit(event.target.value)}>
            {["pc", "m", "m2", "h", "LS", "system"].map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </select>
        </label>
        <label>
          Catalogue product
          <select value={productId} disabled={!canEdit} onChange={(event) => setProductId(event.target.value)}>
            <option value="">No product selected</option>
            {productOptions.map((item) => (
              <option key={item.product_id} value={item.product_id}>
                {item.product_id} · {item.description}
              </option>
            ))}
          </select>
        </label>
        <label>
          Estimator notes
          <textarea value={notes} disabled={!canEdit} onChange={(event) => setNotes(event.target.value)} />
        </label>
        {position.review_state?.recalculation_status ? (
          <p className="inline-message">State: {position.review_state.recalculation_status}</p>
        ) : null}
        {error ? <p className="inline-message error">{error}</p> : null}
        <button className="primary-button" type="submit" disabled={!canEdit || isSaving}>
          <Save size={18} /> {isSaving ? "Saving..." : "Save and recalculate"}
        </button>
      </form>

      {position.conflict_flags.length ? (
        <section>
          <h4>Review flags</h4>
          <ul className="flag-list">
            {position.conflict_flags.map((flag) => (
              <li key={`${flag.code}-${flag.message}`}>
                <strong>{flag.code}</strong>
                <span>{flag.message}</span>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {position.duplicate_group_id ? (
        <section>
          <h4>Duplicate annotation</h4>
          <p>
            {position.duplicate_group_id}: {position.duplicate_classification} ({position.duplicate_count} rows)
          </p>
        </section>
      ) : null}
    </aside>
  );
}
