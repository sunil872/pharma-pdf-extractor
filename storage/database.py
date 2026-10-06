"""
MediAstra Pharma PDF Purchase Import Engine - SQLite Database Management
"""
import os
import sqlite3
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Configurable database path via environment variable
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DEFAULT_DB_PATH = os.environ.get("MEDASTRA_DB_PATH", os.path.join(PROJECT_ROOT, "mediastra.db"))


class ProfileVersionConflictError(Exception):
    """Raised when an optimistic concurrency version check fails."""
    pass


def get_db_path(db_path: Optional[str] = None) -> str:
    """Returns the effective database path."""
    if db_path:
        return db_path
    return os.environ.get("MEDASTRA_DB_PATH", DEFAULT_DB_PATH)


def get_db_connection(db_path: Optional[str] = None) -> sqlite3.Connection:
    """
    Creates and configures a SQLite connection with WAL mode and foreign key support.
    """
    path = get_db_path(db_path)
    # Ensure parent directory exists
    parent = os.path.dirname(path)
    if parent and not os.path.exists(parent):
        os.makedirs(parent, exist_ok=True)

    conn = sqlite3.connect(path, timeout=10.0)
    conn.row_factory = sqlite3.Row
    
    # Configure production SQLite settings
    cursor = conn.cursor()
    cursor.execute("PRAGMA foreign_keys = ON;")
    cursor.execute("PRAGMA busy_timeout = 5000;")
    try:
        cursor.execute("PRAGMA journal_mode = WAL;")
    except Exception as e:
        logger.warning(f"Could not enable WAL mode: {e}")
    cursor.close()
    
    return conn


