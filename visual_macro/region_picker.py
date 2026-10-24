from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QColor, QKeyEvent, QMouseEvent, QPainter, QPen
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from visual_macro.desktop import ScreenCoordinateMapper


class ScreenRegionOverlay(QDialog):
    """Borderless virtual-desktop overlay for choosing a physical screen rectangle."""

    def __init__(
        self,
        mapper: ScreenCoordinateMapper | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.mapper = mapper or ScreenCoordinateMapper.from_desktop()
        self.setWindowTitle("Select Screen Region")
        self.setWindowFlags(
            Qt.WindowType.Dialog
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setGeometry(self.mapper.logical_bounds)
        self.setMouseTracking(True)
        self._drag_start: QPoint | None = None
        self._drag_end: QPoint | None = None
        self._is_dragging = False
        self.screen_rect: tuple[int, int, int, int] | None = None

        self.instruction = QLabel("Drag anywhere to select a screen region  ·  Esc cancels")
        self.instruction.setStyleSheet(
            "background: #20252d; color: white; padding: 9px 14px; border-radius: 5px;"
        )
        self.dimensions = QLabel("No region selected")
        self.dimensions.setStyleSheet(
            "background: #20252d; color: white; padding: 7px 11px; border-radius: 4px;"
        )
        self.confirm_button = QPushButton("Confirm")
        self.confirm_button.setEnabled(False)
        self.cancel_button = QPushButton("Cancel")
        self.confirm_button.clicked.connect(self._confirm)
        self.cancel_button.clicked.connect(self.reject)

        controls = QHBoxLayout()
        controls.addWidget(self.instruction)
        controls.addWidget(self.dimensions)
        controls.addStretch(1)
        controls.addWidget(self.confirm_button)
        controls.addWidget(self.cancel_button)
        controls_widget = QWidget(self)
        controls_widget.setStyleSheet("background: transparent;")
        controls_widget.setLayout(controls)
        controls_widget.setGeometry(16, 16, min(self.width() - 32, 920), 52)

    @property
    def logical_selection(self) -> QRect | None:
        if self._drag_start is None or self._drag_end is None:
            return None
        left = min(self._drag_start.x(), self._drag_end.x())
        top = min(self._drag_start.y(), self._drag_end.y())
        width = abs(self._drag_end.x() - self._drag_start.x()) + 1
        height = abs(self._drag_end.y() - self._drag_start.y()) + 1
        return QRect(left, top, width, height)

    def _event_global_position(self, event: QMouseEvent) -> QPoint:
        return event.globalPosition().toPoint()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start = self._event_global_position(event)
            self._drag_end = self._drag_start
            self._is_dragging = True
            self._update_selection()
            self.update()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._is_dragging:
            self._drag_end = self._event_global_position(event)
            self._update_selection()
            self.update()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._drag_start is not None:
            self._drag_end = self._event_global_position(event)
            self._is_dragging = False
            self._update_selection()
            self.update()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.reject()
            return
        super().keyPressEvent(event)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(5, 8, 12, 145))
        selection = self.logical_selection
        if selection is not None and selection.width() > 0 and selection.height() > 0:
            local_rect = QRect(self.mapFromGlobal(selection.topLeft()), selection.size())
            painter.fillRect(local_rect, QColor(35, 130, 220, 55))
            painter.setPen(QPen(QColor("#64c5ff"), 2))
            painter.drawRect(local_rect.adjusted(0, 0, -1, -1))
            painter.setPen(QColor("white"))
            painter.drawText(
                local_rect.adjusted(7, 5, -5, -5),
                Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft,
                self.dimensions.text(),
            )
        super().paintEvent(event)

    def _update_selection(self) -> None:
        selection = self.logical_selection
        valid = selection is not None and selection.width() > 1 and selection.height() > 1
        self.confirm_button.setEnabled(bool(valid))
        if valid:
            try:
                _, _, width, height = self.mapper.map_rect(selection)
                self.dimensions.setText(f"{width} × {height} px")
            except ValueError:
                self.dimensions.setText("Selection outside desktop")
                self.confirm_button.setEnabled(False)
        else:
            self.dimensions.setText("Drag to select a region")

    def _confirm(self) -> None:
        selection = self.logical_selection
        if selection is None or selection.width() <= 1 or selection.height() <= 1:
            self.dimensions.setText("Select a region larger than zero pixels")
            self.confirm_button.setEnabled(False)
            return
        try:
            self.screen_rect = self.mapper.map_rect(selection)
        except ValueError as exc:
            self.dimensions.setText(str(exc))
            self.confirm_button.setEnabled(False)
            return
        self.accept()
