"""E2 -- Extraction. Find everything localisable, from independent sources.

Two *classes* of source, defined by what they yield rather than by the
technology behind them (§E2). Symbolic sources yield legible content and
where it is; structural sources yield shape and delimitation with no
legible content at all.

Source independence is an architectural requirement, not a detail. Half
the structure of an interface has no legible content -- selection bars,
separators, field frames, scrollbars -- and an engine with one source is
structurally blind to it. Each source may fail on its own without
blinding the others, so a source that raises is recorded as an abstention
and the rest of extraction continues.

**The non-contamination rule.** Any grouping a source produces internally
is provenance, never structure. The OCR engine's `blocks`/`lines` say
something about how the OCR engine batches its output -- with PaddleOCR
every line lands in `block_num: 0` regardless of layout -- and nothing
about how the interface is organised. Inheriting it would import the
source's artefact as if it were a fact about the screen. Grouping belongs
to E4-E6, which is why `source_group` is recorded and then not read.
"""
from typing import Any, Callable

import cv2
import numpy as np

from ocr import DEFAULT_ENGINE

from ..model import Abstention, Geometry, Perception, Primitive, make_ids, sorted_by_position
from ..pipeline import StageOutput

MIN_RULE_LENGTH_RATIO = 0.06    # of the surface's corresponding dimension
MAX_RULE_THICKNESS = 6
MIN_FILL_AREA_RATIO = 0.0004
MAX_FILL_AREA_RATIO = 0.30
MAX_FILL_STDDEV = 18.0          # a fill is flat; that is what makes it a fill


class Extraction:
    name = "E2.extraction"
    produces = "primitive"
    consumes = ("surface",)

    def __init__(self, sources: list["Source"] | None = None, engine: str = DEFAULT_ENGINE):
        self.sources = sources if sources is not None else default_sources(engine)

    def run(self, perception: Perception) -> StageOutput:
        surface = perception.surface
        if surface is None:
            return StageOutput(
                abstentions=(
                    Abstention(
                        stage=self.name, level="primitive", scope_id=None,
                        reason="no_surface",
                    ),
                )
            )

        raw: list[dict[str, Any]] = []
        abstentions: list[Abstention] = []
        notes: list[str] = []

        for source in self.sources:
            try:
                found = source.extract(surface)
            except Exception as exc:                      # noqa: BLE001
                abstentions.append(
                    Abstention(
                        stage=self.name, level="primitive", scope_id=None,
                        reason="source_failed",
                        detail={"source": source.name, "error": str(exc)[:200]},
                    )
                )
                continue
            raw.extend(found)
            notes.append(f"{source.name}: {len(found)}")

        # One deterministic ordering over every source's output, then ids.
        # Sorting before numbering is what makes F7 hold across runs.
        ordered = sorted(
            raw,
            key=lambda d: (
                d["geometry"].y, d["geometry"].x,
                d["geometry"].w, d["geometry"].h,
                d["source"], d.get("content") or "",
            ),
        )
        ids = make_ids("p", len(ordered))
        primitives = tuple(
            Primitive(
                id=pid,
                kind=d["kind"],
                source=d["source"],
                geometry=d["geometry"],
                content=d.get("content"),
                confidence=d.get("confidence", 1.0),
                shape=d.get("shape"),
                source_group=d.get("source_group"),
            )
            for pid, d in zip(ids, ordered)
        )

        return StageOutput(
            products=primitives,
            abstentions=tuple(abstentions),
            notes=tuple(notes),
            parameters={"sources": [s.name for s in self.sources]},
        )


class Source:
    """A primitive source. Named by what it yields, not by its technology."""
    name: str
    kind: str

    def extract(self, surface) -> list[dict[str, Any]]:
        raise NotImplementedError


class SymbolicSource(Source):
    """Legible content plus its location.

    The OCR engine is an implementation choice behind this contract; the
    architecture only knows that some source yields content and geometry.
    """
    kind = "symbolic"

    def __init__(self, engine: str = DEFAULT_ENGINE, lang: str | None = None):
        self.name = f"symbolic:{engine}"
        self._engine_name = engine
        self._lang = lang
        self._engine = None

    def _get_engine(self):
        if self._engine is None:
            from ocr import create_ocr_engine
            self._engine = create_ocr_engine(self._engine_name, lang=self._lang)
        return self._engine

    def extract(self, surface) -> list[dict[str, Any]]:
        result = self._get_engine().read(surface.image)
        out: list[dict[str, Any]] = []
        for block in result.get("blocks", []):
            for line in block.get("lines", []):
                bbox = line.get("bbox")
                text = (line.get("text") or "").strip()
                if not bbox or not text:
                    continue
                geometry = Geometry(
                    x=int(bbox["left"]), y=int(bbox["top"]),
                    w=int(bbox["width"]), h=int(bbox["height"]),
                )
                if geometry.w < 2 or geometry.h < 2:
                    continue
                confidence = max(
                    (w.get("confidence", 0.0) for w in line.get("words", [])),
                    default=0.0,
                )
                out.append({
                    "kind": self.kind,
                    "source": self.name,
                    "geometry": geometry,
                    "content": text,
                    "confidence": float(confidence) / 100.0,
                    # provenance only -- see the non-contamination rule
                    "source_group": f"b{block.get('block_num')}l{line.get('line_num')}",
                })
        return out


