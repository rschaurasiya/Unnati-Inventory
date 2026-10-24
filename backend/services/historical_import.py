"""
Historical Sales Data Import & Normalization Pipeline Service
Provides secure, tabular file parsing (CSV, XLSX, XLS), intelligent column detection,
alias-based mapping, robust value normalization, catalog product matching,
duplicate fingerprinting, atomic transaction import, and complete rollback.
"""
import io
import re
import csv
import uuid
import hashlib
import tempfile
from pathlib import Path
from datetime import datetime, date, time, timedelta
from typing import Optional, List, Dict, Any, Tuple, Set

import openpyxl
from sqlalchemy.orm import Session
from sqlalchemy import func

from backend.models import (
    Product, DailySalesSummary,
    HistoricalImportBatch, HistoricalSaleRecord
)
from backend.schemas import (
    ValidationIssue, NormalizedSalePreview, ValidationSummary,
    UnmatchedProductInfo, ImportAnalyzeResponse,
    ConfirmImportResponse, RollbackImportResponse
)
from backend.services.sales_aggregation import aggregate_sales_for_date


# ============================================================
# 1. SECURITY & PROCESSING LIMITS
# ============================================================

MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB
MAX_ROWS_LIMIT = 50000
MAX_COLUMNS_LIMIT = 100
ALLOWED_EXTENSIONS = {".csv", ".xlsx", ".xls"}


# ============================================================
# 2. CENTRALIZED COLUMN ALIAS SYSTEM
# ============================================================

CANONICAL_ALIASES: Dict[str, List[str]] = {
    "date": [
        "date", "transaction date", "sale date", "invoice date", "billing date",
        "order date", "bill date", "txn date", "dated", "dt", "sales date",
        "posting date", "entry date"
    ],
    "product": [
        "item", "item name", "product", "product name", "product description",
        "description", "particulars", "item description", "commodity", "goods",
        "item title", "product title", "sku name", "item desc", "prod name"
    ],
    "quantity": [
        "qty", "quantity", "units sold", "units", "quantity sold", "volume",
        "count", "pcs", "quantities", "qty sold", "items sold", "amount sold",
        "sales qty", "sold qty"
    ],
    "price": [
        "price", "unit price", "rate", "selling price", "sale price", "mrp",
        "item price", "item rate", "rate per unit", "cost price", "sale rate",
        "unit rate"
    ],
    "total": [
        "total", "total amount", "amount", "total sale", "net amount", "line total",
        "final amount", "subtotal", "gross amount", "total price", "value",
        "sale amount", "turnover"
    ],
    "unit": [
        "unit", "uom", "unit of measure", "measure", "measurement", "metric"
    ],
    "transaction_id": [
        "transaction id", "invoice no", "invoice number", "bill no", "bill number",
        "order id", "txn id", "receipt no", "ref no", "reference", "voucher no",
        "invoice id", "bill id"
    ]
}

REQUIRED_CANONICAL_FIELDS = ["date", "product", "quantity"]


# In-memory staging storage with timestamp for TTL expiration
_STAGING_CACHE: Dict[str, Dict[str, Any]] = {}


# ============================================================
# 3. FILENAME & STRING SANITIZATION
# ============================================================

def sanitize_filename(filename: str) -> str:
    """
    Sanitizes untrusted filename to prevent path traversal and shell injection.
    Strips directory separators, null bytes, and non-whitelisted characters.
    """
    if not filename:
        return f"import_{uuid.uuid4().hex[:8]}.csv"
    # Extract only basename (handles both Windows and Unix path separators)
    clean = Path(filename).name
    # Strip null bytes and dangerous control chars
    clean = re.sub(r'[\x00-\x1f\x7f]', '', clean)
    # Remove path traversal tokens
    clean = clean.replace("..", "").replace("/", "").replace("\\", "").strip()
    if not clean:
        clean = f"import_{uuid.uuid4().hex[:8]}.csv"
    return clean


def normalize_column_name(col: str) -> str:
    """
    Normalizes column headers for robust, case-insensitive comparison.
    Handles:
      - Lowercase conversion
      - Leading/trailing whitespace
      - Underscores and hyphens replaced by single spaces
      - Punctuation removed
      - Repeated whitespace collapsed
    """
    if not col:
        return ""
    c = str(col).strip().lower()
    c = re.sub(r'[\-_\.\:\#\/\\\,]+', ' ', c)
    c = re.sub(r'\s+', ' ', c).strip()
    return c


# ============================================================
# 4. INTELLIGENT COLUMN DETECTION & MAPPING
# ============================================================

