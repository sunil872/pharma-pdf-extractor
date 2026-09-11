import streamlit as st
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
    is_serial_number_header,
    compute_row_accounting,
    fix_column_bleeding,
)

st.set_page_config(page_title="Pharma PDF Purchase Import", layout="wide")

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
    </style>
    """,
    unsafe_allow_html=True,
)


def load_templates():
    if os.path.exists(TEMPLATE_FILE):
        with open(TEMPLATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_template(supplier_key, mapping):
    if not supplier_key:
        raise ValueError("supplier_key is required")
    templates = load_templates()
    templates[supplier_key] = mapping
    with open(TEMPLATE_FILE, "w", encoding="utf-8") as f:
        json.dump(templates, f, indent=2)


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
    num = first_number(val)
    if num is None:
        return 0.0
    return num if keep_sign else abs(num)


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


def build_clean_dataframe(headers, all_rows, confirmed_mappings):
    width = len(headers)
    normalized_rows = []
    for row in all_rows:
        padded = list(row) + [""] * max(0, width - len(row))
        normalized_rows.append(padded[:width])

    index_to_field = {}
    for idx, header in enumerate(headers):
        if is_serial_number_header(header):
            continue
        field = confirmed_mappings.get(header)
        if field:
            index_to_field[idx] = field

    records = []
    for row in normalized_rows:
        record = {}
        field_scores = {}
        for idx, field in index_to_field.items():
            val = row[idx] if idx < len(row) else ""
            score = _value_quality(field, val)
            if field not in record or score > field_scores.get(field, -999):
                record[field] = val
                field_scores[field] = score

        record = fix_column_bleeding(record)

        item = str(record.get("itemName") or "").strip()
        if not item or not re.search(r"[A-Za-z]{3,}", item):
            continue
        if item.count("  ") >= 3 and len(item) > 60:
            continue
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
                billed = num if num is not None else 0.0
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
                        merged_free.append(num if num is not None else 0.0)
            clean_df["freeQuantity"] = merged_free
        else:
            clean_df["freeQuantity"] = free_vals

    if "expiryDate" in clean_df.columns:
        clean_df["expiryDate"] = clean_df["expiryDate"].apply(standardize_date)

    for field in ("rate", "mrp", "amount", "taxableAmount", "netAmount"):
        if field in clean_df.columns:
            clean_df[field] = clean_df[field].apply(
                lambda v: first_number(v) if first_number(v) is not None else 0.0
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

    subset = [c for c in ("itemName", "batchNo", "quantity", "rate") if c in clean_df.columns]
    if subset:
        clean_df = clean_df.drop_duplicates(subset=subset, keep="first").reset_index(drop=True)

    ordered = [c for c in PREVIEW_COLUMN_ORDER if c in clean_df.columns]
    extras = [c for c in clean_df.columns if c not in ordered]
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
        if field_name and field_name not in inverted:
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
    return selected_label


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
    """Chrome-safe preview: open/download full PDF + image snapshots of all pages."""
    st.download_button(
        label="Open / Download full PDF",
        data=pdf_bytes,
        file_name=filename,
        mime="application/pdf",
        key="pdf_preview_download",
        help="Opens/downloads the complete multi-page invoice (works in Chrome).",
    )

    try:
        import pdfplumber

        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            total = len(pdf.pages)
            st.caption(f"{total} page(s) — scroll to review each page below")
            for i, page in enumerate(pdf.pages, start=1):
                st.markdown(f"**Page {i} of {total}**")
                page_image = page.to_image(resolution=100)
                st.image(page_image.original, use_container_width=True)
    except Exception as exc:
        st.warning(f"Could not render page snapshots: {exc}")


st.title("MediAstra - Offline PDF Purchase Import Engine")

templates = load_templates()

with st.sidebar:
    st.header("Cached Templates")
    st.metric("Total templates", len(templates))
    if templates:
        for key in templates.keys():
            st.caption(key)
    else:
        st.caption("No supplier templates saved yet.")

uploaded_file = st.file_uploader("Drop Distributor Invoice PDF", type=["pdf"])

if uploaded_file is not None:
    pdf_bytes = uploaded_file.getvalue()
    uploaded_file.seek(0)

    file_key = f"{uploaded_file.name}:{len(pdf_bytes)}"
    if st.session_state.get("_pdf_file_key") != file_key:
        st.session_state["_pdf_file_key"] = file_key
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
        st.caption(f"Detected automatically (confidence {float(conf):.0%}). You can edit above.")
    elif detected_supplier and supplier_name != detected_supplier:
        st.caption(f"Edited from detected name: {detected_supplier}")
    elif not detected_supplier:
        st.caption("Could not auto-detect supplier name — please type it in.")

    col1, col2, col3 = st.columns(3)
    col1.metric("Supplier GSTIN", metadata.get("supplier_gstin") or "—")
    col2.metric("Invoice Number", metadata.get("invoice_number") or "—")
    col3.metric("Invoice Date", metadata.get("invoice_date") or "—")

    # Persist edited name into metadata used for templates + JSON export.
    metadata = dict(metadata)
    metadata["supplier_name"] = supplier_name or None

    gstin = metadata.get("supplier_gstin")
    supplier_key = supplier_name or gstin
    if gstin:
        st.session_state["detected_gstin"] = gstin
    if supplier_name:
        st.session_state["detected_supplier_name"] = supplier_name

    if saved_template:
        st.success(
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
    map_col, preview_col = st.columns([1.35, 1], gap="large")

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
            predicted_label = (
                " ".join(str(predicted_pdf).replace("\n", " ").split()).strip()
                if predicted_pdf
                else ""
            )
            if select_key not in st.session_state:
                st.session_state[select_key] = (
                    predicted_label if predicted_label in pdf_column_options else ""
                )

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

        clean_df = build_clean_dataframe(headers, normalized_rows, confirmed_mappings)
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
    st.info("Upload a distributor invoice PDF to begin mapping and preview.")

    
