"""
MediAstra Pharma PDF Purchase Import Engine - Storage Service and Repositories
"""
import json
import logging
import re
from contextlib import contextmanager
from datetime import datetime
from typing import Optional, List, Dict, Any, Tuple

from .database import get_db_connection, init_db, ProfileVersionConflictError
from .models import (
    Supplier,
    SupplierLayoutProfile,
    InvoiceDocument,
    ExtractionRun,
    ReviewSessionRecord,
    AuditEvent,
    StockInventoryItem,
    StockMovement,
    PharmacyMasterItem,
    ProductAlias,
)

logger = logging.getLogger(__name__)


def clean_text_helper(text: str) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", " ", str(text)).strip()


class StorageService:
    """
    Authoritative storage service implementing clean abstractions for suppliers,
    layout profiles, invoice documents, extraction runs, review sessions, and audit logging.
    """

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path
        init_db(self.db_path)

    @contextmanager
    def get_connection(self):
        conn = get_db_connection(self.db_path)
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    # --------------------------------------------------------------------------
    # 1. SUPPLIER REPOSITORY METHODS
    # --------------------------------------------------------------------------

    def get_supplier_by_id(self, supplier_id: int) -> Optional[Supplier]:
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM suppliers WHERE id = ?;", (supplier_id,))
            row = cursor.fetchone()
            if not row:
                return None
            return Supplier(
                id=row["id"],
                supplier_key=row["supplier_key"],
                supplier_name=row["supplier_name"],
                gstin=row["gstin"],
                normalized_name=row["normalized_name"],
                identity_status=row["identity_status"],
                profile_version=row["profile_version"],
                profile_confidence=row["profile_confidence"],
                successful_document_count=row["successful_document_count"],
                reviewed_document_count=row["reviewed_document_count"],
                failure_document_count=row["failure_document_count"],
                is_active=bool(row["is_active"]),
                last_seen=row["last_seen"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )

    def find_supplier_by_key(self, supplier_key: str) -> Optional[Supplier]:
        if not supplier_key:
            return None
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM suppliers WHERE supplier_key = ?;", (supplier_key,))
            row = cursor.fetchone()
            if not row:
                # Case-insensitive / normalized search
                norm = clean_text_helper(supplier_key).upper()
                cursor.execute("SELECT * FROM suppliers WHERE UPPER(supplier_key) = ? OR UPPER(gstin) = ? OR normalized_name = ?;", (norm, norm, norm))
                row = cursor.fetchone()
            if not row:
                return None
            return Supplier(
                id=row["id"],
                supplier_key=row["supplier_key"],
                supplier_name=row["supplier_name"],
                gstin=row["gstin"],
                normalized_name=row["normalized_name"],
                identity_status=row["identity_status"],
                profile_version=row["profile_version"],
                profile_confidence=row["profile_confidence"],
                successful_document_count=row["successful_document_count"],
                reviewed_document_count=row["reviewed_document_count"],
                failure_document_count=row["failure_document_count"],
                is_active=bool(row["is_active"]),
                last_seen=row["last_seen"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )

    def find_supplier_by_gstin(self, gstin: str) -> Optional[Supplier]:
        if not gstin:
            return None
        clean_gstin = re.sub(r"[^A-Z0-9]", "", str(gstin).upper().strip())
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM suppliers WHERE gstin = ?;", (clean_gstin,))
            row = cursor.fetchone()
            if not row:
                return None
            return Supplier(
                id=row["id"],
                supplier_key=row["supplier_key"],
                supplier_name=row["supplier_name"],
                gstin=row["gstin"],
                normalized_name=row["normalized_name"],
                identity_status=row["identity_status"],
                profile_version=row["profile_version"],
                profile_confidence=row["profile_confidence"],
                successful_document_count=row["successful_document_count"],
                reviewed_document_count=row["reviewed_document_count"],
                failure_document_count=row["failure_document_count"],
                is_active=bool(row["is_active"]),
                last_seen=row["last_seen"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )

    def find_supplier_by_identity(self, supplier_key: str, gstin: Optional[str] = None, name: Optional[str] = None) -> Optional[Supplier]:
        if gstin:
            sup = self.find_supplier_by_gstin(gstin)
            if sup:
                return sup
        if supplier_key:
            sup = self.find_supplier_by_key(supplier_key)
            if sup:
                return sup
        if name:
            norm_name = clean_text_helper(name).upper()
            with self.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM suppliers WHERE normalized_name = ?;", (norm_name,))
                row = cursor.fetchone()
                if row:
                    return Supplier(
                        id=row["id"],
                        supplier_key=row["supplier_key"],
                        supplier_name=row["supplier_name"],
                        gstin=row["gstin"],
                        normalized_name=row["normalized_name"],
                        identity_status=row["identity_status"],
                        profile_version=row["profile_version"],
                        profile_confidence=row["profile_confidence"],
                        successful_document_count=row["successful_document_count"],
                        reviewed_document_count=row["reviewed_document_count"],
                        failure_document_count=row["failure_document_count"],
                        is_active=bool(row["is_active"]),
                        last_seen=row["last_seen"],
                        created_at=row["created_at"],
                        updated_at=row["updated_at"],
                    )
        return None

    def get_or_create_supplier(self, supplier_name: str, gstin: Optional[str] = None) -> Supplier:
        key = gstin or supplier_name or "UNKNOWN"
        existing = self.find_supplier_by_identity(key, gstin=gstin, name=supplier_name)
        if existing:
            return existing

        now_iso = datetime.now().isoformat()
        norm_name = clean_text_helper(supplier_name).upper()
        clean_gstin = re.sub(r"[^A-Z0-9]", "", str(gstin).upper().strip()) if gstin else None

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO suppliers (
                    supplier_key, supplier_name, gstin, normalized_name,
                    identity_status, profile_version, profile_confidence,
                    successful_document_count, reviewed_document_count, failure_document_count,
                    is_active, last_seen, created_at, updated_at
                ) VALUES (?, ?, ?, ?, 'VERIFIED', 1, 1.0, 0, 0, 0, 1, ?, ?, ?);
            """, (key, supplier_name, clean_gstin, norm_name, now_iso, now_iso, now_iso))
            sup_id = cursor.lastrowid
            return Supplier(
                id=sup_id,
                supplier_key=key,
                supplier_name=supplier_name,
                gstin=clean_gstin,
                normalized_name=norm_name,
                identity_status="VERIFIED",
                created_at=now_iso,
                updated_at=now_iso,
            )

    # --------------------------------------------------------------------------
    # 2. LAYOUT PROFILE REPOSITORY METHODS
    # --------------------------------------------------------------------------

    def get_layout_profiles_for_supplier(self, supplier_id: int) -> List[SupplierLayoutProfile]:
        layouts = []
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM supplier_layout_profiles WHERE supplier_id = ? AND is_active = 1 ORDER BY layout_version ASC;", (supplier_id,))
            for row in cursor.fetchall():
                layouts.append(SupplierLayoutProfile(
                    id=row["id"],
                    supplier_id=row["supplier_id"],
                    layout_id=row["layout_id"],
                    layout_version=row["layout_version"],
                    layout_signature=row["layout_signature"],
                    header_sequence=json.loads(row["header_sequence_json"]),
                    logical_column_count=row["logical_column_count"],
                    relative_column_positions=json.loads(row["relative_positions_json"]),
                    semantic_mapping=json.loads(row["semantic_mapping_json"]),
                    field_reliability=json.loads(row["field_reliability_json"]),
                    multi_value_patterns=json.loads(row["multi_value_patterns_json"]),
                    known_optional_fields=json.loads(row["known_optional_fields_json"]),
                    known_required_fields=json.loads(row["known_required_fields_json"]),
                    profile_confidence=row["profile_confidence"],
                    successful_document_count=row["successful_document_count"],
                    review_count=row["review_count"],
                    failure_count=row["failure_count"],
                    layout_status=row["layout_status"],
                    is_active=bool(row["is_active"]),
                    created_at=row["created_at"],
                    updated_at=row["updated_at"],
                    last_seen=row["last_seen"],
                ))
        return layouts

    # --------------------------------------------------------------------------
    # 3. LEGACY COMPATIBILITY DICTIONARY EXPORT
    # --------------------------------------------------------------------------

    def export_supplier_profiles_dict(self) -> Dict[str, Any]:
        """
        Exports current SQLite state to rich profile dictionary structure
        compatible with Prompt 7-9 matching algorithms and tests.
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM suppliers WHERE is_active = 1;")
            sup_rows = cursor.fetchall()
            
            profiles = {}
            for s_row in sup_rows:
                s_id = s_row["id"]
                s_key = s_row["supplier_key"]
                
                cursor.execute("SELECT * FROM supplier_layout_profiles WHERE supplier_id = ? AND is_active = 1;", (s_id,))
                layout_rows = cursor.fetchall()
                
                layouts_dict = {}
                for l_row in layout_rows:
                    l_id = l_row["layout_id"]
                    layouts_dict[l_id] = {
                        "layout_id": l_id,
                        "layout_version": l_row["layout_version"],
                        "layout_signature": l_row["layout_signature"],
                        "header_sequence": json.loads(l_row["header_sequence_json"]),
                        "logical_column_count": l_row["logical_column_count"],
                        "relative_column_positions": json.loads(l_row["relative_positions_json"]),
                        "semantic_mapping": json.loads(l_row["semantic_mapping_json"]),
                        "field_reliability": json.loads(l_row["field_reliability_json"]),
                        "multi_value_patterns": json.loads(l_row["multi_value_patterns_json"]),
                        "known_optional_fields": json.loads(l_row["known_optional_fields_json"]),
                        "known_required_fields": json.loads(l_row["known_required_fields_json"]),
                        "profile_confidence": l_row["profile_confidence"],
                        "successful_document_count": l_row["successful_document_count"],
                        "review_count": l_row["review_count"],
                        "failure_count": l_row["failure_count"],
                        "layout_status": l_row["layout_status"],
                        "review_history": [],
                        "created_at": l_row["created_at"],
                        "updated_at": l_row["updated_at"],
                        "last_seen": l_row["last_seen"],
                    }

                profiles[s_key] = {
                    "supplier_identity": s_key,
                    "supplier_key": s_key,
                    "supplier_name": s_row["supplier_name"],
                    "gstin": s_row["gstin"],
                    "profile_version": s_row["profile_version"],
                    "profile_confidence": s_row["profile_confidence"],
                    "successful_document_count": s_row["successful_document_count"],
                    "reviewed_document_count": s_row["reviewed_document_count"],
                    "failure_document_count": s_row["failure_document_count"],
                    "last_seen": s_row["last_seen"],
                    "layout_profiles": layouts_dict,
                }
            
            # Global version can be max profile_version or supplier count
            max_v = max([p["profile_version"] for p in profiles.values()], default=1)
            return {"version": max_v, "profiles": profiles}

    # --------------------------------------------------------------------------
    # 4. TRANSACTIONAL PROFILE MEMORY UPDATE WITH OPTIMISTIC LOCKING
    # --------------------------------------------------------------------------

    def save_or_update_supplier_profile_memory(
        self,
        supplier_key: str,
        supplier_name: Optional[str],
        gstin: Optional[str],
        headers: List[str],
        logical_columns: List[Dict[str, Any]],
        resolved_mappings: Dict[str, Any],
        rows: List[List[Any]],
        validation_result: Dict[str, Any],
        is_user_reviewed: bool = False,
        expected_version: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Atomically updates or creates supplier and layout records in SQLite.
        Enforces optimistic concurrency version checking and audit logging.
        """
        # 1. Validation Gate
        doc_conf = validation_result.get("document_confidence", 0.0)
        classification = validation_result.get("classification", "UNRESOLVED")
        critical_mismatches = validation_result.get("accounting_summary", {}).get("critical_mismatches", 0)

        is_safe_auto_accept = (classification == "AUTO_ACCEPT" and doc_conf >= 80.0 and critical_mismatches == 0)
        if not is_user_reviewed and not is_safe_auto_accept:
            return {
                "updated": False,
                "reason": f"Validation gate not passed (Classification: {classification}, Confidence: {doc_conf:.1f}%, Critical Errors: {critical_mismatches}).",
            }

        if not supplier_key:
            supplier_key = supplier_name or gstin
        if not supplier_key:
            return {"updated": False, "reason": "No valid supplier identifier (GSTIN or Name)."}

        clean_gstin = re.sub(r"[^A-Z0-9]", "", str(gstin or "").upper().strip()) if gstin else None
        norm_name = clean_text_helper(supplier_name or "").upper() if supplier_name else None
        now_iso = datetime.now().isoformat()

        # Build flat mapping
        flat_mapping = {}
        for h in headers:
            m = resolved_mappings.get(h, {})
            flat_mapping[h] = m.get("mapped_to")

        # Field reliability data
        field_rel = {}
        for h, m_info in resolved_mappings.items():
            f = m_info.get("mapped_to")
            if f:
                field_rel[f] = {
                    "observed_count": 1,
                    "algorithm_confirmed_count": 0 if is_user_reviewed else 1,
                    "human_confirmed_count": 1 if is_user_reviewed else 0,
                    "inferred_count": 1 if m_info.get("status") == "inferred" else 0,
                    "contradiction_count": 0,
                    "review_correction_count": 1 if is_user_reviewed else 0,
                    "reliability_score": 1.0,
                }

        # Calculate layout signature
        clean_hdrs = [clean_text_helper(h) for h in headers]
        sig_str = "|".join(clean_hdrs) + f"_{len(clean_hdrs)}"
        import hashlib
        sig_hash = hashlib.sha256(sig_str.encode("utf-8")).hexdigest()[:16]

        conn = self.get_connection()
        try:
            conn.execute("BEGIN TRANSACTION;")
            cursor = conn.cursor()

            # Find supplier by GSTIN or supplier_key or normalized name
            cursor.execute("SELECT * FROM suppliers WHERE supplier_key = ? OR (gstin IS NOT NULL AND gstin = ?);", (supplier_key, clean_gstin or ""))
            sup_row = cursor.fetchone()

            if sup_row is None:
                # Brand new supplier
                cursor.execute("""
                    INSERT INTO suppliers (
                        supplier_key, supplier_name, gstin, normalized_name, identity_status,
                        profile_version, profile_confidence, successful_document_count,
                        reviewed_document_count, failure_document_count, is_active,
                        last_seen, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """, (
                    supplier_key,
                    supplier_name,
                    clean_gstin,
                    norm_name,
                    "EXACT_GSTIN" if clean_gstin else "VERIFIED_NAME",
                    1,
                    round(doc_conf / 100.0, 2),
                    1,
                    1 if is_user_reviewed else 0,
                    0,
                    1,
                    now_iso,
                    now_iso,
                    now_iso,
                ))
                supplier_id = cursor.lastrowid
                layout_id = f"layout_v1_{sig_hash}"

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
                    layout_id,
                    1,
                    sig_hash,
                    json.dumps(headers),
                    len(headers),
                    json.dumps([]),
                    json.dumps(flat_mapping),
                    json.dumps(field_rel),
                    json.dumps({}),
                    json.dumps(["hsnCode", "discountPercent", "freeQuantity"]),
                    json.dumps(["itemName", "quantity", "rate", "amount"]),
                    round(doc_conf / 100.0, 2),
                    1,
                    1 if is_user_reviewed else 0,
                    0,
                    "ACTIVE",
                    1,
                    now_iso,
                    now_iso,
                    now_iso,
                ))
                layout_pk = cursor.lastrowid

                # Audit record
                cursor.execute("""
                    INSERT INTO audit_events (event_type, entity_type, entity_id, supplier_id, layout_profile_id, event_data_json, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?);
                """, (
                    "PROFILE_CREATED",
                    "supplier",
                    str(supplier_id),
                    supplier_id,
                    layout_pk,
                    json.dumps({"supplier_key": supplier_key, "layout_id": layout_id, "action": "NEW_SUPPLIER_PROFILE_CREATED"}),
                    now_iso,
                ))

                conn.commit()
                return {
                    "updated": True,
                    "action": "NEW_SUPPLIER_PROFILE_CREATED",
                    "layout_id": layout_id,
                    "supplier_key": supplier_key,
                    "supplier_id": supplier_id,
                }

            # Supplier exists -> Optimistic version check
            current_version = sup_row["profile_version"]
            supplier_id = sup_row["id"]

            if expected_version is not None and current_version != expected_version:
                conn.rollback()
                logger.warning(f"PROFILE_VERSION_CONFLICT: Supplier {supplier_key} current version {current_version} != expected {expected_version}")
                return {
                    "updated": False,
                    "reason": "PROFILE_VERSION_CONFLICT",
                    "conflict": True,
                    "current_version": current_version,
                }

            # Increment supplier version and update counters
            new_version = current_version + 1
            cursor.execute("""
                UPDATE suppliers SET
                    profile_version = ?,
                    successful_document_count = successful_document_count + 1,
                    reviewed_document_count = reviewed_document_count + ?,
                    last_seen = ?,
                    updated_at = ?
                WHERE id = ?;
            """, (new_version, 1 if is_user_reviewed else 0, now_iso, now_iso, supplier_id))

            # Check existing layout profiles for this supplier
            cursor.execute("SELECT * FROM supplier_layout_profiles WHERE supplier_id = ? AND is_active = 1;", (supplier_id,))
            layouts = cursor.fetchall()

            # Find matching layout
            matched_layout = None
            for l_row in layouts:
                if l_row["layout_signature"] == sig_hash:
                    matched_layout = l_row
                    break
                hist_headers = json.loads(l_row["header_sequence_json"])
                # Jaccard + sequence alignment
                clean_hist = [clean_text_helper(h) for h in hist_headers]
                if clean_hist == clean_hdrs:
                    matched_layout = l_row
                    break

            if matched_layout:
                # Update existing layout
                l_id = matched_layout["layout_id"]
                l_pk = matched_layout["id"]
                existing_rel = json.loads(matched_layout["field_reliability_json"])
                existing_mapping = json.loads(matched_layout["semantic_mapping_json"])

                if is_user_reviewed:
                    existing_mapping.update(flat_mapping)

                for f, rel_data in field_rel.items():
                    if f in existing_rel:
                        cur_f = existing_rel[f]
                        cur_f["observed_count"] = cur_f.get("observed_count", 0) + 1
                        if is_user_reviewed:
                            cur_f["human_confirmed_count"] = cur_f.get("human_confirmed_count", 0) + 1
                            cur_f["review_correction_count"] = cur_f.get("review_correction_count", 0) + 1
                        else:
                            cur_f["algorithm_confirmed_count"] = cur_f.get("algorithm_confirmed_count", 0) + 1
                    else:
                        existing_rel[f] = rel_data

                cursor.execute("""
                    UPDATE supplier_layout_profiles SET
                        successful_document_count = successful_document_count + 1,
                        review_count = review_count + ?,
                        semantic_mapping_json = ?,
                        field_reliability_json = ?,
                        last_seen = ?,
                        updated_at = ?
                    WHERE id = ?;
                """, (
                    1 if is_user_reviewed else 0,
                    json.dumps(existing_mapping),
                    json.dumps(existing_rel),
                    now_iso,
                    now_iso,
                    l_pk,
                ))

                cursor.execute("""
                    INSERT INTO audit_events (event_type, entity_type, entity_id, supplier_id, layout_profile_id, event_data_json, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?);
                """, (
                    "PROFILE_UPDATED",
                    "layout_profile",
                    str(l_pk),
                    supplier_id,
                    l_pk,
                    json.dumps({"supplier_key": supplier_key, "layout_id": l_id, "action": "LAYOUT_PROFILE_UPDATED"}),
                    now_iso,
                ))

                conn.commit()
                return {
                    "updated": True,
                    "action": "LAYOUT_PROFILE_UPDATED",
                    "layout_id": l_id,
                    "supplier_key": supplier_key,
                    "supplier_id": supplier_id,
                }
            else:
                # Create brand new layout version (layout_v2, layout_v3) preserving previous!
                version_num = len(layouts) + 1
                new_layout_id = f"layout_v{version_num}_{sig_hash}"

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
                    new_layout_id,
                    version_num,
                    sig_hash,
                    json.dumps(headers),
                    len(headers),
                    json.dumps([]),
                    json.dumps(flat_mapping),
                    json.dumps(field_rel),
                    json.dumps({}),
                    json.dumps(["hsnCode", "discountPercent", "freeQuantity"]),
                    json.dumps(["itemName", "quantity", "rate", "amount"]),
                    round(doc_conf / 100.0, 2),
                    1,
                    1 if is_user_reviewed else 0,
                    0,
                    "ACTIVE",
                    1,
                    now_iso,
                    now_iso,
                    now_iso,
                ))
                new_l_pk = cursor.lastrowid

                cursor.execute("""
                    INSERT INTO audit_events (event_type, entity_type, entity_id, supplier_id, layout_profile_id, event_data_json, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?);
                """, (
                    "LAYOUT_VERSION_CREATED",
                    "layout_profile",
                    str(new_l_pk),
                    supplier_id,
                    new_l_pk,
                    json.dumps({"supplier_key": supplier_key, "layout_id": new_layout_id, "version": version_num}),
                    now_iso,
                ))

                conn.commit()
                return {
                    "updated": True,
                    "action": "NEW_LAYOUT_VERSION_CREATED",
                    "layout_id": new_layout_id,
                    "supplier_key": supplier_key,
                    "supplier_id": supplier_id,
                }
        except Exception as e:
            conn.rollback()
            logger.error(f"Transaction error in save_or_update_supplier_profile_memory: {e}")
            raise e
        finally:
            conn.close()

    # --------------------------------------------------------------------------
    # 5. DOCUMENT & EXTRACTION RUN REPOSITORY METHODS
    # --------------------------------------------------------------------------

    def register_document_and_run(
        self,
        filename: str,
        file_hash: str,
        file_size_bytes: int,
        metadata: Dict[str, Any],
        headers: List[str],
        logical_columns: List[Dict[str, Any]],
        column_mappings: Dict[str, Any],
        rows: List[List[Any]],
    ) -> Tuple[InvoiceDocument, ExtractionRun]:
        """
        Registers an invoice document by SHA-256 and records a new extraction run.
        If document already exists, logs an audit event and appends run without duplicating doc record.
        """
        now_iso = datetime.now().isoformat()
        sup_name = metadata.get("supplier_name")
        gstin = metadata.get("supplier_gstin")
        sup_key = gstin or sup_name
        identity_safety = metadata.get("identity_safety", {})
        doc_status = metadata.get("classification", metadata.get("decision", "RECEIVED"))
        conf = float(metadata.get("confidence", 0.0))

        conn = self.get_connection()
        try:
            conn.execute("BEGIN TRANSACTION;")
            cursor = conn.cursor()

            # Find or link supplier_id
            supplier_id = None
            if sup_key:
                sup = self.find_supplier_by_identity(sup_key, gstin=gstin, name=sup_name)
                if sup:
                    supplier_id = sup.id

            # 1. Check if document exists
            cursor.execute("SELECT * FROM invoice_documents WHERE file_hash = ?;", (file_hash,))
            doc_row = cursor.fetchone()

            if doc_row is None:
                cursor.execute("""
                    INSERT INTO invoice_documents (
                        original_filename, file_hash, file_size_bytes, supplier_id, supplier_key,
                        supplier_identity_status, supplier_confidence, document_status,
                        extraction_decision, extraction_confidence, engine_version, created_at, processed_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """, (
                    filename,
                    file_hash,
                    file_size_bytes,
                    supplier_id,
                    sup_key,
                    identity_safety.get("status", "UNKNOWN"),
                    float(metadata.get("supplier_confidence", 1.0) or 1.0),
                    doc_status,
                    doc_status,
                    conf,
                    "v1.0",
                    now_iso,
                    now_iso,
                ))
                doc_id = cursor.lastrowid
                run_number = 1
            else:
                doc_id = doc_row["id"]
                # Update document status and processed timestamp
                cursor.execute("""
                    UPDATE invoice_documents SET
                        document_status = ?,
                        extraction_decision = ?,
                        extraction_confidence = ?,
                        processed_at = ?
                    WHERE id = ?;
                """, (doc_status, doc_status, conf, now_iso, doc_id))

                # Find run number
                cursor.execute("SELECT COUNT(*) as cnt FROM extraction_runs WHERE document_id = ?;", (doc_id,))
                run_number = cursor.fetchone()["cnt"] + 1

                # Audit duplicate processing
                cursor.execute("""
                    INSERT INTO audit_events (event_type, entity_type, entity_id, supplier_id, event_data_json, created_at)
                    VALUES (?, ?, ?, ?, ?, ?);
                """, (
                    "DUPLICATE_DOCUMENT_RECEIVED",
                    "invoice_document",
                    str(doc_id),
                    supplier_id,
                    json.dumps({"filename": filename, "file_hash": file_hash, "run_number": run_number}),
                    now_iso,
                ))

            # 2. Record Extraction Run
            cursor.execute("""
                INSERT INTO extraction_runs (
                    document_id, run_number, engine_version, extraction_method, confidence,
                    decision, headers_json, logical_columns_json, column_mappings_json,
                    accounting_summary_json, row_count, started_at, completed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """, (
                doc_id,
                run_number,
                "v1.0",
                "coordinate_layout_v1",
                conf,
                doc_status,
                json.dumps(headers),
                json.dumps(logical_columns),
                json.dumps({k: v.get("mapped_to") for k, v in column_mappings.items() if v.get("mapped_to")}),
                json.dumps(metadata.get("validation", {}).get("accounting_summary", {})),
                len(rows),
                now_iso,
                now_iso,
            ))
            run_id = cursor.lastrowid

            conn.commit()

            doc = InvoiceDocument(
                id=doc_id,
                original_filename=filename,
                file_hash=file_hash,
                file_size_bytes=file_size_bytes,
                supplier_id=supplier_id,
                supplier_key=sup_key,
                supplier_identity_status=identity_safety.get("status", "UNKNOWN"),
                supplier_confidence=float(metadata.get("supplier_confidence", 1.0) or 1.0),
                document_status=doc_status,
                extraction_decision=doc_status,
                extraction_confidence=conf,
                created_at=now_iso,
                processed_at=now_iso,
            )

            run = ExtractionRun(
                id=run_id,
                document_id=doc_id,
                run_number=run_number,
                confidence=conf,
                decision=doc_status,
                row_count=len(rows),
                started_at=now_iso,
                completed_at=now_iso,
            )

            return doc, run
        except Exception as e:
            conn.rollback()
            logger.error(f"Error registering document and run: {e}")
            raise e
        finally:
            conn.close()

    # --------------------------------------------------------------------------
    # 6. REVIEW SESSION REPOSITORY METHODS
    # --------------------------------------------------------------------------

    def save_review_session_record(self, review_session: Dict[str, Any]) -> int:
        """Persists a human review session record to SQLite."""
        now_iso = datetime.now().isoformat()
        rev_id = review_session.get("review_id", f"rev_{now_iso}")
        sup_key = review_session.get("supplier_identity") or review_session.get("supplier_name") or review_session.get("gstin")
        
        supplier_id = None
        if sup_key:
            sup = self.find_supplier_by_identity(sup_key, gstin=review_session.get("gstin"), name=review_session.get("supplier_name"))
            if sup:
                supplier_id = sup.id

        conn = self.get_connection()
        try:
            conn.execute("BEGIN TRANSACTION;")
            cursor = conn.cursor()

            cursor.execute("""
                INSERT OR REPLACE INTO review_sessions (
                    review_session_id, supplier_id, original_decision, original_confidence,
                    original_headers_json, logical_columns_json, original_mappings_json,
                    original_rows_json, corrections_json, validated_result_json,
                    review_status, reviewed_by, reviewed_at, is_committed_to_profile, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """, (
                rev_id,
                supplier_id,
                review_session.get("original_decision", "REVIEW_REQUIRED"),
                float(review_session.get("original_confidence", 0.0)),
                json.dumps(review_session.get("original_headers", [])),
                json.dumps(review_session.get("logical_columns", [])),
                json.dumps(review_session.get("original_semantic_mapping", {})),
                json.dumps(review_session.get("original_rows", [])),
                json.dumps(review_session.get("corrections", [])),
                json.dumps(review_session.get("validated_result") or {}),
                review_session.get("review_status", "PENDING_REVIEW"),
                review_session.get("reviewed_by"),
                review_session.get("reviewed_at"),
                1 if review_session.get("profile_update_status") == "UPDATED" else 0,
                now_iso,
            ))
            session_pk = cursor.lastrowid

            cursor.execute("""
                INSERT INTO audit_events (event_type, entity_type, entity_id, supplier_id, event_data_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?);
            """, (
                "REVIEW_COMMITTED" if review_session.get("profile_update_status") == "UPDATED" else "MAPPING_CORRECTION",
                "review_session",
                rev_id,
                supplier_id,
                json.dumps({
                    "review_id": rev_id,
                    "corrections_count": len(review_session.get("corrections", [])),
                    "status": review_session.get("review_status"),
                }),
                now_iso,
            ))

            conn.commit()
            return session_pk
        except Exception as e:
            conn.rollback()
            logger.error(f"Error saving review session: {e}")
            raise e
        finally:
            conn.close()

    # --------------------------------------------------------------------------
    # 7. AUDIT TRAIL QUERY
    # --------------------------------------------------------------------------

    def get_audit_events_for_supplier(self, supplier_id: int) -> List[AuditEvent]:
        events = []
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM audit_events WHERE supplier_id = ? ORDER BY id ASC;", (supplier_id,))
            for row in cursor.fetchall():
                events.append(AuditEvent(
                    id=row["id"],
                    event_type=row["event_type"],
                    entity_type=row["entity_type"],
                    entity_id=row["entity_id"],
                    supplier_id=row["supplier_id"],
                    layout_profile_id=row["layout_profile_id"],
                    event_data=json.loads(row["event_data_json"]),
                    created_at=row["created_at"],
                ))
        return events

    # --------------------------------------------------------------------------
    # 8. STOCK INVENTORY & BATCH MASTER REPOSITORY METHODS
    # --------------------------------------------------------------------------

    def ingest_stock_payload(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Atomically updates the local/cloud pharmacy stock inventory and records stock movements
        from a canonical invoice payload (handling billed + free quantities and return deductions).
        """
        supplier_info = payload.get("supplier", {})
        invoice_info = payload.get("invoice", {})
        stock_items = payload.get("stock_update_items", [])
        returns = payload.get("returns_adjusted", [])

        supplier_name = supplier_info.get("name") or "UNKNOWN"
        supplier_gstin = supplier_info.get("gstin")
        invoice_no = invoice_info.get("invoice_no") or "UNKNOWN"
        invoice_date = invoice_info.get("invoice_date") or datetime.now().strftime("%Y-%m-%d")
        now_iso = datetime.now().isoformat()

        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Find supplier ID if present
            supplier_id = None
            if supplier_gstin:
                cursor.execute("SELECT id FROM suppliers WHERE gstin = ?;", (supplier_gstin,))
                sup_row = cursor.fetchone()
                if sup_row:
                    supplier_id = sup_row["id"]

            items_updated = 0
            total_stock_added = 0.0

            for it in stock_items:
                prod_name = clean_text_helper(it.get("product_name") or "")
                if not prod_name:
                    continue

                pack = clean_text_helper(it.get("pack") or "")
                batch_no = clean_text_helper(it.get("batch_no") or "")
                exp_date = clean_text_helper(it.get("expiry_date") or "")
                hsn = clean_text_helper(it.get("hsn_code") or "")
                billed_qty = float(it.get("billed_quantity") or 0.0)
                free_qty = float(it.get("free_quantity") or 0.0)
                total_qty = float(it.get("total_received_stock") or (billed_qty + free_qty))
                mrp = float(it.get("mrp") or 0.0)
                ptr_rate = float(it.get("ptr_rate") or 0.0)
                disc_pct = float(it.get("discount_percent") or 0.0)
                gst_pct = float(it.get("gst_percent") or 0.0)
                net_amt = float(it.get("line_net_amount") or 0.0)

                # Check if item exists in stock inventory
                cursor.execute("""
                    SELECT id, current_stock_qty FROM stock_inventory
                    WHERE product_name = ? AND pack = ? AND batch_no = ?;
                """, (prod_name, pack, batch_no))
                existing = cursor.fetchone()

                if existing:
                    item_id = existing["id"]
                    new_stock = existing["current_stock_qty"] + total_qty
                    cursor.execute("""
                        UPDATE stock_inventory
                        SET current_stock_qty = ?,
                            mrp = ?,
                            ptr_rate = ?,
                            discount_percent = ?,
                            gst_percent = ?,
                            expiry_date = ?,
                            hsn_code = ?,
                            supplier_id = COALESCE(?, supplier_id),
                            supplier_name = COALESCE(?, supplier_name),
                            last_invoice_no = ?,
                            last_received_date = ?,
                            updated_at = ?
                        WHERE id = ?;
                    """, (new_stock, mrp, ptr_rate, disc_pct, gst_pct, exp_date, hsn,
                          supplier_id, supplier_name, invoice_no, invoice_date, now_iso, item_id))
                else:
                    cursor.execute("""
                        INSERT INTO stock_inventory (
                            product_name, pack, batch_no, expiry_date, hsn_code,
                            current_stock_qty, mrp, ptr_rate, discount_percent, gst_percent,
                            supplier_id, supplier_name, last_invoice_no, last_received_date,
                            created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """, (prod_name, pack, batch_no, exp_date, hsn,
                          total_qty, mrp, ptr_rate, disc_pct, gst_pct,
                          supplier_id, supplier_name, invoice_no, invoice_date,
                          now_iso, now_iso))
                    item_id = cursor.lastrowid

                # Record stock movement
                cursor.execute("""
                    INSERT INTO stock_movements (
                        stock_item_id, invoice_no, movement_type, billed_qty, free_qty, total_qty, rate, net_amount, created_at
                    ) VALUES (?, ?, 'PURCHASE_RECEIPT', ?, ?, ?, ?, ?, ?);
                """, (item_id, invoice_no, billed_qty, free_qty, total_qty, ptr_rate, net_amt, now_iso))

                items_updated += 1
                total_stock_added += total_qty

            # Handle return deductions
            returns_count = 0
            for ret in returns:
                ret_name = clean_text_helper(ret.get("product_name") or ret.get("itemName") or "")
                ret_batch = clean_text_helper(ret.get("batch_no") or ret.get("batchNo") or "")
                ret_qty = float(ret.get("return_qty") or ret.get("quantity") or 0.0)

                if ret_name and ret_qty > 0:
                    cursor.execute("""
                        SELECT id, current_stock_qty FROM stock_inventory
                        WHERE product_name = ? AND (batch_no = ? OR ? = '');
                    """, (ret_name, ret_batch, ret_batch))
                    existing = cursor.fetchone()
                    if existing:
                        item_id = existing["id"]
                        deducted_stock = max(0.0, existing["current_stock_qty"] - ret_qty)
                        cursor.execute("""
                            UPDATE stock_inventory
                            SET current_stock_qty = ?, updated_at = ?
                            WHERE id = ?;
                        """, (deducted_stock, now_iso, item_id))
                        cursor.execute("""
                            INSERT INTO stock_movements (
                                stock_item_id, invoice_no, movement_type, billed_qty, free_qty, total_qty, rate, net_amount, created_at
                            ) VALUES (?, ?, 'RETURN_DEDUCTION', ?, 0, ?, 0, 0, ?);
                        """, (item_id, invoice_no, ret_qty, -ret_qty, now_iso))
                        returns_count += 1

            return {
                "status": "SUCCESS",
                "invoice_no": invoice_no,
                "items_updated": items_updated,
                "total_stock_added": total_stock_added,
                "returns_adjusted": returns_count,
            }

    def get_stock_inventory(self, search: Optional[str] = None, limit: int = 200) -> List[StockInventoryItem]:
        items = []
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if search:
                term = f"%{clean_text_helper(search)}%"
                cursor.execute("""
                    SELECT * FROM stock_inventory
                    WHERE product_name LIKE ? OR batch_no LIKE ? OR hsn_code LIKE ?
                    ORDER BY product_name ASC LIMIT ?;
                """, (term, term, term, limit))
            else:
                cursor.execute("SELECT * FROM stock_inventory ORDER BY product_name ASC LIMIT ?;", (limit,))
            
            for row in cursor.fetchall():
                items.append(StockInventoryItem(
                    id=row["id"],
                    product_name=row["product_name"],
                    pack=row["pack"],
                    batch_no=row["batch_no"],
                    expiry_date=row["expiry_date"],
                    hsn_code=row["hsn_code"],
                    current_stock_qty=row["current_stock_qty"],
                    mrp=row["mrp"],
                    ptr_rate=row["ptr_rate"],
                    discount_percent=row["discount_percent"],
                    gst_percent=row["gst_percent"],
                    supplier_id=row["supplier_id"],
                    supplier_name=row["supplier_name"],
                    last_invoice_no=row["last_invoice_no"],
                    last_received_date=row["last_received_date"],
                    created_at=row["created_at"],
                    updated_at=row["updated_at"],
                ))
        return items

    def get_stock_movements(self, stock_item_id: Optional[int] = None, limit: int = 100) -> List[StockMovement]:
        movements = []
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if stock_item_id:
                cursor.execute("SELECT * FROM stock_movements WHERE stock_item_id = ? ORDER BY id DESC LIMIT ?;", (stock_item_id, limit))
            else:
                cursor.execute("SELECT * FROM stock_movements ORDER BY id DESC LIMIT ?;", (limit,))
            
            for row in cursor.fetchall():
                movements.append(StockMovement(
                    id=row["id"],
                    stock_item_id=row["stock_item_id"],
                    invoice_no=row["invoice_no"],
                    movement_type=row["movement_type"],
                    billed_qty=row["billed_qty"],
                    free_qty=row["free_qty"],
                    total_qty=row["total_qty"],
                    rate=row["rate"],
                    net_amount=row["net_amount"],
                    created_at=row["created_at"],
                ))
        return movements

    # --------------------------------------------------------------------------
    # 8. PHARMACY MASTER ITEMS & PRODUCT ALIAS REPOSITORIES
    # --------------------------------------------------------------------------

    def create_or_update_master_item(self, item: PharmacyMasterItem) -> PharmacyMasterItem:
        now_iso = datetime.now().isoformat()
        norm_name = clean_text_helper(item.item_name).upper()
        item.normalized_name = norm_name

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM pharmacy_master_items WHERE item_code = ?;", (item.item_code,))
            row = cursor.fetchone()

            if row:
                item_id = row["id"]
                cursor.execute("""
                    UPDATE pharmacy_master_items
                    SET item_name = ?,
                        normalized_name = ?,
                        pack = ?,
                        default_hsn = ?,
                        default_gst_percent = ?,
                        updated_at = ?
                    WHERE id = ?;
                """, (item.item_name, norm_name, item.pack, item.default_hsn, item.default_gst_percent, now_iso, item_id))
                item.id = item_id
                item.updated_at = now_iso
            else:
                cursor.execute("""
                    INSERT INTO pharmacy_master_items (
                        item_code, item_name, normalized_name, pack, default_hsn, default_gst_percent, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?);
                """, (item.item_code, item.item_name, norm_name, item.pack, item.default_hsn, item.default_gst_percent, now_iso, now_iso))
                item.id = cursor.lastrowid
                item.created_at = now_iso
                item.updated_at = now_iso
        return item

    def get_master_item_by_code(self, item_code: str) -> Optional[PharmacyMasterItem]:
        if not item_code:
            return None
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM pharmacy_master_items WHERE item_code = ?;", (item_code,))
            row = cursor.fetchone()
            if not row:
                return None
            return PharmacyMasterItem(
                id=row["id"],
                item_code=row["item_code"],
                item_name=row["item_name"],
                normalized_name=row["normalized_name"],
                pack=row["pack"],
                default_hsn=row["default_hsn"],
                default_gst_percent=row["default_gst_percent"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )

    def list_master_items(self, search: Optional[str] = None, limit: int = 100) -> List[PharmacyMasterItem]:
        items = []
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if search:
                term = f"%{clean_text_helper(search).upper()}%"
                cursor.execute("""
                    SELECT * FROM pharmacy_master_items
                    WHERE item_code LIKE ? OR normalized_name LIKE ? OR item_name LIKE ?
                    ORDER BY item_name ASC LIMIT ?;
                """, (term, term, term, limit))
            else:
                cursor.execute("SELECT * FROM pharmacy_master_items ORDER BY item_name ASC LIMIT ?;", (limit,))
            
            for row in cursor.fetchall():
                items.append(PharmacyMasterItem(
                    id=row["id"],
                    item_code=row["item_code"],
                    item_name=row["item_name"],
                    normalized_name=row["normalized_name"],
                    pack=row["pack"],
                    default_hsn=row["default_hsn"],
                    default_gst_percent=row["default_gst_percent"],
                    created_at=row["created_at"],
                    updated_at=row["updated_at"],
                ))
        return items

    def save_product_alias(self, alias: ProductAlias) -> ProductAlias:
        now_iso = datetime.now().isoformat()
        norm_alias = clean_text_helper(alias.raw_alias_text).upper()
        alias.normalized_alias = norm_alias

        with self.get_connection() as conn:
            cursor = conn.cursor()

            # Ensure supplier_id exists if provided
            eff_sup_id = alias.supplier_id
            if eff_sup_id:
                cursor.execute("SELECT id FROM suppliers WHERE id = ?;", (eff_sup_id,))
                if not cursor.fetchone():
                    eff_sup_id = None

            # Ensure master_item_id exists if provided
            eff_master_id = alias.master_item_id
            if eff_master_id:
                cursor.execute("SELECT id FROM pharmacy_master_items WHERE id = ?;", (eff_master_id,))
                if not cursor.fetchone():
                    eff_master_id = None

            # Check existing alias by supplier + raw_alias
            if eff_sup_id:
                cursor.execute("""
                    SELECT id, match_count FROM product_aliases
                    WHERE raw_alias_text = ? AND supplier_id = ?;
                """, (alias.raw_alias_text, eff_sup_id))
            else:
                cursor.execute("""
                    SELECT id, match_count FROM product_aliases
                    WHERE raw_alias_text = ? AND supplier_id IS NULL;
                """, (alias.raw_alias_text,))
            row = cursor.fetchone()

            if row:
                alias_id = row["id"]
                new_cnt = (row["match_count"] or 1) + 1
                cursor.execute("""
                    UPDATE product_aliases
                    SET master_item_id = ?,
                        master_item_code = ?,
                        master_item_name = ?,
                        match_count = ?,
                        confidence = ?,
                        updated_at = ?
                    WHERE id = ?;
                """, (eff_master_id, alias.master_item_code, alias.master_item_name, new_cnt, alias.confidence, now_iso, alias_id))
                alias.id = alias_id
                alias.match_count = new_cnt
                alias.updated_at = now_iso
            else:
                cursor.execute("""
                    INSERT INTO product_aliases (
                        raw_alias_text, normalized_alias, supplier_id, master_item_id,
                        master_item_code, master_item_name, match_count, confidence,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """, (alias.raw_alias_text, norm_alias, eff_sup_id, eff_master_id,
                      alias.master_item_code, alias.master_item_name, alias.match_count, alias.confidence,
                      now_iso, now_iso))
                alias.id = cursor.lastrowid
                alias.created_at = now_iso
                alias.updated_at = now_iso
        return alias

    def find_product_alias(self, raw_alias: str, supplier_id: Optional[int] = None) -> Optional[ProductAlias]:
        if not raw_alias:
            return None
        norm = clean_text_helper(raw_alias).upper()

        with self.get_connection() as conn:
            cursor = conn.cursor()
            # 1. First priority: supplier-specific exact alias
            if supplier_id:
                cursor.execute("""
                    SELECT * FROM product_aliases
                    WHERE supplier_id = ? AND (raw_alias_text = ? OR normalized_alias = ?)
                    ORDER BY confidence DESC, match_count DESC LIMIT 1;
                """, (supplier_id, raw_alias, norm))
                row = cursor.fetchone()
                if row:
                    return self._row_to_product_alias(row)

            # 2. Second priority: global alias (any supplier)
            cursor.execute("""
                SELECT * FROM product_aliases
                WHERE raw_alias_text = ? OR normalized_alias = ?
                ORDER BY match_count DESC, confidence DESC LIMIT 1;
            """, (raw_alias, norm))
            row = cursor.fetchone()
            if row:
                return self._row_to_product_alias(row)
        return None

    def _row_to_product_alias(self, row: Any) -> ProductAlias:
        return ProductAlias(
            id=row["id"],
            raw_alias_text=row["raw_alias_text"],
            normalized_alias=row["normalized_alias"],
            supplier_id=row["supplier_id"],
            master_item_id=row["master_item_id"],
            master_item_code=row["master_item_code"],
            master_item_name=row["master_item_name"],
            match_count=row["match_count"],
            confidence=row["confidence"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def list_product_aliases(self, supplier_id: Optional[int] = None, limit: int = 200) -> List[ProductAlias]:
        aliases = []
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if supplier_id:
                cursor.execute("SELECT * FROM product_aliases WHERE supplier_id = ? ORDER BY match_count DESC LIMIT ?;", (supplier_id, limit))
            else:
                cursor.execute("SELECT * FROM product_aliases ORDER BY match_count DESC LIMIT ?;", (limit,))
            
            for row in cursor.fetchall():
                aliases.append(self._row_to_product_alias(row))
        return aliases

    def seed_default_master_pharmacy_catalogue(self) -> int:
        """Seeds common top Indian retail pharmacy fast-moving molecules and standard items."""
        sample_master_drugs = [
            ("MED-1001", "AMARYL 1MG TABLET", "1x30", "30049099", 12.0),
            ("MED-1002", "AMARYL 2MG TABLET", "1x30", "30049099", 12.0),
            ("MED-1003", "TELMA 40MG TABLET", "1x15", "30049099", 12.0),
            ("MED-1004", "TELMA 80MG TABLET", "1x15", "30049099", 12.0),
            ("MED-1005", "TELMA H TABLET", "1x15", "30049099", 12.0),
            ("MED-1006", "PAN 40MG TABLET", "1x15", "30049099", 12.0),
            ("MED-1007", "PAN D CAPSULE", "1x15", "30049099", 12.0),
            ("MED-1008", "AUGMENTIN 625 DUO TABLET", "1x10", "30049099", 12.0),
            ("MED-1009", "DOLO 650 TABLET", "1x15", "30049099", 12.0),
            ("MED-1010", "CALPOL 650MG TABLET", "1x15", "30049099", 12.0),
            ("MED-1011", "MONTAIR LC TABLET", "1x10", "30049099", 12.0),
            ("MED-1012", "AZITHRAL 500 TABLET", "1x5", "30049099", 12.0),
            ("MED-1013", "GLYCOMET 500 SR TABLET", "1x20", "30049099", 12.0),
            ("MED-1014", "GLYCOMET GP 1 TABLET", "1x15", "30049099", 12.0),
            ("MED-1015", "SHELCAL 500MG TABLET", "1x15", "30049099", 12.0),
            ("MED-1016", "CLAVAM 625 TABLET", "1x10", "30049099", 12.0),
            ("MED-1017", "GELUSIL MPS LIQUID 200ML", "200ML", "30049099", 12.0),
            ("MED-1018", "BECOSULES CAPSULES", "1x20", "30049099", 12.0),
            ("MED-1019", "CANDID B LOTION 30ML", "30ML", "30049099", 12.0),
            ("MED-1020", "BETADINE 10% OINTMENT 20GM", "20GM", "30049099", 12.0),
        ]
        count = 0
        for code, name, pack, hsn, gst in sample_master_drugs:
            item = PharmacyMasterItem(
                item_code=code,
                item_name=name,
                normalized_name=clean_text_helper(name).upper(),
                pack=pack,
                default_hsn=hsn,
                default_gst_percent=gst,
            )
            self.create_or_update_master_item(item)
            count += 1
        return count