def detect_column_mapping(columns: List[str]) -> Tuple[Dict[str, Optional[str]], Dict[str, List[str]], List[str], List[str]]:
    """
    Intelligently maps file columns to internal canonical fields.
    Returns:
      - detected_mapping: {canonical_field: best_matching_raw_column_or_None}
      - ambiguous_columns: {canonical_field: [candidate_raw_columns]}
      - missing_required: [missing_required_fields]
      - ignored_columns: [columns_not_mapped_to_any_field]
    """
    norm_to_raw = {normalize_column_name(col): col for col in columns if col}
    norm_cols = list(norm_to_raw.keys())

    detected_mapping: Dict[str, Optional[str]] = {}
    ambiguous_columns: Dict[str, List[str]] = {}
    used_raw_cols: Set[str] = set()

    for field, aliases in CANONICAL_ALIASES.items():
        candidates: List[Tuple[float, str]] = []  # (score, raw_col)

        for norm_col in norm_cols:
            raw_col = norm_to_raw[norm_col]

            # 1. Exact alias match (score: 2.0)
            if norm_col in aliases:
                candidates.append((2.0, raw_col))
                continue

            # 2. Word boundary / exact substring match (score: 1.0)
            for alias in aliases:
                # e.g., "sales date" has "date"
                pattern = r'\b' + re.escape(alias) + r'\b'
                if re.search(pattern, norm_col):
                    candidates.append((1.0, raw_col))
                    break

        if not candidates:
            detected_mapping[field] = None
        elif len(candidates) == 1:
            detected_mapping[field] = candidates[0][1]
            used_raw_cols.add(candidates[0][1])
        else:
            # Sort by score descending
            candidates.sort(key=lambda x: x[0], reverse=True)
            top_score = candidates[0][0]
            top_candidates = [c[1] for c in candidates if c[0] == top_score]

            if len(top_candidates) == 1:
                detected_mapping[field] = top_candidates[0]
                used_raw_cols.add(top_candidates[0])
            else:
                # Multiple candidates tie for top score: ambiguous!
                ambiguous_columns[field] = top_candidates
                detected_mapping[field] = None

    # Check for missing required columns
    missing_required = [
        rf for rf in REQUIRED_CANONICAL_FIELDS
        if not detected_mapping.get(rf) and rf not in ambiguous_columns
    ]

    # Detect ignored columns (e.g. Customer Phone, Address, GST, Notes)
    ignored_columns = [col for col in columns if col not in used_raw_cols]

    return detected_mapping, ambiguous_columns, missing_required, ignored_columns


# ============================================================
# 5. VALUE NORMALIZERS (DATE, QUANTITY, PRICE)
# ============================================================

def parse_and_normalize_date(val: Any) -> Tuple[Optional[date], Optional[str], Optional[str]]:
    """
    Parses and normalizes sales date across common formats.
    Returns: (parsed_date, warning_message, error_message)
    Supports:
      - ISO: YYYY-MM-DD
      - DD-MM-YYYY, DD/MM/YYYY
      - MM/DD/YYYY (flagged if ambiguous)
      - DD Mon YYYY (e.g. 28 Sep 2026)
      - Python datetime/date objects
      - Timestamps (YYYY-MM-DD HH:MM:SS)
      - Excel float date serials
    """
    if val is None or str(val).strip() == "":
        return None, None, "Date value is empty."

    # Direct date/datetime object
    if isinstance(val, datetime):
        d = val.date()
        if d > date.today():
            return None, None, f"Future date '{d.isoformat()}' is not permitted."
        return d, None, None

    if isinstance(val, date):
        if val > date.today():
            return None, None, f"Future date '{val.isoformat()}' is not permitted."
        return val, None, None

    # Excel date serial (float/int, e.g. 45563)
    if isinstance(val, (int, float)) and not isinstance(val, bool):
        try:
            # Excel base date is 1899-12-30
            excel_epoch = datetime(1899, 12, 30)
            d = (excel_epoch + timedelta(days=float(val))).date()
            if d > date.today():
                return None, None, f"Future date '{d.isoformat()}' is not permitted."
            return d, None, None
        except Exception:
            return None, None, f"Invalid Excel date serial '{val}'."

    s = str(val).strip()

    # If timestamp with time (contains colon), split date part
    if " " in s and ":" in s:
        s = s.split(" ")[0].strip()
    elif "T" in s and ":" in s:
        s = s.split("T")[0].strip()

    # Known format patterns
    date_formats = [
        ("%Y-%m-%d", False),
        ("%Y/%m/%d", False),
        ("%d-%m-%Y", False),
        ("%d/%m/%Y", False),
        ("%d %b %Y", False),
        ("%d %B %Y", False),
        ("%d-%b-%Y", False),
        ("%d-%B-%Y", False),
        ("%m/%d/%Y", True),  # US format: flag potential ambiguity
        ("%m-%d-%Y", True),
    ]

    for fmt, is_us_format in date_formats:
        try:
            parsed = datetime.strptime(s, fmt).date()

            # Reject future sales
            if parsed > date.today():
                return None, None, f"Future date '{s}' ({parsed.isoformat()}) is not permitted."

            # Check ambiguity for numeric date where both day and month <= 12
            warning = None
            if is_us_format:
                parts = re.split(r'[\/\-]', s)
                if len(parts) >= 2:
                    try:
                        p1, p2 = int(parts[0]), int(parts[1])
                        if p1 <= 12 and p2 <= 12:
                            warning = f"Ambiguous date format '{s}': interpreted as MM/DD/YYYY ({parsed.isoformat()})."
                    except ValueError:
                        pass

            return parsed, warning, None
        except ValueError:
            continue

    return None, None, f"Unrecognized date format: '{s}'."


