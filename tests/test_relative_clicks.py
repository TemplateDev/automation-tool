import threading

import pytest

from visual_macro.macros import MacroExecutor
from visual_macro.models import ConfigurationError, Rule


@pytest.mark.parametrize(
    ("action", "expected"),
    [
        ({"type": "click_center"}, (-98, 207)),
        (
            {"type": "click_offset", "offset_x": -10, "offset_y": 5},
            (-108, 212),
        ),
    ],
)
def test_relative_click_actions_log_coordinates_in_simulation(action, expected) -> None:
    messages: list[str] = []
    executor = MacroExecutor(True, messages.append, threading.Event())
    rect = (-103, 204, 11, 7)

    executor.execute([action], detection_rect=rect)

    assert len(messages) == 1
    assert f"({expected[0]}, {expected[1]})" in messages[0]
    assert messages[0].startswith("SIMULATION:")


def test_relative_click_requires_a_detection_rectangle() -> None:
    executor = MacroExecutor(True, lambda _message: None, threading.Event())

    with pytest.raises(ValueError, match="requires a detected image position"):
        executor.execute([{"type": "click_center"}])


def test_offset_click_requires_a_detection_rectangle_without_falling_back() -> None:
    messages: list[str] = []
    executor = MacroExecutor(True, messages.append, threading.Event())

    with pytest.raises(ValueError, match="no detection rectangle"):
        executor.execute(
            [{"type": "click_offset", "offset_x": 1, "offset_y": 2}],
            detection_rect=None,
        )
    assert messages == []


@pytest.mark.parametrize("rect", [(10, 20, 0, 5), (10, 20, 5, -1), (10, 20, 1.5, 4)])
def test_relative_click_rejects_invalid_detection_rectangles(rect) -> None:
    executor = MacroExecutor(True, lambda _message: None, threading.Event())

    with pytest.raises(ValueError, match="valid detected image rectangle"):
        executor.execute([{"type": "click_center"}], detection_rect=rect)


def test_fixed_click_stays_backward_compatible_with_optional_detection() -> None:
    messages: list[str] = []
    executor = MacroExecutor(True, messages.append, threading.Event())

    executor.execute([{"type": "click", "x": 12, "y": 34}])

    assert messages == ["SIMULATION: click left at (12, 34) x1"]


@pytest.mark.parametrize(
    "action",
    [
        {"type": "click_center", "button": "bad"},
        {"type": "click_offset", "offset_x": 1.5, "offset_y": 2},
    ],
)
def test_relative_click_configuration_is_validated(action) -> None:
    with pytest.raises(ConfigurationError):
        Rule(id="invalid", name="Invalid", template_path="image.png", actions=[action])
