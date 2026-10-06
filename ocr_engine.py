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

# 1. Initialize RapidOCR (Local ONNX-based OCR Engine)
try:
    from rapidocr_onnxruntime import RapidOCR
    _rapid_ocr_engine = RapidOCR()
except ImportError:
    _rapid_ocr_engine = None

# 2. PyMuPDF for high-res PDF rendering
try:
    import fitz  # PyMuPDF
except ImportError:
    fitz = None

# 3. Optional Pytesseract fallback
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


def load_image_to_pil(image_input: Union[str, Path, bytes, io.BytesIO, Image.Image]) -> Image.Image:
    """Standardizes various image inputs into a standard RGB PIL Image."""
    if isinstance(image_input, Image.Image):
        return image_input.convert("RGB")
    elif isinstance(image_input, (str, Path)):
        return Image.open(str(image_input)).convert("RGB")
    elif isinstance(image_input, (bytes, io.BytesIO)):
        if isinstance(image_input, bytes):
            image_input = io.BytesIO(image_input)
        return Image.open(image_input).convert("RGB")
    else:
        raise ValueError(f"Unsupported image input type: {type(image_input)}")


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


def preprocess_invoice_image(image_input: Union[Image.Image, np.ndarray, str, Path, bytes]) -> np.ndarray:
    """
    OpenCV image enhancement pipeline:
    1. Grayscale conversion
    2. Auto-deskew
    3. CLAHE (Contrast Limited Adaptive Histogram Equalization)
    4. Binarization
    """
    if isinstance(image_input, (Image.Image, str, Path, bytes, io.BytesIO)):
        pil_img = load_image_to_pil(image_input)
        img_np = np.array(pil_img)
    elif isinstance(image_input, np.ndarray):
        img_np = image_input
    else:
        raise ValueError(f"Unsupported image format: {type(image_input)}")

    if len(img_np.shape) == 3:
        gray = cv2.cvtColor(img_np, cv2.COLOR_RGB2GRAY)
    else:
        gray = img_np.copy()

    deskewed = deskew_image(gray)
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


def extract_text_from_image(image_input: Union[Image.Image, np.ndarray, str, Path]) -> str:
    """Extract full page text from an image with RapidOCR / OpenCV."""
    df = extract_ocr_dataframe_from_image(image_input)
    if df.empty:
        return ""
    lines = reconstruct_lines_from_ocr(df)
    return "\n".join(" ".join(line) for line in lines)