def normalize_quantity(val: Any, expected_unit: Optional[str] = None) -> Tuple[Optional[float], Optional[str], Optional[str], Optional[str]]:
    """
    Normalizes numeric and string quantity values.
    Returns: (normalized_quantity, parsed_unit, warning_message, error_message)
    Examples:
      - 2 -> (2.0, None, None, None)
      - "2 kg" -> (2.0, "kg", None, None)
      - "500 g" (expected_unit="kg") -> (0.5, "kg", None, None)
      - "500 ml" (expected_unit="litre") -> (0.5, "litre", None, None)
    """
    if val is None or str(val).strip() == "":
        return None, None, None, "Quantity is missing or empty."

    if isinstance(val, (int, float)) and not isinstance(val, bool):
        q = float(val)
        if q <= 0:
            return None, None, None, f"Quantity must be strictly positive (got {q})."
        warning = "Unusually large quantity (> 10,000 units)." if q > 10000 else None
        return q, expected_unit or "unit", warning, None

    s = str(val).strip()
    # Extract number and possible unit string
    match = re.match(r'^([\+\-]?[0-9]+(?:\.[0-9]+)?)\s*([a-zA-Z]+)?$', s)
    if not match:
        return None, None, None, f"Malformed numeric quantity: '{s}'."

    raw_num, raw_unit = match.group(1), match.group(2)
    try:
        qty = float(raw_num)
    except ValueError:
        return None, None, None, f"Invalid quantity number: '{raw_num}'."

    if qty <= 0:
        return None, None, None, f"Quantity must be strictly positive (got {qty})."

    unit = (raw_unit.lower() if raw_unit else expected_unit) or "unit"
    warning = None

    # Handle standard sub-unit conversions (grams to kg, ml to litre)
    exp_u = (expected_unit or "").lower()
    if unit in ["g", "gm", "gram", "grams"]:
        if exp_u in ["kg", "kilogram", "kilo"]:
            qty = round(qty / 1000.0, 4)
            unit = "kg"
        else:
            unit = "g"
    elif unit in ["ml", "millilitre", "milliliter"]:
        if exp_u in ["litre", "liter", "l"]:
            qty = round(qty / 1000.0, 4)
            unit = "litre"
        else:
            unit = "ml"

    # Flag incompatible unit conflict
    if exp_u and unit != "unit" and unit != exp_u:
        # e.g., file says "kg" but product is "piece" or "packet"
        if exp_u in ["piece", "packet", "dozen"] and unit in ["kg", "g", "litre"]:
            warning = f"Unit mismatch: file specifies '{unit}' but product expects '{exp_u}'."

    if qty > 10000:
        warning = f"Unusually large quantity ({qty} {unit})."

    return qty, unit, warning, None


def normalize_price(val: Any, default_unit_price: float = 0.0) -> Tuple[Optional[float], Optional[str], Optional[str]]:
    """
    Normalizes monetary price values.
    Returns: (normalized_price, warning_message, error_message)
    Supports: 120, 120.00, ₹120, Rs.120, Rs 120, INR 120, 1,200.50
    """
    if val is None or str(val).strip() == "":
        # Price is optional; fall back to catalog price
        return default_unit_price, "Unit price missing; defaulted to catalog unit price.", None

    if isinstance(val, (int, float)) and not isinstance(val, bool):
        p = round(float(val), 2)
        if p < 0:
            return None, None, f"Price cannot be negative (got {p})."
        return p, None, None

    s = str(val).strip()
    # Strip currency symbols and letters
    clean = re.sub(r'[₹$€£\s]|(?:rs\.?|inr)', '', s, flags=re.IGNORECASE)
    # Remove comma separators
    clean = clean.replace(',', '').strip()

    try:
        p = round(float(clean), 2)
        if p < 0:
            return None, None, f"Price cannot be negative (got {p})."
        return p, None, None
    except ValueError:
        return None, None, f"Malformed monetary price: '{s}'."


# ============================================================
# 6. PRODUCT MATCHING ENGINE
# ============================================================

def _token_similarity(s1: str, s2: str) -> float:
    """Calculates simple Jaccard / token set similarity between two product names."""
    tokens1 = set(re.findall(r'\w+', s1.lower()))
    tokens2 = set(re.findall(r'\w+', s2.lower()))
    if not tokens1 or not tokens2:
        return 0.0
    intersection = tokens1.intersection(tokens2)
    union = tokens1.union(tokens2)
    return len(intersection) / len(union)


