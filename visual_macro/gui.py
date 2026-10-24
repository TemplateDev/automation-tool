from __future__ import annotations

import ctypes
import sys
import uuid
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any

import cv2
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QCloseEvent, QImage, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QSpinBox,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QToolBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from visual_macro.models import (
    ConfigurationError,
    Profile,
    Rule,
    load_profile,
    save_profile,
    validate_action,
)
from visual_macro.desktop import (
    ScreenCoordinateMapper,
    capture_screen_region,
    frame_relative_region,
)
from visual_macro.region_picker import ScreenRegionOverlay
from visual_macro.worker import MacroWorker


class ActionDialog(QDialog):
    """Typed editor for the click, press, and delay actions supported by the executor."""

    def __init__(self, parent=None, action: dict[str, Any] | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Edit Action" if action else "Add Action")

        self.type_input = QComboBox()
        self.type_input.addItem("Click at screen coordinates", "click")
        self.type_input.addItem("Click detected image center", "click_center")
        self.type_input.addItem("Click offset from detected image center", "click_offset")
        self.type_input.addItem("Press a key", "press")
        self.type_input.addItem("Wait", "delay")

        self.click_fields = QWidget()
        click_form = QFormLayout(self.click_fields)
        self.x_input = QSpinBox()
        self.x_input.setRange(-100000, 100000)
        self.y_input = QSpinBox()
        self.y_input.setRange(-100000, 100000)
        self.button_input = QComboBox()
        self.button_input.addItems(["left", "right", "middle"])
        self.clicks_input = QSpinBox()
        self.clicks_input.setRange(1, 10)
        click_form.addRow("Screen X", self.x_input)
        click_form.addRow("Screen Y", self.y_input)
        click_form.addRow("Mouse button", self.button_input)
        click_form.addRow("Click count", self.clicks_input)

        self.center_fields = QWidget()
        center_form = QFormLayout(self.center_fields)
        self.center_button_input = QComboBox()
        self.center_button_input.addItems(["left", "right", "middle"])
        self.center_clicks_input = QSpinBox()
        self.center_clicks_input.setRange(1, 10)
        center_form.addRow("Mouse button", self.center_button_input)
        center_form.addRow("Click count", self.center_clicks_input)

        self.offset_fields = QWidget()
        offset_form = QFormLayout(self.offset_fields)
        self.offset_x_input = QSpinBox()
        self.offset_x_input.setRange(-100000, 100000)
        self.offset_y_input = QSpinBox()
        self.offset_y_input.setRange(-100000, 100000)
        self.offset_button_input = QComboBox()
        self.offset_button_input.addItems(["left", "right", "middle"])
        self.offset_clicks_input = QSpinBox()
        self.offset_clicks_input.setRange(1, 10)
        offset_form.addRow("X offset from center", self.offset_x_input)
        offset_form.addRow("Y offset from center", self.offset_y_input)
        offset_form.addRow("Mouse button", self.offset_button_input)
        offset_form.addRow("Click count", self.offset_clicks_input)

        self.press_fields = QWidget()
        press_form = QFormLayout(self.press_fields)
        self.key_input = QLineEdit()
        self.key_input.setPlaceholderText("For example: enter, space, or a")
        press_form.addRow("Key", self.key_input)

        self.delay_fields = QWidget()
        delay_form = QFormLayout(self.delay_fields)
        self.seconds_input = QDoubleSpinBox()
        self.seconds_input.setRange(0, 300)
        self.seconds_input.setDecimals(2)
        self.seconds_input.setSuffix(" seconds")
        delay_form.addRow("Duration", self.seconds_input)

        self.fields_stack = QStackedWidget()
        self.fields_stack.addWidget(self.click_fields)
        self.fields_stack.addWidget(self.center_fields)
        self.fields_stack.addWidget(self.offset_fields)
        self.fields_stack.addWidget(self.press_fields)
        self.fields_stack.addWidget(self.delay_fields)
        self.type_input.currentIndexChanged.connect(self._update_fields)
        self.error_label = QLabel()
        self.error_label.setObjectName("action_error")
        self.error_label.setStyleSheet("color: #ff8178;")

        form = QFormLayout()
        form.addRow("Action", self.type_input)
        form.addRow(self.fields_stack)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._validate_and_accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.error_label)
        layout.addWidget(buttons)

        if action is not None:
            index = self.type_input.findData(action.get("type"))
            if index >= 0:
                self.type_input.setCurrentIndex(index)
            if action.get("type") == "click":
                self.x_input.setValue(action.get("x", 0))
                self.y_input.setValue(action.get("y", 0))
                self.button_input.setCurrentText(action.get("button", "left"))
                self.clicks_input.setValue(action.get("clicks", 1))
            elif action.get("type") == "click_center":
                self.center_button_input.setCurrentText(action.get("button", "left"))
                self.center_clicks_input.setValue(action.get("clicks", 1))
            elif action.get("type") == "click_offset":
                self.offset_x_input.setValue(action.get("offset_x", 0))
                self.offset_y_input.setValue(action.get("offset_y", 0))
                self.offset_button_input.setCurrentText(action.get("button", "left"))
                self.offset_clicks_input.setValue(action.get("clicks", 1))
            elif action.get("type") == "press":
                self.key_input.setText(action.get("key", ""))
            elif action.get("type") == "delay":
                self.seconds_input.setValue(action.get("seconds", 0))
        self._update_fields()

    def _update_fields(self) -> None:
        field_index = {
            "click": 0,
            "click_center": 1,
            "click_offset": 2,
            "press": 3,
            "delay": 4,
        }[self.type_input.currentData()]
        self.fields_stack.setCurrentIndex(field_index)

    def action(self) -> dict[str, Any]:
        kind = self.type_input.currentData()
        if kind == "click":
            action = {
                "type": "click",
                "x": self.x_input.value(),
                "y": self.y_input.value(),
                "button": self.button_input.currentText(),
                "clicks": self.clicks_input.value(),
            }
        elif kind == "click_center":
            action = {
                "type": kind,
                "button": self.center_button_input.currentText(),
                "clicks": self.center_clicks_input.value(),
            }
        elif kind == "click_offset":
            action = {
                "type": kind,
                "offset_x": self.offset_x_input.value(),
                "offset_y": self.offset_y_input.value(),
                "button": self.offset_button_input.currentText(),
                "clicks": self.offset_clicks_input.value(),
            }
        elif kind == "press":
            action = {"type": "press", "key": self.key_input.text().strip()}
        else:
            action = {"type": "delay", "seconds": self.seconds_input.value()}
        validate_action(action)
        return action

    def _validate_and_accept(self) -> None:
        try:
            self.action()
        except ConfigurationError as exc:
            self.error_label.setText(str(exc))
            return
        self.accept()


