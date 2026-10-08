"""
MediAstra Pharma PDF Purchase Import Engine - Pharmacy Master Product Alias Engine
Resolves arbitrary supplier product descriptions to standardized internal pharmacy ERP item codes
using deterministic token normalization, supplier alias memory, and high-confidence fuzzy matching.
"""
import re
import logging
from typing import Optional, List, Dict, Any, Tuple
from rapidfuzz import fuzz

from storage import StorageService
from storage.models import PharmacyMasterItem, ProductAlias

logger = logging.getLogger(__name__)

# Common pharma dosage forms and packaging noise tokens to strip for core brand matching
FORMULATION_NOISE_REGEX = re.compile(
    r"(?i)\b("
    r"tablets?|tabs?|capsules?|caps?|syrups?|syp|injections?|inj|drops?|"
    r"ointments?|oint|gels?|creams?|suspensions?|susp|solutions?|soln|lotions?|"
    r"respules?|rotacaps?|inhalers?|mouthwash|spray|powder|infusion|vials?|ampoules?|amps?|"
    r"duo|sr|mr|cr|er|xl|ds|forte|plus|md|dt|"
    r"\d+\s*['x\*]\s*\d+s?|\d+['’]s|\d+s|\d+\s*(?:gm|ml|ltr|g)\b|"
    r"strip|strips|bottle|bottles|tube|tubes|pack|blister"
    r")\b"
)


def normalize_drug_name_tokens(raw_name: str) -> str:
    """
    Strips formulation suffixes, pack counts, and non-alphanumeric noise
    to extract the core brand/molecule token for high-accuracy matching.
    e.g. 'TELMA 40MG TAB 15S' -> 'TELMA 40MG'
         'AUGMENTIN 625 DUO TABLETS 10S' -> 'AUGMENTIN 625'
         'PAN-D CAPSULE (1X15)' -> 'PAN D'
    """
    if not raw_name:
        return ""

    text = str(raw_name).upper().strip()

    # Standardize strength formatting: '40 MG' -> '40MG', '1 GM' -> '1GM'
    text = re.sub(r"(\d+)\s+(MG|GM|MCG|ML|IU|G|MG/ML)\b", r"\1\2", text)

    # Remove special punctuation
    text = re.sub(r"[\(\)\[\]\{\}\/\\,\:\;\*\#\@\!\?]", " ", text)
    text = re.sub(r"[-_]", " ", text)

    # Remove formulation noise
    text = FORMULATION_NOISE_REGEX.sub(" ", text)

    # Collapse whitespace
    cleaned = re.sub(r"\s+", " ", text).strip()
    return cleaned if cleaned else raw_name.upper().strip()


