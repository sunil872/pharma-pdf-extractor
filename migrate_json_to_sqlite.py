"""
MediAstra Pharma PDF Purchase Import Engine - JSON to SQLite Migration Script
Idempotent migration from supplier_profiles.json and templates.json into SQLite.
"""
import os
import sys
import json
import argparse
import re
from datetime import datetime

# Ensure project root is on sys.path
PROJECT_ROOT = os.path.abspath(os.path.dirname(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from storage import StorageService, get_db_connection, init_db


def clean_text_helper(text: str) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", " ", str(text)).strip()


def run_migration(
    json_path: str = os.path.join(PROJECT_ROOT, "supplier_profiles.json"),
    templates_path: str = os.path.join(PROJECT_ROOT, "templates.json"),
    db_path: str = None,
) -> dict:
    """
    Idempotently migrates JSON supplier profiles and templates into SQLite.
    Returns migration report.
    """
    service = StorageService(db_path=db_path)
    init_db(db_path)
    
    report = {
        "suppliers_imported": 0,
        "layouts_imported": 0,
        "records_skipped": 0,
        "conflicts": 0,
        "errors": [],
        "timestamp": datetime.now().isoformat(),
    }

    if not os.path.exists(json_path):
        report["errors"].append(f"JSON source file not found: {json_path}")
        return report

    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        report["errors"].append(f"Failed to parse JSON file {json_path}: {e}")
        return report

    profiles = data.get("profiles", {})
    if not profiles and isinstance(data, dict):
        profiles = data

    conn = service.get_connection()
    try:
        conn.execute("BEGIN TRANSACTION;")
        cursor = conn.cursor()
        now_iso = datetime.now().isoformat()

        for sup_key, prof in profiles.items():
            try:
                sup_name = prof.get("supplier_name")
                gstin = prof.get("gstin")
                clean_gstin = re.sub(r"[^A-Z0-9]", "", str(gstin or "").upper().strip()) if gstin else None
                norm_name = clean_text_helper(sup_name or "").upper() if sup_name else None
                
                # Check if supplier exists
                cursor.execute("SELECT id, profile_version FROM suppliers WHERE supplier_key = ? OR (gstin IS NOT NULL AND gstin = ?);", (sup_key, clean_gstin or ""))
                existing_sup = cursor.fetchone()

                if existing_sup is None:
                    cursor.execute("""
                        INSERT INTO suppliers (
                            supplier_key, supplier_name, gstin, normalized_name, identity_status,
                            profile_version, profile_confidence, successful_document_count,
                            reviewed_document_count, failure_document_count, is_active,
                            last_seen, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """, (
                        sup_key,
                        sup_name,
                        clean_gstin,
                        norm_name,
                        "EXACT_GSTIN" if clean_gstin else "VERIFIED_NAME",
                        prof.get("profile_version", 1),
                        float(prof.get("profile_confidence", 1.0)),
                        int(prof.get("successful_document_count", 1)),
                        int(prof.get("reviewed_document_count", 0)),
                        int(prof.get("failure_document_count", 0)),
                        1,
                        prof.get("last_seen", now_iso),
                        prof.get("created_at", now_iso),
                        prof.get("last_seen", now_iso),
                    ))
                    supplier_id = cursor.lastrowid
                    report["suppliers_imported"] += 1
                else:
                    supplier_id = existing_sup["id"]
                    report["records_skipped"] += 1

                # Migrate Layout Profiles
                layouts = prof.get("layout_profiles", {})
                for l_id, l_prof in layouts.items():
                    cursor.execute("SELECT id FROM supplier_layout_profiles WHERE supplier_id = ? AND layout_id = ?;", (supplier_id, l_id))
                    existing_layout = cursor.fetchone()

                    if existing_layout is None:
                        cursor.execute("""
                            INSERT INTO supplier_layout_profiles (
                                supplier_id, layout_id, layout_version, layout_signature,
                                header_sequence_json, logical_column_count, relative_positions_json,
                                semantic_mapping_json, field_reliability_json, multi_value_patterns_json,
                                known_optional_fields_json, known_required_fields_json, profile_confidence,
                                successful_document_count, review_count, failure_count, layout_status,
                                is_active, created_at, updated_at, last_seen
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                        """, (
                            supplier_id,
                            l_id,
                            int(l_prof.get("layout_version", 1)),
                            l_prof.get("layout_signature", ""),
                            json.dumps(l_prof.get("header_sequence", [])),
                            int(l_prof.get("logical_column_count", len(l_prof.get("header_sequence", [])))),
                            json.dumps(l_prof.get("relative_column_positions", [])),
                            json.dumps(l_prof.get("semantic_mapping", {})),
                            json.dumps(l_prof.get("field_reliability", {})),
                            json.dumps(l_prof.get("multi_value_patterns", {})),
                            json.dumps(l_prof.get("known_optional_fields", ["hsnCode", "discountPercent", "freeQuantity"])),
                            json.dumps(l_prof.get("known_required_fields", ["itemName", "quantity", "rate", "amount"])),
                            float(l_prof.get("profile_confidence", 0.90)),
                            int(l_prof.get("successful_document_count", 1)),
                            int(l_prof.get("review_count", 0)),
                            int(l_prof.get("failure_count", 0)),
                            l_prof.get("layout_status", "ACTIVE"),
                            1,
                            l_prof.get("created_at", now_iso),
                            l_prof.get("updated_at", now_iso),
                            l_prof.get("last_seen", now_iso),
                        ))
                        report["layouts_imported"] += 1
                    else:
                        report["records_skipped"] += 1

            except Exception as e:
                report["conflicts"] += 1
                report["errors"].append(f"Error migrating supplier {sup_key}: {e}")

        conn.commit()
    except Exception as e:
        conn.rollback()
        report["errors"].append(f"Transaction failure: {e}")
    finally:
        conn.close()

    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Migrate supplier profiles from JSON to SQLite.")
    parser.add_argument("--json-path", default=os.path.join(PROJECT_ROOT, "supplier_profiles.json"))
    parser.add_argument("--templates-path", default=os.path.join(PROJECT_ROOT, "templates.json"))
    parser.add_argument("--db-path", default=None)
    args = parser.parse_args()

    res = run_migration(args.json_path, args.templates_path, args.db_path)
    print("=" * 60)
    print("JSON TO SQLITE MIGRATION REPORT")
    print("=" * 60)
    print(f"Suppliers Imported: {res['suppliers_imported']}")
    print(f"Layouts Imported:   {res['layouts_imported']}")
    print(f"Records Skipped:    {res['records_skipped']}")
    print(f"Conflicts:          {res['conflicts']}")
    print(f"Errors:             {len(res['errors'])}")
    if res["errors"]:
        for err in res["errors"]:
            print(f"  - {err}")
    print("=" * 60)