class ActionBuilder(QWidget):
    """List editor that only creates action dictionaries understood by MacroExecutor."""

    def __init__(self, actions: list[dict[str, Any]] | None = None, parent=None) -> None:
        super().__init__(parent)
        self.actions = deepcopy(actions or [])
        self.action_list = QTableWidget(0, 1)
        self.action_list.setHorizontalHeaderLabels(["Macro sequence"])
        self.action_list.horizontalHeader().setStretchLastSection(True)
        self.action_list.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.action_list.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.action_list.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.action_list.cellDoubleClicked.connect(lambda _row, _column: self._edit_action())

        self.add_button = QPushButton("Add")
        self.edit_button = QPushButton("Edit")
        self.duplicate_button = QPushButton("Duplicate")
        self.remove_button = QPushButton("Remove")
        self.up_button = QPushButton("Move Up")
        self.down_button = QPushButton("Move Down")
        self.add_button.clicked.connect(self._add_action)
        self.edit_button.clicked.connect(self._edit_action)
        self.duplicate_button.clicked.connect(self._duplicate_action)
        self.remove_button.clicked.connect(self._remove_action)
        self.up_button.clicked.connect(lambda: self._move_action(-1))
        self.down_button.clicked.connect(lambda: self._move_action(1))

        buttons = QHBoxLayout()
        for button in (
            self.add_button,
            self.edit_button,
            self.duplicate_button,
            self.remove_button,
            self.up_button,
            self.down_button,
        ):
            buttons.addWidget(button)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.action_list)
        layout.addLayout(buttons)
        self._refresh()

    def _selected_row(self) -> int:
        return self.action_list.currentRow()

    def _add_action(self) -> None:
        dialog = ActionDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.actions.append(dialog.action())
            self._refresh(select=len(self.actions) - 1)

    def _edit_action(self) -> None:
        row = self._selected_row()
        if not 0 <= row < len(self.actions):
            return
        dialog = ActionDialog(self, self.actions[row])
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.actions[row] = dialog.action()
            self._refresh(select=row)

    def _duplicate_action(self) -> None:
        row = self._selected_row()
        if 0 <= row < len(self.actions):
            self.actions.insert(row + 1, deepcopy(self.actions[row]))
            self._refresh(select=row + 1)

    def _remove_action(self) -> None:
        row = self._selected_row()
        if 0 <= row < len(self.actions):
            self.actions.pop(row)
            self._refresh(select=min(row, len(self.actions) - 1))

    def _move_action(self, offset: int) -> None:
        row = self._selected_row()
        target = row + offset
        if 0 <= row < len(self.actions) and 0 <= target < len(self.actions):
            self.actions[row], self.actions[target] = self.actions[target], self.actions[row]
            self._refresh(select=target)

    def _refresh(self, select: int = -1) -> None:
        self.action_list.setRowCount(len(self.actions))
        for row, action in enumerate(self.actions):
            item = QTableWidgetItem(_action_summary(action))
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.action_list.setItem(row, 0, item)
        if 0 <= select < len(self.actions):
            self.action_list.selectRow(select)
        self.action_list.resizeRowsToContents()