def match_product(
    raw_name: str,
    catalog_products: List[Product],
    user_mappings: Optional[Dict[str, int]] = None
) -> Tuple[Optional[Product], float, str]:
    """
    Matches raw imported product name against catalog products.
    Strategy hierarchy:
      1. User manual mapping override
      2. Exact match (case-insensitive)
      3. Alias match (from product.aliases)
      4. Hindi name match
      5. Normalized match (strip size descriptors like 1kg, 500g, packet)
      6. Fuzzy token match (threshold >= 0.85; protects against Milk vs Milk Powder)
    Returns: (matched_product, confidence_score, match_type)
    """
    if not raw_name or not str(raw_name).strip():
        return None, 0.0, "UNMATCHED"

    clean_raw = str(raw_name).strip()
    raw_lower = clean_raw.lower()

    # 1. User manual override
    if user_mappings and clean_raw in user_mappings:
        target_id = user_mappings[clean_raw]
        target = next((p for p in catalog_products if p.id == target_id), None)
        if target:
            return target, 1.0, "MANUAL"

    # 2. Exact match
    for prod in catalog_products:
        if prod.name.strip().lower() == raw_lower:
            return prod, 1.0, "EXACT"

    # 3. Alias match
    for prod in catalog_products:
        if prod.aliases:
            aliases = [a.strip().lower() for a in prod.aliases.split(",") if a.strip()]
            if raw_lower in aliases:
                return prod, 0.98, "ALIAS"

    # 4. Hindi name match
    for prod in catalog_products:
        if prod.hindi_name and prod.hindi_name.strip().lower() == raw_lower:
            return prod, 0.95, "HINDI"

    # 5. Normalized match (strip common weight/packaging descriptors)
    # e.g., "Tata Salt 1kg" -> "tata salt"
    stripped_raw = re.sub(r'\b(?:\d+(?:\.\d+)?\s*(?:kg|g|gm|litre|l|ml|pack|packet|pouch|pcs))\b', '', raw_lower)
    stripped_raw = re.sub(r'[\W_]+', ' ', stripped_raw).strip()

    if stripped_raw and stripped_raw != raw_lower:
        for prod in catalog_products:
            prod_norm = re.sub(r'\b(?:\d+(?:\.\d+)?\s*(?:kg|g|gm|litre|l|ml|pack|packet|pouch|pcs))\b', '', prod.name.lower())
            prod_norm = re.sub(r'[\W_]+', ' ', prod_norm).strip()
            if prod_norm == stripped_raw:
                return prod, 0.92, "NORMALIZED"

    # 6. Fuzzy token matching with confusion protection
    best_prod = None
    best_score = 0.0

    for prod in catalog_products:
        score = _token_similarity(raw_lower, prod.name.lower())

        # Anti-confusion check: do NOT map "Milk" to "Milk Powder"
        # If one has "powder" or "oil" or "salt" and the other doesn't, reject
        critical_words = {"powder", "refined", "mustard", "sarson", "atta", "maida", "besan"}
        raw_words = set(re.findall(r'\w+', raw_lower))
        prod_words = set(re.findall(r'\w+', prod.name.lower()))
        diff_words = (raw_words ^ prod_words).intersection(critical_words)
        if diff_words:
            # Penalize heavily
            score *= 0.3

        if score > best_score:
            best_score = score
            best_prod = prod

    if best_prod and best_score >= 0.85:
        return best_prod, round(best_score, 2), "FUZZY"

    return None, round(best_score, 2), "UNMATCHED"


# ============================================================
# 7. ROW FINGERPRINTING (DEDUPLICATION PROTECTION)
# ============================================================

def generate_row_fingerprint(
    sale_date: date,
    product_id: int,
    quantity: float,
    total_amount: float,
    transaction_id: Optional[str] = None
) -> str:
    """
    Computes deterministic SHA-256 fingerprint for deduplication.
    Incorporates transaction_id if present; otherwise uses normalized date, product, qty, and total.
    """
    if transaction_id and str(transaction_id).strip():
        clean_tx = str(transaction_id).strip().upper()
        payload = f"TX:{clean_tx}:{sale_date.isoformat()}:{product_id}:{round(quantity, 3)}:{round(total_amount, 2)}"
    else:
        payload = f"ROW:{sale_date.isoformat()}:{product_id}:{round(quantity, 3)}:{round(total_amount, 2)}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# ============================================================
# 8. TABULAR FILE PARSING (CSV, XLSX, XLS)
# ============================================================