class RuleSource(Source):
    """Separators: long thin lines.

    Structurally valuable because they delimit a region without depending
    on background colour at all -- an interface can separate two areas
    with a line while keeping one flat background across both.
    """
    name = "structural:rules"
    kind = "structural"

    def extract(self, surface) -> list[dict[str, Any]]:
        gray = cv2.cvtColor(surface.image, cv2.COLOR_BGR2GRAY)
        edges = cv2.Canny(cv2.GaussianBlur(gray, (3, 3), 0), 50, 150)
        out: list[dict[str, Any]] = []

        for axis, kernel_shape, min_len in (
            ("horizontal", (max(12, surface.width // 12), 1),
             surface.width * MIN_RULE_LENGTH_RATIO),
            ("vertical", (1, max(12, surface.height // 12)),
             surface.height * MIN_RULE_LENGTH_RATIO),
        ):
            kernel = cv2.getStructuringElement(cv2.MORPH_RECT, kernel_shape)
            opened = cv2.morphologyEx(edges, cv2.MORPH_OPEN, kernel)
            contours, _ = cv2.findContours(
                opened, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
            )
            for contour in contours:
                x, y, w, h = cv2.boundingRect(contour)
                length, thickness = (w, h) if axis == "horizontal" else (h, w)
                if length < min_len or thickness > MAX_RULE_THICKNESS:
                    continue
                out.append({
                    "kind": self.kind,
                    "source": self.name,
                    "geometry": Geometry(x=x, y=y, w=w, h=h),
                    "shape": f"rule_{axis}",
                    "confidence": 0.8,
                })
        return out


class FilledRectSource(Source):
    """Solid filled rectangles -- the selection bar as a *shape*.

    Deliberately independent of the colour reasoning in E7. When a BIOS
    marks selection with a bar, that bar exists as geometry whether or not
    its colour statistics stand out, and two independent channels
    agreeing is worth more than one channel measured twice.
    """
    name = "structural:filled_rects"
    kind = "structural"

    def extract(self, surface) -> list[dict[str, Any]]:
        image = surface.image
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        surface_area = float(surface.width * surface.height)

        edges = cv2.Canny(cv2.GaussianBlur(gray, (5, 5), 0), 30, 110)
        edges = cv2.morphologyEx(
            edges, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
        )
        contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)

        out: list[dict[str, Any]] = []
        for contour in contours:
            area = cv2.contourArea(contour)
            ratio = area / surface_area
            if ratio < MIN_FILL_AREA_RATIO or ratio > MAX_FILL_AREA_RATIO:
                continue
            x, y, w, h = cv2.boundingRect(contour)
            if w < 8 or h < 6:
                continue
            # Rectangularity: the contour should account for most of its box.
            if area < 0.72 * w * h:
                continue
            interior = image[y + h // 4: y + 3 * h // 4, x + w // 4: x + 3 * w // 4]
            if interior.size == 0:
                continue
            if float(interior.reshape(-1, 3).std(axis=0).mean()) > MAX_FILL_STDDEV:
                continue
            out.append({
                "kind": self.kind,
                "source": self.name,
                "geometry": Geometry(x=x, y=y, w=w, h=h),
                "shape": "filled_rect",
                "confidence": 0.7,
            })
        return _drop_near_duplicates(out)


def _drop_near_duplicates(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Edge-based contour finding reports the same shape more than once
    (inner and outer edge). Keep the largest of each overlapping cluster.
    """
    ordered = sorted(items, key=lambda d: d["geometry"].area, reverse=True)
    kept: list[dict[str, Any]] = []
    for item in ordered:
        g = item["geometry"]
        if any(
            g.intersection_area(k["geometry"]) > 0.8 * min(g.area, k["geometry"].area)
            for k in kept
        ):
            continue
        kept.append(item)
    return kept


def default_sources(engine: str = DEFAULT_ENGINE) -> list[Source]:
    return [SymbolicSource(engine=engine), RuleSource(), FilledRectSource()]
