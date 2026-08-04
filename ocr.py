"""OCR engine abstraction.

Kept behind a small interface (Tesseract, PaddleOCR) so swapping engines
doesn't require touching main.py or the output schema consumers (the
future AI model) will already depend on.
"""
from abc import ABC, abstractmethod

import shutil

import cv2
import pytesseract
from pytesseract import Output

if not shutil.which("tesseract"):
    _default_windows_path = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    import os
    if os.path.isfile(_default_windows_path):
        pytesseract.pytesseract.tesseract_cmd = _default_windows_path


def preprocess(image, upscale=2.0):
    """Grayscale + upscale, which helps Tesseract on small BIOS menu fonts."""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    if upscale and upscale != 1.0:
        gray = cv2.resize(gray, None, fx=upscale, fy=upscale, interpolation=cv2.INTER_CUBIC)
    return gray


class OCREngine(ABC):
    @abstractmethod
    def read(self, image):
        """Return a structured dict: image_size, full_text, blocks[].lines[].words[]."""
        raise NotImplementedError


class TesseractOCR(OCREngine):
    def __init__(self, lang="eng", upscale=2.0, min_confidence=0):
        self.lang = lang
        self.upscale = upscale
        self.min_confidence = min_confidence

    def read(self, image):
        height, width = image.shape[:2]
        prepped = preprocess(image, upscale=self.upscale)
        scale = self.upscale or 1.0

        data = pytesseract.image_to_data(prepped, lang=self.lang, output_type=Output.DICT)

        blocks = {}
        full_text_parts = []

        n = len(data["text"])
        for i in range(n):
            text = data["text"][i].strip()
            conf_raw = data["conf"][i]
            try:
                conf = float(conf_raw)
            except (TypeError, ValueError):
                conf = -1.0

            if not text or conf < self.min_confidence:
                continue

            block_num = data["block_num"][i]
            line_num = data["line_num"][i]

            # bbox coords come back in upscaled pixel space; rescale to original image.
            bbox = {
                "left": round(data["left"][i] / scale),
                "top": round(data["top"][i] / scale),
                "width": round(data["width"][i] / scale),
                "height": round(data["height"][i] / scale),
            }

            block = blocks.setdefault(block_num, {"block_num": block_num, "lines": {}})
            line = block["lines"].setdefault(
                line_num, {"line_num": line_num, "words": []}
            )
            line["words"].append({"text": text, "confidence": conf, "bbox": bbox})
            full_text_parts.append(text)

        ordered_blocks = []
        for block_num in sorted(blocks):
            lines_dict = blocks[block_num]["lines"]
            ordered_lines = []
            for line_num in sorted(lines_dict):
                words = lines_dict[line_num]["words"]
                line_bbox = _merge_bboxes(w["bbox"] for w in words)
                line_text = " ".join(w["text"] for w in words)
                ordered_lines.append({
                    "line_num": line_num,
                    "text": line_text,
                    "bbox": line_bbox,
                    "words": words,
                })
            ordered_blocks.append({"block_num": block_num, "lines": ordered_lines})

        return {
            "engine": "tesseract",
            "image_size": {"width": width, "height": height},
            "full_text": "\n".join(
                " ".join(w["text"] for w in line["words"])
                for block in ordered_blocks
                for line in block["lines"]
            ),
            "blocks": ordered_blocks,
        }


class PaddleOCREngine(OCREngine):
    """Deep-learning OCR (PP-OCR), noticeably more accurate than Tesseract
    on real screen photos (varied lighting/angle) while keeping the same
    word/line/block + bbox schema.

    Model preprocessing steps we don't need for a flat, upright screen
    photo (document unwarping, page/textline orientation) are disabled
    for speed. `enable_mkldnn=False` works around a PaddlePaddle 3.3.1
    oneDNN/PIR crash (ConvertPirAttribute2RuntimeAttribute) seen on this
    machine -- revisit if a PaddlePaddle update fixes it upstream.
    """

    def __init__(self, lang="en", min_confidence=0):
        from paddleocr import PaddleOCR as _PaddleOCR

        self.min_confidence = min_confidence
        self._engine = _PaddleOCR(
            lang=lang,
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
            enable_mkldnn=False,
        )

    def read(self, image):
        height, width = image.shape[:2]
        results = self._engine.predict(image, return_word_box=True)
        page = results[0] if results else {}

        rec_texts = page.get("rec_texts", [])
        rec_scores = page.get("rec_scores", [])
        rec_boxes = page.get("rec_boxes", [])
        text_word = page.get("text_word", [])
        text_word_boxes = page.get("text_word_boxes", [])

        lines = []
        full_text_parts = []
        for i, line_text in enumerate(rec_texts):
            if not line_text.strip():
                continue
            confidence = round(float(rec_scores[i]) * 100, 2) if i < len(rec_scores) else -1.0
            if confidence < self.min_confidence:
                continue

            line_bbox = _box_to_bbox(rec_boxes[i]) if i < len(rec_boxes) else None

            words = []
            tokens = text_word[i] if i < len(text_word) else [line_text]
            token_boxes = text_word_boxes[i] if i < len(text_word_boxes) else []
            for j, token in enumerate(tokens):
                token = token.strip()
                if not token:
                    continue
                bbox = _box_to_bbox(token_boxes[j]) if j < len(token_boxes) else line_bbox
                words.append({"text": token, "confidence": confidence, "bbox": bbox})
            if not words:
                words = [{"text": line_text, "confidence": confidence, "bbox": line_bbox}]

            lines.append({
                "line_num": i,
                "text": line_text,
                "bbox": line_bbox,
                "words": words,
            })
            full_text_parts.append(line_text)

        blocks = [{"block_num": 0, "lines": lines}] if lines else []

        return {
            "engine": "paddleocr",
            "image_size": {"width": width, "height": height},
            "full_text": "\n".join(full_text_parts),
            "blocks": blocks,
        }


def _box_to_bbox(box):
    x0, y0, x1, y1 = (int(v) for v in box)
    return {"left": x0, "top": y0, "width": x1 - x0, "height": y1 - y0}


def create_ocr_engine(name, lang=None, upscale=2.0):
    """lang=None picks each engine's natural default -- Tesseract uses
    ISO 639-2 codes ("eng"), PaddleOCR uses its own short codes ("en").
    `upscale` only applies to Tesseract; PaddleOCR does its own internal
    preprocessing.
    """
    if name == "tesseract":
        return TesseractOCR(lang=lang or "eng", upscale=upscale)
    if name == "paddleocr":
        return PaddleOCREngine(lang=lang or "en")
    raise ValueError(f"Unknown OCR engine: {name}")


def _merge_bboxes(bboxes):
    bboxes = list(bboxes)
    left = min(b["left"] for b in bboxes)
    top = min(b["top"] for b in bboxes)
    right = max(b["left"] + b["width"] for b in bboxes)
    bottom = max(b["top"] + b["height"] for b in bboxes)
    return {"left": left, "top": top, "width": right - left, "height": bottom - top}
