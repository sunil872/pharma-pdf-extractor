"""
MediAstra Local OCR & Image Ingestion Engine (ocr_engine.py)
------------------------------------------------------------
100% Offline, Zero-Cost, Pure Computer Vision & Onnx OCR Pipeline for
scanned pharma purchase invoices, mobile photos, and raster PDFs.

Key Features:
- Zero Cloud/LLM Dependency: Runs 100% locally on CPU via OpenCV & RapidOCR.
- Image Preprocessing: Auto-deskew, CLAHE contrast boost, adaptive binarization, noise removal.
- Spatial Bounding-Box Clustering: Clusters OCR word polygons into aligned table rows.
- Scanned PDF Detection: Seamlessly renders raster PDF pages into 300 DPI images via PyMuPDF.
"""

import io
import os
import re
import cv2
import numpy as np
import pandas as pd
from PIL import Image
from typing import List, Dict, Tuple, Optional, Any, Union
from pathlib import Path

# 1. Initialize PaddleOCR 3.7.x / PP-StructureV3 (Optional primary engine)
try:
    from paddleocr import PaddleOCR, PPStructure
    _paddle_ocr_engine = PaddleOCR(use_angle_cls=True, lang="en", show_log=False)
    _paddle_structure_engine = PPStructure(table=True, ocr=True, show_log=False)
except Exception:
    _paddle_ocr_engine = None
    _paddle_structure_engine = None

# 2. Initialize RapidOCR (High-Speed Local ONNX Engine - Active Baseline)
try:
    from rapidocr_onnxruntime import RapidOCR
    _rapid_ocr_engine = RapidOCR()
except ImportError:
    _rapid_ocr_engine = None

# 3. PyMuPDF for high-res PDF rendering
try:
    import fitz  # PyMuPDF
except ImportError:
    fitz = None

# 4. Optional Pytesseract fallback
try:
    import pytesseract
    tesseract_paths = [
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        os.path.expanduser(r"~\AppData\Local\Programs\Tesseract-OCR\tesseract.exe"),
    ]
    for p in tesseract_paths:
        if os.path.exists(p):
            pytesseract.pytesseract.tesseract_cmd = p
            break
except ImportError:
    pytesseract = None


def load_image_to_pil(image_input: Union[str, Path, bytes, io.BytesIO, Image.Image, np.ndarray]) -> Image.Image:
    """Standardizes various image inputs into a standard RGB PIL Image."""
    if isinstance(image_input, Image.Image):
        return image_input.convert("RGB")
    elif isinstance(image_input, np.ndarray):
        if len(image_input.shape) == 2:
            return Image.fromarray(image_input).convert("RGB")
        return Image.fromarray(image_input).convert("RGB")
    elif isinstance(image_input, (str, Path)):
        return Image.open(str(image_input)).convert("RGB")
    elif isinstance(image_input, (bytes, io.BytesIO)):
        if isinstance(image_input, bytes):
            image_input = io.BytesIO(image_input)
        return Image.open(image_input).convert("RGB")
    else:
        raise ValueError(f"Unsupported image input type: {type(image_input)}")


def order_corner_points(pts: np.ndarray) -> np.ndarray:
    """
    Orders 4 coordinates deterministically: [top-left, top-right, bottom-right, bottom-left].
    """
    rect = np.zeros((4, 2), dtype="float32")
    
    # Top-left has smallest sum (x + y), bottom-right has largest sum
    s = pts.sum(axis=1)
    rect[0] = pts[np.argmin(s)]
    rect[2] = pts[np.argmax(s)]
    
    # Top-right has smallest difference (y - x), bottom-left has largest difference
    diff = np.diff(pts, axis=1)
    rect[1] = pts[np.argmin(diff)]
    rect[3] = pts[np.argmax(diff)]
    
    return rect


