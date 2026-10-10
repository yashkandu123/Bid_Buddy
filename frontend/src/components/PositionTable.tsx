import { chf, pct } from "../app/format";
import type { TenderPosition } from "../app/types";
import { StatusBadge } from "./StatusBadge";

export function PositionTable({
  positions,
  onSelect
}: {
  positions: TenderPosition[];
  onSelect: (position: TenderPosition) => void;
}) {
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>ID</th>
            <th>Page</th>
            <th>Description</th>
            <th>Qty</th>
            <th>Status</th>
            <th>Product</th>
            <th>Confidence</th>
            <th>Direct cost</th>
          </tr>
        </thead>
        <tbody>
          {positions.map((position) => (
            <tr key={position.lv_id} onClick={() => onSelect(position)}>
              <td>{position.lv_id}</td>
              <td>{position.source_page}</td>
              <td className="description-cell">{position.original_description}</td>
              <td>
                {position.quantity} {position.unit}
              </td>
              <td>
                <StatusBadge status={position.status} />
              </td>
              <td>{position.matched_product_id ?? "—"}</td>
              <td>{pct(position.match_confidence)}</td>
              <td>{chf(position.accepted_direct_position_cost_chf ?? undefined)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
