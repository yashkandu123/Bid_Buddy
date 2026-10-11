import { Save, X } from "lucide-react";
import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { chf } from "../app/format";
import { updatePositionReview } from "../app/apiClient";
import type { CatalogItem, TenderPosition, TenderResult } from "../app/types";
import { StatusBadge } from "./StatusBadge";
import { useReviewNavigation } from "../app/ReviewNavigationContext";

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
  const [unitCost, setUnitCost] = useState("");
  const [costEdited, setCostEdited] = useState(false);
  const [unit, setUnit] = useState("pc");
  const [productId, setProductId] = useState("");
  const [notes, setNotes] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isSaving, setSaving] = useState(false);
  const saveTimer = useRef<number | undefined>(undefined);
  const saving = useRef(false);
  const { setPending } = useReviewNavigation();
  const savedCost = String(position?.net_unit_cost_chf ?? catalog.find(item => item.product_id === position?.matched_product_id)?.net_cost_chf ?? "");
  const dirty = Boolean(position && (
    quantity !== String(position.quantity) || unit !== position.unit || productId !== (position.matched_product_id ?? "") ||
    notes !== (position.review_state?.estimator_notes ?? "") || unitCost !== savedCost
  ));

  useEffect(() => { setPending(dirty || isSaving); }, [dirty, isSaving, setPending]);
  useEffect(() => () => setPending(false), [setPending]);
  useEffect(() => {
    if (!dirty) return;
    const warn = (event: BeforeUnloadEvent) => { event.preventDefault(); };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  useEffect(() => {
    if (!position) return;
    setQuantity(String(position.quantity));
    setUnitCost(String(position.net_unit_cost_chf ?? catalog.find(item => item.product_id === position.matched_product_id)?.net_cost_chf ?? ""));
    setCostEdited(position.review_state?.overridden_fields.includes("net_unit_cost_chf") ?? false);
    setUnit(position.unit);
    setProductId(position.matched_product_id ?? "");
    setNotes(position.review_state?.estimator_notes ?? "");
    setError(null);
  }, [position]);

  useEffect(() => {
    if (!position || !jobId || isSaving) return;
    const savedCost = String(position.net_unit_cost_chf ?? catalog.find(item => item.product_id === position.matched_product_id)?.net_cost_chf ?? "");
    if (quantity === String(position.quantity) && unitCost === savedCost) return;
    if (!quantity || Number(quantity) <= 0 || (costEdited && (!unitCost || Number(unitCost) < 0))) return;
    const timer = window.setTimeout(() => { void saveChanges(); }, 400);
    saveTimer.current = timer;
    return () => window.clearTimeout(timer);
  }, [quantity, unitCost, position, jobId, notes, unit, productId, costEdited]);

  const productOptions = useMemo(
    () => catalog.filter((item) => !unit || item.unit === unit),
    [catalog, unit]
  );

  if (!position) return null;
  const canEdit = Boolean(jobId);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await saveChanges();
  }

  async function saveChanges() {
    if (!jobId || !position) return;
    if (saving.current) return false;
    window.clearTimeout(saveTimer.current);
    if (!quantity || !Number.isFinite(Number(quantity)) || Number(quantity) <= 0) {
      setError("Enter a positive quantity.");
      return false;
    }
    if (costEdited && (!unitCost || !Number.isFinite(Number(unitCost)) || Number(unitCost) < 0)) {
      setError("Enter a non-negative unit cost.");
      return false;
    }
    saving.current = true;
    setSaving(true);
    setError(null);
    try {
      const updated = await updatePositionReview(jobId, position.lv_id, {
        quantity: Number(quantity),
        unit,
        matched_product_id: productId || null,
        estimator_notes: notes,
        ...(costEdited ? { net_unit_cost_chf: Number(unitCost) } : {})
      });
      onSaved(updated);
      return true;
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : "Could not save review changes.");
      return false;
    } finally {
      saving.current = false;
      setSaving(false);
    }
  }

  return (
    <aside className="drawer" aria-label="Position traceability">
      <button className="icon-button drawer-close" type="button" disabled={isSaving} onClick={async () => { if (!dirty || await saveChanges()) onClose(); }} aria-label="Close details">
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
            disabled={!canEdit || isSaving}
            onChange={(event) => setQuantity(event.target.value)}
          />
        </label>
        <label>
          Unit Cost (CHF)
          <input type="number" min="0" step="0.01" value={unitCost}
            disabled={!canEdit || isSaving || !productId || !["calculated", "supplier_quote_required"].includes(position.status)}
            onChange={(event) => { setUnitCost(event.target.value); setCostEdited(true); }} />
        </label>
        <p>Net material cost per unit; labour and allowances are recalculated by the backend.</p>
        {costEdited ? <span className="status-badge">Edited unit cost</span> : null}
        {isSaving ? <p role="status">Saving and recalculating...</p> : null}
        <label>
          Unit
          <select value={unit} disabled={!canEdit || isSaving} onChange={(event) => setUnit(event.target.value)}>
            {["pc", "m", "m2", "h", "LS", "system"].map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </select>
        </label>
        <label>
          Catalogue product
          <select value={productId} disabled={!canEdit || isSaving} onChange={(event) => setProductId(event.target.value)}>
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
          <textarea value={notes} disabled={!canEdit || isSaving} onChange={(event) => setNotes(event.target.value)} />
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
