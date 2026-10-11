from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any


FAMILY_TERMS = {
    "supply_valve": ("supply air valve", "zuluftventil", "zuluft tellerventil", "bouche de soufflage", "soupape de soufflage"),
    "exhaust_valve": ("exhaust air valve", "abluftventil", "abluft tellerventil", "bouche d extraction", "bouche de reprise"),
    "fire_damper": ("fire damper", "brandschutzklappe", "clapet coupe feu"),
    "manual_damper": ("manual balancing damper", "drosselklappe", "registre d equilibrage", "registre manuel"),
    "silencer": ("silencer", "schalldampfer", "schalldaempfer", "schalldoempfer", "silencieux acoustique"),
    "flow_controller": ("flow controller", "volumenstromregler", "regulateur de debit"),
    "vav": ("variable volume controller", "variable volume flow controller", "vav controller", "variabler volumenstromregler", "regulateur de debit variable"),
    "cav": ("constant volume controller", "constant volume flow controller", "cav controller", "konstantvolumenstromregler", "regulateur de debit constant"),
    "insulation": ("duct insulation", "external insulation", "aussendammung", "aussendaemmung", "aussendoemmung", "warmedammung", "waermedaemmung", "isolation de gaine", "isolation exterieure"),
    "fire_seal": ("fire seal", "penetration seal", "penetration sealing", "durchdringung", "brandschutzabschottung", "calfeutrement coupe feu"),
    "inspection_cover": ("inspection cover", "revisionsdeckel", "revisisondeckel", "trappe de visite"),
    "support": ("connection angle", "anschlusswinkel", "anschlusswinkle", "equerre de fixation"),
    "circular_duct": ("circular duct", "rundrohr", "runde luftleitung", "gaine circulaire"),
    "rectangular_duct": ("rectangular duct", "blechkanal", "rechteckkanal", "gaine rectangulaire"),
    "bend": ("circular bend", "rohrbogen", "bogen", "coude circulaire"),
    "air_handling_unit": ("air handling unit", "luftungsgerat", "lueftungsgeraet", "luftungsgeraet", "zuluftgeraet", "centrale de traitement d air"),
    "fan": ("fan unit", "ventilator", "ventilateur"),
    "differential_pressure_sensor": ("differential pressure transmitter", "druckdifferenzfuhler", "druckdifferenzfuehler", "capteur de pression differentielle"),
    "temperature_sensor": ("temperature sensor", "temperaturfuhler", "temperaturfuehler", "sonde de temperature"),
    "actuator": ("actuator", "drehantrieb", "stellantrieb", "servomoteur"),
    "flow_sensor": ("volume flow transmitter", "volumenstromfuhler", "volumenstromfuehler", "capteur de debit"),
    "smoke_detector": ("duct smoke detector", "kanalrauchmelder", "detecteur de fumee de gaine"),
    "flexible_connector": ("flexible connector", "verbindungsmanschette", "manchette souple"),
    "blank_section": ("blank section", "leerteil", "section vide"),
    "rain_hood": ("rain hood", "regenhut", "chapeau pare pluie"),
    "mounting_frame": ("mounting frame", "montagerahmen", "cadre de montage"),
    "potential_bonding": ("equipotential bonding", "potentialverbindung", "liaison equipotentielle"),
}

MATERIAL_TERMS = {
    "galvanized": ("galvanized", "galvanised", "verzinkt", "acier galvanise"),
    "stainless": ("stainless", "v2a", "inox", "acier inoxydable"),
    "mineral_wool": ("mineral wool", "mineralwoll", "laine minerale"),
    "plastic": ("plastic", "kunststoff", "plastique"),
    "polyurethane": ("polyurethane", "polyurethan", "polyurethanschaum", "mousse polyurethane"),
}

COMPONENT_NOUNS = {
    "actuator",
    "bend",
    "controller",
    "cover",
    "damper",
    "duct",
    "insulation",
    "seal",
    "sensor",
    "silencer",
    "transmitter",
    "unit",
    "valve",
}

