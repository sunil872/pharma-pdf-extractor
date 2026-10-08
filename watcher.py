"""
MediAstra Pharma PDF Purchase Import Engine - Hot-Folder Ingestion Daemon & Watcher Pipeline
Monitors incoming supplier invoice folders, verifies file write completion, executes deterministic extraction,
auto-syncs inventory to SQLite on AUTO_ACCEPT, routes documents, and triggers multi-ERP exports.
"""
import os
import sys
import time
import shutil
import hashlib
import logging
import threading
from datetime import datetime
from typing import Optional, List, Dict, Any, Callable, Union

PROJECT_ROOT = os.path.abspath(os.path.dirname(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from batch_processor import (
    DocumentProcessingResult,
    discover_pdf_files,
    process_single_document,
)
from storage import StorageService
from storage.models import AuditEvent
from product_alias_engine import resolve_invoice_row_aliases
from hsn_tax_sentinel import audit_invoice_tax_compliance
from export_engine import (
    export_to_marg_csv,
    export_to_tally_xml,
    export_to_busy_vyapar_excel,
    export_to_canonical_json,
)

logger = logging.getLogger("mediastra.watcher")


def is_file_ready_for_processing(filepath: str, wait_probe_sec: float = 0.5) -> bool:
    """
    Ensures that a file is completely written and not currently being copied or locked
    by another process (e.g. WhatsApp Desktop downloading, scanner writing, network copy).
    """
    if not os.path.exists(filepath):
        return False

    try:
        size1 = os.path.getsize(filepath)
        if size1 == 0:
            return False

        time.sleep(wait_probe_sec)

        size2 = os.path.getsize(filepath)
        if size1 != size2:
            return False  # Still actively growing

        # Attempt to open file in binary append/read mode to test file lock
        with open(filepath, "rb") as f:
            f.read(1024)
        return True
    except (IOError, OSError, PermissionError):
        return False


class InvoiceFolderWatcher:
    """
    Continuous, autonomous hot-folder directory monitor for incoming pharmaceutical invoices.
    """

    def __init__(
        self,
        inbox_dir: str = "incoming_invoices",
        processed_dir: str = "processed_invoices",
        review_dir: str = "review_queue",
        error_dir: str = "corrupted_invoices",
        storage_service: Optional[StorageService] = None,
        poll_interval_sec: float = 2.0,
        auto_sync_stock: bool = True,
        auto_generate_exports: Optional[List[str]] = None,
    ):
        self.inbox_dir = os.path.abspath(inbox_dir)
        self.processed_dir = os.path.abspath(processed_dir)
        self.review_dir = os.path.abspath(review_dir)
        self.error_dir = os.path.abspath(error_dir)
        self.exports_dir = os.path.join(self.processed_dir, "exports")

        self.storage_service = storage_service or StorageService()
        self.poll_interval_sec = poll_interval_sec
        self.auto_sync_stock = auto_sync_stock
        self.auto_generate_exports = auto_generate_exports or ["marg_csv", "tally_xml", "excel", "canonical"]

        # Ensure all working directories exist
        for d in (self.inbox_dir, self.processed_dir, self.review_dir, self.error_dir, self.exports_dir):
            os.makedirs(d, exist_ok=True)

        # Threading state
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._is_running = False
        self._lock = threading.Lock()

        # Metrics tracking
        self.total_scanned = 0
        self.total_auto_accepted = 0
        self.total_review_queued = 0
        self.total_errors = 0
        self.total_duplicates = 0
        self.last_scan_time: Optional[str] = None
        self.last_processed_file: Optional[str] = None

        # Observer callbacks
        self._listeners: List[Callable[[DocumentProcessingResult], None]] = []

    def add_listener(self, callback: Callable[[DocumentProcessingResult], None]) -> None:
        """Registers a callback invoked whenever an invoice is processed."""
        with self._lock:
            self._listeners.append(callback)

    def is_running(self) -> bool:
        return self._is_running

    def get_watcher_metrics(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "is_running": self._is_running,
                "inbox_dir": self.inbox_dir,
                "processed_dir": self.processed_dir,
                "review_dir": self.review_dir,
                "error_dir": self.error_dir,
                "total_scanned": self.total_scanned,
                "total_auto_accepted": self.total_auto_accepted,
                "total_review_queued": self.total_review_queued,
                "total_errors": self.total_errors,
                "total_duplicates": self.total_duplicates,
                "last_scan_time": self.last_scan_time,
                "last_processed_file": self.last_processed_file,
                "poll_interval_sec": self.poll_interval_sec,
            }

    def start(self) -> None:
        """Starts the background monitoring daemon thread."""
        with self._lock:
            if self._is_running:
                logger.warning("Watcher is already running.")
                return

            self._stop_event.clear()
            self._is_running = True
            self._thread = threading.Thread(target=self._worker_loop, daemon=True, name="MediAstra-WatcherDaemon")
            self._thread.start()
            logger.info(f"🚀 Started InvoiceFolderWatcher on directory: '{self.inbox_dir}'")

    def stop(self, timeout: float = 5.0) -> None:
        """Stops the background monitoring daemon thread gracefully."""
        with self._lock:
            if not self._is_running:
                return

            self._stop_event.set()
            self._is_running = False

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)
            logger.info("🛑 Stopped InvoiceFolderWatcher daemon.")

    def _worker_loop(self) -> None:
        """Continuous background execution loop."""
        while not self._stop_event.is_set():
            try:
                self.scan_and_process_once()
            except Exception as e:
                logger.error(f"Error in watcher scan cycle: {e}", exc_info=True)

            self._stop_event.wait(timeout=self.poll_interval_sec)

    def scan_and_process_once(self) -> List[DocumentProcessingResult]:
        """
        Executes a single sweep over the inbox folder:
        - Discovers files
        - Checks write completeness
        - Processes via MediAstra extraction pipeline
        - Ingests stock inventory & exports on AUTO_ACCEPT
        - Moves file to corresponding destination folder
        """
        self.last_scan_time = datetime.now().isoformat()
        discovered_files = discover_pdf_files(self.inbox_dir, recursive=False)
        if not discovered_files:
            return []

        results = []
        for file_path in discovered_files:
            if self._stop_event.is_set():
                break

            fname = os.path.basename(file_path)

            # 1. Probe write lock completeness
            if not is_file_ready_for_processing(file_path, wait_probe_sec=0.4):
                logger.debug(f"File '{fname}' is not yet fully written or locked. Skipping for next cycle.")
                continue

            logger.info(f"[HOT_FOLDER_INGEST] Processing incoming file: '{fname}'")
            self.last_processed_file = fname
            self.total_scanned += 1

            # 2. Execute full extraction pipeline
            res = process_single_document(
                pdf_path=file_path,
                storage_service=self.storage_service,
                allow_profile_updates=True,
            )

            # 3. Enrich with Master Product Alias & HSN Tax Audit
            if res.extracted_rows:
                # Find supplier ID
                sup = self.storage_service.find_supplier_by_key(res.gstin or res.supplier_name or "")
                sup_id = sup.id if sup else None

                # Enrich rows with master aliases
                enriched_rows = resolve_invoice_row_aliases(
                    res.extracted_rows,
                    supplier_id=sup_id,
                    storage_service=self.storage_service,
                )
                res.extracted_rows = enriched_rows

                # Perform HSN & Statutory GST compliance check
                invoice_meta = {
                    "supplier_name": res.supplier_name,
                    "supplier_gstin": res.gstin,
                    "invoice_no": res.filename,
                }
                tax_audit = audit_invoice_tax_compliance(enriched_rows, invoice_meta=invoice_meta)
                if not tax_audit["is_overall_compliant"]:
                    res.validation_warnings += tax_audit["compliance_alerts_count"]

            # 4. Route and Archive Document Based on Decision
            self._route_processed_file(file_path, res)
            results.append(res)

            # 5. Notify observers
            for cb in self._listeners:
                try:
                    cb(res)
                except Exception as e:
                    logger.error(f"Error executing watcher listener callback: {e}")

        return results

    def _route_processed_file(self, original_path: str, result: DocumentProcessingResult) -> None:
        """
        Moves the physical file to its target destination directory:
        - AUTO_ACCEPT -> processed_invoices/ (with stock update & exports)
        - REVIEW_REQUIRED / UNRESOLVED -> review_queue/
        - FAILED -> corrupted_invoices/
        """
        fname = os.path.basename(original_path)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        base_name, ext = os.path.splitext(fname)

        if result.is_duplicate:
            self.total_duplicates += 1

        if result.status == "SUCCESS" and result.decision == "AUTO_ACCEPT":
            self.total_auto_accepted += 1
            dest_file = os.path.join(self.processed_dir, f"{base_name}_{timestamp}{ext}")

            # 1. Ingest into Stock Inventory Database
            if self.auto_sync_stock and result.extracted_rows:
                try:
                    doc_meta = {
                        "supplier_name": result.supplier_name or "UNKNOWN",
                        "gstin": result.gstin or "",
                        "invoice_number": fname,
                        "invoice_date": datetime.now().strftime("%Y-%m-%d"),
                    }
                    canonical_payload = export_to_canonical_json(result.extracted_rows, metadata=doc_meta)
                    self.storage_service.ingest_stock_payload(canonical_payload)
                    logger.info(f"✓ Automatically synced {len(result.extracted_rows)} stock items to inventory database.")
                except Exception as e:
                    logger.error(f"Failed to auto-sync stock inventory for '{fname}': {e}")

            # 2. Auto-Generate Multi-ERP Exports
            try:
                self._generate_automatic_exports(result, base_name, timestamp)
            except Exception as e:
                logger.error(f"Failed to auto-generate ERP exports for '{fname}': {e}")

            # 3. Move file to processed folder
            self._safe_move_file(original_path, dest_file)
            logger.info(f"✓ Archived accepted invoice to: '{dest_file}'")

        elif result.decision in ("REVIEW_REQUIRED", "UNRESOLVED") or (result.status == "SUCCESS" and result.decision != "AUTO_ACCEPT"):
            self.total_review_queued += 1
            dest_file = os.path.join(self.review_dir, f"{base_name}_{timestamp}{ext}")
            self._safe_move_file(original_path, dest_file)
            logger.info(f"⚠️ Routed invoice to Human-in-the-Loop review queue: '{dest_file}'")

        else:
            self.total_errors += 1
            dest_file = os.path.join(self.error_dir, f"{base_name}_{timestamp}{ext}")
            self._safe_move_file(original_path, dest_file)
            logger.error(f"🚨 Moved corrupted/unreadable invoice to errors folder: '{dest_file}'")

    def _generate_automatic_exports(self, result: DocumentProcessingResult, base_name: str, timestamp: str) -> None:
        """Generates Marg CSV, Tally XML, and Busy Excel files in the exports directory."""
        if not result.extracted_rows:
            return

        import pandas as pd
        df = pd.DataFrame(result.extracted_rows)
        meta = {
            "supplier_name": result.supplier_name or "UNKNOWN",
            "gstin": result.gstin or "",
            "invoice_no": result.filename,
            "invoice_date": datetime.now().strftime("%Y-%m-%d"),
        }

        # 1. Marg ERP CSV
        if "marg_csv" in self.auto_generate_exports:
            marg_path = os.path.join(self.exports_dir, f"{base_name}_{timestamp}_marg.csv")
            export_to_marg_csv(df, metadata=meta, output_path=marg_path)

        # 2. Tally XML
        if "tally_xml" in self.auto_generate_exports:
            tally_path = os.path.join(self.exports_dir, f"{base_name}_{timestamp}_tally.xml")
            export_to_tally_xml(df, metadata=meta, output_path=tally_path)

        # 3. Excel (Busy / Vyapar)
        if "excel" in self.auto_generate_exports:
            excel_path = os.path.join(self.exports_dir, f"{base_name}_{timestamp}_excel.xlsx")
            export_to_busy_vyapar_excel(df, metadata=meta, output_path=excel_path)

        # 4. Canonical JSON
        if "canonical" in self.auto_generate_exports:
            json_path = os.path.join(self.exports_dir, f"{base_name}_{timestamp}_canonical.json")
            export_to_canonical_json(result.extracted_rows, metadata=meta, output_path=json_path)

    def _safe_move_file(self, src: str, dst: str) -> None:
        """Safely moves a file, handling potential overwrite or path conflicts."""
        try:
            if os.path.exists(src):
                shutil.move(src, dst)
        except Exception as e:
            logger.error(f"Error moving file from '{src}' to '{dst}': {e}")
