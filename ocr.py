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
    oneDNN/PIR crash (ConvertPirAttribute2RuntimeAttribute) -- confirmed
    still present on 3.3.1 (the latest release) and independent of model
    choice: PP-OCRv6 and PP-OCRv4 both hit it identically, immediately,
    on the first `predict()` call.

    `ocr_version="PP-OCRv4"` pins the older, smaller "mobile" det+rec
    pair instead of leaving PaddleOCR to pick its own default for
    lang="en", which is the PP-OCRv6 "medium" pair. That default matters
    a lot without mkldnn: measured on this machine, just *constructing*
    the v6 medium pair took over 7 minutes of continuous 8-core CPU work
    without finishing a single `predict()` call. Pinned to v4 mobile,
    construction is ~3-9s (cached vs. cold) and a full perception-engine
    run against a 1280x720 capture is ~31s end to end. Same non-mkldnn
    fallback path either way -- the smaller graph is what makes the
    difference between unusable and usable. Revisit the version pin
    together with `enable_mkldnn` if a PaddlePaddle release ever fixes
    the oneDNN/PIR crash upstream.
    """

    def __init__(self, lang="en", min_confidence=0):
        from paddleocr import PaddleOCR as _PaddleOCR

        self.min_confidence = min_confidence
        self._engine = _PaddleOCR(
            lang=lang,
            ocr_version="PP-OCRv4",
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


class RapidOCREngine(OCREngine):
    """The same PP-OCR model lineage as PaddleOCREngine, but run through
    RapidOCR's own ONNX/OpenVINO export instead of paddlex. That matters
    on Windows: paddlex's real acceleration backends (openvino,
    onnxruntime) route through its HPI plugin, which depends on
    `ultra-infer-python` -- a package with no Windows wheel (confirmed by
    `paddlex --install hpi-cpu` failing outright; PaddleX's own docs say
    Windows needs WSL/Docker for it). RapidOCR needs neither paddlex nor
    WSL -- `pip install rapidocr onnxruntime` (or `openvino`) is enough.

    Measured end to end on a 1280x720 capture: ~2-6s (onnxruntime) /
    ~4-6s (openvino), against PaddleOCREngine's ~30s+ on the same image
    and hardware (no GPU, mkldnn unusable -- see
    docs/specs/p-specs/paddleocr-cpu-lento-sem-mkldnn.md). Text quality
    on that capture matched PaddleOCR line for line, but it has not been
    run through the formal gabarito comparison test_selection.py uses.
    """

    def __init__(self, backend="onnxruntime", min_confidence=0):
        from rapidocr import RapidOCR as _RapidOCR
        from rapidocr.utils.typings import EngineType, LangDet, LangRec

        engine_type = {
            "onnxruntime": EngineType.ONNXRUNTIME,
            "openvino": EngineType.OPENVINO,
        }[backend]
        self.backend = backend
        self.min_confidence = min_confidence
        self._engine = _RapidOCR(params={
            "Det.engine_type": engine_type, "Det.lang_type": LangDet.EN,
            "Rec.engine_type": engine_type, "Rec.lang_type": LangRec.EN,
            # Screen photos are shot upright; the 180-degree-rotation
            # classifier is a cost with nothing to correct here.
            "Global.use_cls": False,
            # Otherwise every read prints a paragraph about which model
            # file it loaded -- fine while choosing an engine, noise once
            # this is the default and runs on every capture.
            "Global.log_level": "warning",
        })

    def read(self, image):
        height, width = image.shape[:2]
        result = self._engine(image)

        lines = []
        if result is not None and result.boxes is not None:
            for i, (box, text, score) in enumerate(
                zip(result.boxes, result.txts, result.scores)
            ):
                confidence = round(float(score) * 100, 2)
                if confidence < self.min_confidence:
                    continue
                bbox = _polygon_to_bbox(box)
                lines.append({
                    "line_num": i,
                    "text": text,
                    "bbox": bbox,
                    # RapidOCR reports one score per line, not per word --
                    # the line stands in as its own single "word" rather
                    # than inventing a split the engine didn't make.
                    "words": [{"text": text, "confidence": confidence, "bbox": bbox}],
                })

        blocks = [{"block_num": 0, "lines": lines}] if lines else []
        return {
            "engine": f"rapidocr-{self.backend}",
            "image_size": {"width": width, "height": height},
            "full_text": "\n".join(line["text"] for line in lines),
            "blocks": blocks,
        }


def _polygon_to_bbox(box):
    xs = [float(p[0]) for p in box]
    ys = [float(p[1]) for p in box]
    left, top = min(xs), min(ys)
    return {
        "left": int(round(left)), "top": int(round(top)),
        "width": int(round(max(xs) - left)), "height": int(round(max(ys) - top)),
    }


class WinOCREngine(OCREngine):
    """Windows' own OCR (`Windows.Media.Ocr`), through the `winocr`
    wrapper. Ships with the OS -- no model to download, convert, or pick
    an inference backend for. Measured end to end on a 1280x720 capture:
    ~0.3s, roughly 100x PaddleOCREngine on the same image and hardware.

    The underlying API reports no per-word confidence, unlike every other
    engine here -- every word gets a fixed 100.0 rather than a fabricated
    number, so downstream code that weighs confidence should know this
    engine's confidence is not a real per-word signal.
    """

    def __init__(self, lang="en-US"):
        self.lang = lang

    def read(self, image):
        import winocr

        height, width = image.shape[:2]
        result = winocr.recognize_cv2_sync(image, lang=self.lang)

        lines = []
        for i, line in enumerate(result.get("lines") or []):
            words = []
            for word in line.get("words") or []:
                rect = word.get("bounding_rect") or {}
                bbox = {
                    "left": round(rect.get("x", 0)), "top": round(rect.get("y", 0)),
                    "width": round(rect.get("width", 0)), "height": round(rect.get("height", 0)),
                }
                words.append({"text": word.get("text", ""), "confidence": 100.0, "bbox": bbox})
            if not words:
                continue
            lines.append({
                "line_num": i,
                "text": line.get("text", ""),
                "bbox": _merge_bboxes(w["bbox"] for w in words),
                "words": words,
            })

        blocks = [{"block_num": 0, "lines": lines}] if lines else []
        return {
            "engine": "winocr",
            "image_size": {"width": width, "height": height},
            "full_text": "\n".join(line["text"] for line in lines),
            "blocks": blocks,
        }



# Every entry point offers the same engines, from one list, because they
# did not: --engine was copy-pasted into five argparse calls, and when
# the RapidOCR/winocr engines were added, main.py and watcher.py silently
# kept offering the old two.
ENGINE_CHOICES = [
    "rapidocr-openvino",
    "rapidocr-onnxruntime",
    "paddleocr",
    "winocr",
    "tesseract",
]

# Measured on this machine against a live UGREEN capture of a Positivo
# BIOS screen (docs/studies/estudo-motores-ocr.md): 4.5s to read, against
# paddleocr's 44.1s on the same frame, and the perception engine reached
# the same conclusion from it (the selected tab, two channels agreeing).
# PaddleOCR is not slow by nature here -- it is slow because this machine
# has no NVIDIA GPU and PaddlePaddle 3.3.1's oneDNN path crashes, so it
# runs unaccelerated (docs/specs/p-specs/paddleocr-cpu-lento-sem-mkldnn.md).
# Revisit if that changes: same models, different executor.
DEFAULT_ENGINE = "rapidocr-openvino"


def create_ocr_engine(name, lang=None, upscale=2.0):
    """lang=None picks each engine's natural default -- Tesseract uses
    ISO 639-2 codes ("eng"), PaddleOCR uses its own short codes ("en"),
    winocr uses BCP-47 tags ("en-US"). `upscale` only applies to
    Tesseract; the others do their own internal preprocessing.
    """
    if name == "tesseract":
        return TesseractOCR(lang=lang or "eng", upscale=upscale)
    if name == "paddleocr":
        return PaddleOCREngine(lang=lang or "en")
    if name == "rapidocr-onnxruntime":
        return RapidOCREngine(backend="onnxruntime")
    if name == "rapidocr-openvino":
        return RapidOCREngine(backend="openvino")
    if name == "winocr":
        return WinOCREngine(lang=lang or "en-US")
    raise ValueError(f"Unknown OCR engine: {name}")


def _merge_bboxes(bboxes):
    bboxes = list(bboxes)
    left = min(b["left"] for b in bboxes)
    top = min(b["top"] for b in bboxes)
    right = max(b["left"] + b["width"] for b in bboxes)
    bottom = max(b["top"] + b["height"] for b in bboxes)
    return {"left": left, "top": top, "width": right - left, "height": bottom - top}