def parse_file_to_rows(file_bytes: bytes, filename: str) -> Tuple[List[str], List[Dict[str, Any]], str]:
    """
    Safely parses CSV, XLSX, or XLS byte stream into column headers and row dictionaries.
    Enforces maximum size, row limit, and column limit.
    Returns: (headers, rows, file_type)
    """
    if len(file_bytes) > MAX_FILE_SIZE_BYTES:
        raise ValueError(f"File size ({round(len(file_bytes) / (1024*1024), 2)} MB) exceeds maximum limit of 10 MB.")

    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise ValueError(f"Unsupported file extension '{ext}'. Only CSV, XLSX, and XLS formats are supported.")

    headers: List[str] = []
    rows: List[Dict[str, Any]] = []
    file_type = ext.replace(".", "").upper()

    if ext == ".csv":
        # Decode CSV with BOM and encoding fallback
        text = None
        for enc in ["utf-8-sig", "utf-8", "latin-1", "cp1252"]:
            try:
                text = file_bytes.decode(enc)
                break
            except UnicodeDecodeError:
                continue

        if text is None:
            raise ValueError("Unable to decode CSV file. Please ensure it is saved in UTF-8 format.")

        stream = io.StringIO(text)
        # Delimiter sniffing (comma, tab, semicolon, pipe)
        first_line = stream.readline()
        stream.seek(0)

        delimiter = ","
        for cand in [",", "\t", ";", "|"]:
            if cand in first_line:
                delimiter = cand
                break

        reader = csv.reader(stream, delimiter=delimiter)
        raw_rows = list(reader)

        if not raw_rows:
            raise ValueError("The uploaded CSV file is empty.")

        headers = [str(h) for h in raw_rows[0] if str(h).strip()]
        if len(headers) > MAX_COLUMNS_LIMIT:
            raise ValueError(f"File contains {len(headers)} columns, exceeding maximum limit of {MAX_COLUMNS_LIMIT}.")

        for line_idx, r in enumerate(raw_rows[1:], start=2):
            if not any(r):  # skip blank lines
                continue
            row_dict = {}
            for col_idx, h in enumerate(headers):
                val = r[col_idx] if col_idx < len(r) else None
                row_dict[h] = val
            rows.append(row_dict)

            if len(rows) > MAX_ROWS_LIMIT:
                raise ValueError(f"File exceeds maximum allowed limit of {MAX_ROWS_LIMIT} rows.")

    elif ext == ".xlsx":
        try:
            wb = openpyxl.load_workbook(io.BytesIO(file_bytes), read_only=True, data_only=True)
            sheet = wb.active
            if not sheet:
                raise ValueError("Excel file contains no active worksheet.")

            sheet_iter = sheet.iter_rows(values_only=True)
            header_row = next(sheet_iter, None)
            if not header_row:
                raise ValueError("Excel worksheet is empty.")

            headers = [str(h).strip() for h in header_row if h is not None and str(h).strip()]
            if len(headers) > MAX_COLUMNS_LIMIT:
                raise ValueError(f"Excel file contains {len(headers)} columns, exceeding maximum limit of {MAX_COLUMNS_LIMIT}.")

            for r in sheet_iter:
                if not any(r):
                    continue
                row_dict = {}
                for col_idx, h in enumerate(headers):
                    val = r[col_idx] if col_idx < len(r) else None
                    row_dict[h] = val
                rows.append(row_dict)

                if len(rows) > MAX_ROWS_LIMIT:
                    wb.close()
                    raise ValueError(f"Excel file exceeds maximum allowed limit of {MAX_ROWS_LIMIT} rows.")

            wb.close()
        except Exception as e:
            if isinstance(e, ValueError):
                raise
            raise ValueError(f"Error parsing XLSX file: {str(e)}")

    elif ext == ".xls":
        try:
            import xlrd
            wb = xlrd.open_workbook(file_contents=file_bytes)
            sheet = wb.sheet_by_index(0)
            if sheet.nrows == 0:
                raise ValueError("XLS worksheet is empty.")

            headers = [str(sheet.cell_value(0, c)).strip() for c in range(sheet.ncols) if str(sheet.cell_value(0, c)).strip()]
            for r in range(1, sheet.nrows):
                row_dict = {
                    headers[c]: sheet.cell_value(r, c)
                    for c in range(min(len(headers), sheet.ncols))
                }
                rows.append(row_dict)
                if len(rows) > MAX_ROWS_LIMIT:
                    raise ValueError(f"XLS file exceeds maximum allowed limit of {MAX_ROWS_LIMIT} rows.")
        except ImportError:
            raise ValueError("Legacy .xls format requires the 'xlrd' library. Please save your spreadsheet as .xlsx or .csv and re-upload.")
        except Exception as e:
            if isinstance(e, ValueError):
                raise
            raise ValueError(f"Error parsing XLS file: {str(e)}")

    return headers, rows, file_type


# ============================================================
# 9. STAGING & ANALYSIS ENGINE
# ============================================================