GENERIC_MATCH_TOKENS = {
    "air",
    "and",
    "avec",
    "for",
    "from",
    "mit",
    "oder",
    "the",
    "und",
    "with",
}

# pdfplumber can expose an un-decodable umlaut as U+FFFD. Repair only known
# HVAC roots; a blanket replacement would manufacture words and false matches.
CORRUPTED_HVAC_ROOTS = {
    "d�mm": "daemm",
    "d�mpf": "daempf",
    "f�hler": "fuehler",
    "ger�t": "geraet",
    "gr�sse": "groesse",
    "l�ft": "lueft",
    "w�rme": "waerme",
}


@dataclass(frozen=True)
class SemanticCandidate:
    product_id: str
    score: int
    evidence: tuple[str, ...]


def normalise_multilingual(value: str) -> str:
    value = repair_extraction_text(value)
    value = value.lower().replace("ß", "ss").replace("ø", "o").replace("�", "o")
    value = "".join(character for character in unicodedata.normalize("NFKD", value) if not unicodedata.combining(character))
    value = re.sub(r"(?<=\d),(?=\d)", ".", value)
    return re.sub(r"[^a-z0-9.]+", " ", value).strip()


def repair_extraction_text(value: str) -> str:
    repaired = value.lower()
    for corrupted, replacement in CORRUPTED_HVAC_ROOTS.items():
        repaired = repaired.replace(corrupted, replacement)
    return repaired


def concepts_for_text(value: str, vocabulary: dict[str, tuple[str, ...]] = FAMILY_TERMS) -> set[str]:
    text = normalise_multilingual(value)
    return {
        concept
        for concept, terms in vocabulary.items()
        if any(normalise_multilingual(term) in text for term in terms)
    }


def rank_semantic_candidates(
    *,
    text: str,
    unit: str | None,
    technical_attributes: dict[str, Any],
    catalog: list[dict[str, str]],
    deterministic_product_id: str | None = None,
    limit: int = 8,
) -> list[SemanticCandidate]:
    source = normalise_multilingual(text)
    source_families = concepts_for_text(source)
    source_materials = concepts_for_text(source, MATERIAL_TERMS)
    source_tokens = {
        token for token in source.split()
        if len(token) > 2 and token not in GENERIC_MATCH_TOKENS
    }
    deterministic_product = next(
        (product for product in catalog if product["product_id"] == deterministic_product_id),
        None,
    )
    deterministic_category = (
        deterministic_product.get("category") if deterministic_product is not None else None
    )
    deterministic_components = _catalogue_component_nouns(deterministic_product)
    ranked: list[SemanticCandidate] = []

    for product in catalog:
        product_id = product["product_id"]
        if unit and product.get("unit") != unit and product_id != deterministic_product_id:
            continue
        candidate_text = " ".join(
            str(product.get(key, ""))
            for key in ("category", "subcategory", "manufacturer", "model", "description")
        )
        candidate_normalised = normalise_multilingual(candidate_text)
        candidate_families = concepts_for_text(candidate_normalised)
        candidate_materials = concepts_for_text(candidate_normalised, MATERIAL_TERMS)
        shared_families = source_families & candidate_families
        same_deterministic_category = bool(
            deterministic_category
            and product.get("category") == deterministic_category
            and product.get("unit") == deterministic_product.get("unit")
            and bool(deterministic_components & _catalogue_component_nouns(product))
        )
        if (
            source_families
            and not shared_families
            and product_id != deterministic_product_id
            and not same_deterministic_category
        ):
            continue

        evidence: list[str] = []
        score = 0
        if product_id == deterministic_product_id:
            score += 100
            evidence.append("existing deterministic product")
        if shared_families:
            score += 35 * len(shared_families)
            evidence.append("component type: " + ", ".join(sorted(shared_families)))
        elif same_deterministic_category:
            score += 4
            evidence.append("same catalogue category and unit as deterministic match")
        shared_tokens = source_tokens & {
            token for token in candidate_normalised.split()
            if len(token) > 2 and token not in GENERIC_MATCH_TOKENS
        }
        if shared_tokens:
            score += min(len(shared_tokens), 8)
            evidence.append("shared terms: " + ", ".join(sorted(shared_tokens)[:8]))
        if unit and product.get("unit") == unit:
            score += 5
            evidence.append(f"unit={unit}")
        technical_score, technical_evidence = _technical_score(technical_attributes, candidate_normalised)
        if "insulation" in shared_families:
            source_thicknesses = _millimetre_values(source)
            candidate_thicknesses = _millimetre_values(candidate_normalised)
            shared_thicknesses = source_thicknesses & candidate_thicknesses
            if shared_thicknesses:
                technical_score += 18
                technical_evidence.append(
                    "insulation_thickness=" + ",".join(str(value) for value in sorted(shared_thicknesses)) + "mm"
                )
        score += technical_score
        evidence.extend(technical_evidence)
        if source_materials & candidate_materials:
            score += 8
            evidence.append("material: " + ", ".join(sorted(source_materials & candidate_materials)))

        # Unit agreement alone is not semantic evidence.
        if (
            product_id == deterministic_product_id
            or shared_families
            or same_deterministic_category
            or shared_tokens
            or technical_score
        ):
            ranked.append(SemanticCandidate(product_id, score, tuple(evidence)))

    return sorted(ranked, key=lambda item: (-item.score, item.product_id))[:limit]