class RuleDialog(QDialog):
    def __init__(self, parent=None, rule: Rule | None = None, template_path: str = "") -> None:
        super().__init__(parent)
        self.setWindowTitle("Edit Rule" if rule else "Add Rule")
        self.resize(620, 700)
        self._rule_id = rule.id if rule else str(uuid.uuid4())
        self._error_label = QLabel()
        self._error_label.setObjectName("rule_error")
        self._error_label.setStyleSheet("color: #ff8178;")

        self.name_input = QLineEdit(rule.name if rule else (Path(template_path).stem or "New rule"))
        self.template_path = rule.template_path if rule else template_path
        self.thumbnail = QLabel()
        self.thumbnail.setFixedSize(104, 76)
        self.thumbnail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumbnail.setStyleSheet("background: #20252d; border: 1px solid #3c424c;")
        self.filename_label = QLabel()
        self.filename_label.setWordWrap(True)
        self.choose_image_button = QPushButton("Choose Image…")
        self.choose_image_button.clicked.connect(self._browse_template)
        self.capture_template_button = QPushButton("Capture Template…")
        self.capture_template_button.clicked.connect(self._capture_template)

        image_row = QHBoxLayout()
        image_row.addWidget(self.thumbnail)
        image_info = QVBoxLayout()
        image_info.addWidget(self.filename_label)
        image_buttons = QHBoxLayout()
        image_buttons.addWidget(self.choose_image_button)
        image_buttons.addWidget(self.capture_template_button)
        image_info.addLayout(image_buttons)
        image_row.addLayout(image_info, 1)

        self.threshold_input = QDoubleSpinBox()
        self.threshold_input.setRange(0, 100)
        self.threshold_input.setSingleStep(1)
        self.threshold_input.setDecimals(1)
        self.threshold_input.setSuffix("%")
        self.threshold_input.setValue((rule.threshold if rule else 0.8) * 100)
        threshold_help = QLabel("Higher thresholds require a closer visual match.")
        threshold_help.setWordWrap(True)
        self.region_enabled = QCheckBox("Only search inside a screen region")
        self.region_enabled.setChecked(bool(rule and rule.region))
        region = rule.region if rule and rule.region else (0, 0, 800, 600)
        self.region_x = self._coordinate_spin()
        self.region_y = self._coordinate_spin()
        self.region_width = self._coordinate_spin(1)
        self.region_height = self._coordinate_spin(1)
        for widget, value in zip(
            (self.region_x, self.region_y, self.region_width, self.region_height), region
        ):
            widget.setValue(value)
        region_form = QFormLayout()
        region_form.addRow("Left (X)", self.region_x)
        region_form.addRow("Top (Y)", self.region_y)
        region_form.addRow("Width", self.region_width)
        region_form.addRow("Height", self.region_height)
        self.advanced_toggle = QToolButton()
        self.advanced_toggle.setText("Advanced: screen search region")
        self.advanced_toggle.setCheckable(True)
        self.advanced_toggle.setChecked(False)
        self.advanced_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.advanced_toggle.setArrowType(Qt.ArrowType.RightArrow)
        self.advanced_region = QWidget()
        self.advanced_region.setLayout(region_form)
        self.advanced_region.setVisible(False)
        self.advanced_toggle.toggled.connect(self._toggle_advanced)
        self.region_enabled.toggled.connect(self._update_region_enabled)
        self.select_region_button = QPushButton("Select Region…")
        self.select_region_button.clicked.connect(self._select_region)
        self.region_summary = QLabel(
            "Full screen" if not rule or not rule.region else self._format_region(rule.region)
        )
        self.region_summary.setStyleSheet("color: #aab1bc;")

        recognition = QGroupBox("Recognition")
        region_form.insertRow(0, "", self.region_enabled)
        recognition_form = QFormLayout(recognition)
        recognition_form.addRow("Rule name", self.name_input)
        recognition_form.addRow("Image template", image_row)
        recognition_form.addRow("Confidence threshold", self.threshold_input)
        recognition_form.addRow("", threshold_help)
        recognition_form.addRow("Search area", self.select_region_button)
        recognition_form.addRow("", self.region_summary)
        recognition_form.addRow("", self.advanced_toggle)
        recognition_form.addRow("", self.advanced_region)

        self.action_builder = ActionBuilder(rule.actions if rule else [])
        actions_group = QGroupBox("Actions")
        actions_layout = QVBoxLayout(actions_group)
        actions_layout.addWidget(QLabel("Actions run in order when the image is detected."))
        actions_layout.addWidget(self.action_builder)

        self.cooldown_input = QDoubleSpinBox()
        self.cooldown_input.setRange(0, 3600)
        self.cooldown_input.setDecimals(2)
        self.cooldown_input.setSuffix(" seconds")
        self.cooldown_input.setValue(rule.cooldown if rule else 1.0)
        self.repeat_input = QCheckBox("Allow repeat triggers while the image remains visible")
        self.repeat_input.setChecked(rule.repeat if rule else False)
        self.enabled_input = QCheckBox("Rule enabled")
        self.enabled_input.setChecked(rule.enabled if rule else True)
        behavior = QGroupBox("Trigger Behavior")
        behavior_form = QFormLayout(behavior)
        behavior_form.addRow("Cooldown", self.cooldown_input)
        behavior_form.addRow("", self.repeat_input)
        behavior_form.addRow("", self.enabled_input)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._validate_and_accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(recognition)
        layout.addWidget(actions_group, 1)
        layout.addWidget(behavior)
        layout.addWidget(self._error_label)
        layout.addWidget(buttons)
        self._update_image()
        self._update_region_enabled()

    @staticmethod
    def _coordinate_spin(minimum: int = 0) -> QSpinBox:
        spin = QSpinBox()
        spin.setRange(minimum, 100000)
        return spin

    def _toggle_advanced(self, expanded: bool) -> None:
        self.advanced_region.setVisible(expanded)
        self.advanced_toggle.setArrowType(
            Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow
        )

    def _update_region_enabled(self) -> None:
        enabled = self.region_enabled.isChecked()
        for field in (self.region_x, self.region_y, self.region_width, self.region_height):
            field.setEnabled(enabled)

    def _update_image(self) -> None:
        path = Path(self.template_path) if self.template_path else None
        self.filename_label.setText(path.name if path else "No image selected")
        pixmap = QPixmap(str(path)) if path else QPixmap()
        if not pixmap.isNull():
            self.thumbnail.setPixmap(
                pixmap.scaled(
                    self.thumbnail.size(),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
            self.thumbnail.setToolTip(str(path))
        else:
            self.thumbnail.setPixmap(QPixmap())
            self.thumbnail.setText("Preview unavailable")

    def _browse_template(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Choose image template",
            self.template_path,
            "Image files (*.png *.jpg *.jpeg *.bmp *.webp);;All files (*.*)",
        )
        if path:
            self.template_path = path
            self._update_image()
            if not self.name_input.text().strip() or self.name_input.text() == "New rule":
                self.name_input.setText(Path(path).stem)

    @staticmethod
    def _format_region(region: tuple[int, int, int, int]) -> str:
        x, y, width, height = region
        return f"X {x}, Y {y}  ·  {width} × {height} px"

    def _select_region(self) -> None:
        try:
            mapper = ScreenCoordinateMapper.from_desktop()
            overlay = ScreenRegionOverlay(mapper, self)
            if overlay.exec() != QDialog.DialogCode.Accepted or overlay.screen_rect is None:
                return
            bounds = mapper.virtual_bounds
            region = frame_relative_region(
                overlay.screen_rect,
                (bounds["left"], bounds["top"]),
                (bounds["height"], bounds["width"]),
            )
        except (OSError, RuntimeError, ValueError) as exc:
            self._error_label.setText(f"Could not select a screen region: {exc}")
            return
        self.region_enabled.setChecked(True)
        for widget, value in zip(
            (self.region_x, self.region_y, self.region_width, self.region_height), region
        ):
            widget.setValue(value)
        self.region_summary.setText(self._format_region(region))

    def _capture_template(self) -> None:
        try:
            mapper = ScreenCoordinateMapper.from_desktop()
            overlay = ScreenRegionOverlay(mapper, self)
            if overlay.exec() != QDialog.DialogCode.Accepted or overlay.screen_rect is None:
                return
            image = capture_screen_region(overlay.screen_rect)
        except (OSError, RuntimeError, ValueError) as exc:
            self._error_label.setText(f"Could not capture template: {exc}")
            return

        height, width, _channels = image.shape
        preview = QImage(
            image.data,
            width,
            height,
            image.strides[0],
            QImage.Format.Format_BGR888,
        ).copy()
        preview_dialog = QDialog(self)
        preview_dialog.setWindowTitle("Preview Template Capture")
        preview_dialog.resize(640, 520)
        preview_label = QLabel()
        preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        preview_label.setPixmap(
            QPixmap.fromImage(preview).scaled(
                600,
                420,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
        preview_buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        preview_buttons.accepted.connect(preview_dialog.accept)
        preview_buttons.rejected.connect(preview_dialog.reject)
        preview_layout = QVBoxLayout(preview_dialog)
        preview_layout.addWidget(QLabel(f"Captured template: {width} × {height} pixels"))
        preview_layout.addWidget(preview_label, 1)
        preview_layout.addWidget(preview_buttons)
        if preview_dialog.exec() != QDialog.DialogCode.Accepted:
            return

        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save captured template",
            self.template_path,
            "PNG image (*.png);;JPEG image (*.jpg *.jpeg);;Bitmap image (*.bmp)",
        )
        if not path:
            return
        if not Path(path).suffix:
            path += ".png"
        try:
            saved = cv2.imwrite(path, image)
        except cv2.error as exc:
            self._error_label.setText(f"Could not save captured template: {exc}")
            return
        if not saved:
            self._error_label.setText(f"Could not save captured template: {path}")
            return
        self.template_path = str(Path(path).resolve())
        self._update_image()
        if not self.name_input.text().strip() or self.name_input.text() == "New rule":
            self.name_input.setText(Path(path).stem)

    def _build_rule(self) -> Rule:
        region = None
        if self.region_enabled.isChecked():
            region = (
                self.region_x.value(),
                self.region_y.value(),
                self.region_width.value(),
                self.region_height.value(),
            )
        return Rule(
            id=self._rule_id,
            name=self.name_input.text().strip(),
            template_path=self.template_path.strip(),
            threshold=self.threshold_input.value() / 100,
            region=region,
            cooldown=self.cooldown_input.value(),
            repeat=self.repeat_input.isChecked(),
            enabled=self.enabled_input.isChecked(),
            actions=deepcopy(self.action_builder.actions),
        )

    def _validate_and_accept(self) -> None:
        try:
            self._build_rule()
        except ConfigurationError as exc:
            self._error_label.setText(str(exc))
            return
        self.accept()

    def rule(self) -> Rule:
        return self._build_rule()


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Visual Macro Automation")
        self.resize(1060, 760)
        self.rules: list[Rule] = []
        self.profile_path: Path | None = None
        self.worker: MacroWorker | None = None
        self._has_error = False
        self.setStyleSheet(
            """
            QMainWindow, QWidget { background: #171a1f; color: #e4e8ee; }
            QGroupBox { border: 1px solid #383e48; border-radius: 6px; margin-top: 10px; padding: 8px; }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; }
            QLineEdit, QPlainTextEdit, QSpinBox, QDoubleSpinBox, QComboBox, QTableWidget {
                background: #20252d; border: 1px solid #3c424c; border-radius: 4px; padding: 4px;
                selection-background-color: #315a83;
            }
            QHeaderView::section { background: #252b34; padding: 6px; border: 0; }
            QPushButton, QToolButton { background: #2a3039; border: 1px solid #424955; border-radius: 4px; padding: 6px 10px; }
            QPushButton:hover, QToolButton:hover { background: #353d48; }
            QPushButton:disabled { color: #858b95; }
            QToolBar { border: 0; spacing: 6px; }
            """
        )

        self.interval_input = QDoubleSpinBox()
        self.interval_input.setRange(0.1, 3600)
        self.interval_input.setDecimals(2)
        self.interval_input.setSuffix(" seconds")
        self.interval_input.setValue(1.0)
        self.simulation_input = QCheckBox("Simulation mode")
        self.simulation_input.setChecked(True)
        self.simulation_input.setToolTip("When enabled, planned actions are logged but no input is sent.")
        self.simulation_input.toggled.connect(self._update_mode_indicator)

        self._create_toolbar()

        header = QHBoxLayout()
        title = QLabel("Visual Macro Automation")
        title.setStyleSheet("font-size: 22px; font-weight: 600;")
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(QLabel("Capture every"))
        header.addWidget(self.interval_input)

        self.status_indicator = QLabel()
        self.status_indicator.setMinimumWidth(100)
        self.status_indicator.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.total_label = QLabel()
        self.enabled_label = QLabel()
        self.mode_label = QLabel()
        stats = QHBoxLayout()
        stats.addWidget(self.status_indicator)
        stats.addWidget(self.total_label)
        stats.addWidget(self.enabled_label)
        stats.addStretch(1)
        stats.addWidget(self.mode_label)
        stats.addWidget(self.simulation_input)

        self.add_button = QPushButton("＋  Add Rule")
        self.add_button.setObjectName("primaryAdd")
        self.add_button.setStyleSheet(
            "QPushButton { background: #2e7d5b; border: 0; padding: 9px 16px; font-weight: 600; }"
            "QPushButton:hover { background: #36936b; }"
        )
        self.add_button.clicked.connect(self._add_rule)
        self.test_button = QPushButton("Test Rule")
        self.test_button.setToolTip("Test the selected rule and preview actions without sending input.")
        self.start_button = QPushButton("▶  Start")
        self.start_button.setStyleSheet(
            "QPushButton { background: #286b4e; border: 0; padding: 9px 16px; font-weight: 600; }"
        )
        self.stop_button = QPushButton("■  Stop")
        self.stop_button.setStyleSheet(
            "QPushButton { background: #9b3e3e; border: 0; padding: 9px 16px; font-weight: 600; }"
        )
        self.stop_button.setEnabled(False)
        self.test_button.clicked.connect(self._test_rule)
        self.start_button.clicked.connect(self._start_monitoring)
        self.stop_button.clicked.connect(self._stop_monitoring)
        run_controls = QHBoxLayout()
        run_controls.addWidget(self.add_button)
        run_controls.addWidget(self.test_button)
        run_controls.addStretch(1)
        run_controls.addWidget(self.start_button)
        run_controls.addWidget(self.stop_button)

        self.rule_table = QTableWidget(0, 6)
        self.rule_table.setHorizontalHeaderLabels(
            ["Image and rule", "Threshold", "Actions", "Cooldown", "Enabled", ""]
        )
        self.rule_table.horizontalHeader().setStretchLastSection(False)
        self.rule_table.horizontalHeader().setMinimumSectionSize(80)
        self.rule_table.setColumnWidth(0, 300)
        self.rule_table.setColumnWidth(1, 100)
        self.rule_table.setColumnWidth(2, 240)
        self.rule_table.setColumnWidth(3, 100)
        self.rule_table.setColumnWidth(4, 80)
        self.rule_table.setColumnWidth(5, 90)
        self.rule_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.rule_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.rule_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.rule_table.cellDoubleClicked.connect(lambda _row, _column: self._edit_rule())
        self.rule_stack = QStackedWidget()
        self.empty_state = QLabel(
            "No rules yet\n\nAdd an image template to start building your first visual macro."
        )
        self.empty_state.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_state.setWordWrap(True)
        self.empty_state.setStyleSheet("font-size: 16px; color: #aab1bc; padding: 48px;")
        self.rule_stack.addWidget(self.empty_state)
        self.rule_stack.addWidget(self.rule_table)

        self.log_toggle = QToolButton()
        self.log_toggle.setText("Activity log")
        self.log_toggle.setCheckable(True)
        self.log_toggle.setChecked(True)
        self.log_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.log_toggle.setArrowType(Qt.ArrowType.DownArrow)
        self.log_panel = QPlainTextEdit()
        self.log_panel.setReadOnly(True)
        self.log_panel.setMaximumBlockCount(3000)
        self.log_panel.setPlaceholderText("Recognition results, planned actions, and errors appear here.")
        self.log_toggle.toggled.connect(self._toggle_log)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.addLayout(header)
        layout.addLayout(stats)
        layout.addLayout(run_controls)
        layout.addWidget(self.rule_stack, 1)
        layout.addWidget(self.log_toggle)
        layout.addWidget(self.log_panel)
        self.setCentralWidget(content)
        self._refresh_rules()
        self._set_status("Stopped")
        self._update_mode_indicator()

    def _create_toolbar(self) -> None:
        toolbar = QToolBar("Profiles")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)
        load_action = QAction("Load Profile…", self)
        load_action.triggered.connect(self._load_profile)
        save_action = QAction("Save Profile", self)
        save_action.triggered.connect(self._save_profile)
        toolbar.addAction(load_action)
        toolbar.addAction(save_action)
        self.load_button = load_action
        self.save_button = save_action
        file_menu = self.menuBar().addMenu("&Profile")
        file_menu.addAction(load_action)
        file_menu.addAction(save_action)

    def _add_rule(self) -> None:
        dialog = RuleDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            rule = dialog.rule()
            self.rules.append(rule)
            self._refresh_rules()
            self._log(f"Added rule: {rule.name}")

    def _edit_rule(self, row: int | None = None) -> None:
        row = self.rule_table.currentRow() if row is None else row
        if not 0 <= row < len(self.rules):
            return
        dialog = RuleDialog(self, self.rules[row])
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.rules[row] = dialog.rule()
            self._refresh_rules()
            self.rule_table.selectRow(row)
            self._log(f"Updated rule: {self.rules[row].name}")

    def _delete_rule(self, row: int | None = None) -> None:
        row = self.rule_table.currentRow() if row is None else row
        if not 0 <= row < len(self.rules):
            return
        rule = self.rules[row]
        answer = QMessageBox.question(
            self,
            "Delete rule?",
            f"Delete “{rule.name}”? This cannot be undone.",
            QMessageBox.StandardButton.Delete | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Delete:
            return
        self.rules.pop(row)
        self._refresh_rules()
        self._log(f"Deleted rule: {rule.name}")

    def _toggle_rule_enabled(self, row: int, enabled: bool) -> None:
        if 0 <= row < len(self.rules):
            self.rules[row].enabled = enabled
            self._refresh_rules()

    def _test_rule(self) -> None:
        row = self.rule_table.currentRow()
        if not 0 <= row < len(self.rules):
            self._log_error("Select a rule to test.")
            return
        rule = self.rules[row]
        if not rule.enabled:
            self._log_error(f"Enable the rule before testing it: {rule.name}.")
            return
        self._launch_worker([rule], once=True)
        self._log(f"Testing rule: {rule.name} (simulation preview; no input will be sent)")

    def _start_monitoring(self) -> None:
        try:
            profile = Profile(
                interval=self.interval_input.value(),
                simulation=self.simulation_input.isChecked(),
                rules=self.rules.copy(),
            )
        except ConfigurationError as exc:
            self._log_error(str(exc))
            return
        if not any(rule.enabled for rule in profile.rules):
            self._log_error("Add or enable at least one rule before starting.")
            return
        self._launch_worker(profile.rules)

    def _launch_worker(self, rules: list[Rule], once: bool = False) -> None:
        if self.worker is not None:
            self._log_error("Stop the current operation before starting another.")
            return
        try:
            profile = Profile(
                interval=self.interval_input.value(),
                simulation=self.simulation_input.isChecked(),
                rules=rules,
            )
        except ConfigurationError as exc:
            self._log_error(str(exc))
            return
        self._has_error = False
        self.worker = MacroWorker(profile, rules, once)
        self.worker.log_message.connect(self._log)
        self.worker.error_message.connect(self._on_worker_error)
        self.worker.finished.connect(self._worker_finished)
        self._set_running_controls(True)
        self._set_status("Running")
        self.worker.start()

    def _stop_monitoring(self) -> None:
        if self.worker is not None:
            self._log("Stop requested; waiting for the current operation to finish.")
            self.stop_button.setEnabled(False)
            self.worker.stop()

    def _worker_finished(self) -> None:
        self.worker = None
        self._set_running_controls(False)
        self._set_status("Error" if self._has_error else "Stopped")

    def _on_worker_error(self, message: str) -> None:
        self._has_error = True
        self._log_error(message)
        self._set_status("Error")

    def _set_running_controls(self, running: bool) -> None:
        for button in (self.add_button, self.test_button, self.start_button):
            button.setEnabled(not running)
        self.stop_button.setEnabled(running)
        self.rule_table.setEnabled(not running)
        self.interval_input.setEnabled(not running)
        self.simulation_input.setEnabled(not running)
        for action in (self.load_button, self.save_button):
            action.setEnabled(not running)

    def _set_status(self, status: str) -> None:
        colors = {"Stopped": "#737b87", "Running": "#45b881", "Error": "#ef6b63"}
        self.status_indicator.setText(f"●  {status}")
        self.status_indicator.setStyleSheet(
            f"color: {colors[status]}; font-weight: 700; padding: 4px 8px;"
        )

    def _update_mode_indicator(self) -> None:
        if not hasattr(self, "mode_label"):
            return
        simulation = self.simulation_input.isChecked()
        self.mode_label.setText(
            "SIMULATION — planned actions only"
            if simulation
            else "LIVE INPUT — sends real mouse/keyboard input"
        )
        self.mode_label.setStyleSheet(
            "color: #7ee0ae; font-weight: 600;"
            if simulation
            else "color: #ff8178; font-weight: 700;"
        )

    def _toggle_log(self, expanded: bool) -> None:
        self.log_panel.setVisible(expanded)
        self.log_toggle.setArrowType(Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow)

    def _load_profile(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Load profile", "", "JSON profiles (*.json);;All files (*.*)"
        )
        if not path:
            return
        try:
            profile = load_profile(path)
        except (OSError, ConfigurationError) as exc:
            self._log_error(f"Could not load profile: {exc}")
            return
        self._apply_profile(profile)
        self.profile_path = Path(path).resolve()
        self._log(f"Loaded profile: {self.profile_path}")

    def _save_profile(self) -> None:
        path = self.profile_path
        if path is None:
            filename, _ = QFileDialog.getSaveFileName(
                self, "Save profile", "", "JSON profiles (*.json)"
            )
            if not filename:
                return
            path = Path(filename).resolve()
            if path.suffix.lower() != ".json":
                path = path.with_suffix(".json")
        try:
            profile = Profile(
                interval=self.interval_input.value(),
                simulation=self.simulation_input.isChecked(),
                rules=self.rules.copy(),
            )
            save_profile(profile, path)
        except (OSError, ConfigurationError) as exc:
            self._log_error(f"Could not save profile: {exc}")
            return
        self.profile_path = path
        self._log(f"Saved profile: {self.profile_path}")

    def _apply_profile(self, profile: Profile) -> None:
        self.rules = profile.rules.copy()
        self.interval_input.setValue(profile.interval)
        self.simulation_input.setChecked(profile.simulation)
        self._refresh_rules()

    def _refresh_rules(self) -> None:
        self.total_label.setText(f"Rules: {len(self.rules)}")
        enabled_count = sum(rule.enabled for rule in self.rules)
        self.enabled_label.setText(f"Enabled: {enabled_count}")
        self.rule_stack.setCurrentWidget(self.rule_table if self.rules else self.empty_state)
        self.rule_table.setRowCount(len(self.rules))
        for row, rule in enumerate(self.rules):
            image_cell = QWidget()
            image_layout = QHBoxLayout(image_cell)
            image_layout.setContentsMargins(5, 3, 5, 3)
            thumbnail = QLabel()
            thumbnail.setFixedSize(44, 38)
            thumbnail.setAlignment(Qt.AlignmentFlag.AlignCenter)
            pixmap = QPixmap(rule.template_path)
            if not pixmap.isNull():
                thumbnail.setPixmap(
                    pixmap.scaled(
                        thumbnail.size(),
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
            else:
                thumbnail.setText("No preview")
            detail = QVBoxLayout()
            name = QLabel(rule.name)
            name.setStyleSheet("font-weight: 600;")
            filename = QLabel(Path(rule.template_path).name)
            filename.setStyleSheet("color: #aab1bc;")
            filename.setToolTip(rule.template_path)
            detail.addWidget(name)
            detail.addWidget(filename)
            image_layout.addWidget(thumbnail)
            image_layout.addLayout(detail, 1)
            self.rule_table.setCellWidget(row, 0, image_cell)

            for column, text in (
                (1, f"{rule.threshold:.0%}"),
                (2, _actions_summary(rule.actions)),
                (3, f"{rule.cooldown:g}s"),
            ):
                item = QTableWidgetItem(text)
                item.setToolTip(text)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.rule_table.setItem(row, column, item)

            enabled = QCheckBox()
            enabled.setChecked(rule.enabled)
            enabled.setToolTip("Rule enabled")
            enabled.stateChanged.connect(
                lambda state, rule_row=row: self._toggle_rule_enabled(
                    rule_row, state == Qt.CheckState.Checked.value
                )
            )
            enabled_cell = QWidget()
            enabled_layout = QHBoxLayout(enabled_cell)
            enabled_layout.setContentsMargins(0, 0, 0, 0)
            enabled_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
            enabled_layout.addWidget(enabled)
            self.rule_table.setCellWidget(row, 4, enabled_cell)

            edit_button = QPushButton("Edit")
            edit_button.clicked.connect(lambda _checked=False, rule_row=row: self._edit_rule(rule_row))
            self.rule_table.setCellWidget(row, 5, edit_button)
            self.rule_table.setRowHeight(row, 48)
        self.rule_table.setEnabled(self.worker is None)

    def _log(self, message: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_panel.appendPlainText(f"[{timestamp}] {message}")

    def _log_error(self, message: str) -> None:
        self._has_error = True
        if hasattr(self, "status_indicator"):
            self._set_status("Error")
        self._log(f"ERROR: {message}")

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.worker is not None:
            self.worker.stop()
            self.worker.wait()
        event.accept()


def _action_summary(action: dict[str, Any]) -> str:
    kind = action.get("type")
    if kind == "click":
        count = action.get("clicks", 1)
        button = action.get("button", "left")
        return f"{button.title()} click ({action.get('x')}, {action.get('y')})" + (
            f" ×{count}" if count > 1 else ""
        )
    if kind == "click_center":
        count = action.get("clicks", 1)
        return f"{action.get('button', 'left').title()} click image center" + (
            f" ×{count}" if count > 1 else ""
        )
    if kind == "click_offset":
        count = action.get("clicks", 1)
        return (
            f"{action.get('button', 'left').title()} click center "
            f"({action.get('offset_x', 0):+}, {action.get('offset_y', 0):+})"
            + (f" ×{count}" if count > 1 else "")
        )
    if kind == "press":
        return f"Press {action.get('key', '?')}"
    if kind == "delay":
        return f"Wait {action.get('seconds', '?')}s"
    return f"Unsupported action: {kind}"


def _actions_summary(actions: list[dict[str, Any]]) -> str:
    if not actions:
        return "No actions"
    summary = " → ".join(_action_summary(action) for action in actions[:2])
    if len(actions) > 2:
        summary += f" → +{len(actions) - 2} more"
    return summary


def main() -> int:
    from PySide6.QtWidgets import QApplication

    _enable_per_monitor_dpi_awareness()
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec()


def _enable_per_monitor_dpi_awareness() -> None:
    if sys.platform != "win32":
        return
    try:
        user32 = ctypes.windll.user32
        set_context = getattr(user32, "SetProcessDpiAwarenessContext", None)
        if set_context is not None and set_context(ctypes.c_void_p(-4)):
            return
        error = ctypes.get_last_error()
        if error == 5:
            return
        result = int(ctypes.windll.shcore.SetProcessDpiAwareness(2)) & 0xFFFFFFFF
        if result in (0, 0x80070005):
            return
        raise OSError(f"Windows DPI-awareness setup returned HRESULT 0x{result:08X}")
    except (AttributeError, OSError) as exc:
        import warnings

        warnings.warn(
            f"Could not enable per-monitor DPI awareness; desktop coordinates may not align: {exc}",
            RuntimeWarning,
            stacklevel=2,
        )