def analyze_and_stage_file(
    file_bytes: bytes,
    filename: str,
    db: Session,
    custom_mapping: Optional[Dict[str, str]] = None,
    product_mappings: Optional[Dict[str, int]] = None
) -> ImportAnalyzeResponse:
    """
    Parses file, detects column mapping, validates and normalizes all rows,
    identifies warnings and errors, produces preview, and stages the batch in memory.
    Zero database records are written at this stage.
    """
    safe_name = sanitize_filename(filename)
    headers, rows, file_type = parse_file_to_rows(file_bytes, safe_name)

    # 1. Column detection
    detected_mapping, ambiguous_cols, missing_required, ignored_cols = detect_column_mapping(headers)

    # Apply custom mapping overrides if provided by user
    if custom_mapping:
        for k, v in custom_mapping.items():
            if v in headers:
                detected_mapping[k] = v
                if k in ambiguous_cols:
                    del ambiguous_cols[k]

    # Re-check missing required fields after overrides
    missing_required = [
        rf for rf in REQUIRED_CANONICAL_FIELDS
        if not detected_mapping.get(rf) and rf not in ambiguous_cols
    ]

    import_id = f"IMP-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6].upper()}"

    # If missing required fields or unresolved ambiguous columns, stop and return diagnostics
    if missing_required or ambiguous_cols:
        status_code = "AMBIGUOUS_COLUMNS" if ambiguous_cols else "MISSING_REQUIRED_COLUMNS"
        msg = (
            f"Unable to automatically identify required fields: {', '.join(missing_required)}. "
            if missing_required else
            f"Ambiguous column candidates detected for {list(ambiguous_cols.keys())}. User selection required."
        )
        return ImportAnalyzeResponse(
            status=status_code,
            import_id=import_id,
            filename=safe_name,
            file_type=file_type,
            file_size_bytes=len(file_bytes),
            total_rows=len(rows),
            total_columns=len(headers),
            detected_columns=headers,
            detected_mapping=detected_mapping,
            ambiguous_columns=ambiguous_cols,
            missing_required_columns=missing_required,
            ignored_columns=ignored_cols,
            validation_summary=ValidationSummary(
                total_rows=len(rows),
                valid_rows=0,
                warning_rows=0,
                invalid_rows=len(rows)
            ),
            sample_preview=[],
            unmatched_products=[],
            errors=[ValidationIssue(row=0, field="columns", message=msg, severity="ERROR")],
            warnings=[],
            is_ready_for_import=False,
            message=msg
        )

    # 2. Extract catalog products for matching
    catalog_products = db.query(Product).all()

    # Column references from mapping
    col_date = detected_mapping.get("date")
    col_prod = detected_mapping.get("product")
    col_qty = detected_mapping.get("quantity")
    col_price = detected_mapping.get("price")
    col_total = detected_mapping.get("total")
    col_unit = detected_mapping.get("unit")
    col_txid = detected_mapping.get("transaction_id")

    valid_records: List[Dict[str, Any]] = []
    errors: List[ValidationIssue] = []
    warnings: List[ValidationIssue] = []
    sample_preview: List[NormalizedSalePreview] = []
    unmatched_tracker: Dict[str, Dict[str, Any]] = {}  # {raw_name: {count, suggestion}}

    unique_dates: Set[date] = set()

    # 3. Row-by-row validation & normalization
    for idx, row in enumerate(rows, start=1):
        row_warnings: List[str] = []
        is_row_valid = True

        # Field: Date
        raw_date_val = row.get(col_date)
        parsed_d, d_warn, d_err = parse_and_normalize_date(raw_date_val)
        if d_err:
            errors.append(ValidationIssue(row=idx, field="date", value=str(raw_date_val), message=d_err, severity="ERROR"))
            is_row_valid = False
        else:
            unique_dates.add(parsed_d)
            if d_warn:
                row_warnings.append(d_warn)
                warnings.append(ValidationIssue(row=idx, field="date", value=str(raw_date_val), message=d_warn, severity="WARNING"))

        # Field: Product
        raw_prod_name = row.get(col_prod)
        matched_prod, confidence, match_type = match_product(
            str(raw_prod_name or ""),
            catalog_products,
            user_mappings=product_mappings
        )

        if not matched_prod:
            errors.append(ValidationIssue(
                row=idx,
                field="product",
                value=str(raw_prod_name),
                message=f"Product '{raw_prod_name}' not found in store catalog.",
                severity="ERROR"
            ))
            is_row_valid = False

            # Track unmatched for user resolution
            clean_p = str(raw_prod_name or "").strip()
            if clean_p:
                if clean_p not in unmatched_tracker:
                    unmatched_tracker[clean_p] = {"count": 1, "suggestion": None, "confidence": 0.0}
                else:
                    unmatched_tracker[clean_p]["count"] += 1
        elif match_type == "FUZZY":
            row_warnings.append(f"Fuzzy matched to '{matched_prod.name}' ({int(confidence*100)}% confidence).")

        # Field: Quantity
        raw_qty_val = row.get(col_qty)
        exp_unit = matched_prod.unit if matched_prod else None
        qty, unit, q_warn, q_err = normalize_quantity(raw_qty_val, expected_unit=exp_unit)
        if q_err:
            errors.append(ValidationIssue(row=idx, field="quantity", value=str(raw_qty_val), message=q_err, severity="ERROR"))
            is_row_valid = False
        else:
            if q_warn:
                row_warnings.append(q_warn)
                warnings.append(ValidationIssue(row=idx, field="quantity", value=str(raw_qty_val), message=q_warn, severity="WARNING"))

        # Field: Price & Total
        raw_price_val = row.get(col_price) if col_price else None
        def_price = matched_prod.unit_price if matched_prod else 0.0
        price, p_warn, p_err = normalize_price(raw_price_val, default_unit_price=def_price)
        if p_err:
            errors.append(ValidationIssue(row=idx, field="price", value=str(raw_price_val), message=p_err, severity="ERROR"))
            is_row_valid = False
        else:
            if p_warn:
                row_warnings.append(p_warn)
                warnings.append(ValidationIssue(row=idx, field="price", value=str(raw_price_val), message=p_warn, severity="WARNING"))

        # Compute or validate Total
        raw_total_val = row.get(col_total) if col_total else None
        if raw_total_val is not None and str(raw_total_val).strip() != "":
            total_amt, _, t_err = normalize_price(raw_total_val, default_unit_price=round((qty or 0.0) * (price or 0.0), 2))
            if t_err:
                errors.append(ValidationIssue(row=idx, field="total", value=str(raw_total_val), message=t_err, severity="ERROR"))
                is_row_valid = False
        else:
            total_amt = round((qty or 0.0) * (price or 0.0), 2)

        # Field: Transaction ID
        tx_id = str(row.get(col_txid) or "").strip() if col_txid else None

        # Build normalized preview item
        if is_row_valid and parsed_d and matched_prod and qty is not None and price is not None:
            norm_record = {
                "row_index": idx,
                "sale_date": parsed_d,
                "product_id": matched_prod.id,
                "raw_product_name": str(raw_prod_name),
                "quantity": qty,
                "unit": unit or matched_prod.unit,
                "unit_price": price,
                "total_amount": total_amt,
                "transaction_id": tx_id,
                "row_fingerprint": generate_row_fingerprint(parsed_d, matched_prod.id, qty, total_amt, tx_id),
                "warnings": row_warnings
            }
            valid_records.append(norm_record)

            if len(sample_preview) < 10:
                sample_preview.append(NormalizedSalePreview(
                    row=idx,
                    sale_date=parsed_d.isoformat(),
                    raw_product_name=str(raw_prod_name),
                    matched_product_id=matched_prod.id,
                    matched_product_name=matched_prod.name,
                    match_confidence=confidence,
                    match_type=match_type,
                    quantity=qty,
                    unit=unit or matched_prod.unit,
                    unit_price=price,
                    total_amount=total_amt,
                    transaction_id=tx_id,
                    warnings=row_warnings
                ))

    # Compile unmatched products summary
    unmatched_list = [
        UnmatchedProductInfo(
            raw_name=name,
            occurrence_count=info["count"],
            suggested_product_id=info["suggestion"],
            confidence=info["confidence"]
        )
        for name, info in unmatched_tracker.items()
    ]

    valid_count = len(valid_records)
    invalid_count = len(rows) - valid_count
    warning_count = len(warnings)

    earliest = min(unique_dates).isoformat() if unique_dates else None
    latest = max(unique_dates).isoformat() if unique_dates else None
    usable_days = len(unique_dates)

    summary = ValidationSummary(
        total_rows=len(rows),
        valid_rows=valid_count,
        warning_rows=warning_count,
        invalid_rows=invalid_count,
        earliest_date=earliest,
        latest_date=latest,
        usable_days_count=usable_days
    )

    # Stage the valid records in memory cache
    _STAGING_CACHE[import_id] = {
        "import_id": import_id,
        "filename": safe_name,
        "file_type": file_type,
        "file_size_bytes": len(file_bytes),
        "total_rows": len(rows),
        "valid_records": valid_records,
        "invalid_count": invalid_count,
        "warning_count": warning_count,
        "unique_dates": [d.isoformat() for d in unique_dates],
        "earliest_date": earliest,
        "latest_date": latest,
        "usable_days_count": usable_days,
        "column_mapping": detected_mapping,
        "staged_at": datetime.utcnow()
    }

    is_ready = (valid_count > 0)
    status_msg = (
        f"Validation complete: {valid_count} valid rows, {invalid_count} invalid rows, {warning_count} warnings."
        if is_ready else
        f"Validation failed: No valid rows identified. {invalid_count} rows have critical errors."
    )

    return ImportAnalyzeResponse(
        status="READY" if is_ready else "NO_VALID_DATA",
        import_id=import_id,
        filename=safe_name,
        file_type=file_type,
        file_size_bytes=len(file_bytes),
        total_rows=len(rows),
        total_columns=len(headers),
        detected_columns=headers,
        detected_mapping=detected_mapping,
        ambiguous_columns={},
        missing_required_columns=[],
        ignored_columns=ignored_cols,
        validation_summary=summary,
        sample_preview=sample_preview,
        unmatched_products=unmatched_list,
        errors=errors[:100],  # cap to top 100 for responsive payload
        warnings=warnings[:100],
        is_ready_for_import=is_ready,
        message=status_msg
    )