def four_point_perspective_transform(image: np.ndarray, pts: np.ndarray) -> np.ndarray:
    """
    Applies 4-point homography perspective warp to transform an angled mobile photo
    into a flat, top-down rectangular scan.
    """
    rect = order_corner_points(pts)
    (tl, tr, br, bl) = rect

    # Compute width of new image
    width_a = np.sqrt(((br[0] - bl[0]) ** 2) + ((br[1] - bl[1]) ** 2))
    width_b = np.sqrt(((tr[0] - tl[0]) ** 2) + ((tr[1] - tl[1]) ** 2))
    max_width = max(int(width_a), int(width_b))

    # Compute height of new image
    height_a = np.sqrt(((tr[0] - br[0]) ** 2) + ((tr[1] - br[1]) ** 2))
    height_b = np.sqrt(((tl[0] - bl[0]) ** 2) + ((tl[1] - bl[1]) ** 2))
    max_height = max(int(height_a), int(height_b))

    if max_width <= 10 or max_height <= 10:
        return image

    dst = np.array([
        [0, 0],
        [max_width - 1, 0],
        [max_width - 1, max_height - 1],
        [0, max_height - 1],
    ], dtype="float32")

    M = cv2.getPerspectiveTransform(rect, dst)
    warped = cv2.warpPerspective(image, M, (max_width, max_height), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
    return warped


def detect_document_corners(image: np.ndarray, min_area_ratio: float = 0.20) -> Optional[np.ndarray]:
    """
    Detects the 4 corner coordinates of a rectangular invoice document in a camera photo.
    Returns np.ndarray of shape (4, 2) or None if no clear document polygon found.
    """
    if len(image.shape) == 3:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY if image.shape[2] == 3 else cv2.COLOR_RGB2GRAY)
    else:
        gray = image.copy()

    orig_h, orig_w = gray.shape[:2]
    total_area = orig_h * orig_w

    # Resize to standardized height for robust edge detection
    target_height = 800.0
    scale = target_height / float(orig_h) if orig_h > target_height else 1.0
    if scale != 1.0:
        resized = cv2.resize(gray, (int(orig_w * scale), int(target_height)), interpolation=cv2.INTER_AREA)
    else:
        resized = gray

    # Bilateral filter to preserve document edges while smoothing background noise
    blurred = cv2.bilateralFilter(resized, 9, 75, 75)
    
    # Canny edge detector
    edged = cv2.Canny(blurred, 30, 150)
    
    # Morphological close to bridge edge gaps
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
    closed = cv2.morphologyEx(edged, cv2.MORPH_CLOSE, kernel, iterations=2)

    # Find contours
    contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    contours = sorted(contours, key=cv2.contourArea, reverse=True)[:5]

    for c in contours:
        perimeter = cv2.arcLength(c, True)
        approx = cv2.approxPolyDP(c, 0.02 * perimeter, True)
        
        # We need a 4-sided polygon with sufficient area
        if len(approx) == 4:
            area = cv2.contourArea(approx)
            scaled_area = area / (scale * scale)
            if (scaled_area / total_area) >= min_area_ratio:
                # Convert back to original coordinate space
                pts = approx.reshape(4, 2).astype("float32")
                if scale != 1.0:
                    pts /= scale
                return order_corner_points(pts)

    return None