def resolve_product_alias(
    raw_item_name: str,
    supplier_id: Optional[int] = None,
    storage_service: Optional[StorageService] = None,
    fuzzy_threshold: float = 75.0,
) -> Dict[str, Any]:
    """
    Resolves an extracted invoice item name to a pharmacy master ERP item code.
    1. Check supplier-specific exact alias in SQLite.
    2. Check global alias across all suppliers in SQLite.
    3. Perform high-confidence fuzzy token matching against pharmacy master catalog.
    4. Return structured resolution result.
    """
    raw_clean = re.sub(r"\s+", " ", str(raw_item_name or "")).strip()
    if not raw_clean:
        return {
            "original_name": "",
            "master_item_code": "",
            "master_item_name": "",
            "match_type": "UNRESOLVED",
            "match_score": 0.0,
            "is_resolved": False,
            "default_hsn": "",
            "default_gst_percent": 12.0,
        }

    norm_name = normalize_drug_name_tokens(raw_clean)

    if storage_service is None:
        storage_service = StorageService()

    # 1 & 2: Direct SQLite Alias Lookup (Supplier-Specific or Global)
    try:
        alias_record = storage_service.find_product_alias(raw_clean, supplier_id=supplier_id)
        if not alias_record and norm_name != raw_clean:
            alias_record = storage_service.find_product_alias(norm_name, supplier_id=supplier_id)

        if alias_record:
            match_type = "SUPPLIER_ALIAS" if (alias_record.supplier_id == supplier_id and supplier_id is not None) else "GLOBAL_ALIAS"
            # Fetch master item for HSN / GST defaults
            master_item = storage_service.get_master_item_by_code(alias_record.master_item_code)
            return {
                "original_name": raw_clean,
                "master_item_code": alias_record.master_item_code,
                "master_item_name": alias_record.master_item_name,
                "match_type": match_type,
                "match_score": round(alias_record.confidence * 100.0, 1),
                "is_resolved": True,
                "default_hsn": master_item.default_hsn if master_item else "30049099",
                "default_gst_percent": master_item.default_gst_percent if master_item else 12.0,
            }
    except Exception as e:
        logger.warning(f"Error checking product alias in storage: {e}")

    # 3: Fuzzy Matching against Master Catalog
    try:
        master_items = storage_service.list_master_items(limit=500)
        best_match = None
        best_score = 0.0

        for m_item in master_items:
            # Score 1: Token Sort Ratio on raw name vs master name
            s1 = fuzz.token_sort_ratio(raw_clean.upper(), m_item.item_name.upper())
            # Score 2: Token Sort Ratio on normalized name vs master normalized name
            s2 = fuzz.token_sort_ratio(norm_name, m_item.normalized_name)
            # Score 3: Token Set Ratio (handles subset words and variations well)
            s3 = fuzz.token_set_ratio(raw_clean.upper(), m_item.item_name.upper())
            s4 = fuzz.token_set_ratio(norm_name, m_item.normalized_name)
            # Score 5: Partial ratio for prefix/subset variations
            s5 = fuzz.partial_ratio(norm_name, m_item.normalized_name)

            # Score 6: Compare core brand and numbers with units stripped (e.g. TELMA 40 vs TELMA 40MG)
            core_input = re.sub(r"(?<=\d)(MG|GM|MCG|ML|IU|G)\b", "", norm_name).strip()
            core_master = re.sub(r"(?<=\d)(MG|GM|MCG|ML|IU|G)\b", "", m_item.normalized_name).strip()
            s_core = fuzz.token_sort_ratio(core_input, core_master) if core_input and core_master else 0.0

            combined_score = max(s1, s2, s3, s4, s_core, s5 if s5 >= 95 else 0.0)

            if combined_score > best_score:
                best_score = combined_score
                best_match = m_item

        if best_match and best_score >= fuzzy_threshold:
            return {
                "original_name": raw_clean,
                "master_item_code": best_match.item_code,
                "master_item_name": best_match.item_name,
                "match_type": "FUZZY_MATCH" if best_score < 99.0 else "EXACT_NAME_MATCH",
                "match_score": round(best_score, 1),
                "is_resolved": True,
                "default_hsn": best_match.default_hsn,
                "default_gst_percent": best_match.default_gst_percent,
            }
    except Exception as e:
        logger.warning(f"Error running fuzzy master matching: {e}")

    # 4: Unresolved Fallback
    return {
        "original_name": raw_clean,
        "master_item_code": "",
        "master_item_name": "",
        "match_type": "UNRESOLVED",
        "match_score": 0.0,
        "is_resolved": False,
        "default_hsn": "30049099",
        "default_gst_percent": 12.0,
    }


def resolve_invoice_row_aliases(
    rows: List[Dict[str, Any]],
    supplier_id: Optional[int] = None,
    storage_service: Optional[StorageService] = None,
) -> List[Dict[str, Any]]:
    """
    Enriches a list of extracted invoice item dictionaries with ERP master mapping fields:
    - master_item_code
    - master_item_name
    - alias_match_type
    - alias_match_score
    """
    if storage_service is None:
        storage_service = StorageService()

    enriched_rows = []
    for r in rows:
        row_copy = dict(r)
        item_name = (
            row_copy.get("itemName")
            or row_copy.get("product_name")
            or row_copy.get("item_name")
            or row_copy.get("description")
            or ""
        )
        if item_name:
            res = resolve_product_alias(item_name, supplier_id=supplier_id, storage_service=storage_service)
            row_copy["master_item_code"] = res["master_item_code"]
            row_copy["master_item_name"] = res["master_item_name"]
            row_copy["alias_match_type"] = res["match_type"]
            row_copy["alias_match_score"] = res["match_score"]
        else:
            row_copy["master_item_code"] = ""
            row_copy["master_item_name"] = ""
            row_copy["alias_match_type"] = "UNRESOLVED"
            row_copy["alias_match_score"] = 0.0

        enriched_rows.append(row_copy)

    return enriched_rows


def learn_product_alias(
    raw_alias: str,
    master_item_code: str,
    master_item_name: str,
    supplier_id: Optional[int] = None,
    storage_service: Optional[StorageService] = None,
    confidence: float = 1.0,
) -> ProductAlias:
    """
    Persists a confirmed mapping from a supplier product description to a master item code in SQLite.
    """
    if storage_service is None:
        storage_service = StorageService()

    # Find master item id
    master_item = storage_service.get_master_item_by_code(master_item_code)
    master_id = master_item.id if master_item else None

    alias = ProductAlias(
        raw_alias_text=raw_alias.strip(),
        normalized_alias=normalize_drug_name_tokens(raw_alias),
        supplier_id=supplier_id,
        master_item_id=master_id,
        master_item_code=master_item_code.strip(),
        master_item_name=master_item_name.strip(),
        confidence=confidence,
    )
    return storage_service.save_product_alias(alias)