def init_db(db_path: Optional[str] = None) -> None:
    """
    Initializes the SQLite schema with normalized tables, foreign keys, and indexes.
    Idempotent: Safe to call repeatedly without losing data.
    """
    path = get_db_path(db_path)
    conn = get_db_connection(path)
    try:
        cursor = conn.cursor()
        
        # 1. Suppliers Table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS suppliers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                supplier_key TEXT NOT NULL UNIQUE,
                supplier_name TEXT,
                gstin TEXT,
                normalized_name TEXT,
                identity_status TEXT NOT NULL DEFAULT 'UNKNOWN',
                profile_version INTEGER NOT NULL DEFAULT 1,
                profile_confidence REAL NOT NULL DEFAULT 1.0,
                successful_document_count INTEGER NOT NULL DEFAULT 0,
                reviewed_document_count INTEGER NOT NULL DEFAULT 0,
                failure_document_count INTEGER NOT NULL DEFAULT 0,
                is_active INTEGER NOT NULL DEFAULT 1,
                last_seen TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
        """)

        # 2. Supplier Layout Profiles Table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS supplier_layout_profiles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                supplier_id INTEGER NOT NULL,
                layout_id TEXT NOT NULL,
                layout_version INTEGER NOT NULL DEFAULT 1,
                layout_signature TEXT NOT NULL,
                header_sequence_json TEXT NOT NULL DEFAULT '[]',
                logical_column_count INTEGER NOT NULL DEFAULT 0,
                relative_positions_json TEXT NOT NULL DEFAULT '[]',
                semantic_mapping_json TEXT NOT NULL DEFAULT '{}',
                field_reliability_json TEXT NOT NULL DEFAULT '{}',
                multi_value_patterns_json TEXT NOT NULL DEFAULT '{}',
                known_optional_fields_json TEXT NOT NULL DEFAULT '[]',
                known_required_fields_json TEXT NOT NULL DEFAULT '[]',
                profile_confidence REAL NOT NULL DEFAULT 0.90,
                successful_document_count INTEGER NOT NULL DEFAULT 1,
                review_count INTEGER NOT NULL DEFAULT 0,
                failure_count INTEGER NOT NULL DEFAULT 0,
                layout_status TEXT NOT NULL DEFAULT 'ACTIVE',
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                last_seen TEXT,
                FOREIGN KEY (supplier_id) REFERENCES suppliers (id) ON DELETE CASCADE,
                UNIQUE (supplier_id, layout_id)
            );
        """)

        # 3. Invoice Documents Table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS invoice_documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                original_filename TEXT NOT NULL,
                file_hash TEXT NOT NULL UNIQUE,
                file_size_bytes INTEGER NOT NULL DEFAULT 0,
                supplier_id INTEGER,
                supplier_key TEXT,
                supplier_identity_status TEXT NOT NULL DEFAULT 'UNKNOWN',
                supplier_confidence REAL NOT NULL DEFAULT 1.0,
                document_status TEXT NOT NULL DEFAULT 'RECEIVED',
                extraction_decision TEXT,
                extraction_confidence REAL NOT NULL DEFAULT 0.0,
                engine_version TEXT NOT NULL DEFAULT 'v1.0',
                created_at TEXT NOT NULL,
                processed_at TEXT,
                FOREIGN KEY (supplier_id) REFERENCES suppliers (id) ON DELETE SET NULL
            );
        """)

        # 4. Extraction Runs Table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS extraction_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                document_id INTEGER NOT NULL,
                run_number INTEGER NOT NULL DEFAULT 1,
                engine_version TEXT NOT NULL DEFAULT 'v1.0',
                layout_profile_id INTEGER,
                extraction_method TEXT NOT NULL DEFAULT 'coordinate_layout_v1',
                confidence REAL NOT NULL DEFAULT 0.0,
                decision TEXT NOT NULL DEFAULT 'UNKNOWN',
                headers_json TEXT NOT NULL DEFAULT '[]',
                logical_columns_json TEXT NOT NULL DEFAULT '[]',
                column_mappings_json TEXT NOT NULL DEFAULT '{}',
                accounting_summary_json TEXT NOT NULL DEFAULT '{}',
                row_count INTEGER NOT NULL DEFAULT 0,
                started_at TEXT NOT NULL,
                completed_at TEXT,
                error_info TEXT,
                FOREIGN KEY (document_id) REFERENCES invoice_documents (id) ON DELETE CASCADE,
                FOREIGN KEY (layout_profile_id) REFERENCES supplier_layout_profiles (id) ON DELETE SET NULL
            );
        """)

        # 5. Review Sessions Table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS review_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                review_session_id TEXT NOT NULL UNIQUE,
                document_id INTEGER,
                run_id INTEGER,
                supplier_id INTEGER,
                original_decision TEXT NOT NULL DEFAULT 'REVIEW_REQUIRED',
                original_confidence REAL NOT NULL DEFAULT 0.0,
                original_headers_json TEXT NOT NULL DEFAULT '[]',
                logical_columns_json TEXT NOT NULL DEFAULT '[]',
                original_mappings_json TEXT NOT NULL DEFAULT '{}',
                original_rows_json TEXT NOT NULL DEFAULT '[]',
                corrections_json TEXT NOT NULL DEFAULT '[]',
                validated_result_json TEXT,
                review_status TEXT NOT NULL DEFAULT 'PENDING_REVIEW',
                reviewed_by TEXT,
                reviewed_at TEXT,
                is_committed_to_profile INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                FOREIGN KEY (document_id) REFERENCES invoice_documents (id) ON DELETE SET NULL,
                FOREIGN KEY (run_id) REFERENCES extraction_runs (id) ON DELETE SET NULL,
                FOREIGN KEY (supplier_id) REFERENCES suppliers (id) ON DELETE SET NULL
            );
        """)

        # 6. Audit Events Table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS audit_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                entity_type TEXT NOT NULL,
                entity_id TEXT,
                supplier_id INTEGER,
                layout_profile_id INTEGER,
                event_data_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                FOREIGN KEY (supplier_id) REFERENCES suppliers (id) ON DELETE SET NULL,
                FOREIGN KEY (layout_profile_id) REFERENCES supplier_layout_profiles (id) ON DELETE SET NULL
            );
        """)

        # Indexes for high-performance lookups
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_suppliers_gstin ON suppliers (gstin);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_suppliers_key ON suppliers (supplier_key);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_suppliers_norm_name ON suppliers (normalized_name);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_layouts_supplier_id ON supplier_layout_profiles (supplier_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_layouts_sig ON supplier_layout_profiles (layout_signature);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_docs_file_hash ON invoice_documents (file_hash);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_docs_status ON invoice_documents (document_status);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_docs_supplier_id ON invoice_documents (supplier_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_runs_doc_id ON extraction_runs (document_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_reviews_session_id ON review_sessions (review_session_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_audit_event_type ON audit_events (event_type);")

        conn.commit()
    finally:
        conn.close()
