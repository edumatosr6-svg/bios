"""E1 -- Conditioning. v1 depth: canonical geometry only.

The maturity table (§6) puts photometric normalisation and the validity
mask in v2, and deliberately so: rectification alone already makes
position, size, pitch and alignment comparable, which is everything E4-E6
need. Photometric work only pays off once observation variance is
*measured* to be the dominant error, and building it before that is cost
without demonstrated return.

What rectification buys is not cosmetic. Every geometric descriptor E3
produces -- alignment, pitch regularity, relative size -- is meaningless
across elements while the surface is still a photograph taken at an
angle. Two menu items the same width on screen are not the same width in
the photo.

The pass-through path matters as much as the success path. A synthetic
screenshot has no bezel and no quad to find; failing to rectify it is
correct, not an error. The stage records which happened, because
downstream comparability differs and that has to be visible rather than
assumed.
"""
from typing import Any

import cv2
import numpy as np

from ..model import Abstention, Perception, Surface
from ..pipeline import StageOutput

MIN_QUAD_AREA_RATIO = 0.25      # a screen fills a good part of the frame
MAX_QUAD_AREA_RATIO = 0.995     # ~the whole frame means we found the frame
MIN_ASPECT, MAX_ASPECT = 0.4, 4.0


class Conditioning:
    name = "E1.conditioning"
    produces = "surface"
    consumes = ("bundle",)

    def __init__(self, rectify: bool = True):
        self.rectify = rectify

    def run(self, perception: Perception) -> StageOutput:
        bundle = perception.bundle
        if bundle is None:
            return StageOutput(
                abstentions=(
                    Abstention(
                        stage=self.name, level="surface", scope_id=None,
                        reason="no_bundle",
                    ),
                )
            )

        frame = bundle.representative
        height, width = frame.shape[:2]
        notes: list[str] = []
        abstentions: list[Abstention] = []

        quad = _find_screen_quad(frame) if self.rectify else None

        if quad is None:
            canonical, transform, rectified = frame, None, False
            if self.rectify:
                notes.append("no screen quad found; identity pass-through")
                abstentions.append(
                    Abstention(
                        stage=self.name, level="surface", scope_id=None,
                        reason="rectification_unavailable",
                        detail={"effect": "geometry comparable within frame only"},
                    )
                )
        else:
            canonical, matrix = _warp(frame, quad)
            transform = tuple(tuple(float(v) for v in row) for row in matrix)
            rectified = True
            notes.append("rectified from detected screen quad")

        surface = Surface(
            image=canonical,
            width=canonical.shape[1],
            height=canonical.shape[0],
            rectified=rectified,
            transform=transform,
            quality={"focus": _focus_measure(canonical)},
            frames_used=len(bundle.frames),
        )
        return StageOutput(
            products=surface,
            abstentions=tuple(abstentions),
            notes=tuple(notes),
            parameters={"rectify": self.rectify, "depth": "v1_geometry_only"},
        )


def _find_screen_quad(frame: Any) -> np.ndarray | None:
    """Largest plausible convex quadrilateral -- the panel in the photo."""
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(gray, 40, 140)
    edges = cv2.dilate(edges, np.ones((3, 3), np.uint8), iterations=1)

    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None

    frame_area = float(frame.shape[0] * frame.shape[1])
    best, best_area = None, 0.0
    for contour in sorted(contours, key=cv2.contourArea, reverse=True)[:12]:
        area = cv2.contourArea(contour)
        ratio = area / frame_area
        if ratio < MIN_QUAD_AREA_RATIO or ratio > MAX_QUAD_AREA_RATIO:
            continue
        approx = cv2.approxPolyDP(contour, 0.02 * cv2.arcLength(contour, True), True)
        if len(approx) != 4 or not cv2.isContourConvex(approx):
            continue
        quad = _order_corners(approx.reshape(4, 2).astype(np.float32))
        w, h = _quad_size(quad)
        if h <= 0 or not (MIN_ASPECT <= w / h <= MAX_ASPECT):
            continue
        if area > best_area:
            best, best_area = quad, area
    return best


def _order_corners(pts: np.ndarray) -> np.ndarray:
    """Top-left, top-right, bottom-right, bottom-left."""
    summed = pts.sum(axis=1)
    diff = np.diff(pts, axis=1).ravel()
    return np.array(
        [
            pts[np.argmin(summed)],
            pts[np.argmin(diff)],
            pts[np.argmax(summed)],
            pts[np.argmax(diff)],
        ],
        dtype=np.float32,
    )


def _quad_size(quad: np.ndarray) -> tuple[float, float]:
    tl, tr, br, bl = quad
    width = max(np.linalg.norm(tr - tl), np.linalg.norm(br - bl))
    height = max(np.linalg.norm(bl - tl), np.linalg.norm(br - tr))
    return float(width), float(height)


def _warp(frame: Any, quad: np.ndarray) -> tuple[Any, np.ndarray]:
    """Warp to the quad's own dimensions, so we resample as little as
    possible -- rectification should not also be a resize.
    """
    width, height = _quad_size(quad)
    w, h = int(round(width)), int(round(height))
    target = np.array([[0, 0], [w - 1, 0], [w - 1, h - 1], [0, h - 1]], dtype=np.float32)
    matrix = cv2.getPerspectiveTransform(quad, target)
    return cv2.warpPerspective(frame, matrix, (w, h)), matrix


def _focus_measure(image: Any) -> float:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())
