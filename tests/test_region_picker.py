from PySide6.QtCore import QPoint, QPointF, QRect, Qt, QEvent
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QTest

from visual_macro.desktop import (
    ScreenCoordinateMapper,
    clip_physical_rect,
    frame_relative_region,
)
from visual_macro.region_picker import ScreenPositionOverlay, ScreenRegionOverlay


def _mapper() -> ScreenCoordinateMapper:
    return ScreenCoordinateMapper(
        screens=[(QRect(-100, 0, 100, 100), 2.0), (QRect(0, 0, 100, 100), 1.5)],
        monitors=[
            {"left": -200, "top": 0, "width": 350, "height": 200},
            {"left": -200, "top": 0, "width": 200, "height": 200},
            {"left": 0, "top": 0, "width": 150, "height": 150},
        ],
    )


def test_mapper_handles_negative_origins_and_mixed_display_scaling() -> None:
    mapper = _mapper()

    assert mapper.map_point(-90, 10) == (-180, 20)
    assert mapper.map_point(10, 10) == (15, 15)
    assert mapper.map_rect(QRect(-90, 10, 21, 21)) == (-180, 20, 41, 41)

    assert mapper.logical_point_for_screen(-200, 0) == (-100, 0)
    assert mapper.logical_point_for_screen(-1, 199) == (-1, 99)
    assert mapper.logical_point_for_screen(149, 149) == (99, 99)
    assert mapper.logical_point_for_screen(350, 0) is None
    assert not mapper.contains_logical_point(100, 0)


def test_region_is_converted_to_existing_frame_relative_coordinates() -> None:
    region = frame_relative_region(
        screen_rect=(-180, 20, 50, 40),
        frame_origin=(-200, 0),
        frame_shape=(200, 350),
    )

    assert region == (20, 20, 50, 40)


def test_region_clipping_rejects_selection_outside_virtual_desktop() -> None:
    assert clip_physical_rect(
        (-210, -10, 40, 40),
        {"left": -200, "top": 0, "width": 350, "height": 200},
    ) == (-200, 0, 30, 30)


def test_overlay_confirm_returns_screen_coordinates_and_escape_cancels(qapp) -> None:
    overlay = ScreenRegionOverlay(_mapper())
    overlay.show()
    qapp.processEvents()

    QTest.mousePress(overlay, Qt.MouseButton.LeftButton, pos=QPoint(10, 10))
    QTest.mouseMove(overlay, QPoint(30, 30), 10)
    QTest.mouseRelease(overlay, Qt.MouseButton.LeftButton, pos=QPoint(30, 30))
    qapp.processEvents()
    assert overlay.confirm_button.isEnabled()
    overlay._confirm()

    assert overlay.screen_rect == (-180, 20, 41, 41)
    overlay.close()

    cancelled = ScreenRegionOverlay(_mapper())
    cancelled.show()
    qapp.processEvents()
    QTest.keyClick(cancelled, Qt.Key.Key_Escape)
    assert cancelled.result() == cancelled.DialogCode.Rejected
    cancelled.close()


def test_overlay_rejects_a_zero_area_drag(qapp) -> None:
    overlay = ScreenRegionOverlay(_mapper())
    overlay.show()
    qapp.processEvents()
    position = QPoint(10, 10)
    QTest.mousePress(overlay, Qt.MouseButton.LeftButton, pos=position)
    QTest.mouseRelease(overlay, Qt.MouseButton.LeftButton, pos=position)
    qapp.processEvents()

    assert not overlay.confirm_button.isEnabled()
    assert overlay.screen_rect is None
    overlay.close()


def test_overlay_supports_dragging_from_bottom_right_to_top_left(qapp) -> None:
    overlay = ScreenRegionOverlay(_mapper())
    overlay._drag_start = QPoint(-70, 30)
    overlay._drag_end = QPoint(-90, 10)
    overlay._update_selection()
    overlay._confirm()
    assert overlay.screen_rect == (-180, 20, 41, 41)
    overlay.close()


def test_position_overlay_picks_and_confirms_executor_coordinates(qapp) -> None:
    mapper = _mapper()
    overlay = ScreenPositionOverlay(mapper)
    event = QMouseEvent(
        QEvent.Type.MouseButtonPress,
        QPointF(10, 10),
        QPointF(10, 10),
        QPointF(-90, 10),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )

    overlay.mousePressEvent(event)
    assert overlay.selected_position == (-180, 20)
    assert overlay.coordinates.text() == "X -180, Y 20"
    assert overlay.confirm_button.isEnabled()
    overlay._confirm()
    assert overlay.result() == overlay.DialogCode.Accepted
    overlay.close()


def test_position_overlay_retry_and_escape_cancel(qapp) -> None:
    overlay = ScreenPositionOverlay(_mapper())
    overlay.selected_position = (-180, 20)
    overlay._retry()
    assert overlay.selected_position is None
    assert not overlay.confirm_button.isEnabled()
    QTest.keyClick(overlay, Qt.Key.Key_Escape)
    assert overlay.result() == overlay.DialogCode.Rejected
    overlay.close()