def _catalogue_component_nouns(product: dict[str, str] | None) -> set[str]:
    if not product:
        return set()
    text = normalise_multilingual(
        " ".join(str(product.get(key, "")) for key in ("subcategory", "description"))
    )
    return set(text.split()) & COMPONENT_NOUNS


def _millimetre_values(text: str) -> set[int]:
    return {
        int(float(match.group(1)))
        for match in re.finditer(r"\b(\d+(?:\.\d+)?)\s*mm\b", text)
    }


def semantic_conflicts(
    *,
    source_text: str,
    technical_attributes: dict[str, Any],
    candidate: dict[str, str],
) -> list[dict[str, str]]:
    candidate_text = " ".join(
        str(candidate.get(key, "")) for key in ("category", "subcategory", "model", "description")
    )
    source_families = concepts_for_text(source_text)
    candidate_families = concepts_for_text(candidate_text)
    conflicts: list[dict[str, str]] = []
    if source_families and candidate_families and source_families.isdisjoint(candidate_families):
        conflicts.append({"code": "component_type_mismatch", "message": "Candidate component type conflicts with tender evidence."})

    source_materials = concepts_for_text(source_text, MATERIAL_TERMS)
    candidate_materials = concepts_for_text(candidate_text, MATERIAL_TERMS)
    if source_materials and candidate_materials and source_materials.isdisjoint(candidate_materials):
        conflicts.append({"code": "material_mismatch", "message": "Candidate material conflicts with tender evidence."})
    return conflicts


def _technical_score(attrs: dict[str, Any], candidate_text: str) -> tuple[int, list[str]]:
    score = 0
    evidence: list[str] = []
    for item in attrs.get("diameters", []):
        if not isinstance(item, dict) or "value_mm" not in item:
            continue
        value = str(int(float(item["value_mm"])))
        if re.search(rf"(?:dn|[- ]){re.escape(value)}\b", candidate_text):
            score += 18
            evidence.append(f"diameter={value}mm")
    for item in attrs.get("dimensions", []):
        if not isinstance(item, dict):
            continue
        values = [str(int(float(value))) for value in item.get("values_mm", [])]
        if values and all(re.search(rf"\b{re.escape(value)}\b", candidate_text) for value in values):
            score += 20
            evidence.append("dimensions=" + "x".join(values) + "mm")
    for rating in attrs.get("fire_ratings", []):
        normalized = normalise_multilingual(str(rating)).replace(" ", "")
        if normalized and normalized in candidate_text.replace(" ", "").replace("-", ""):
            score += 15
            evidence.append(f"fire_rating={rating}")
    return score, evidence
