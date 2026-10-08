"""
MediAstra Pharma PDF Purchase Import Engine - Storage Domain Models
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List, Dict, Any


@dataclass
class Supplier:
    id: Optional[int] = None
    supplier_key: str = ""
    supplier_name: Optional[str] = None
    gstin: Optional[str] = None
    normalized_name: Optional[str] = None
    identity_status: str = "UNKNOWN"
    profile_version: int = 1
    profile_confidence: float = 1.0
    successful_document_count: int = 0
    reviewed_document_count: int = 0
    failure_document_count: int = 0
    is_active: bool = True
    last_seen: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


@dataclass
class SupplierLayoutProfile:
    id: Optional[int] = None
    supplier_id: int = 0
    layout_id: str = ""
    layout_version: int = 1
    layout_signature: str = ""
    header_sequence: List[str] = field(default_factory=list)
    logical_column_count: int = 0
    relative_column_positions: List[Dict[str, Any]] = field(default_factory=list)
    semantic_mapping: Dict[str, Any] = field(default_factory=dict)
    field_reliability: Dict[str, Any] = field(default_factory=dict)
    multi_value_patterns: Dict[str, Any] = field(default_factory=dict)
    known_optional_fields: List[str] = field(default_factory=lambda: ["hsnCode", "discountPercent", "freeQuantity"])
    known_required_fields: List[str] = field(default_factory=lambda: ["itemName", "quantity", "rate", "amount"])
    profile_confidence: float = 0.90
    successful_document_count: int = 1
    review_count: int = 0
    failure_count: int = 0
    layout_status: str = "ACTIVE"
    is_active: bool = True
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    last_seen: Optional[str] = None


@dataclass
class InvoiceDocument:
    id: Optional[int] = None
    original_filename: str = ""
    file_hash: str = ""  # SHA-256
    file_size_bytes: int = 0
    supplier_id: Optional[int] = None
    supplier_key: Optional[str] = None
    supplier_identity_status: str = "UNKNOWN"
    supplier_confidence: float = 1.0
    document_status: str = "RECEIVED"  # RECEIVED, PROCESSING, AUTO_ACCEPT, REVIEW_REQUIRED, UNRESOLVED, FAILED
    extraction_decision: Optional[str] = None
    extraction_confidence: float = 0.0
    engine_version: str = "v1.0"
    created_at: Optional[str] = None
    processed_at: Optional[str] = None


@dataclass
class ExtractionRun:
    id: Optional[int] = None
    document_id: int = 0
    run_number: int = 1
    engine_version: str = "v1.0"
    layout_profile_id: Optional[int] = None
    extraction_method: str = "coordinate_layout_v1"
    confidence: float = 0.0
    decision: str = "UNKNOWN"
    headers: List[str] = field(default_factory=list)
    logical_columns: List[Dict[str, Any]] = field(default_factory=list)
    column_mappings: Dict[str, Any] = field(default_factory=dict)
    accounting_summary: Dict[str, Any] = field(default_factory=dict)
    row_count: int = 0
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    error_info: Optional[str] = None


@dataclass
class ReviewSessionRecord:
    id: Optional[int] = None
    review_session_id: str = ""
    document_id: Optional[int] = None
    run_id: Optional[int] = None
    supplier_id: Optional[int] = None
    original_decision: str = "REVIEW_REQUIRED"
    original_confidence: float = 0.0
    original_headers: List[str] = field(default_factory=list)
    logical_columns: List[Dict[str, Any]] = field(default_factory=list)
    original_mappings: Dict[str, Any] = field(default_factory=dict)
    original_rows: List[List[Any]] = field(default_factory=list)
    corrections: List[Dict[str, Any]] = field(default_factory=list)
    validated_result: Optional[Dict[str, Any]] = None
    review_status: str = "PENDING_REVIEW"
    reviewed_by: Optional[str] = None
    reviewed_at: Optional[str] = None
    is_committed_to_profile: bool = False
    created_at: Optional[str] = None


@dataclass
class AuditEvent:
    id: Optional[int] = None
    event_type: str = ""  # PROFILE_CREATED, PROFILE_UPDATED, LAYOUT_VERSION_CREATED, MAPPING_CORRECTION, REVIEW_COMMITTED, STALE_UPDATE_REJECTED, DUPLICATE_DOCUMENT_RECEIVED
    entity_type: str = ""  # supplier, layout_profile, document, review_session
    entity_id: Optional[str] = None
    supplier_id: Optional[int] = None
    layout_profile_id: Optional[int] = None
    event_data: Dict[str, Any] = field(default_factory=dict)
    created_at: Optional[str] = None


@dataclass
class StockInventoryItem:
    id: Optional[int] = None
    product_name: str = ""
    pack: str = ""
    batch_no: str = ""
    expiry_date: str = ""
    hsn_code: str = ""
    current_stock_qty: float = 0.0
    mrp: float = 0.0
    ptr_rate: float = 0.0
    discount_percent: float = 0.0
    gst_percent: float = 0.0
    supplier_id: Optional[int] = None
    supplier_name: Optional[str] = None
    last_invoice_no: Optional[str] = None
    last_received_date: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


@dataclass
class StockMovement:
    id: Optional[int] = None
    stock_item_id: int = 0
    invoice_no: str = ""
    movement_type: str = "PURCHASE_RECEIPT"  # PURCHASE_RECEIPT, RETURN_DEDUCTION, MANUAL_ADJUSTMENT
    billed_qty: float = 0.0
    free_qty: float = 0.0
    total_qty: float = 0.0
    rate: float = 0.0
    net_amount: float = 0.0
    created_at: Optional[str] = None


@dataclass
class PharmacyMasterItem:
    """Standardized pharmacy master medicine entry for internal ERP mapping."""
    id: Optional[int] = None
    item_code: str = ""  # e.g. 'MED-1001'
    item_name: str = ""  # e.g. 'TELMA 40MG TABLET'
    normalized_name: str = ""  # e.g. 'TELMA 40MG'
    pack: str = ""  # e.g. "15'S"
    default_hsn: str = "30049099"
    default_gst_percent: float = 12.0
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


@dataclass
class ProductAlias:
    """Supplier product description mapping to master pharmacy item code."""
    id: Optional[int] = None
    raw_alias_text: str = ""  # e.g. 'TELMA 40 TAB 15S'
    normalized_alias: str = ""  # e.g. 'TELMA 40'
    supplier_id: Optional[int] = None
    master_item_id: Optional[int] = None
    master_item_code: str = ""
    master_item_name: str = ""
    match_count: int = 1
    confidence: float = 1.0
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