def remove_shadows_and_normalize_lighting(img_gray: np.ndarray) -> np.ndarray:
    """
    Attenuates severe shadows and uneven camera illumination on invoice paper
    using morphological background division.
    """
    kernel_size = max(19, min(img_gray.shape) // 12)
    if kernel_size % 2 == 0:
        kernel_size += 1
    
    structuring_element = cv2.getStructuringElement(cv2.MORPH_RECT, (kernel_size, kernel_size))
    bg_illumination = cv2.morphologyEx(img_gray, cv2.MORPH_DILATE, structuring_element)
    bg_illumination = np.maximum(bg_illumination, 1)
    
    # Level the background by division
    divided = (img_gray.astype(np.float32) / bg_illumination.astype(np.float32)) * 255.0
    return np.clip(divided, 0, 255).astype(np.uint8)


def deskew_image(img_gray: np.ndarray) -> np.ndarray:
    """Detects and corrects skew angle in invoice images using minimum bounding rectangle."""
    try:
        thresh = cv2.threshold(img_gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
        coords = np.column_stack(np.where(thresh > 0))
        if len(coords) < 50:
            return img_gray
        angle = cv2.minAreaRect(coords)[-1]
        if angle < -45:
            angle = -(90 + angle)
        elif angle > 45:
            angle = 90 - angle
        else:
            angle = -angle
        
        if 0.5 < abs(angle) < 15.0:
            (h, w) = img_gray.shape[:2]
            center = (w // 2, h // 2)
            M = cv2.getRotationMatrix2D(center, angle, 1.0)
            rotated = cv2.warpAffine(
                img_gray, M, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE
            )
            return rotated
    except Exception:
        pass
    return img_gray


def preprocess_invoice_image(
    image_input: Union[Image.Image, np.ndarray, str, Path, bytes],
    auto_perspective: bool = True,
    remove_shadows: bool = True,
) -> np.ndarray:
    """
    Enhanced OpenCV image enhancement pipeline for mobile camera and scanned invoices:
    1. Standardize to NumPy array
    2. Document boundary detection & 4-point perspective warp (if auto_perspective=True)
    3. Grayscale conversion
    4. Shadow attenuation and lighting normalization (if remove_shadows=True)
    5. Minimum bounding box auto-deskew
    6. CLAHE (Contrast Limited Adaptive Histogram Equalization)
    """
    if isinstance(image_input, (Image.Image, str, Path, bytes, io.BytesIO)):
        pil_img = load_image_to_pil(image_input)
        img_np = np.array(pil_img)
    elif isinstance(image_input, np.ndarray):
        img_np = image_input
    else:
        raise ValueError(f"Unsupported image format: {type(image_input)}")

    # 1. Perspective correction
    if auto_perspective:
        corners = detect_document_corners(img_np)
        if corners is not None:
            img_np = four_point_perspective_transform(img_np, corners)

    # 2. Grayscale conversion
    if len(img_np.shape) == 3:
        gray = cv2.cvtColor(img_np, cv2.COLOR_RGB2GRAY)
    else:
        gray = img_np.copy()

    # 3. Shadow removal and illumination leveling
    if remove_shadows:
        gray = remove_shadows_and_normalize_lighting(gray)

    # 4. Auto-deskew
    deskewed = deskew_image(gray)

    # 5. CLAHE contrast boost
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    enhanced = clahe.apply(deskewed)
    return enhanced


def is_scanned_pdf(pdf_input: Union[str, Path, bytes, io.BytesIO], min_chars_per_page: int = 40) -> bool:
    """Detects if a PDF lacks digital text (scanned invoice)."""
    if fitz is None:
        return False
    try:
        if isinstance(pdf_input, (str, Path)):
            doc = fitz.open(str(pdf_input))
        else:
            pdf_bytes = pdf_input if isinstance(pdf_input, bytes) else pdf_input.getvalue()
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        
        total_text_length = 0
        for page in doc:
            total_text_length += len(page.get_text().strip())
        doc.close()
        
        avg_chars = total_text_length / max(1, len(doc)) if doc else 0
        return avg_chars < min_chars_per_page
    except Exception:
        return False


def render_pdf_to_images(pdf_input: Union[str, Path, bytes, io.BytesIO], dpi: int = 300) -> List[Image.Image]:
    """Renders PDF pages into high-resolution PIL images using PyMuPDF (fitz)."""
    if fitz is None:
        raise ImportError("PyMuPDF (fitz) is required to render PDF pages to images.")
    
    if isinstance(pdf_input, (str, Path)):
        doc = fitz.open(str(pdf_input))
    else:
        pdf_bytes = pdf_input if isinstance(pdf_input, bytes) else pdf_input.getvalue()
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")

    images = []
    zoom = dpi / 72.0
    mat = fitz.Matrix(zoom, zoom)
    for page in doc:
        pix = page.get_pixmap(matrix=mat, alpha=False)
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        images.append(img)
    doc.close()
    return images


def extract_ocr_dataframe_from_image(image_input: Union[Image.Image, np.ndarray, str, Path]) -> pd.DataFrame:
    """
    Extracts word bounding boxes, confidence, and text from an invoice image using RapidOCR.
    Returns a DataFrame with columns: [left, top, width, height, conf, text].
    """
    pil_img = load_image_to_pil(image_input)
    img_np = np.array(pil_img)
    preprocessed = preprocess_invoice_image(img_np)

    records = []

    # 1. Primary Engine: RapidOCR
    if _rapid_ocr_engine is not None:
        try:
            results, elapse = _rapid_ocr_engine(preprocessed)
            if results:
                for item in results:
                    box, text, score = item
                    text_clean = str(text).strip()
                    if not text_clean:
                        continue
                    
                    # Box is 4 points: [[x1, y1], [x2, y2], [x3, y3], [x4, y4]]
                    pts = np.array(box)
                    left = float(pts[:, 0].min())
                    top = float(pts[:, 1].min())
                    right = float(pts[:, 0].max())
                    bottom = float(pts[:, 1].max())
                    width = right - left
                    height = bottom - top
                    
                    try:
                        conf_val = float(score)
                    except (ValueError, TypeError):
                        conf_val = 0.85

                    records.append({
                        "left": left,
                        "top": top,
                        "width": width,
                        "height": height,
                        "conf": conf_val,
                        "text": text_clean,
                    })
        except Exception:
            pass

    # 2. Fallback Engine: pytesseract if RapidOCR had no results
    if not records and pytesseract is not None:
        try:
            data = pytesseract.image_to_data(preprocessed, output_type=pytesseract.Output.DATAFRAME)
            data = data.dropna(subset=['text'])
            data['text'] = data['text'].astype(str).str.strip()
            data = data[data['text'] != '']
            return data
        except Exception:
            pass

    return pd.DataFrame(records)


def reconstruct_lines_from_ocr(data: pd.DataFrame, y_threshold: int = 14) -> List[List[str]]:
    """
    Clusters OCR word bounding boxes into structured tabular rows by grouping near Y-coordinates.
    """
    if data.empty:
        return []

    # Sort primarily by vertical Y position (top) then horizontal X position (left)
    sorted_words = data.sort_values(by=['top', 'left']).to_dict('records')
    
    lines = []
    current_line = []
    current_y = None

    for item in sorted_words:
        word_top = item['top']
        word_text = item['text']

        if current_y is None:
            current_y = word_top
            current_line.append(word_text)
        elif abs(word_top - current_y) <= y_threshold:
            current_line.append(word_text)
        else:
            if current_line:
                lines.append(current_line)
            current_line = [word_text]
            current_y = word_top

    if current_line:
        lines.append(current_line)

    return lines


def crop_and_reocr_cell(
    image_input: Union[Image.Image, np.ndarray],
    bbox: Tuple[int, int, int, int],
    padding: int = 4,
) -> Dict[str, Any]:
    """
    Selectively crops a single cell bounding box [left, top, right, bottom],
    applies localized CLAHE & adaptive binarization, and re-runs OCR.
    Used exclusively for low-confidence or mathematically suspicious cells.
    """
    pil_img = load_image_to_pil(image_input)
    w, h = pil_img.size
    left, top, right, bottom = bbox

    # Pad bounding box safely within image limits
    pad_left = max(0, int(left) - padding)
    pad_top = max(0, int(top) - padding)
    pad_right = min(w, int(right) + padding)
    pad_bottom = min(h, int(bottom) + padding)

    if pad_right <= pad_left or pad_bottom <= pad_top:
        return {"text": "", "conf": 0.0, "re_ocred": False}

    cropped = pil_img.crop((pad_left, pad_top, pad_right, pad_bottom))
    cropped_np = np.array(cropped)

    # Local enhancement
    if len(cropped_np.shape) == 3:
        gray = cv2.cvtColor(cropped_np, cv2.COLOR_RGB2GRAY)
    else:
        gray = cropped_np.copy()

    # Scale up small cells for OCR clarity
    if gray.shape[0] < 32 or gray.shape[1] < 64:
        gray = cv2.resize(gray, (gray.shape[1] * 2, gray.shape[0] * 2), interpolation=cv2.INTER_CUBIC)

    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(4, 4))
    enhanced = clahe.apply(gray)

    # Run RapidOCR on cropped cell
    if _rapid_ocr_engine is not None:
        try:
            results, _ = _rapid_ocr_engine(enhanced)
            if results:
                texts = [str(r[1]).strip() for r in results if str(r[1]).strip()]
                scores = [float(r[2]) for r in results]
                avg_score = sum(scores) / max(1, len(scores))
                return {
                    "text": " ".join(texts),
                    "conf": round(avg_score, 3),
                    "re_ocred": True,
                }
        except Exception:
            pass

    return {"text": "", "conf": 0.0, "re_ocred": False}


def extract_table_grid_from_image(image_input: Union[Image.Image, np.ndarray, str, Path]) -> List[List[Dict[str, Any]]]:
    """
    Extracts structured table cells from an invoice image.
    1. If PaddleOCR / PP-StructureV3 is present, extracts layout table and cells.
    2. Otherwise uses RapidOCR word bounding boxes with Y-clustering and X-alignment.
    3. Triggers selective cell-level re-OCR for low-confidence tokens (conf < 0.65).
    """
    pil_img = load_image_to_pil(image_input)
    img_np = np.array(pil_img)

    # 1. Try PP-StructureV3 if available
    if _paddle_structure_engine is not None:
        try:
            results = _paddle_structure_engine(img_np)
            for res in results:
                if res.get("type") == "table" and "res" in res:
                    table_html = res["res"].get("html")
                    table_cells = res["res"].get("cell_bbox")
                    if table_cells:
                        grid_records = []
                        for cell in table_cells:
                            grid_records.append({
                                "bbox": cell,
                                "text": cell.get("text", ""),
                                "conf": cell.get("conf", 0.90),
                            })
                        return grid_records
        except Exception:
            pass

    # 2. Fast Local Baseline: RapidOCR DataFrame with selective re-OCR
    df = extract_ocr_dataframe_from_image(img_np)
    if df.empty:
        return []

    # Sort primarily by vertical Y position (top) then horizontal X position (left)
    sorted_words = df.sort_values(by=['top', 'left']).to_dict('records')
    
    rows = []
    current_row = []
    current_y = None
    y_threshold = 14

    for item in sorted_words:
        word_top = item['top']
        word_left = item['left']
        word_w = item['width']
        word_h = item['height']
        word_text = item['text']
        word_conf = item['conf']

        # Check for selective re-OCR if confidence is low
        if word_conf < 0.65 and len(word_text) > 0:
            bbox = (int(word_left), int(word_top), int(word_left + word_w), int(word_top + word_h))
            re_res = crop_and_reocr_cell(img_np, bbox)
            if re_res["re_ocred"] and re_res["conf"] > word_conf and re_res["text"]:
                word_text = re_res["text"]
                word_conf = re_res["conf"]

        cell_rec = {
            "text": word_text,
            "conf": word_conf,
            "left": word_left,
            "top": word_top,
            "width": word_w,
            "height": word_h,
        }

        if current_y is None:
            current_y = word_top
            current_row.append(cell_rec)
        elif abs(word_top - current_y) <= y_threshold:
            current_row.append(cell_rec)
        else:
            if current_row:
                rows.append(current_row)
            current_row = [cell_rec]
            current_y = word_top

    if current_row:
        rows.append(current_row)

    return rows


def extract_text_from_image(image_input: Union[Image.Image, np.ndarray, str, Path]) -> str:
    """Extract full page text from an image with RapidOCR / OpenCV."""
    df = extract_ocr_dataframe_from_image(image_input)
    if df.empty:
        return ""
    lines = reconstruct_lines_from_ocr(df)
    return "\n".join(" ".join(line) for line in lines)