# ============================================================
# 10. SAFE IMPORT EXECUTION (ATOMIC TRANSACTION & DEDUPLICATION)
# ============================================================

def execute_staged_import(
    db: Session,
    import_id: str,
    import_mode: str = "SKIP_INVALID",
    notes: Optional[str] = None
) -> ConfirmImportResponse:
    """
    Executes staged import within an atomic database transaction.
    Guarantees:
      - Inventory stock quantities are NOT altered.
      - Duplicates are detected via row fingerprint and skipped.
      - DailySalesSummary is updated for all affected dates.
      - Full rollback if any database exception occurs.
    """
    staged = _STAGING_CACHE.get(import_id)
    if not staged:
        raise ValueError(f"Staged import session '{import_id}' has expired or does not exist. Please re-upload the file.")

    valid_records = staged["valid_records"]
    if not valid_records:
        raise ValueError(f"No valid records to import for session '{import_id}'.")

    if import_mode == "REJECT_IF_ANY_INVALID" and staged["invalid_count"] > 0:
        raise ValueError(f"Import cancelled: {staged['invalid_count']} invalid rows detected and mode is set to REJECT_IF_ANY_INVALID.")

    # 1. Fetch existing fingerprints for deduplication
    existing_fingerprints: Set[str] = {
        fp[0] for fp in db.query(HistoricalSaleRecord.row_fingerprint).filter(HistoricalSaleRecord.is_active == True).all()
    }

    # 2. Atomic transaction
    try:
        batch_audit = HistoricalImportBatch(
            import_id=import_id,
            source_filename=staged["filename"],
            file_type=staged["file_type"],
            file_size_bytes=staged["file_size_bytes"],
            total_rows=staged["total_rows"],
            valid_rows=len(valid_records),
            invalid_rows=staged["invalid_count"],
            warning_rows=staged["warning_count"],
            imported_records=0,
            skipped_duplicates=0,
            earliest_date=datetime.strptime(staged["earliest_date"], "%Y-%m-%d").date() if staged["earliest_date"] else None,
            latest_date=datetime.strptime(staged["latest_date"], "%Y-%m-%d").date() if staged["latest_date"] else None,
            usable_days_count=staged["usable_days_count"],
            status="COMPLETED",
            column_mapping_json=str(staged["column_mapping"]),
            confirmed_at=datetime.utcnow(),
            notes=notes or f"Imported {staged['filename']} ({len(valid_records)} valid rows)"
        )
        db.add(batch_audit)
        db.flush()

        imported_count = 0
        duplicate_count = 0
        affected_dates: Set[date] = set()
        affected_products: Set[int] = set()

        for rec in valid_records:
            fp = rec["row_fingerprint"]
            if fp in existing_fingerprints:
                duplicate_count += 1
                continue

            sale_rec = HistoricalSaleRecord(
                import_batch_id=batch_audit.id,
                import_id=import_id,
                source_type="IMPORTED",
                source_file=staged["filename"],
                external_transaction_id=rec["transaction_id"],
                row_fingerprint=fp,
                sale_date=rec["sale_date"],
                product_id=rec["product_id"],
                raw_product_name=rec["raw_product_name"],
                quantity=rec["quantity"],
                unit=rec["unit"],
                unit_price=rec["unit_price"],
                total_amount=rec["total_amount"],
                is_active=True
            )
            db.add(sale_rec)
            existing_fingerprints.add(fp)
            affected_dates.add(rec["sale_date"])
            affected_products.add(rec["product_id"])
            imported_count += 1

        batch_audit.imported_records = imported_count
        batch_audit.skipped_duplicates = duplicate_count
        db.flush()

        # 3. Synchronize canonical daily summaries for all affected dates
        for d in affected_dates:
            aggregate_sales_for_date(db, d)

        db.commit()
        try:
            from backend.services.forecasting import invalidate_forecast_cache
            invalidate_forecast_cache()
        except Exception:
            pass

        # Clean cache
        del _STAGING_CACHE[import_id]

        # Calculate overall forecasting sufficiency
        total_usable_days = len(
            {s.sale_date for s in db.query(DailySalesSummary).filter(DailySalesSummary.total_quantity_sold > 0).all()}
        )
        forecasting_status = "SUFFICIENT_DATA" if total_usable_days >= 7 else "INSUFFICIENT_DATA"

        return ConfirmImportResponse(
            status="SUCCESS",
            import_id=import_id,
            message=f"Successfully imported {imported_count} records ({duplicate_count} duplicate records skipped).",
            total_rows_processed=staged["total_rows"],
            imported_records_count=imported_count,
            skipped_duplicate_count=duplicate_count,
            skipped_invalid_count=staged["invalid_count"],
            earliest_date=staged["earliest_date"],
            latest_date=staged["latest_date"],
            usable_days_count=total_usable_days,
            forecasting_status=forecasting_status,
            min_days_required=7,
            active_products_updated_count=len(affected_products)
        )
    except Exception as e:
        db.rollback()
        raise RuntimeError(f"Database error during historical sales import: {str(e)}")


