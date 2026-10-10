import type { ProductCategory, TenderPosition } from "./types";

export const PRODUCT_CATEGORIES: ProductCategory[] = [
  { key: "all", label: "All" },
  { key: "supply-air-valves", label: "Supply-air valves" },
  { key: "exhaust-air-valves", label: "Exhaust-air valves" },
  { key: "ductwork", label: "Ductwork & fittings" },
  { key: "dampers-flow", label: "Dampers & flow control" },
  { key: "silencers", label: "Silencers" },
  { key: "fire-protection", label: "Fire protection" },
  { key: "insulation", label: "Insulation" },
  { key: "equipment", label: "Equipment/packages" },
  { key: "controls", label: "Controls" },
  { key: "supports", label: "Supports" },
  { key: "other", label: "Other / unclassified" }
];

export function positionCategory(position: TenderPosition): string {
  const category = position.catalogue_traceability?.category;
  const subcategory = position.catalogue_traceability?.subcategory;
  if (category === "Air terminal" && subcategory === "Supply valve") return "supply-air-valves";
  if (category === "Air terminal" && subcategory === "Exhaust valve") return "exhaust-air-valves";
  if (category === "Ductwork") return "ductwork";
  if (category === "Damper" || category === "Flow controller") return "dampers-flow";
  if (category === "Silencer") return "silencers";
  if (category === "Fire protection") return "fire-protection";
  if (category === "Insulation") return "insulation";
  if (category === "Equipment") return "equipment";
  if (category === "Controls") return "controls";
  if (category === "Support") return "supports";

  const text = `${position.original_description} ${position.source_line}`.toLowerCase();
  if (containsAny(text, ["zuluft", "supply"]) && containsAny(text, ["tellerventil", "valve"])) {
    return "supply-air-valves";
  }
  if (containsAny(text, ["abluft", "exhaust"]) && containsAny(text, ["tellerventil", "valve"])) {
    return "exhaust-air-valves";
  }
  if (containsAny(text, ["kanal", "rohr", "bogen"])) return "ductwork";
  if (containsAny(text, ["drosselklappe", "volumenstromregler", "vfc", "tvr", "tvj", "vvs"])) {
    return "dampers-flow";
  }
  if (containsAny(text, ["schalld", "ms-f", "kosd"])) return "silencers";
  if (containsAny(text, ["brandschutz", "ei30", "ei 30", "ei90", "ei 90", "durchdring"])) {
    return "fire-protection";
  }
  if (containsAny(text, ["dämm", "d�mm", "mineralwolle", "v2a ummantelung"])) return "insulation";
  if (containsAny(text, ["feldgerät", "feldger", "fühler", "f�hler", "sensor"])) return "controls";
  return "other";
}

function containsAny(text: string, needles: string[]): boolean {
  return needles.some((needle) => text.includes(needle));
}
