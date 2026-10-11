"""Local before/after classification evaluation; reuses Phase B2 reference checks."""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.reconcile_phase_b2 import read_rows, evaluate_inventory, reference_comparison
from src.tender_pricing.data_loading import load_project_data
from src.tender_pricing.pdf_ingestion import extract_pdf_text_pages, PdfPageText
from src.tender_pricing.position_parser import parse_lv_positions, parse_page_positions
from src.tender_pricing.product_matching import classify_position

PROBES = {
    'decimal_comma_valve': 'Zuluft - Tellerventil\nGrösse Ø 12,5 cm Stk 6',
    'vfc_pressure_not_diameter': 'Einkanal-Volumenstromregler\nTyp VFC\nMod. DN V DP\ncm m3/h Pa\nVFC 8 40-100 250 Stk 12',
    'valve_quantity_not_diameter': 'Zuluft - Tellerventil\nStk 10',
    'controls_temperature': 'Kanaltemperaturfühler Stk 6',
    'controls_differential': 'Druckdifferenzfühler Stk 2',
    'controls_combined_sensor': 'Kanaltemperatur- und Feuchtefühler Stk 6',
    'controls_pressure_switch': 'Druckwächter Stk. 4',
    'controls_actuator': 'Drehantrieb, 20 Nm, Stk. 2\nAC/DC 24 V, Auf/Zu, 3-Punkt, 150 s, IP54',
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=['before', 'after'])
    args = parser.parse_args()
    output = ROOT / 'outputs/parser_matcher_improvement'
    output.mkdir(exist_ok=True)
    target = output / (args.stage + '.json')
    if target.exists():
        raise SystemExit('Preserve existing evaluation; stage output already exists.')
    data = load_project_data(ROOT)
    snapshot = output / 'source_pages.json'
    if not snapshot.exists():
        selected = sorted({int(r['source_page']) for r in data['examples']} | {81, 82, 110, 165, 166})
        pages = extract_pdf_text_pages(ROOT / 'BKP_244_LV_Lueftung_260804.pdf', selected)
        snapshot.write_text(json.dumps([{'page_number': p.page_number, 'text': p.text} for p in pages], ensure_ascii=False, indent=2), encoding='utf-8')
    pages = [PdfPageText(**p) for p in json.loads(snapshot.read_text(encoding='utf-8'))]
    page_set = {p.page_number for p in pages}
    positions = parse_lv_positions(pages)
    corrected = [r for r in read_rows(ROOT / 'outputs/phase8h_extraction_correction/corrected_candidates.jsonl') if r['pdf_page'] in page_set]
    excluded = [r for r in read_rows(ROOT / 'outputs/phase8h_extraction_correction/excluded_false_positives.jsonl') if r['pdf_page'] in page_set]
    results = evaluate_inventory(corrected, excluded, positions, data)
    references = reference_comparison(data, results)
    catalog = {r['product_id']: r for r in data['catalog']}
    productivity = {r['install_code']: r for r in data['productivity']}
    classify = lambda p: classify_position(p, catalog, productivity, data['parameters'])
    probes = {name: [classify(p) for p in parse_page_positions(PdfPageText(1, text))] for name, text in PROBES.items()}
    payload = {'reference_counts': dict(Counter(r['category'] for r in references)),
               'references': references, 'selected_page_status_counts': dict(Counter(r['status'] for r in results)),
               'results': results, 'probes': probes, 'source_pages': sorted(page_set),
               'notes': ['Classification only; no costs calculated.', 'Primary selected matches evaluated; candidates do not constitute commercial equivalence.']}
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'reference_counts': payload['reference_counts'], 'selected_page_status_counts': payload['selected_page_status_counts'],
                      'probes': {name: [(r['matched_product_id'], r['status']) for r in rows] for name, rows in probes.items()}}, indent=2))


if __name__ == '__main__':
    main()
