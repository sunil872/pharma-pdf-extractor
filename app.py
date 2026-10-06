import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import json
import os
import re
import io
from rapidfuzz import process, fuzz

from extractor import (
    extract_pdf_table,
    extract_invoice_metadata,
    parse_compound_qty,
    standardize_date,
    ALIAS_DICT,
    SYSTEM_COLUMNS,
    SYSTEM_FIELD_ORDER,
    PREVIEW_COLUMN_ORDER,
    clean_text,
    match_column_name,
    _header_field_priority_score,
    is_serial_number_header,
    compute_row_accounting,
    fix_column_bleeding,
    load_supplier_profiles,
    update_supplier_profile_memory,
    create_review_session,
    apply_and_validate_review_corrections,
    commit_reviewed_layout_to_profile_memory,
    validate_supplier_identity_safety,
)
from batch_processor import (
    process_single_document,
    process_batch,
    export_batch_results,
    discover_pdf_files,
    BatchProcessingResult,
    DocumentProcessingResult,
)
from storage import StorageService, DEFAULT_DB_PATH

st.set_page_config(page_title="MediAstra - Pharma PDF Purchase Import Engine", layout="wide")

TEMPLATE_FILE = "templates.json"
SYSTEM_FIELDS = [f for f in SYSTEM_FIELD_ORDER if f in ALIAS_DICT]
EXPIRY_FORMAT_OPTIONS = ["MM/YYYY", "MM-YY", "MM/YY", "YYYY-MM", "DD-MM-YYYY"]