# ============================================================
# 11. IMPORT ROLLBACK
# ============================================================

def rollback_import_batch(db: Session, import_id: str) -> RollbackImportResponse:
    """
    Rolls back an imported batch completely.
    Deactivates or deletes historical sales records, reconciles daily summaries,
    and updates batch status to ROLLED_BACK.
    """
    batch = db.query(HistoricalImportBatch).filter(HistoricalImportBatch.import_id == import_id).first()
    if not batch:
        raise ValueError(f"Import batch '{import_id}' not found.")

    if batch.status == "ROLLED_BACK":
        return RollbackImportResponse(
            status="ALREADY_ROLLED_BACK",
            import_id=import_id,
            message="Batch is already rolled back.",
            records_deactivated_count=0,
            dates_recalculated_count=0
        )

    records = db.query(HistoricalSaleRecord).filter(
        HistoricalSaleRecord.import_id == import_id,
        HistoricalSaleRecord.is_active == True
    ).all()

    affected_dates: Set[date] = {r.sale_date for r in records}
    record_count = len(records)

    try:
        # Deactivate all records
        for r in records:
            r.is_active = False

        batch.status = "ROLLED_BACK"
        batch.rolled_back_at = datetime.utcnow()
        db.flush()

        # Recalculate daily sales summaries for affected dates
        for d in affected_dates:
            aggregate_sales_for_date(db, d)

        db.commit()
        try:
            from backend.services.forecasting import invalidate_forecast_cache
            invalidate_forecast_cache()
        except Exception:
            pass

        return RollbackImportResponse(
            status="SUCCESS",
            import_id=import_id,
            message=f"Successfully rolled back import batch '{import_id}'. {record_count} records deactivated.",
            records_deactivated_count=record_count,
            dates_recalculated_count=len(affected_dates)
        )
    except Exception as e:
        db.rollback()
        raise RuntimeError(f"Failed to rollback import batch '{import_id}': {str(e)}")
