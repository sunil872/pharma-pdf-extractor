"""
Unit tests for MediAstra Phase 3:
- Local OCR & Structure Pipeline (ocr_engine.py)
- Selective Cell Re-OCR
- Structured Grid Extraction
"""

import pytest
import numpy as np
from PIL import Image, ImageDraw, ImageFont
import pandas as pd
import ocr_engine


def create_synthetic_cell_image(text: str = "88.80", width: int = 120, height: int = 40) -> Image.Image:
    """Generates a clean synthetic image with specified text."""
    img = Image.new("RGB", (width, height), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    draw.text((10, 10), text, fill=(0, 0, 0))
    return img


def test_crop_and_reocr_cell_on_synthetic_image():
    """Test that crop_and_reocr_cell successfully crops and extracts text."""
    img = create_synthetic_cell_image("88.80", width=150, height=50)
    bbox = (5, 5, 140, 45)

    res = ocr_engine.crop_and_reocr_cell(img, bbox)

    assert isinstance(res, dict)
    assert "text" in res
    assert "conf" in res
    assert "re_ocred" in res
    if res["re_ocred"]:
        assert "88" in res["text"] or "80" in res["text"]


def test_reconstruct_lines_from_ocr_clustering():
    """Test spatial Y-clustering from DataFrame."""
    df = pd.DataFrame([
        {"left": 10, "top": 20, "width": 50, "height": 15, "conf": 0.95, "text": "AMARYL"},
        {"left": 70, "top": 22, "width": 40, "height": 15, "conf": 0.95, "text": "1MG"},
        {"left": 10, "top": 50, "width": 60, "height": 15, "conf": 0.92, "text": "ASTYMIN"},
        {"left": 80, "top": 52, "width": 50, "height": 15, "conf": 0.92, "text": "FORTE"},
    ])

    lines = ocr_engine.reconstruct_lines_from_ocr(df, y_threshold=10)

    assert len(lines) == 2
    assert lines[0] == ["AMARYL", "1MG"]
    assert lines[1] == ["ASTYMIN", "FORTE"]


def test_extract_table_grid_from_synthetic_image():
    """Test extract_table_grid_from_image returns grouped rows of cell records."""
    img = Image.new("RGB", (300, 100), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    draw.text((10, 15), "Product", fill=(0, 0, 0))
    draw.text((150, 15), "Rate", fill=(0, 0, 0))
    draw.text((10, 60), "Amaryl", fill=(0, 0, 0))
    draw.text((150, 60), "88.80", fill=(0, 0, 0))

    grid = ocr_engine.extract_table_grid_from_image(img)

    assert isinstance(grid, list)
    if grid:
        assert len(grid) >= 1
        assert isinstance(grid[0], list)
        assert "text" in grid[0][0]