st.markdown(
    """
    <style>
    .map-header {
        font-size: 0.78rem;
        font-weight: 700;
        color: #64748b;
        text-transform: uppercase;
        letter-spacing: 0.04em;
        padding: 0.35rem 0;
        border-bottom: 1px solid #e2e8f0;
        margin-bottom: 0.35rem;
    }
    .sys-label {
        font-weight: 700;
        color: #0f172a;
        font-size: 0.95rem;
        line-height: 1.2;
    }
    .sys-desc {
        color: #94a3b8;
        font-size: 0.78rem;
        margin-top: 0.1rem;
    }
    .sample-text {
        color: #64748b;
        font-size: 0.85rem;
        padding-top: 0.55rem;
    }
    .sample-empty {
        color: #cbd5e1;
        font-size: 0.85rem;
        padding-top: 0.55rem;
    }
    .pdf-frame {
        border: 1px solid #e2e8f0;
        border-radius: 8px;
        overflow: hidden;
        background: #f8fafc;
    }
    [data-testid="stImage"] {
        width: 100% !important;
        display: flex !important;
        justify-content: center !important;
    }
    [data-testid="stImage"] img {
        width: 100% !important;
        max-width: 100% !important;
        height: auto !important;
        object-fit: contain !important;
        border: 1px solid #e2e8f0;
        border-radius: 6px;
        box-shadow: 0 1px 4px rgba(0, 0, 0, 0.06);
    }
    [data-testid="stMetricValue"] {
        font-size: 1.15rem !important;
        font-weight: 700 !important;
        color: #0f172a !important;
        white-space: normal !important;
        word-break: break-word !important;
        overflow: visible !important;
        text-overflow: unset !important;
        line-height: 1.25 !important;
    }
    [data-testid="stMetricValue"] > div {
        font-size: 1.15rem !important;
        font-weight: 700 !important;
        white-space: normal !important;
        word-break: break-word !important;
        overflow: visible !important;
        text-overflow: unset !important;
        line-height: 1.25 !important;
    }
    [data-testid="stMetricLabel"] {
        font-size: 0.78rem !important;
        font-weight: 600 !important;
        color: #64748b !important;
        text-transform: uppercase !important;
        letter-spacing: 0.04em !important;
    }
    .antigravity-splitter {
        display: flex;
        align-items: center;
        justify-content: center;
        width: 8px;
        cursor: col-resize;
        background: #e2e8f0;
        border-radius: 4px;
        transition: background 0.15s ease, box-shadow 0.15s ease;
        margin: 0 4px;
        user-select: none;
        z-index: 10;
    }
    .antigravity-splitter:hover, .antigravity-splitter.dragging {
        background: #3b82f6 !important;
        box-shadow: 0 0 8px rgba(59, 130, 246, 0.5);
    }
    .antigravity-splitter::after {
        content: "⋮";
        font-size: 16px;
        color: #94a3b8;
        pointer-events: none;
    }
    .antigravity-splitter:hover::after, .antigravity-splitter.dragging::after {
        color: #ffffff;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


def load_templates():
    if os.path.exists(TEMPLATE_FILE):
        with open(TEMPLATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_template(supplier_key, mapping, headers=None, rows=None, metadata=None):
    if not supplier_key:
        raise ValueError("supplier_key is required")
    templates = load_templates()
    templates[supplier_key] = mapping
    with open(TEMPLATE_FILE, "w", encoding="utf-8") as f:
        json.dump(templates, f, indent=2)

    # Update rich profile memory
    try:
        resolved_dict = {
            h: {"mapped_to": f, "status": "user_confirmed"}
            for h, f in mapping.items()
        }
        val_dummy = {
            "classification": "AUTO_ACCEPT",
            "document_confidence": 100.0,
            "accounting_summary": {"critical_mismatches": 0},
        }
        update_supplier_profile_memory(
            supplier_key=supplier_key,
            supplier_name=(metadata.get("supplier_name") if metadata else None) or supplier_key,
            gstin=metadata.get("supplier_gstin") if metadata else None,
            headers=headers or list(mapping.keys()),
            logical_columns=[],
            resolved_mappings=resolved_dict,
            rows=rows or [],
            validation_result=val_dummy,
            is_user_reviewed=True,
        )
    except Exception:
        pass


def resolve_saved_template(templates: dict, metadata: dict):
    if not templates or not metadata:
        return None
    name = metadata.get("supplier_name")
    gstin = metadata.get("supplier_gstin")
    if name and name in templates:
        return templates[name]
    if gstin and gstin in templates:
        return templates[gstin]
    return None


def first_number(val):
    if val is None:
        return None
    text = str(val).strip()
    if not text:
        return None
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def clean_percent_value(val, keep_sign: bool = False):
    if val is None or str(val).strip() == "":
        return None
    num = first_number(val)
    if num is None:
        return None
    return num if keep_sign else abs(num)


def format_percentage(val, decimals: int = 1) -> str:
    """Format confidence value safely in standard 0-100% scale."""
    if val is None:
        return "0.0%" if decimals > 0 else "0%"
    try:
        f = float(val)
        if 0.0 < f <= 1.0:
            f = f * 100.0
        return f"{f:.{decimals}f}%"
    except (ValueError, TypeError):
        return "0.0%" if decimals > 0 else "0%"


def _value_quality(system_field, val) -> float:
    if val is None:
        return -1.0
    text = str(val).strip()
    if not text:
        return -1.0

    if system_field in {"itemName", "company", "batchNo", "pack", "hsnCode"}:
        return 50.0 - min(len(text), 40) + (10.0 if re.search(r"[A-Za-z]", text) else 0.0)

    if system_field in {
        "quantity", "freeQuantity", "rate", "mrp", "discountPercent",
        "gstPercent", "cgstPercent", "sgstPercent",
        "amount", "taxableAmount", "netAmount",
    }:
        num = first_number(text)
        if num is None:
            return -1.0
        digit_len = len(re.sub(r"\D", "", text))
        if digit_len > 8:
            return 0.0
        if system_field in {"rate", "mrp", "amount", "taxableAmount", "netAmount"}:
            if abs(num) > 1000000:
                return 0.0
            if num == 0:
                return 5.0
            return 40.0 - min(digit_len, 15) + (10.0 if abs(num) < 100000 else 0.0)
        if system_field in {"quantity", "freeQuantity"} and not (0 <= abs(num) < 100000):
            return 0.0
        return 30.0 - min(digit_len, 20) + (5.0 if abs(num) < 10000 else 0.0)

    return 1.0


def build_clean_dataframe(headers, all_rows, confirmed_mappings=None, fallback_column_mappings=None):
    width = len(headers)
    normalized_rows = []
    for row in all_rows:
        padded = list(row) + [""] * max(0, width - len(row))
        normalized_rows.append(padded[:width])

    # 1. Normalize confirmed_mappings into direct PDF header -> system field mapping
    user_map = {}
    if confirmed_mappings:
        # Check if confirmed_mappings is inverted (field_name -> pdf_header)
        is_inverted = any(k in SYSTEM_COLUMNS for k in confirmed_mappings.keys()) and not any(
            v in SYSTEM_COLUMNS for v in confirmed_mappings.values() if isinstance(v, str)
        )
        if is_inverted:
            for field, pdf_h in confirmed_mappings.items():
                if pdf_h:
                    user_map[str(pdf_h)] = field
        else:
            for pdf_h, field_val in confirmed_mappings.items():
                if not pdf_h:
                    continue
                field_name = (
                    field_val.get("mapped_to")
                    if isinstance(field_val, dict)
                    else field_val
                )
                if field_name:
                    user_map[str(pdf_h)] = field_name

    # 2. Normalize fallback_column_mappings
    fallback_map = {}
    if fallback_column_mappings:
        for pdf_h, m in fallback_column_mappings.items():
            if not pdf_h:
                continue
            field_name = m.get("mapped_to") if isinstance(m, dict) else m
            if field_name:
                fallback_map[str(pdf_h)] = field_name

    # 3. Resolve header index to system field
    index_to_field = {}
    for idx, header in enumerate(headers):
        if is_serial_number_header(header):
            continue

        field = None
        # Check user_map first
        if header in user_map:
            field = user_map[header]
        else:
            h_norm = " ".join(str(header).replace("\n", " ").split()).strip()
            h_clean = clean_text(header)
            for um_h, um_f in user_map.items():
                if um_h == h_norm or clean_text(um_h) == h_clean:
                    field = um_f
                    break

        # Fallback to engine's column_mappings
        if not field and fallback_map:
            if header in fallback_map:
                field = fallback_map[header]
            else:
                h_clean = clean_text(header)
                for fb_h, fb_f in fallback_map.items():
                    if clean_text(fb_h) == h_clean:
                        field = fb_f
                        break

        # Fallback to match_column_name
        if not field:
            field = match_column_name(header)

        if field:
            index_to_field[idx] = field

    records = []
    for row in normalized_rows:
        record = {}
        raw_snapshot = {}
        field_scores = {}
        for idx, field in index_to_field.items():
            val = row[idx] if idx < len(row) else ""
            score = _value_quality(field, val)
            if field not in record or score > field_scores.get(field, -999):
                record[field] = val
                raw_snapshot[field] = val
                field_scores[field] = score

        record["_raw_values"] = raw_snapshot
        record = fix_column_bleeding(record)

        # Normalize product description spaces without truncating words
        item = " ".join(str(record.get("itemName") or "").split())
        if not item or not re.search(r"[A-Za-z]{3,}", item):
            continue
        if item.count("  ") >= 3 and len(item) > 60:
            continue
        record["itemName"] = item
        records.append(record)

    clean_df = pd.DataFrame.from_records(records)
    if clean_df.empty:
        return clean_df

    if "quantity" in clean_df.columns:
        billed_vals = []
        free_vals = []
        for val in clean_df["quantity"]:
            billed, free = parse_compound_qty(val)
            if billed == 0.0 and free == 0.0:
                num = first_number(val)
                billed = num if num is not None else None
            billed_vals.append(billed)
            free_vals.append(free)
        clean_df["quantity"] = billed_vals

        if "freeQuantity" in clean_df.columns:
            merged_free = []
            for parsed_free, existing in zip(free_vals, clean_df["freeQuantity"].tolist()):
                if parsed_free:
                    merged_free.append(parsed_free)
                else:
                    _billed, free_only = parse_compound_qty(existing)
                    if free_only:
                        merged_free.append(free_only)
                    else:
                        num = first_number(existing)
                        merged_free.append(num if num is not None else None)
            clean_df["freeQuantity"] = merged_free
        else:
            clean_df["freeQuantity"] = free_vals

    if "expiryDate" in clean_df.columns:
        clean_df["expiryDate"] = clean_df["expiryDate"].apply(standardize_date)

    for field in ("rate", "mrp", "amount", "taxableAmount", "netAmount"):
        if field in clean_df.columns:
            clean_df[field] = clean_df[field].apply(
                lambda v: first_number(v) if v is not None and str(v).strip() != "" else None
            )

    if "discountPercent" in clean_df.columns:
        clean_df["discountPercent"] = clean_df["discountPercent"].apply(
            lambda v: clean_percent_value(v, keep_sign=True)
        )

    for field in ("gstPercent", "cgstPercent", "sgstPercent"):
        if field in clean_df.columns:
            clean_df[field] = clean_df[field].apply(clean_percent_value)

    accounted_rows = [
        compute_row_accounting(rec) for rec in clean_df.to_dict(orient="records")
    ]
    clean_df = pd.DataFrame.from_records(accounted_rows)

    # Note: Destructive deduplication removed to protect legitimate duplicate invoice lines
    ordered = [c for c in PREVIEW_COLUMN_ORDER if c in clean_df.columns]
    extras = [c for c in clean_df.columns if c not in ordered and not c.startswith("_")]
    return clean_df[ordered + extras]


def invert_column_mappings(column_mappings: dict) -> dict:
    inverted = {}
    for pdf_header, system_field in column_mappings.items():
        if not system_field or not pdf_header:
            continue
        field_name = (
            system_field.get("mapped_to")
            if isinstance(system_field, dict)
            else system_field
        )
        if not field_name:
            continue
        if field_name not in inverted:
            inverted[field_name] = pdf_header
        else:
            existing_header = inverted[field_name]
            score_new = _header_field_priority_score(field_name, pdf_header)
            score_old = _header_field_priority_score(field_name, existing_header)
            if score_new > score_old:
                inverted[field_name] = pdf_header
    return inverted


def header_options(headers):
    seen = set()
    options = [""]
    for header in headers:
        if is_serial_number_header(header):
            continue
        label = " ".join(str(header).replace("\n", " ").split()).strip()
        if not label or label in seen:
            continue
        seen.add(label)
        options.append(label)
    return options


def resolve_header(headers, selected_label: str):
    if not selected_label:
        return None
    for header in headers:
        label = " ".join(str(header).replace("\n", " ").split()).strip()
        if label == selected_label:
            return header
    for header in headers:
        if clean_text(header) == clean_text(selected_label):
            return header
    return selected_label


def resolve_best_header_option(
    field: str,
    predicted_pdf: str,
    pdf_column_options: list,
    headers: list = None,
    column_mappings: dict = None,
) -> str:
    """Finds the most accurate matching option in pdf_column_options for a given system field."""
    if not pdf_column_options:
        return ""

    # 1. Exact match in options
    if predicted_pdf and predicted_pdf in pdf_column_options:
        return predicted_pdf

    # 2. Collapsed whitespace match
    if predicted_pdf:
        norm_pred = " ".join(str(predicted_pdf).replace("\n", " ").split()).strip()
        if norm_pred in pdf_column_options:
            return norm_pred

        # 3. Clean-text case-insensitive match against options
        cleaned_pred = clean_text(predicted_pdf)
        if cleaned_pred:
            for opt in pdf_column_options:
                if opt and clean_text(opt) == cleaned_pred:
                    return opt

    # 4. Check column_mappings from extraction pipeline
    if column_mappings:
        for h, m in column_mappings.items():
            mapped = m.get("mapped_to") if isinstance(m, dict) else m
            if mapped == field:
                h_label = " ".join(str(h).replace("\n", " ").split()).strip()
                if h_label in pdf_column_options:
                    return h_label
                for opt in pdf_column_options:
                    if opt and clean_text(opt) == clean_text(h):
                        return opt

    # 5. Check ALIAS_DICT aliases
    aliases = ALIAS_DICT.get(field, [])
    alias_cleans = {clean_text(a) for a in aliases if clean_text(a)}
    for opt in pdf_column_options:
        if opt and clean_text(opt) in alias_cleans:
            return opt

    return ""


def sample_for_header(headers, rows, selected_label: str, limit: int = 3) -> str:
    header = resolve_header(headers, selected_label)
    if not header:
        return ""
    try:
        idx = headers.index(header)
    except ValueError:
        return ""

    samples = []
    for row in rows:
        if idx >= len(row):
            continue
        val = str(row[idx] or "").replace("\n", " ").strip()
        if not val:
            continue
        if val not in samples:
            samples.append(val)
        if len(samples) >= limit:
            break
    if not samples:
        return "N/A"
    joined = ", ".join(samples)
    return joined if len(joined) <= 70 else joined[:67] + "..."


def render_pdf_preview(pdf_bytes: bytes, filename: str = "invoice.pdf"):
    """Interactive paginated high-resolution PDF preview with < and > page navigation."""
    st.download_button(
        label="Open / Download full PDF",
        data=pdf_bytes,
        file_name=filename,
        mime="application/pdf",
        key="pdf_preview_download",
        help="Opens/downloads the complete multi-page invoice (works in Chrome).",
    )

    try:
        # 1. Determine total pages using pypdfium2 (preferred for high-DPI quality) or pdfplumber
        total = 0
        pdfium_doc = None
        try:
            import pypdfium2
            pdfium_doc = pypdfium2.PdfDocument(pdf_bytes)
            total = len(pdfium_doc)
        except Exception:
            pdfium_doc = None

        if pdfium_doc is None:
            import pdfplumber
            with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                total = len(pdf.pages)

        if total == 0:
            st.info("The uploaded PDF has no pages.")
            return

        if "pdf_preview_page" not in st.session_state:
            st.session_state["pdf_preview_page"] = 1

        # Clamp current page to valid bounds
        current_page = max(1, min(st.session_state["pdf_preview_page"], total))
        st.session_state["pdf_preview_page"] = current_page

        # Render navigation bar if multi-page
        if total > 1:
            nav_col1, nav_col2, nav_col3 = st.columns([1, 2, 1])
            with nav_col1:
                prev_disabled = (current_page <= 1)
                if st.button("◀", key="btn_pdf_prev", disabled=prev_disabled, help="Previous Page", use_container_width=True):
                    st.session_state["pdf_preview_page"] = max(1, current_page - 1)
                    st.rerun()

            with nav_col2:
                st.markdown(
                    f"<div style='text-align: center; font-weight: 600; font-size: 0.95rem; padding-top: 0.35rem; color: #1e293b;'>"
                    f"Page {current_page} of {total}"
                    f"</div>",
                    unsafe_allow_html=True,
                )

            with nav_col3:
                next_disabled = (current_page >= total)
                if st.button("▶", key="btn_pdf_next", disabled=next_disabled, help="Next Page", use_container_width=True):
                    st.session_state["pdf_preview_page"] = min(total, current_page + 1)
                    st.rerun()
        else:
            st.caption("Page 1 of 1")

        # 2. Render selected page at crystal-clear high resolution (scale=3.0 ~ 216 DPI)
        if pdfium_doc is not None:
            page = pdfium_doc[current_page - 1]
            pil_image = page.render(scale=3.0).to_pil()
            st.image(pil_image, use_container_width=True)
        else:
            import pdfplumber
            with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                page = pdf.pages[current_page - 1]
                page_image = page.to_image(resolution=250)
                st.image(page_image.original, use_container_width=True)

    except Exception as exc:
        st.warning(f"Could not render page preview: {exc}")


st.title("MediAstra - PDF Purchase Invoice Extractor")

templates = load_templates()

with st.sidebar:
    st.header("Cached Templates")
    st.metric("Total templates", len(templates))
    if templates:
        for key in templates.keys():
            st.caption(key)
    else:
        st.caption("No supplier templates saved yet.")

tab_single, tab_batch, tab_eval = st.tabs([
    "📄 Single Invoice Extraction",
    "📦 Batch Processing & Review Queue",
    "📊 Evaluation & Error Analysis",
])

with tab_single:
    uploaded_file = st.file_uploader("Drop Distributor Invoice PDF", type=["pdf"], key="single_pdf_uploader")

if uploaded_file is not None:
    pdf_bytes = uploaded_file.getvalue()
    uploaded_file.seek(0)

    file_key = f"{uploaded_file.name}:{len(pdf_bytes)}"
    if st.session_state.get("_pdf_file_key") != file_key:
        st.session_state["_pdf_file_key"] = file_key
        st.session_state["pdf_preview_page"] = 1
        for key in list(st.session_state.keys()):
            if (
                str(key).startswith("map_pdf_")
                or str(key).startswith("clear_map_")
                or str(key).startswith("supplier_name_edit")
            ):
                del st.session_state[key]
        st.session_state.pop("_supplier_name_seed", None)

    uploaded_file.seek(0)
    preview_meta = extract_invoice_metadata(uploaded_file)
    saved_template = resolve_saved_template(templates, preview_meta)
    uploaded_file.seek(0)

    with st.spinner("Extracting invoice tables and metadata..."):
        metadata, headers, column_mappings, all_rows = extract_pdf_table(
            uploaded_file,
            saved_template=saved_template,
        )

    st.subheader("1. Extracted Invoice Metadata")
    detected_supplier = (metadata.get("supplier_name") or "").strip()
    if st.session_state.get("_supplier_name_seed") is None:
        st.session_state["_supplier_name_seed"] = detected_supplier

    edit_key = f"supplier_name_edit_{file_key}"
    if edit_key not in st.session_state:
        st.session_state[edit_key] = st.session_state["_supplier_name_seed"]

    supplier_name = st.text_input(
        "Supplier Name",
        key=edit_key,
        help=(
            "Auto-detected from the top-left bold/large header. "
            "Edit if the PDF picked the wrong line (buyer, address, invoice title)."
        ),
        placeholder="Enter supplier / seller trade name",
    ).strip()

    conf = metadata.get("supplier_confidence")
    if detected_supplier and supplier_name == detected_supplier and conf is not None:
        st.caption(f"Detected automatically (confidence {format_percentage(conf, 0)}). You can edit above.")
    elif detected_supplier and supplier_name != detected_supplier:
        st.caption(f"Edited from detected name: {detected_supplier}")
    elif not detected_supplier:
        st.caption("Could not auto-detect supplier name — please type it in.")

    val_info = metadata.get("validation", {})
    doc_status = val_info.get("classification") or metadata.get("document_status", "REVIEW_REQUIRED")
    doc_conf = val_info.get("document_confidence", metadata.get("document_confidence", 0.0))
    drift_info = val_info.get("layout_drift", {})
    drift_status = drift_info.get("status", "")

    col1, col2, col3, col4 = st.columns([1.3, 0.95, 0.95, 1.3])
    col1.metric("Supplier GSTIN", metadata.get("supplier_gstin") or "—")
    col2.metric("Invoice Number", metadata.get("invoice_number") or "—")
    col3.metric("Invoice Date", metadata.get("invoice_date") or "—")
    status_label = f"{doc_status} ({format_percentage(doc_conf, 0)})"
    col4.metric("Engine Confidence", status_label)

    # Persist edited name into metadata used for templates + JSON export.
    metadata = dict(metadata)
    metadata["supplier_name"] = supplier_name or None

    gstin = metadata.get("supplier_gstin")
    supplier_key = supplier_name or gstin
    if gstin:
        st.session_state["detected_gstin"] = gstin
    if supplier_name:
        st.session_state["detected_supplier_name"] = supplier_name

    if doc_status == "AUTO_ACCEPT":
        st.success(f"✓ **AUTO ACCEPT** — All critical fields mapped with high confidence ({format_percentage(doc_conf, 1)}). Arithmetic and row geometry validated.")
    elif doc_status == "REVIEW_REQUIRED":
        st.warning(f"⚠️ **REVIEW REQUIRED** — Confidence: {format_percentage(doc_conf, 1)}. Please verify mapped columns and line items below.")
    else:
        st.error(f"❌ **UNRESOLVED** — Low confidence ({format_percentage(doc_conf, 1)}) or structural ambiguity. Manual column mapping required.")

    if drift_status == "LAYOUT_DRIFT":
        st.info("ℹ️ **Layout Drift Detected**: The supplier's invoice layout differs from the saved template. Current invoice layout evidence was prioritized as a prior.")
    elif saved_template:
        st.caption(
            "Some columns were automatically mapped using your saved supplier template. "
            "Please map the remaining columns to update your template."
        )
    elif supplier_key:
        st.caption(
            f"New supplier detected ({supplier_key}). Please verify column mappings below."
        )

    predicted_by_system = invert_column_mappings(column_mappings)
    pdf_column_options = header_options(headers)

    st.subheader("2. Update Supplier Template")

    map_col, preview_col = st.columns([60, 40], gap="small")

    # Antigravity-style vertical blue draggable divider between Column Mapping and PDF Preview
    components.html(
        """
        <script>
        (function() {
            const pDoc = window.parent.document;
            const pWin = window.parent;
            if (!pDoc || !pWin) return;

            // 1. Inject Antigravity-style bright blue splitter CSS into parent document
            if (!pDoc.getElementById("ag-blue-splitter-style")) {
                const s = pDoc.createElement("style");
                s.id = "ag-blue-splitter-style";
                s.textContent = `
                    .ag-blue-splitter {
                        width: 8px !important;
                        min-width: 8px !important;
                        max-width: 8px !important;
                        cursor: col-resize !important;
                        background: transparent;
                        margin: 0 -4px;
                        position: relative;
                        z-index: 50;
                        user-select: none !important;
                        -webkit-user-select: none !important;
                        display: flex;
                        align-items: center;
                        justify-content: center;
                    }
                    .ag-blue-splitter::before {
                        content: "";
                        position: absolute;
                        top: 0;
                        bottom: 0;
                        left: 3px;
                        width: 2px;
                        background: #cbd5e1;
                        border-radius: 1px;
                        transition: all 0.15s ease;
                    }
                    .ag-blue-splitter:hover::before, .ag-blue-splitter.dragging::before {
                        left: 2px;
                        width: 4px;
                        background: #007acc !important;
                        box-shadow: 0 0 10px rgba(0, 122, 204, 0.8) !important;
                    }
                `;
                pDoc.head.appendChild(s);
            }

            // 2. Attach draggable splitter to the Section 2 column container
            function attachSplitter() {
                const blocks = pDoc.querySelectorAll('div[data-testid="stHorizontalBlock"]');
                let targetBlock = null;
                for (let b of blocks) {
                    const txt = b.textContent || "";
                    if (txt.includes("Column Mapping") && txt.includes("PDF Preview")) {
                        targetBlock = b;
                        break;
                    }
                }
                if (!targetBlock) return;

                const cols = targetBlock.querySelectorAll(':scope > div[data-testid="column"]');
                if (cols.length < 2) return;

                const leftCol = cols[0];
                const rightCol = cols[1];

                // Restore saved drag ratio or default 60%
                const saved = pWin.sessionStorage.getItem("ag_pane_split_ratio");
                const currentPct = saved ? parseFloat(saved) : 60;
                leftCol.style.flex = `0 0 ${currentPct}%`;
                leftCol.style.maxWidth = `${currentPct}%`;
                leftCol.style.width = `${currentPct}%`;
                rightCol.style.flex = `0 0 ${100 - currentPct}%`;
                rightCol.style.maxWidth = `${100 - currentPct}%`;
                rightCol.style.width = `${100 - currentPct}%`;

                if (targetBlock.querySelector('.ag-blue-splitter')) return;

                const divider = pDoc.createElement('div');
                divider.className = 'ag-blue-splitter';
                divider.title = 'Drag to resize Column Mapping and PDF Preview';
                targetBlock.insertBefore(divider, rightCol);

                let isDragging = false;

                divider.addEventListener('mousedown', function(e) {
                    isDragging = true;
                    divider.classList.add('dragging');
                    pDoc.body.style.cursor = 'col-resize';
                    pDoc.body.style.userSelect = 'none';
                    e.preventDefault();
                    e.stopPropagation();
                });

                pWin.addEventListener('mousemove', function(e) {
                    if (!isDragging) return;
                    const rect = targetBlock.getBoundingClientRect();
                    if (rect.width <= 0) return;
                    let pct = ((e.clientX - rect.left) / rect.width) * 100;
                    pct = Math.max(15, Math.min(85, pct));

                    leftCol.style.flex = `0 0 ${pct}%`;
                    leftCol.style.maxWidth = `${pct}%`;
                    leftCol.style.width = `${pct}%`;
                    rightCol.style.flex = `0 0 ${100 - pct}%`;
                    rightCol.style.maxWidth = `${100 - pct}%`;
                    rightCol.style.width = `${100 - pct}%`;

                    pWin.sessionStorage.setItem("ag_pane_split_ratio", pct.toFixed(1));
                });

                pWin.addEventListener('mouseup', function() {
                    if (isDragging) {
                        isDragging = false;
                        divider.classList.remove('dragging');
                        pDoc.body.style.cursor = '';
                        pDoc.body.style.userSelect = '';
                    }
                });
            }

            attachSplitter();
            setTimeout(attachSplitter, 200);
            setTimeout(attachSplitter, 600);
            setTimeout(attachSplitter, 1200);
        })();
        </script>
        """,
        height=0,
    )

    confirmed_mappings = {}
    system_to_pdf = {}

    with map_col:
        st.markdown("##### Column Mapping")
        st.caption(
            "Map each system column to a PDF column. Sample data helps you verify the match."
        )

        h1, h2, h3, h4 = st.columns([1.35, 1.25, 1.35, 0.35])
        h1.markdown('<div class="map-header">System Column</div>', unsafe_allow_html=True)
        h2.markdown('<div class="map-header">PDF Column</div>', unsafe_allow_html=True)
        h3.markdown('<div class="map-header">Sample Data</div>', unsafe_allow_html=True)
        h4.markdown('<div class="map-header">Actions</div>', unsafe_allow_html=True)

        r1, r2, r3, r4 = st.columns([1.35, 1.25, 1.35, 0.35])
        with r1:
            st.markdown(
                '<div class="sys-label">Expiry Date Format</div>'
                '<div class="sys-desc">Format of the expiry date</div>',
                unsafe_allow_html=True,
            )
        with r2:
            default_fmt = metadata.get("expiry_date_format") or "MM/YYYY"
            fmt_index = (
                EXPIRY_FORMAT_OPTIONS.index(default_fmt)
                if default_fmt in EXPIRY_FORMAT_OPTIONS
                else 0
            )
            expiry_format = st.selectbox(
                "Expiry format",
                options=EXPIRY_FORMAT_OPTIONS,
                index=fmt_index,
                key="map_expiry_format",
                label_visibility="collapsed",
            )
        with r3:
            st.markdown(
                f'<div class="sample-text">{expiry_format}</div>',
                unsafe_allow_html=True,
            )
        with r4:
            st.write("")

        r1, r2, r3, r4 = st.columns([1.35, 1.25, 1.35, 0.35])
        with r1:
            inv_mapped = bool(metadata.get("invoice_number"))
            check = " ✓" if inv_mapped else ""
            st.markdown(
                f'<div class="sys-label">Invoice Number{check}</div>'
                '<div class="sys-desc">Invoice number from the purchase document</div>',
                unsafe_allow_html=True,
            )
        with r2:
            st.text_input(
                "Invoice number source",
                value=metadata.get("invoice_number") or "",
                disabled=True,
                key="map_invoice_number_display",
                label_visibility="collapsed",
            )
        with r3:
            sample = metadata.get("invoice_number") or "N/A"
            st.markdown(
                f'<div class="sample-text">{sample}</div>',
                unsafe_allow_html=True,
            )
        with r4:
            st.write("")

        st.divider()

        for field in SYSTEM_FIELDS:
            meta = SYSTEM_COLUMNS.get(field, {})
            label = meta.get("label", field)
            required = meta.get("required", False)
            description = meta.get("description", "")

            clear_key = f"clear_map_{field}"
            select_key = f"map_pdf_{field}"

            if st.session_state.get(clear_key):
                st.session_state[select_key] = ""
                st.session_state[clear_key] = False

            predicted_pdf = predicted_by_system.get(field, "")
            best_match = resolve_best_header_option(
                field=field,
                predicted_pdf=predicted_pdf,
                pdf_column_options=pdf_column_options,
                headers=headers,
                column_mappings=column_mappings,
            )
            if select_key not in st.session_state:
                st.session_state[select_key] = best_match

            current_selection = st.session_state.get(select_key, "")
            is_mapped = bool(current_selection)
            check = " ✓" if is_mapped else ""
            star = " *" if required else ""

            c1, c2, c3, c4 = st.columns([1.35, 1.25, 1.35, 0.35])
            with c1:
                st.markdown(
                    f'<div class="sys-label">{label}{star}{check}</div>'
                    f'<div class="sys-desc">{description}</div>',
                    unsafe_allow_html=True,
                )
            with c2:
                selection = st.selectbox(
                    f"pdf_col_{field}",
                    options=pdf_column_options,
                    key=select_key,
                    label_visibility="collapsed",
                    placeholder="Type to search PDF columns...",
                )
            with c3:
                if selection:
                    sample = sample_for_header(headers, all_rows, selection)
                    st.markdown(
                        f'<div class="sample-text">{sample}</div>',
                        unsafe_allow_html=True,
                    )
                else:
                    st.markdown(
                        '<div class="sample-empty">No column selected</div>',
                        unsafe_allow_html=True,
                    )
            with c4:
                if st.button("✕", key=f"btn_clear_{field}", help=f"Clear {label}"):
                    st.session_state[clear_key] = True
                    st.rerun()

            if selection:
                resolved = resolve_header(headers, selection)
                system_to_pdf[field] = resolved
                confirmed_mappings[resolved] = field

        missing_required = [
            SYSTEM_COLUMNS[f]["label"]
            for f in SYSTEM_FIELDS
            if SYSTEM_COLUMNS.get(f, {}).get("required") and f not in system_to_pdf
        ]

        save_left, save_right = st.columns([1, 1])
        with save_left:
            if st.button("Save as Supplier Template", type="primary"):
                if not supplier_key:
                    st.error(
                        "Cannot save template without a detected Supplier Name or GSTIN."
                    )
                else:
                    save_template(supplier_key, confirmed_mappings)
                    st.session_state["expiry_date_format"] = expiry_format
                    st.toast(f"Template saved for {supplier_key}")
                    st.rerun()
        with save_right:
            if missing_required:
                st.caption(
                    "Missing required: "
                    + ", ".join(missing_required[:6])
                    + ("…" if len(missing_required) > 6 else "")
                )

    with preview_col:
        st.markdown("##### PDF Preview")
        st.caption(uploaded_file.name)
        render_pdf_preview(pdf_bytes, filename=uploaded_file.name or "invoice.pdf")

    metadata = dict(metadata)
    metadata["expiry_date_format"] = (
        st.session_state.get("map_expiry_format")
        or metadata.get("expiry_date_format")
        or "MM/YYYY"
    )

    invoice_no = metadata.get("invoice_number") or "invoice"

    st.subheader("3. Structured Line Items Preview")
    if headers and all_rows and confirmed_mappings:
        normalized_rows = []
        for row in all_rows:
            padded = list(row) + [""] * max(0, len(headers) - len(row))
            normalized_rows.append(padded[: len(headers)])

        clean_df = build_clean_dataframe(
            headers,
            normalized_rows,
            confirmed_mappings=confirmed_mappings,
            fallback_column_mappings=column_mappings,
        )
        display_df = clean_df.copy()
        display_df.insert(0, "s.no", range(1, len(display_df) + 1))

        st.dataframe(display_df, use_container_width=True, hide_index=True)

        csv_bytes = display_df.to_csv(index=False).encode("utf-8")
        st.download_button(
            label="Download CSV",
            data=csv_bytes,
            file_name=f"{invoice_no}_purchase.csv",
            mime="text/csv",
        )
    else:
        clean_df = pd.DataFrame()
        st.info("No line items available to preview. Map at least Item Name to continue.")

    st.subheader("4. JSON Data Contract")
    payload = {
        "invoiceMetadata": metadata,
        "purchaseItems": clean_df.to_dict(orient="records") if not clean_df.empty else [],
    }
    json_bytes = json.dumps(payload, indent=2).encode("utf-8")
    st.download_button(
        label="Download JSON",
        data=json_bytes,
        file_name=f"{invoice_no}_purchase.json",
        mime="application/json",
    )
else:
    with tab_single:
        st.info("Upload a distributor invoice PDF to begin mapping and preview.")

with tab_batch:
    st.subheader("📦 Production Batch Invoice Processing Pipeline")
    st.caption("Process multi-invoice batches with automatic error isolation, duplicate detection, and SQLite persistence.")

    batch_mode = st.radio("Select Batch Input Source:", ["Upload Multiple PDFs", "Server / Local Folder Path"], horizontal=True)
    
    batch_pdf_paths = []
    
    if batch_mode == "Upload Multiple PDFs":
        batch_files = st.file_uploader(
            "Upload Batch PDF Invoices",
            type=["pdf"],
            accept_multiple_files=True,
            key="batch_pdf_uploader",
        )
        if batch_files:
            import tempfile
            temp_batch_dir = os.path.join(tempfile.gettempdir(), "mediastra_batch_uploads")
            os.makedirs(temp_batch_dir, exist_ok=True)
            for bf in batch_files:
                out_path = os.path.join(temp_batch_dir, bf.name)
                with open(out_path, "wb") as f:
                    f.write(bf.getvalue())
                batch_pdf_paths.append(out_path)
    else:
        folder_input = st.text_input("Folder Path Containing PDF Invoices:", placeholder="e.g. C:/Invoices or ./Sample Invoices")
        if folder_input and os.path.exists(folder_input):
            batch_pdf_paths = discover_pdf_files(folder_input)
            st.caption(f"Discovered {len(batch_pdf_paths)} PDF files in folder.")

    if batch_pdf_paths:
        if st.button("🚀 Start Batch Processing", type="primary"):
            storage_service = StorageService()
            progress_bar = st.progress(0.0)
            status_text = st.empty()

            def update_progress(current_idx, total_count, current_result):
                pct = current_idx / max(1, total_count)
                progress_bar.progress(pct)
                status_text.text(f"Processing ({current_idx}/{total_count}): {current_result.filename} - [{current_result.decision}]")

            batch_res = process_batch(
                batch_pdf_paths,
                storage_service=storage_service,
                progress_callback=update_progress,
            )
            progress_bar.progress(1.0)
            status_text.success(f"Batch completed in {batch_res.total_duration_sec:.2f}s!")

            # KPI Summary
            col1, col2, col3, col4, col5 = st.columns(5)
            col1.metric("Total Invoices", batch_res.total_documents)
            col2.metric("✅ Auto Accept", batch_res.auto_accept_count)
            col3.metric("⚠️ Review Required", batch_res.review_required_count)
            col4.metric("❓ Unresolved", batch_res.unresolved_count)
            col5.metric("❌ Failed", batch_res.failed_count)

            # Results Table
            st.subheader("Batch Results Summary")
            summary_rows = []
            for d in batch_res.document_results:
                summary_rows.append({
                    "Filename": d.filename,
                    "Supplier": d.supplier_name or "UNKNOWN",
                    "GSTIN": d.gstin or "N/A",
                    "Decision": d.decision,
                    "Confidence": f"{d.confidence:.1f}%",
                    "Rows": d.row_count,
                    "Time (s)": f"{d.duration_sec:.2f}",
                    "Duplicate": "Yes" if d.is_duplicate else "No",
                    "Error": d.error_message or "",
                })
            df_summary = pd.DataFrame(summary_rows)
            st.dataframe(df_summary, use_container_width=True)

            # Review Queue
            review_queue = [d for d in batch_res.document_results if d.decision in ("REVIEW_REQUIRED", "UNRESOLVED")]
            if review_queue:
                st.subheader(f"⚠️ Review Queue ({len(review_queue)} invoices requiring operator attention)")
                rq_df = pd.DataFrame([
                    {
                        "Filename": r.filename,
                        "Supplier": r.supplier_name,
                        "Decision": r.decision,
                        "Confidence": f"{r.confidence:.1f}%",
                        "Warnings": r.validation_warnings,
                    }
                    for r in review_queue
                ])
                st.dataframe(rq_df, use_container_width=True)

            # Export
            st.subheader("Batch Consolidated Export")
            csv_data = export_batch_results(batch_res, export_format="csv")
            json_data = export_batch_results(batch_res, export_format="json")

            c_exp1, c_exp2 = st.columns(2)
            c_exp1.download_button(
                label="📥 Download Consolidated CSV",
                data=csv_data,
                file_name=f"{batch_res.batch_id}_export.csv",
                mime="text/csv",
            )
            c_exp2.download_button(
                label="📥 Download Consolidated JSON",
                data=json_data,
                file_name=f"{batch_res.batch_id}_export.json",
                mime="application/json",
            )

# ------------------------------------------------------------------------------
# 3. TAB: EVALUATION & ERROR ANALYSIS (Prompt 12)
# ------------------------------------------------------------------------------
with tab_eval:
    st.header("📊 Real-World Invoice Evaluation & Error Analysis")
    st.markdown(
        "Diagnostic evaluation framework measuring extraction quality, field precision, row alignment, "
        "and pipeline stage error taxonomy across diverse invoice categories."
    )

    eval_res_path = os.path.join(os.path.dirname(__file__), "evaluation", "results", "evaluation_results.json")
    manifest_path = os.path.join(os.path.dirname(__file__), "evaluation", "manifest.json")

    eval_data = None
    if os.path.exists(eval_res_path):
        try:
            with open(eval_res_path, "r", encoding="utf-8") as f:
                eval_data = json.load(f)
        except Exception:
            pass

    col_btn, col_info = st.columns([1, 3])
    with col_btn:
        if st.button("▶ Run Full Evaluation", type="primary", use_container_width=True):
            with st.spinner("Executing evaluation across manifest invoices..."):
                try:
                    from evaluation.evaluator import InvoiceEvaluator
                    from evaluation.report_generator import EvaluationReportGenerator

                    evaluator = InvoiceEvaluator()
                    eval_data = evaluator.run_evaluation()
                    rep_gen = EvaluationReportGenerator()
                    rep_gen.save_json_results(eval_data)
                    rep_gen.generate_markdown_report(eval_data)
                    st.success("Evaluation complete! Results and reports updated.")
                except Exception as e:
                    st.error(f"Evaluation failed: {e}")

    if eval_data:
        # High-level KPIs
        kpi1, kpi2, kpi3, kpi4, kpi5 = st.columns(5)
        total_docs = eval_data.get("total_documents_evaluated", 0)
        dec_map = eval_data.get("decision_breakdown", {})
        auto_cnt = dec_map.get("AUTO_ACCEPT", 0)
        auto_pct = (auto_cnt / max(total_docs, 1)) * 100
        aa_safety = eval_data.get("auto_accept_safety", {})
        row_met = eval_data.get("row_metrics", {})
        avg_time = eval_data.get("average_document_time_ms", 0.0)

        kpi1.metric("Evaluated Invoices", total_docs)
        kpi2.metric("AUTO_ACCEPT Rate", f"{auto_pct:.1f}%")
        kpi3.metric("AUTO_ACCEPT Precision", f"{aa_safety.get('precision', 1.0)*100:.1f}%")
        kpi4.metric("Row Accuracy", f"{row_met.get('row_accuracy', 0.0)*100:.1f}%")
        kpi5.metric("Avg Duration", f"{avg_time:.0f} ms/doc")

        # Sub-tabs for deep diagnostics
        sub_overview, sub_fields, sub_mapping, sub_safety, sub_priorities = st.tabs([
            "📋 Overview & Decisions",
            "🔍 Field-Level Metrics",
            "🔀 Mapping Confusion Matrix",
            "🛡️ Safety & Decisions",
            "🎯 Engineering Priorities",
        ])

        with sub_overview:
            st.subheader("Dataset Summary & Decision Breakdown")
            cat_map = eval_data.get("dataset_categories", {})
            cat_df = pd.DataFrame([
                {
                    "Category": cat,
                    "Count": cnt,
                }
                for cat, cnt in cat_map.items()
            ])
            st.dataframe(cat_df, use_container_width=True)

            st.subheader("Evaluated Documents")
            docs_df = pd.DataFrame([
                {
                    "Filename": d.get("filename"),
                    "Category": d.get("dataset_category"),
                    "Supplier": d.get("supplier_name"),
                    "Decision": d.get("decision"),
                    "Confidence": f"{d.get('confidence', 0.0):.1f}%",
                    "Extracted Rows": d.get("extracted_row_count"),
                    "Expected Rows": d.get("expected_row_count"),
                    "Correct": "✅" if d.get("is_correct") else "⚠️",
                    "Time (ms)": f"{d.get('processing_time_ms', 0):.0f}",
                }
                for d in eval_data.get("documents", [])
            ])
            st.dataframe(docs_df, use_container_width=True)

        with sub_fields:
            st.subheader("Field-Level Extraction Precision, Recall & F1")
            f_metrics = eval_data.get("field_metrics", {})
            f_rows = []
            for f_name, fm in sorted(f_metrics.items()):
                if fm.get("total_ground_truth", 0) > 0 or fm.get("total_predictions", 0) > 0:
                    f_rows.append({
                        "Field": f_name,
                        "Ground Truth Items": fm.get("total_ground_truth", 0),
                        "Predictions": fm.get("total_predictions", 0),
                        "Exact Matches": fm.get("exact_matches", 0),
                        "Norm/Tol Matches": fm.get("tolerance_matches", 0) or fm.get("normalized_matches", 0),
                        "Precision": f"{fm.get('precision', 0.0):.2f}",
                        "Recall": f"{fm.get('recall', 0.0):.2f}",
                        "F1 Score": f"{fm.get('f1', 0.0):.2f}",
                    })
            if f_rows:
                st.dataframe(pd.DataFrame(f_rows), use_container_width=True)
            else:
                st.info("No field-level metrics recorded.")

        with sub_mapping:
            st.subheader("Semantic Column Mapping Confusion Matrix")
            conf_matrix = eval_data.get("column_mapping_confusion", {})
            conf_rows = []
            for exp, preds in conf_matrix.items():
                for pred, count in preds.items():
                    conf_rows.append({
                        "Expected Canonical Field": exp,
                        "Predicted Field": pred,
                        "Count": count,
                        "Status": "✅ Correct" if exp == pred else "⚠️ Misaligned",
                    })
            if conf_rows:
                st.dataframe(pd.DataFrame(conf_rows), use_container_width=True)
            else:
                st.info("No column mapping confusion detected.")

            st.subheader("Pipeline Stage Root-Cause Error Distribution")
            rc_dist = eval_data.get("root_cause_distribution", {})
            if rc_dist:
                rc_df = pd.DataFrame([
                    {"Root Cause Stage": k, "Defect Count": v}
                    for k, v in sorted(rc_dist.items(), key=lambda x: x[1], reverse=True)
                ])
                st.dataframe(rc_df, use_container_width=True)

        with sub_safety:
            st.subheader("AUTO_ACCEPT Safety & Calibration")
            c_s1, c_s2 = st.columns(2)
            with c_s1:
                st.markdown(f"- **Total AUTO_ACCEPT**: `{aa_safety.get('total_auto_accept', 0)}`")
                st.markdown(f"- **Verified Correct**: `{aa_safety.get('fully_correct', 0)}`")
                st.markdown(f"- **With Field Errors**: `{aa_safety.get('with_field_errors', 0)}`")
                st.markdown(f"- **With Row Errors**: `{aa_safety.get('with_row_errors', 0)}`")
            with c_s2:
                calibs = eval_data.get("confidence_calibration", [])
                st.dataframe(pd.DataFrame(calibs), use_container_width=True)

        with sub_priorities:
            st.subheader("🎯 Evidence-Backed Engineering Priorities")
            priorities = eval_data.get("engineering_priorities", [])
            for p in priorities:
                st.markdown(f"#### Priority {p.get('priority')}: {p.get('area')}")
                st.markdown(f"- **Measured Evidence**: {p.get('reason')}")
                st.markdown(f"- **Suggested Action**: {p.get('suggested_action')}")
                st.divider()
    else:
        st.info("No evaluation results available yet. Click 'Run Full Evaluation' to begin.")



    
