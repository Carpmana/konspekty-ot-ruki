"""Искусственно заполненный бланк — для тестов и демонстрации без настоящего почерка.

Буквы рисуются шрифтом, слегка искажаются, затем лист «фотографируется»:
перспектива, неравномерный свет, шум. Это проверяет импорт, но, конечно,
не заменяет образцы настоящего почерка.
"""

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .template import DPI, TEMPLATE_SETS, render_page, set_pages
from .units import mm_to_px

INK = (35, 45, 150)


def fill_template(font_path: str, seed: int = 0, x_height_mm: float = 3.6, key: str = "main") -> list[np.ndarray]:
    rng = np.random.default_rng(seed)
    pages = set_pages(key)
    out = []
    for cells in pages:
        img = render_page(cells, cells[0].page, len(pages), TEMPLATE_SETS[key])
        for c in cells:
            size = int(mm_to_px(x_height_mm, DPI) / 0.5 * rng.normal(1.0, 0.04))
            font = ImageFont.truetype(font_path, size)
            layer = Image.new("L", (int(mm_to_px(c.w, DPI)), int(mm_to_px(c.h, DPI))), 0)
            d = ImageDraw.Draw(layer)
            base = mm_to_px(c.baseline_y - c.y, DPI)
            asc = font.getmetrics()[0]
            d.text((mm_to_px(2.2, DPI) + rng.normal(0, 4), base - asc + rng.normal(0, 3)), c.request.text,
                   fill=255, font=font)
            layer = layer.rotate(rng.normal(0, 2.0), resample=Image.BILINEAR, center=(layer.width / 2, base))
            ink = Image.new("RGB", layer.size, INK)
            img.paste(ink, (int(mm_to_px(c.x, DPI)), int(mm_to_px(c.y, DPI))), layer)
        out.append(np.array(img))
    return out


def photograph(img: np.ndarray, seed: int = 0, strength: float = 1.0) -> np.ndarray:
    """Имитация фото с телефона: перспектива, тень, шум, лёгкое размытие."""
    rng = np.random.default_rng(seed)
    h, w = img.shape[:2]
    pad = int(0.06 * w)
    canvas = np.full((h + 2 * pad, w + 2 * pad, 3), (110, 90, 70), np.uint8)
    canvas[pad:pad + h, pad:pad + w] = img
    H, W = canvas.shape[:2]
    src = np.float32([[0, 0], [W, 0], [W, H], [0, H]])
    jit = rng.uniform(-1, 1, (4, 2)).astype(np.float32) * 0.035 * W * strength
    dst = src + jit
    M = cv2.getPerspectiveTransform(src, dst)
    out = cv2.warpPerspective(canvas, M, (W, H), borderValue=(110, 90, 70)).astype(np.float32)
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    light = 1.0 - 0.25 * strength * (xx / W) * (yy / H)
    out *= light[..., None]
    out += rng.normal(0, 3 * strength, out.shape)
    out = cv2.GaussianBlur(out, (0, 0), 0.8)
    return np.clip(out, 0, 255).astype(np.uint8)
