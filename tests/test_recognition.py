import cv2
import numpy as np
import pytest

from visual_macro.models import Rule
from visual_macro.recognition import TemplateMatcher


def test_matcher_reports_full_screen_location_and_confidence(tmp_path) -> None:
    rng = np.random.default_rng(4)
    template = rng.integers(0, 256, size=(8, 9), dtype=np.uint8)
    screen = rng.integers(0, 256, size=(40, 50), dtype=np.uint8)
    screen[12:20, 17:26] = template
    template_path = tmp_path / "template.png"
    cv2.imwrite(str(template_path), template)

    rule = Rule(
        id="target",
        name="Target",
        template_path=str(template_path),
        threshold=0.99,
        region=(10, 8, 30, 25),
    )
    frame = cv2.cvtColor(screen, cv2.COLOR_GRAY2BGR)

    result = TemplateMatcher().match(frame, rule)

    assert result.matched
    assert result.location == (17, 12)
    assert result.bbox == (17, 12, 9, 8)
    assert result.confidence >= 0.99


def test_matcher_distinguishes_colors_with_identical_grayscale(tmp_path) -> None:
    template = np.full((8, 8, 3), (255, 0, 0), dtype=np.uint8)
    grayscale_equivalent = np.full((8, 8, 3), (0, 0, 98), dtype=np.uint8)
    assert np.array_equal(
        cv2.cvtColor(template, cv2.COLOR_BGR2GRAY),
        cv2.cvtColor(grayscale_equivalent, cv2.COLOR_BGR2GRAY),
    )
    template_path = tmp_path / "blue-template.png"
    assert cv2.imwrite(str(template_path), template)

    frame = np.zeros((24, 32, 3), dtype=np.uint8)
    frame[4:12, 2:10] = grayscale_equivalent
    frame[14:22, 20:28] = template
    rule = Rule(
        id="color-target",
        name="Color target",
        template_path=str(template_path),
        threshold=0.99,
    )

    result = TemplateMatcher().match(frame, rule)

    assert result.matched
    assert result.location == (20, 14)
    assert result.bbox == (20, 14, 8, 8)
    assert result.confidence >= 0.99


def test_match_bbox_includes_search_region_and_virtual_desktop_origin(tmp_path) -> None:
    rng = np.random.default_rng(12)
    template = rng.integers(0, 256, size=(6, 7), dtype=np.uint8)
    screen = rng.integers(0, 256, size=(45, 55), dtype=np.uint8)
    screen[18:24, 21:28] = template
    template_path = tmp_path / "template.png"
    cv2.imwrite(str(template_path), template)
    rule = Rule(
        id="target",
        name="Target",
        template_path=str(template_path),
        threshold=0.99,
        region=(12, 10, 30, 25),
    )

    result = TemplateMatcher().match(
        cv2.cvtColor(screen, cv2.COLOR_GRAY2BGR),
        rule,
        screen_origin=(-1920, -100),
    )

    assert result.location == (21, 18)
    assert result.bbox == (-1899, -82, 7, 6)


def test_matcher_reports_absence_below_threshold(tmp_path) -> None:
    template_path = tmp_path / "template.png"
    cv2.imwrite(str(template_path), np.full((5, 5), 255, dtype=np.uint8))
    rule = Rule(id="target", name="Target", template_path=str(template_path), threshold=0.9)
    frame = np.zeros((20, 20, 3), dtype=np.uint8)

    result = TemplateMatcher().match(frame, rule)

    assert not result.matched
    assert result.location is None


def test_matcher_reports_missing_and_invalid_templates(tmp_path) -> None:
    matcher = TemplateMatcher()
    missing = Rule(id="missing", name="Missing", template_path=str(tmp_path / "missing.png"))
    with pytest.raises(FileNotFoundError, match="was not found"):
        matcher.match(np.zeros((20, 20, 3), dtype=np.uint8), missing)

    invalid_path = tmp_path / "invalid.png"
    invalid_path.write_bytes(b"invalid image bytes")
    invalid = Rule(id="invalid", name="Invalid", template_path=str(invalid_path))
    with pytest.raises(ValueError, match="not a readable image"):
        matcher.match(np.zeros((20, 20, 3), dtype=np.uint8), invalid)


def test_matcher_does_not_return_location_when_confidence_is_below_threshold(tmp_path) -> None:
    rng = np.random.default_rng(91)
    template = rng.integers(0, 255, size=(7, 8), dtype=np.uint8)
    path = tmp_path / "template.png"
    cv2.imwrite(str(path), template)
    rule = Rule(id="target", name="Target", template_path=str(path), threshold=1.0)

    result = TemplateMatcher().match(np.zeros((25, 25, 3), dtype=np.uint8), rule)

    assert result.confidence < 1.0
    assert not result.matched
    assert result.location is None
    assert result.bbox is None
