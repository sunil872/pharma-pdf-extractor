"""
MediAstra Pharma PDF Purchase Import Engine - Production Batch Processing & Job Pipeline
Provides generic, error-isolated, observable batch processing for arbitrary supplier invoices.
"""
import os
import sys
import glob
import time
import json
import hashlib
import logging
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Optional, List, Dict, Any, Callable, Union
import pandas as pd

# Ensure project root is on sys.path
PROJECT_ROOT = os.path.abspath(os.path.dirname(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from extractor import extract_pdf_table, ALIAS_DICT

CANONICAL_COLUMNS = list(ALIAS_DICT.keys())
from storage import StorageService

# Setup structured logger
logger = logging.getLogger("mediastra.batch_processor")
if not logger.handlers:
    handler = logging.StreamHandler(sys.stdout)
    formatter = logging.Formatter(
        "[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


# ------------------------------------------------------------------------------
# 1. DATA CONTRACTS / MODELS
# ------------------------------------------------------------------------------

@dataclass
class DocumentProcessingResult:
    """Stable result record for a single processed invoice PDF."""
    file_path: str = ""
    filename: str = ""
    file_hash: str = ""  # SHA-256
    file_size_bytes: int = 0
    status: str = "SUCCESS"  # SUCCESS, FAILED, DUPLICATE
    decision: str = "UNKNOWN"  # AUTO_ACCEPT, REVIEW_REQUIRED, UNRESOLVED, FAILED
    confidence: float = 0.0
    supplier_name: Optional[str] = None
    gstin: Optional[str] = None
    supplier_identity_status: str = "UNKNOWN"
    layout_id: Optional[str] = None
    row_count: int = 0
    extracted_rows: List[Dict[str, Any]] = field(default_factory=list)
    headers: List[str] = field(default_factory=list)
    logical_columns: List[Dict[str, Any]] = field(default_factory=list)
    column_mappings: Dict[str, Any] = field(default_factory=dict)
    validation_errors: int = 0
    validation_warnings: int = 0
    is_duplicate: bool = False
    duration_sec: float = 0.0
    error_message: Optional[str] = None
    document_id: Optional[int] = None
    run_id: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        # Avoid dumping raw product rows in lightweight summary dictionary
        d.pop("extracted_rows", None)
        return d


@dataclass
class BatchProcessingResult:
    """Consolidated summary for an entire batch processing job."""
    batch_id: str = ""
    input_path: str = ""
    total_documents: int = 0
    auto_accept_count: int = 0
    review_required_count: int = 0
    unresolved_count: int = 0
    failed_count: int = 0
    duplicate_count: int = 0
    total_rows: int = 0
    start_time: str = ""
    end_time: str = ""
    total_duration_sec: float = 0.0
    document_results: List[DocumentProcessingResult] = field(default_factory=list)

    def summary_dict(self) -> Dict[str, Any]:
        return {
            "batch_id": self.batch_id,
            "input_path": self.input_path,
            "total_documents": self.total_documents,
            "auto_accept": self.auto_accept_count,
            "review_required": self.review_required_count,
            "unresolved": self.unresolved_count,
            "failed": self.failed_count,
            "duplicates": self.duplicate_count,
            "total_rows": self.total_rows,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "total_duration_sec": round(self.total_duration_sec, 2),
            "avg_sec_per_pdf": round(self.total_duration_sec / max(1, self.total_documents), 3),
        }


# ------------------------------------------------------------------------------
# 2. INPUT DISCOVERY
# ------------------------------------------------------------------------------

def discover_pdf_files(
    input_path: Union[str, List[str]],
    recursive: bool = True,
) -> List[str]:
    """
    Discovers PDF files from a directory, single file, or list of paths.
    - Supports case-insensitive extensions (.pdf, .PDF, .Pdf).
    - Handles spaces, parentheses, and Unicode in filenames.
    - Returns deterministically sorted paths.
    """
    discovered = []

    VALID_EXTS = (".pdf", ".png", ".jpg", ".jpeg", ".tiff", ".bmp")
    if isinstance(input_path, (list, tuple, set)):
        for item in input_path:
            discovered.extend(discover_pdf_files(str(item), recursive=recursive))
        return sorted(list(set(discovered)))

    path_str = str(input_path).strip()
    if not path_str or not os.path.exists(path_str):
        return []

    if os.path.isfile(path_str):
        if path_str.lower().endswith(VALID_EXTS):
            return [os.path.abspath(path_str)]
        return []

    if os.path.isdir(path_str):
        if recursive:
            for root, _, files in os.walk(path_str):
                for f in files:
                    if f.lower().endswith(VALID_EXTS):
                        discovered.append(os.path.abspath(os.path.join(root, f)))
        else:
            for f in os.listdir(path_str):
                if f.lower().endswith(VALID_EXTS):
                    discovered.append(os.path.abspath(os.path.join(path_str, f)))

    return sorted(list(set(discovered)))


# ------------------------------------------------------------------------------
# 3. SINGLE DOCUMENT PROCESSING WITH ERROR ISOLATION
# ------------------------------------------------------------------------------

def process_single_document(
    pdf_path: str,
    storage_service: Optional[StorageService] = None,
    allow_profile_updates: bool = True,
) -> DocumentProcessingResult:
    """
    Processes a single invoice PDF with full error isolation and observability.
    - Pre-checks file existence, readability, and non-zero size.
    - Computes SHA-256 hash.
    - Detects duplicate documents using SQLite persistence.
    - Executes extraction pipeline non-destructively.
    - Records run metadata into SQLite.
    """
    t0 = time.perf_counter()
    fname = os.path.basename(pdf_path)
    logger.info(f"[DOC_STARTED] File: '{fname}' | Path: '{pdf_path}'")

    # 1. Pre-Check: File existence and size
    if not os.path.exists(pdf_path):
        err_msg = f"File not found: {pdf_path}"
        logger.error(f"[DOC_FAILED] File: '{fname}' | Reason: {err_msg}")
        return DocumentProcessingResult(
            file_path=pdf_path,
            filename=fname,
            status="FAILED",
            decision="FAILED",
            error_message=err_msg,
            duration_sec=round(time.perf_counter() - t0, 3),
        )

    try:
        file_size = os.path.getsize(pdf_path)
    except Exception as e:
        err_msg = f"Cannot read file size: {e}"
        logger.error(f"[DOC_FAILED] File: '{fname}' | Reason: {err_msg}")
        return DocumentProcessingResult(
            file_path=pdf_path,
            filename=fname,
            status="FAILED",
            decision="FAILED",
            error_message=err_msg,
            duration_sec=round(time.perf_counter() - t0, 3),
        )

    if file_size == 0:
        err_msg = "Invalid empty / zero-byte PDF file"
        logger.error(f"[DOC_FAILED] File: '{fname}' | Reason: {err_msg}")
        return DocumentProcessingResult(
            file_path=pdf_path,
            filename=fname,
            file_size_bytes=0,
            status="FAILED",
            decision="FAILED",
            error_message=err_msg,
            duration_sec=round(time.perf_counter() - t0, 3),
        )

    # Compute SHA-256
    try:
        with open(pdf_path, "rb") as f:
            file_content = f.read()
            file_hash = hashlib.sha256(file_content).hexdigest()
    except Exception as e:
        err_msg = f"Error reading file bytes for SHA-256 calculation: {e}"
        logger.error(f"[DOC_FAILED] File: '{fname}' | Reason: {err_msg}")
        return DocumentProcessingResult(
            file_path=pdf_path,
            filename=fname,
            file_size_bytes=file_size,
            status="FAILED",
            decision="FAILED",
            error_message=err_msg,
            duration_sec=round(time.perf_counter() - t0, 3),
        )

    # 2. Check duplicate status in storage
    is_duplicate = False
    if storage_service is not None:
        try:
            with storage_service.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT id FROM invoice_documents WHERE file_hash = ?;", (file_hash,))
                if cursor.fetchone() is not None:
                    is_duplicate = True
                    logger.info(f"[DUPLICATE_DETECTED] File: '{fname}' | SHA-256: {file_hash[:12]} already registered in database.")
        except Exception as e:
            logger.warning(f"Could not check duplicate status in storage: {e}")

    # 3. Execute Extraction Pipeline (Isolated)
    try:
        metadata, headers, column_mappings, all_rows = extract_pdf_table(pdf_path)
    except Exception as e:
        err_msg = f"Extraction exception: {e}"
        logger.error(f"[DOC_FAILED] File: '{fname}' | Exception: {err_msg}", exc_info=True)
        return DocumentProcessingResult(
            file_path=pdf_path,
            filename=fname,
            file_hash=file_hash,
            file_size_bytes=file_size,
            status="FAILED",
            decision="FAILED",
            error_message=err_msg,
            is_duplicate=is_duplicate,
            duration_sec=round(time.perf_counter() - t0, 3),
        )

    # 4. Extract Metrics & Decisions
    sup_name = metadata.get("supplier_name")
    gstin = metadata.get("supplier_gstin")
    identity_safety = metadata.get("identity_safety", {})
    decision = metadata.get("classification", metadata.get("decision", "UNRESOLVED"))
    conf = float(metadata.get("confidence", 0.0))
    drift = metadata.get("drift_report", {})
    layout_id = drift.get("matched_layout_id")
    val = metadata.get("validation", {})
    crit_errors = val.get("accounting_summary", {}).get("critical_mismatches", 0)
    warnings_count = len(val.get("field_warnings", []))

    # Format extracted rows into clean dictionaries
    formatted_rows = []
    # Map physical column index to canonical field name
    col_idx_to_field = {}
    for idx, h in enumerate(headers):
        m = column_mappings.get(h, {})
        mapped = m.get("mapped_to")
        if mapped:
            col_idx_to_field[idx] = mapped

    for r in all_rows:
        row_dict = {}
        for idx, val_cell in enumerate(r):
            field_name = col_idx_to_field.get(idx, f"col_{idx}")
            row_dict[field_name] = val_cell
        formatted_rows.append(row_dict)

    # 5. Persist to SQLite Storage
    doc_id = None
    run_id = None
    if storage_service is not None:
        try:
            doc_rec, run_rec = storage_service.register_document_and_run(
                filename=fname,
                file_hash=file_hash,
                file_size_bytes=file_size,
                metadata=metadata,
                headers=headers,
                logical_columns=metadata.get("logical_columns", []),
                column_mappings=column_mappings,
                rows=all_rows,
            )
            doc_id = doc_rec.id
            run_id = run_rec.id
        except Exception as e:
            logger.error(f"Error persisting document to SQLite: {e}")

    duration = round(time.perf_counter() - t0, 3)
    logger.info(
        f"[DOC_COMPLETED] File: '{fname}' | Supplier: '{sup_name or 'UNKNOWN'}' | "
        f"Decision: {decision} | Conf: {conf:.1f}% | Rows: {len(all_rows)} | Time: {duration}s"
    )

    return DocumentProcessingResult(
        file_path=pdf_path,
        filename=fname,
        file_hash=file_hash,
        file_size_bytes=file_size,
        status="SUCCESS",
        decision=decision,
        confidence=conf,
        supplier_name=sup_name,
        gstin=gstin,
        supplier_identity_status=identity_safety.get("status", "UNKNOWN"),
        layout_id=layout_id,
        row_count=len(all_rows),
        extracted_rows=formatted_rows,
        headers=headers,
        logical_columns=metadata.get("logical_columns", []),
        column_mappings={k: v.get("mapped_to") for k, v in column_mappings.items()},
        validation_errors=crit_errors,
        validation_warnings=warnings_count,
        is_duplicate=is_duplicate,
        duration_sec=duration,
        document_id=doc_id,
        run_id=run_id,
    )


# ------------------------------------------------------------------------------
# 4. BATCH PROCESSING PIPELINE
# ------------------------------------------------------------------------------

def process_batch(
    input_path: Union[str, List[str]],
    storage_service: Optional[StorageService] = None,
    allow_profile_updates: bool = True,
    progress_callback: Optional[Callable[[int, int, DocumentProcessingResult], None]] = None,
) -> BatchProcessingResult:
    """
    Executes sequential, error-isolated batch processing over a collection of invoice PDFs.
    - Discovers and deterministically orders files.
    - Maintains independent processing boundaries across suppliers.
    - Emits progress and aggregates batch KPIs.
    """
    t_start = time.perf_counter()
    start_iso = datetime.now().isoformat()
    batch_id = f"batch_{hashlib.sha256((str(input_path) + start_iso).encode()).hexdigest()[:12]}"

    pdf_files = discover_pdf_files(input_path)
    total_files = len(pdf_files)
    logger.info(f"[BATCH_STARTED] Batch ID: {batch_id} | Total PDFs discovered: {total_files}")

    doc_results: List[DocumentProcessingResult] = []
    auto_accept = 0
    review_required = 0
    unresolved = 0
    failed = 0
    duplicates = 0
    total_rows = 0

    for idx, fpath in enumerate(pdf_files):
        res = process_single_document(
            pdf_path=fpath,
            storage_service=storage_service,
            allow_profile_updates=allow_profile_updates,
        )
        doc_results.append(res)

        # Update metrics
        if res.decision == "AUTO_ACCEPT":
            auto_accept += 1
        elif res.decision == "REVIEW_REQUIRED":
            review_required += 1
        elif res.decision == "UNRESOLVED":
            unresolved += 1
        elif res.decision == "FAILED":
            failed += 1

        if res.is_duplicate:
            duplicates += 1

        total_rows += res.row_count

        if progress_callback:
            try:
                progress_callback(idx + 1, total_files, res)
            except Exception as e:
                logger.warning(f"Error in batch progress callback: {e}")

    end_iso = datetime.now().isoformat()
    total_duration = round(time.perf_counter() - t_start, 3)

    logger.info(
        f"[BATCH_COMPLETED] Batch ID: {batch_id} | Processed: {total_files} | "
        f"AUTO_ACCEPT: {auto_accept} | REVIEW_REQUIRED: {review_required} | "
        f"UNRESOLVED: {unresolved} | FAILED: {failed} | Total Rows: {total_rows} | Duration: {total_duration}s"
    )

    return BatchProcessingResult(
        batch_id=batch_id,
        input_path=str(input_path),
        total_documents=total_files,
        auto_accept_count=auto_accept,
        review_required_count=review_required,
        unresolved_count=unresolved,
        failed_count=failed,
        duplicate_count=duplicates,
        total_rows=total_rows,
        start_time=start_iso,
        end_time=end_iso,
        total_duration_sec=total_duration,
        document_results=doc_results,
    )


# ------------------------------------------------------------------------------
# 5. BATCH EXPORT (CSV / JSON)
# ------------------------------------------------------------------------------

def export_batch_results(
    batch_result: BatchProcessingResult,
    export_format: str = "csv",
    output_path: Optional[str] = None,
    include_failed: bool = False,
) -> Union[str, pd.DataFrame]:
    """
    Exports consolidated batch extraction results to CSV or JSON format.
    Maintains document provenance columns and canonical product fields.
    """
    all_rows = []
    
    for doc in batch_result.document_results:
        if not include_failed and doc.status == "FAILED":
            continue
        
        for r in doc.extracted_rows:
            row_entry = {
                "batch_id": batch_result.batch_id,
                "document_id": doc.document_id,
                "filename": doc.filename,
                "file_hash": doc.file_hash,
                "supplier_name": doc.supplier_name,
                "supplier_gstin": doc.gstin,
                "decision": doc.decision,
                "confidence": doc.confidence,
            }
            # Append all product fields
            row_entry.update(r)
            all_rows.append(row_entry)

    df = pd.DataFrame(all_rows)

    # Reorder columns to place document metadata first, followed by canonical columns
    meta_cols = ["batch_id", "document_id", "filename", "file_hash", "supplier_name", "supplier_gstin", "decision", "confidence"]
    existing_cols = list(df.columns)
    ordered_cols = [c for c in meta_cols if c in existing_cols] + [c for c in existing_cols if c not in meta_cols]
    if not df.empty:
        df = df[ordered_cols]

    if export_format.lower() in ("xlsx", "excel"):
        from export_engine import export_to_formatted_excel
        batch_meta = {
            "supplier_name": f"Batch Consolidated ({batch_result.total_documents} invoices)",
            "gstin": "CONSOLIDATED",
            "invoice_no": batch_result.batch_id,
            "invoice_date": batch_result.start_time[:10] if batch_result.start_time else "",
        }
        excel_bytes = export_to_formatted_excel(df, metadata=batch_meta, output_path=output_path)
        return excel_bytes
    elif export_format.lower() in ("marg", "marg_csv"):
        from export_engine import export_to_marg_csv
        batch_meta = {
            "supplier_name": f"Batch Consolidated ({batch_result.total_documents} invoices)",
            "invoice_no": batch_result.batch_id,
        }
        return export_to_marg_csv(df, metadata=batch_meta, output_path=output_path)
    elif export_format.lower() in ("tally", "tally_xml"):
        from export_engine import export_to_tally_xml
        batch_meta = {
            "supplier_name": "Batch Invoices",
            "invoice_no": batch_result.batch_id,
            "invoice_date": batch_result.start_time[:10] if batch_result.start_time else "",
        }
        return export_to_tally_xml(df, metadata=batch_meta, output_path=output_path)
    elif export_format.lower() in ("canonical", "cloud_json", "stock_sync"):
        from export_engine import export_to_canonical_json
        canonical_docs = []
        for doc in batch_result.document_results:
            if not include_failed and doc.status == "FAILED":
                continue
            doc_meta = {
                "supplier_name": doc.supplier_name,
                "gstin": doc.gstin,
                "invoice_number": doc.filename,
            }
            canonical_docs.append(export_to_canonical_json(doc.extracted_rows, metadata=doc_meta))
        
        json_str = json.dumps({
            "batch_id": batch_result.batch_id,
            "total_documents": len(canonical_docs),
            "documents": canonical_docs,
        }, indent=2)
        if output_path:
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(json_str)
        return json_str
    elif export_format.lower() == "json":
        json_str = df.to_json(orient="records", indent=2)
        if output_path:
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(json_str)
        return json_str
    else:
        # CSV format
        csv_str = df.to_csv(index=False)
        if output_path:
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(csv_str)
        return csv_str


def sync_batch_to_stock_inventory(
    batch_result: BatchProcessingResult,
    storage_service: Optional[StorageService] = None,
) -> Dict[str, Any]:
    """
    Ingests all successfully processed invoice rows from a batch job directly
    into the pharmacy stock inventory master database.
    """
    if storage_service is None:
        storage_service = StorageService()

    from export_engine import export_to_canonical_json

    total_invoices_synced = 0
    total_items_updated = 0
    total_stock_added = 0.0
    total_returns_adjusted = 0

    for doc in batch_result.document_results:
        if doc.status == "FAILED" or not doc.extracted_rows:
            continue

        doc_meta = {
            "supplier_name": doc.supplier_name,
            "gstin": doc.gstin,
            "invoice_number": doc.filename,
            "date": batch_result.start_time[:10] if batch_result.start_time else "",
        }

        canonical_payload = export_to_canonical_json(doc.extracted_rows, metadata=doc_meta)
        sync_res = storage_service.ingest_stock_payload(canonical_payload)

        total_invoices_synced += 1
        total_items_updated += sync_res.get("items_updated", 0)
        total_stock_added += sync_res.get("total_stock_added", 0.0)
        total_returns_adjusted += sync_res.get("returns_adjusted", 0)

    return {
        "status": "SUCCESS",
        "batch_id": batch_result.batch_id,
        "invoices_synced": total_invoices_synced,
        "items_updated": total_items_updated,
        "total_stock_added": total_stock_added,
        "returns_adjusted": total_returns_adjusted,
    }

