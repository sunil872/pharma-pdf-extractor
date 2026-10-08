"""
Unit and Integration Tests for MediAstra Phase 10:
- Mobile Phone Camera Perspective Correction
- 4-Point Homography Warp
- Document Boundary & Corner Detection
- Shadow Attenuation & Lighting Normalization
"""

import pytest
import numpy as np
import cv2
from PIL import Image, ImageDraw

from ocr_engine import (
    order_corner_points,
    four_point_perspective_transform,
    detect_document_corners,
    remove_shadows_and_normalize_lighting,
    preprocess_invoice_image,
)


def test_order_corner_points():
    """Verify deterministic ordering [top_left, top_right, bottom_right, bottom_left]."""
    # Unordered points for a 100x100 box
    pts = np.array([
        [100, 100],  # bottom_right
        [0, 0],      # top_left
        [100, 0],    # top_right
        [0, 100],    # bottom_left
    ], dtype="float32")

    ordered = order_corner_points(pts)

    # Expected: [0, 0], [100, 0], [100, 100], [0, 100]
    np.testing.assert_array_almost_equal(ordered[0], [0, 0])
    np.testing.assert_array_almost_equal(ordered[1], [100, 0])
    np.testing.assert_array_almost_equal(ordered[2], [100, 100])
    np.testing.assert_array_almost_equal(ordered[3], [0, 100])


def test_four_point_perspective_transform_synthetic():
    """Test 4-point homography warp on skewed quadrilateral."""
    # Create an image (400x400)
    img = np.zeros((400, 400, 3), dtype=np.uint8)
    
    # Skewed document coordinates
    skewed_pts = np.array([
        [50, 60],    # top-left
        [320, 40],   # top-right
        [350, 360],  # bottom-right
        [40, 340],   # bottom-left
    ], dtype="float32")

    warped = four_point_perspective_transform(img, skewed_pts)

    assert warped is not None
    assert len(warped.shape) == 3
    assert warped.shape[0] > 250  # Height
    assert warped.shape[1] > 250  # Width


def test_detect_document_corners_on_synthetic_photo():
    """Test finding corners of a bright white invoice sheet on a dark background."""
    # Dark counter background (500x500)
    bg = np.zeros((500, 500), dtype=np.uint8) + 40
    
    # Draw a tilted white document in the center
    doc_pts = np.array([
        [80, 70],
        [420, 60],
        [440, 430],
        [60, 420],
    ], dtype=np.int32)
    cv2.fillPoly(bg, [doc_pts], 240)

    corners = detect_document_corners(bg, min_area_ratio=0.20)

    assert corners is not None
    assert corners.shape == (4, 2)
    # Check that top-left corner is near (80, 70)
    assert abs(corners[0][0] - 80) < 30
    assert abs(corners[0][1] - 70) < 30


def test_remove_shadows_and_normalize_lighting():
    """Test shadow removal on image with severe gradient shadow."""
    img = np.ones((200, 200), dtype=np.uint8) * 200
    
    # Add harsh dark shadow gradient on right half (dropping to ~50)
    for c in range(100, 200):
        img[:, c] = np.clip(200 - (c - 100) * 1.5, 50, 200).astype(np.uint8)

    # Initial variance across shadowed region
    std_before = np.std(img[:, 100:200])

    shadow_removed = remove_shadows_and_normalize_lighting(img)

    assert shadow_removed is not None
    assert shadow_removed.shape == (200, 200)
    # The shadowed region should be significantly leveled and brighter
    std_after = np.std(shadow_removed[:, 100:200])
    mean_shadow_after = np.mean(shadow_removed[:, 150:200])
    assert mean_shadow_after > 200  # Lifted back to white paper level
    assert std_after < std_before


def test_preprocess_invoice_image_end_to_end():
    """Test preprocess_invoice_image with perspective correction and shadow attenuation."""
    pil_img = Image.new("RGB", (300, 300), color=(255, 255, 255))
    draw = ImageDraw.Draw(pil_img)
    draw.text((20, 50), "DISTRIBUTOR PURCHASE INVOICE", fill=(0, 0, 0))
    draw.text((20, 100), "AMARYL 1MG TABLET", fill=(0, 0, 0))

    enhanced = preprocess_invoice_image(pil_img, auto_perspective=True, remove_shadows=True)

    assert isinstance(enhanced, np.ndarray)
    assert len(enhanced.shape) == 2  # 2D grayscale array ready for OCR
    assert enhanced.shape[0] > 100
    assert enhanced.shape[1] > 100
