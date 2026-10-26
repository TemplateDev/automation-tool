from __future__ import annotations

import ctypes
import sys
import uuid
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any

import cv2
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction, QCloseEvent, QImage, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QButtonGroup,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QRadioButton,
    QSpinBox,
    QStackedWidget,
    QStyle,
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
    Macro,
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
from visual_macro.region_picker import ScreenPositionOverlay, ScreenRegionOverlay
from visual_macro.worker import MacroWorker
from visual_macro.storage import ApplicationStorage, StorageError


class ActionDialog(QDialog):
    """Typed editor for the click, press, and delay actions supported by the executor."""

    def __init__(
        self,
        parent=None,
        action: dict[str, Any] | None = None,
        action_depth: int = 0,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Edit Action" if action else "Add Action")

        self.type_input = QComboBox()
        self.type_input.addItem("Click at screen coordinates", "click")
        self.type_input.addItem("Click detected image center", "click_center")
        self.type_input.addItem("Click offset from detected image center", "click_offset")
        self.type_input.addItem("Move mouse to screen position", "move")
        self.type_input.addItem("Scroll mouse wheel", "scroll")
        self.type_input.addItem("Press a key", "press")
        self.type_input.addItem("Type text", "type_text")
        self.type_input.addItem("Press a key combination", "hotkey")
        self.type_input.addItem("Hold a key", "key_down")
        self.type_input.addItem("Release a key", "key_up")
        self.type_input.addItem("Wait", "delay")
        self.type_input.addItem("Wait for an image", "wait_image")
        self.type_input.addItem("Branch on an image", "if_image")
        if action_depth < 5:
            self.type_input.addItem("Repeat an action sequence", "repeat")

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
        self.pick_position_button = QPushButton("Pick Position…")
        self.pick_position_button.setToolTip(
            "Select a point on the desktop and use its input-executor coordinates."
        )
        self.pick_position_button.clicked.connect(
            lambda: self._pick_position(self.x_input, self.y_input)
        )
        self.position_summary = QLabel()
        self.x_input.valueChanged.connect(self._update_position_summary)
        self.y_input.valueChanged.connect(self._update_position_summary)
        position_row = QHBoxLayout()
        position_row.addWidget(self.pick_position_button)
        position_row.addWidget(self.position_summary, 1)
        click_form.addRow("Position", position_row)
        click_form.addRow("Screen X", self.x_input)
        click_form.addRow("Screen Y", self.y_input)
        click_form.addRow("Mouse button", self.button_input)
        click_form.addRow("Click count (2 = double-click)", self.clicks_input)

        self.center_fields = QWidget()
        center_form = QFormLayout(self.center_fields)
        self.center_button_input = QComboBox()
        self.center_button_input.addItems(["left", "right", "middle"])
        self.center_clicks_input = QSpinBox()
        self.center_clicks_input.setRange(1, 10)
        center_form.addRow("Mouse button", self.center_button_input)
        center_form.addRow("Click count (2 = double-click)", self.center_clicks_input)

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
        offset_form.addRow("Click count (2 = double-click)", self.offset_clicks_input)

        self.move_fields = QWidget()
        move_form = QFormLayout(self.move_fields)
        self.move_x_input = QSpinBox()
        self.move_x_input.setRange(-100000, 100000)
        self.move_y_input = QSpinBox()
        self.move_y_input.setRange(-100000, 100000)
        self.move_pick_button = QPushButton("Pick Position…")
        self.move_pick_button.clicked.connect(
            lambda: self._pick_position(self.move_x_input, self.move_y_input)
        )
        move_form.addRow("Screen X", self.move_x_input)
        move_form.addRow("Screen Y", self.move_y_input)
        move_form.addRow(self.move_pick_button)

        self.scroll_fields = QWidget()
        scroll_form = QFormLayout(self.scroll_fields)
        self.scroll_direction_input = QComboBox()
        self.scroll_direction_input.addItem("Vertical", "vertical")
        self.scroll_direction_input.addItem("Horizontal", "horizontal")
        self.scroll_amount_input = QSpinBox()
        self.scroll_amount_input.setRange(-10000, 10000)
        self.scroll_amount_input.setSpecialValueText("0")
        scroll_form.addRow("Direction", self.scroll_direction_input)
        scroll_form.addRow("Amount (negative reverses direction)", self.scroll_amount_input)

        self.press_fields = QWidget()
        press_form = QFormLayout(self.press_fields)
        self.key_input = QComboBox()
        self.key_input.setEditable(True)
        self.key_input.addItems(_common_keys())
        self.key_input.setCurrentText("")
        self.key_input.setToolTip("Choose a common key or type a supported key name.")
        press_form.addRow("Key", self.key_input)

        self.text_fields = QWidget()
        text_form = QFormLayout(self.text_fields)
        self.text_input = QPlainTextEdit()
        self.text_input.setMaximumHeight(100)
        self.text_input.setPlaceholderText("Text to type")
        text_form.addRow("Text", self.text_input)

        self.hotkey_fields = QWidget()
        hotkey_form = QFormLayout(self.hotkey_fields)
        self.hotkey_input = QLineEdit()
        self.hotkey_input.setPlaceholderText("ctrl, c")
        self.hotkey_input.setToolTip("Enter two or more supported keys separated by commas.")
        hotkey_form.addRow("Keys in order", self.hotkey_input)

        self.delay_fields = QWidget()
        delay_form = QFormLayout(self.delay_fields)
        self.seconds_input = QDoubleSpinBox()
        self.seconds_input.setRange(0, 300)
        self.seconds_input.setDecimals(2)
        self.seconds_input.setSuffix(" seconds")
        delay_form.addRow("Duration", self.seconds_input)

        self.condition_fields = QWidget()
        condition_layout = QVBoxLayout(self.condition_fields)
        condition_form = QFormLayout()
        self.condition_mode_input = QComboBox()
        self.condition_mode_input.addItem("Wait until it appears", "appears")
        self.condition_mode_input.addItem("Wait until it disappears", "disappears")
        self.condition_path_input = QLineEdit()
        self.condition_path_input.setPlaceholderText("Choose an image template")
        self.condition_browse_button = QPushButton("Choose Image…")
        self.condition_browse_button.clicked.connect(self._browse_condition_template)
        path_row = QHBoxLayout()
        path_row.addWidget(self.condition_path_input, 1)
        path_row.addWidget(self.condition_browse_button)
        self.condition_threshold_input = QSpinBox()
        self.condition_threshold_input.setRange(0, 100)
        self.condition_threshold_input.setValue(85)
        self.condition_threshold_input.setSuffix("%")
        self.condition_timeout_input = QDoubleSpinBox()
        self.condition_timeout_input.setRange(0, 300)
        self.condition_timeout_input.setDecimals(2)
        self.condition_timeout_input.setSuffix(" seconds")
        self.condition_interval_input = QDoubleSpinBox()
        self.condition_interval_input.setRange(0.05, 10)
        self.condition_interval_input.setDecimals(2)
        self.condition_interval_input.setValue(0.25)
        self.condition_interval_input.setSuffix(" seconds")
        condition_form.addRow("Condition", self.condition_mode_input)
        condition_form.addRow("Image template", path_row)
        condition_form.addRow("Confidence threshold", self.condition_threshold_input)
        condition_form.addRow("Timeout", self.condition_timeout_input)
        condition_form.addRow("Check every", self.condition_interval_input)
        condition_layout.addLayout(condition_form)
        self.then_actions_label = QLabel("When detected, run:")
        self.then_actions_builder = ActionBuilder([], self, action_depth=action_depth + 1)
        self.else_actions_label = QLabel("When not detected before timeout, run:")
        self.else_actions_builder = ActionBuilder([], self, action_depth=action_depth + 1)
        condition_layout.addWidget(self.then_actions_label)
        condition_layout.addWidget(self.then_actions_builder)
        condition_layout.addWidget(self.else_actions_label)
        condition_layout.addWidget(self.else_actions_builder)

        self.repeat_fields = QWidget()
        repeat_form = QVBoxLayout(self.repeat_fields)
        repeat_count_form = QFormLayout()
        self.repeat_count_input = QSpinBox()
        self.repeat_count_input.setRange(1, 100)
        repeat_count_form.addRow("Repeat count", self.repeat_count_input)
        repeat_form.addLayout(repeat_count_form)
        self.repeat_builder = ActionBuilder([], self, action_depth=action_depth + 1)
        repeat_form.addWidget(QLabel("Actions to repeat"))
        repeat_form.addWidget(self.repeat_builder)

        self.fields_stack = QStackedWidget()
        for fields in (
            self.click_fields,
            self.center_fields,
            self.offset_fields,
            self.move_fields,
            self.scroll_fields,
            self.press_fields,
            self.text_fields,
            self.hotkey_fields,
            self.delay_fields,
            self.condition_fields,
            self.repeat_fields,
        ):
            self.fields_stack.addWidget(fields)
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
                self.key_input.setCurrentText(action.get("key", ""))
            elif action.get("type") in {"key_down", "key_up"}:
                self.key_input.setCurrentText(action.get("key", ""))
            elif action.get("type") == "move":
                self.move_x_input.setValue(action.get("x", 0))
                self.move_y_input.setValue(action.get("y", 0))
            elif action.get("type") == "scroll":
                index = self.scroll_direction_input.findData(
                    action.get("direction", "vertical")
                )
                self.scroll_direction_input.setCurrentIndex(max(0, index))
                self.scroll_amount_input.setValue(action.get("amount", 1))
            elif action.get("type") == "type_text":
                self.text_input.setPlainText(action.get("text", ""))
            elif action.get("type") == "hotkey":
                self.hotkey_input.setText(", ".join(action.get("keys", [])))
            elif action.get("type") == "repeat":
                self.repeat_count_input.setValue(action.get("count", 1))
                self.repeat_builder.set_actions(action.get("actions", []))
            elif action.get("type") == "delay":
                self.seconds_input.setValue(action.get("seconds", 0))
            elif action.get("type") in {"wait_image", "if_image"}:
                mode_index = self.condition_mode_input.findData(
                    action.get("condition", "appears")
                )
                self.condition_mode_input.setCurrentIndex(max(0, mode_index))
                self.condition_path_input.setText(action.get("template_path", ""))
                self.condition_threshold_input.setValue(
                    round(action.get("threshold", 0.85) * 100)
                )
                self.condition_timeout_input.setValue(action.get("timeout", 10))
                self.condition_interval_input.setValue(action.get("interval", 0.25))
                self.then_actions_builder.set_actions(action.get("then_actions", []))
                self.else_actions_builder.set_actions(action.get("else_actions", []))
        self._update_fields()
        self._update_position_summary()

    def _pick_position(
        self,
        x_input: QSpinBox | None = None,
        y_input: QSpinBox | None = None,
    ) -> None:
        x_input = x_input or self.x_input
        y_input = y_input or self.y_input
        try:
            mapper = ScreenCoordinateMapper.from_desktop()
            overlay = ScreenPositionOverlay(mapper, self)
            if overlay.exec() != QDialog.DialogCode.Accepted:
                return
            if overlay.selected_position is None:
                self.error_label.setText("No screen position was selected.")
                return
            x, y = overlay.selected_position
            x_input.setValue(x)
            y_input.setValue(y)
            self.error_label.clear()
        except (RuntimeError, ValueError) as exc:
            self.error_label.setText(f"Could not select a desktop position: {exc}")

    def _update_position_summary(self) -> None:
        self.position_summary.setText(
            f"Executor coordinates: ({self.x_input.value()}, {self.y_input.value()})"
        )

    def _browse_condition_template(self) -> None:
        path, _selected_filter = QFileDialog.getOpenFileName(
            self,
            "Choose Image Condition Template",
            "",
            "Image files (*.png *.jpg *.jpeg *.bmp *.webp)",
        )
        if path:
            self.condition_path_input.setText(path)

    def _update_fields(self) -> None:
        field_index = {
            "click": 0,
            "click_center": 1,
            "click_offset": 2,
            "move": 3,
            "scroll": 4,
            "press": 5,
            "type_text": 6,
            "hotkey": 7,
            "delay": 8,
            "wait_image": 9,
            "if_image": 9,
            "repeat": 10,
            "key_down": 5,
            "key_up": 5,
        }[self.type_input.currentData()]
        self.fields_stack.setCurrentIndex(field_index)
        is_branch = self.type_input.currentData() == "if_image"
        self.condition_mode_input.setVisible(not is_branch)
        self.then_actions_label.setVisible(is_branch)
        self.then_actions_builder.setVisible(is_branch)
        self.else_actions_label.setVisible(is_branch)
        self.else_actions_builder.setVisible(is_branch)

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
        elif kind in {"press", "key_down", "key_up"}:
            action = {"type": kind, "key": self.key_input.currentText().strip()}
        elif kind == "move":
            action = {
                "type": kind,
                "x": self.move_x_input.value(),
                "y": self.move_y_input.value(),
            }
        elif kind == "scroll":
            action = {
                "type": kind,
                "direction": self.scroll_direction_input.currentData(),
                "amount": self.scroll_amount_input.value(),
            }
        elif kind == "type_text":
            action = {"type": kind, "text": self.text_input.toPlainText()}
        elif kind == "hotkey":
            action = {
                "type": kind,
                "keys": [key.strip() for key in self.hotkey_input.text().split(",") if key.strip()],
            }
        elif kind == "wait_image":
            action = {
                "type": kind,
                "condition": self.condition_mode_input.currentData(),
                "template_path": self.condition_path_input.text().strip(),
                "threshold": self.condition_threshold_input.value() / 100,
                "timeout": self.condition_timeout_input.value(),
                "interval": self.condition_interval_input.value(),
            }
        elif kind == "if_image":
            action = {
                "type": kind,
                "template_path": self.condition_path_input.text().strip(),
                "threshold": self.condition_threshold_input.value() / 100,
                "timeout": self.condition_timeout_input.value(),
                "interval": self.condition_interval_input.value(),
                "then_actions": deepcopy(self.then_actions_builder.actions),
                "else_actions": deepcopy(self.else_actions_builder.actions),
            }
        elif kind == "repeat":
            action = {
                "type": kind,
                "count": self.repeat_count_input.value(),
                "actions": deepcopy(self.repeat_builder.actions),
            }
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

    actions_changed = Signal()

    def __init__(
        self,
        actions: list[dict[str, Any]] | None = None,
        parent=None,
        action_depth: int = 0,
    ) -> None:
        super().__init__(parent)
        self.actions = deepcopy(actions or [])
        self.action_depth = action_depth
        self.action_list = QTableWidget(0, 1)
        self.action_list.setHorizontalHeaderLabels(["Actions in this macro"])
        self.action_list.horizontalHeader().setStretchLastSection(True)
        self.action_list.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.action_list.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.action_list.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.action_list.cellDoubleClicked.connect(lambda _row, _column: self._edit_action())
        self.empty_state = QLabel(
            "This macro has no actions yet. Add an action to define what it should do."
        )
        self.empty_state.setWordWrap(True)
        self.empty_state.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_state.setStyleSheet("color: #aab1bc; padding: 16px;")

        self.add_button = QPushButton("Add Action…")
        self.edit_button = QPushButton("Edit Action")
        self.duplicate_button = QPushButton("Duplicate Action")
        self.remove_button = QPushButton("Delete Action")
        self.up_button = QPushButton("Move Up")
        self.down_button = QPushButton("Move Down")
        self.add_button.setToolTip("Add a mouse, keyboard, timing, or repeat action.")
        self.edit_button.setToolTip("Edit the selected action's settings.")
        self.duplicate_button.setToolTip("Insert a copy of the selected action after it.")
        self.remove_button.setToolTip("Delete only the selected action from this macro.")
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
        layout.addWidget(self.empty_state)
        layout.addWidget(self.action_list)
        layout.addLayout(buttons)
        self._refresh()

    def _selected_row(self) -> int:
        return self.action_list.currentRow()

    def _add_action(self) -> None:
        dialog = ActionDialog(self, action_depth=self.action_depth)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.actions.append(dialog.action())
            self._refresh(select=len(self.actions) - 1)
            self.actions_changed.emit()

    def _edit_action(self) -> None:
        row = self._selected_row()
        if not 0 <= row < len(self.actions):
            return
        dialog = ActionDialog(self, self.actions[row], action_depth=self.action_depth)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.actions[row] = dialog.action()
            self._refresh(select=row)
            self.actions_changed.emit()

    def _duplicate_action(self) -> None:
        row = self._selected_row()
        if 0 <= row < len(self.actions):
            self.actions.insert(row + 1, deepcopy(self.actions[row]))
            self._refresh(select=row + 1)
            self.actions_changed.emit()

    def _remove_action(self) -> None:
        row = self._selected_row()
        if 0 <= row < len(self.actions):
            self.actions.pop(row)
            self._refresh(select=min(row, len(self.actions) - 1))
            self.actions_changed.emit()

    def _move_action(self, offset: int) -> None:
        row = self._selected_row()
        target = row + offset
        if 0 <= row < len(self.actions) and 0 <= target < len(self.actions):
            self.actions[row], self.actions[target] = self.actions[target], self.actions[row]
            self._refresh(select=target)
            self.actions_changed.emit()

    def set_actions(self, actions: list[dict[str, Any]]) -> None:
        self.actions = deepcopy(actions)
        self._refresh()

    def _refresh(self, select: int = -1) -> None:
        has_actions = bool(self.actions)
        self.empty_state.setVisible(not has_actions)
        self.action_list.setVisible(has_actions)
        self.action_list.setRowCount(len(self.actions))
        for row, action in enumerate(self.actions):
            item = QTableWidgetItem(_action_summary(action))
            icon_kind = action.get("type")
            icon_pixmap = {
                "click": QStyle.StandardPixmap.SP_ComputerIcon,
                "click_center": QStyle.StandardPixmap.SP_ComputerIcon,
                "click_offset": QStyle.StandardPixmap.SP_ComputerIcon,
                "move": QStyle.StandardPixmap.SP_ArrowForward,
                "scroll": QStyle.StandardPixmap.SP_ArrowDown,
                "press": QStyle.StandardPixmap.SP_FileIcon,
                "key_down": QStyle.StandardPixmap.SP_FileIcon,
                "key_up": QStyle.StandardPixmap.SP_FileIcon,
                "hotkey": QStyle.StandardPixmap.SP_FileDialogDetailedView,
                "type_text": QStyle.StandardPixmap.SP_FileDialogContentsView,
                "delay": QStyle.StandardPixmap.SP_MediaPause,
                "repeat": QStyle.StandardPixmap.SP_BrowserReload,
                "wait_image": QStyle.StandardPixmap.SP_MediaPlay,
                "if_image": QStyle.StandardPixmap.SP_FileDialogListView,
            }.get(icon_kind, QStyle.StandardPixmap.SP_FileIcon)
            item.setIcon(self.style().standardIcon(icon_pixmap))
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.action_list.setItem(row, 0, item)
        if 0 <= select < len(self.actions):
            self.action_list.selectRow(select)
        self.action_list.resizeRowsToContents()


class MacroBuilder(QWidget):
    """Manage named macro sequences and their actions independently."""

    def __init__(self, macros: list[Macro], parent=None) -> None:
        super().__init__(parent)
        self.macros = deepcopy(macros)
        self.macro_list = QTableWidget(0, 1)
        self.macro_list.setHorizontalHeaderLabels(["Macros run when this rule triggers"])
        self.macro_list.horizontalHeader().setStretchLastSection(True)
        self.macro_list.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.macro_list.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.macro_list.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.macro_list.currentCellChanged.connect(self._selection_changed)
        self.macro_empty_state = QLabel(
            "No macros yet. Add a macro to define an independent action sequence."
        )
        self.macro_empty_state.setWordWrap(True)
        self.macro_empty_state.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.macro_empty_state.setStyleSheet("color: #aab1bc; padding: 10px;")

        self.add_macro_button = QPushButton("Add macro…")
        self.edit_macro_button = QPushButton("Rename macro…")
        self.duplicate_macro_button = QPushButton("Duplicate macro")
        self.remove_macro_button = QPushButton("Delete macro")
        self.macro_up_button = QPushButton("Move macro up")
        self.macro_down_button = QPushButton("Move macro down")
        self.add_macro_button.clicked.connect(self._add_macro)
        self.edit_macro_button.clicked.connect(self._edit_macro)
        self.duplicate_macro_button.clicked.connect(self._duplicate_macro)
        self.remove_macro_button.clicked.connect(self._delete_macro)
        self.macro_up_button.clicked.connect(lambda: self._move_macro(-1))
        self.macro_down_button.clicked.connect(lambda: self._move_macro(1))

        macro_buttons = QHBoxLayout()
        for button in (
            self.add_macro_button,
            self.edit_macro_button,
            self.duplicate_macro_button,
            self.remove_macro_button,
            self.macro_up_button,
            self.macro_down_button,
        ):
            macro_buttons.addWidget(button)

        self.action_builder = ActionBuilder(
            self.macros[0].actions if self.macros else []
        )
        self.action_builder.actions_changed.connect(self._sync_selected_actions)
        self.macros_group = QGroupBox("Actions in selected macro")
        actions_layout = QVBoxLayout(self.macros_group)
        actions_layout.addWidget(self.action_builder)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.macro_empty_state)
        layout.addWidget(self.macro_list)
        layout.addLayout(macro_buttons)
        layout.addWidget(self.macros_group)
        self._refresh_macros(select=0 if self.macros else -1)

    @property
    def actions(self) -> list[dict[str, Any]]:
        return self.action_builder.actions

    def _selected_macro(self) -> int:
        return self.macro_list.currentRow()

    def _sync_selected_actions(self, *_args) -> None:
        row = self._selected_macro()
        if 0 <= row < len(self.macros):
            self.macros[row].actions = deepcopy(self.action_builder.actions)
            self._refresh_macros(select=row)

    def _selection_changed(self, current_row: int, *_args) -> None:
        old_row = self._selected_macro_before_change
        if 0 <= old_row < len(self.macros):
            self.macros[old_row].actions = deepcopy(self.action_builder.actions)
        if 0 <= current_row < len(self.macros):
            self.action_builder.set_actions(self.macros[current_row].actions)
        else:
            self.action_builder.set_actions([])
        self._selected_macro_before_change = current_row

    def _refresh_macros(self, select: int = -1) -> None:
        self._selected_macro_before_change = select
        self.macro_empty_state.setVisible(not self.macros)
        self.macro_list.setVisible(bool(self.macros))
        self.macro_list.setRowCount(len(self.macros))
        for row, macro in enumerate(self.macros):
            item = QTableWidgetItem(f"{macro.name}  ·  {len(macro.actions)} action(s)")
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.macro_list.setItem(row, 0, item)
        if 0 <= select < len(self.macros):
            self.macro_list.selectRow(select)
            self.action_builder.set_actions(self.macros[select].actions)
        else:
            self.action_builder.set_actions([])
        self.macros_group.setTitle(
            "Actions in selected macro"
            if self.macros
            else "Actions (add a macro first)"
        )

    def _add_macro(self) -> None:
        name, accepted = QInputDialog.getText(self, "Add macro", "Macro name:")
        if not accepted or not name.strip():
            return
        if self._name_exists(name):
            QMessageBox.warning(self, "Duplicate macro name", "Choose a unique macro name.")
            return
        self._sync_selected_actions()
        self.macros.append(Macro(name.strip(), []))
        self._refresh_macros(select=len(self.macros) - 1)

    def _edit_macro(self) -> None:
        row = self._selected_macro()
        if not 0 <= row < len(self.macros):
            return
        name, accepted = QInputDialog.getText(
            self, "Rename macro", "Macro name:", text=self.macros[row].name
        )
        if not accepted or not name.strip():
            return
        if self._name_exists(name, exclude=row):
            QMessageBox.warning(self, "Duplicate macro name", "Choose a unique macro name.")
            return
        self.macros[row].name = name.strip()
        self._refresh_macros(select=row)

    def _duplicate_macro(self) -> None:
        row = self._selected_macro()
        if not 0 <= row < len(self.macros):
            return
        self._sync_selected_actions()
        original = self.macros[row]
        name = self._unique_copy_name(original.name)
        self.macros.insert(row + 1, Macro(name, deepcopy(original.actions)))
        self._refresh_macros(select=row + 1)

    def _delete_macro(self) -> None:
        row = self._selected_macro()
        if not 0 <= row < len(self.macros):
            return
        macro = self.macros[row]
        answer = QMessageBox.question(
            self,
            "Delete entire macro?",
            f"Delete macro “{macro.name}” and all {len(macro.actions)} of its actions?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.macros.pop(row)
        self._refresh_macros(select=min(row, len(self.macros) - 1))

    def _move_macro(self, offset: int) -> None:
        row = self._selected_macro()
        target = row + offset
        if 0 <= row < len(self.macros) and 0 <= target < len(self.macros):
            self._sync_selected_actions()
            self.macros[row], self.macros[target] = self.macros[target], self.macros[row]
            self._refresh_macros(select=target)

    def _name_exists(self, name: str, exclude: int = -1) -> bool:
        normalized = name.strip().casefold()
        return any(
            index != exclude and macro.name.casefold() == normalized
            for index, macro in enumerate(self.macros)
        )

    def _unique_copy_name(self, original: str) -> str:
        base = f"Copy of {original}"
        name = base
        suffix = 2
        while self._name_exists(name):
            name = f"{base} ({suffix})"
            suffix += 1
        return name


class RuleDialog(QDialog):
    def __init__(
        self,
        parent=None,
        rule: Rule | None = None,
        template_path: str = "",
        storage: ApplicationStorage | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Edit Rule" if rule else "Add Rule")
        self.resize(620, 700)
        self._rule_id = rule.id if rule else str(uuid.uuid4())
        self.storage = storage or ApplicationStorage()
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
        self.choose_image_button = QPushButton("Import Image…")
        self.choose_image_button.clicked.connect(self._import_template)
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
        self.select_region_button = QPushButton("Select Region")
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

        macros = (
            deepcopy(rule.macros)
            if rule and rule.macros
            else [Macro("Default macro", deepcopy(rule.actions if rule else []))]
        )
        self.macro_builder = MacroBuilder(macros)
        self.action_builder = self.macro_builder.action_builder
        actions_group = QGroupBox("Actions")
        actions_layout = QVBoxLayout(actions_group)
        actions_layout.addWidget(
            QLabel("Each macro runs in order when this rule detects its image.")
        )
        actions_layout.addWidget(self.macro_builder)

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

    def _import_template(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Import image template",
            self.template_path,
            "Image files (*.png *.jpg *.jpeg *.bmp *.webp);;All files (*.*)",
        )
        if path:
            try:
                managed_path = self.storage.import_image(path)
            except StorageError as exc:
                self._error_label.setText(str(exc))
                return
            self.template_path = str(managed_path)
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
        friendly_name = QLineEdit(self.name_input.text().strip() or "Captured template")
        friendly_name.setPlaceholderText("Friendly template name")
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
        preview_buttons = QHBoxLayout()
        confirm_save = QPushButton("Save to Application Templates")
        cancel_save = QPushButton("Cancel")
        preview_buttons.addStretch(1)
        preview_buttons.addWidget(confirm_save)
        preview_buttons.addWidget(cancel_save)
        confirm_save.clicked.connect(preview_dialog.accept)
        cancel_save.clicked.connect(preview_dialog.reject)
        preview_layout = QVBoxLayout(preview_dialog)
        preview_layout.addWidget(QLabel(f"Captured template: {width} × {height} pixels"))
        preview_layout.addWidget(QLabel("Friendly name"))
        preview_layout.addWidget(friendly_name)
        preview_layout.addWidget(preview_label, 1)
        preview_layout.addLayout(preview_buttons)
        if preview_dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            saved_path = self.storage.store_capture(image, friendly_name.text())
        except StorageError as exc:
            self._error_label.setText(str(exc))
            return
        self.template_path = str(saved_path)
        self._update_image()
        if not self.name_input.text().strip() or self.name_input.text() == "New rule":
            self.name_input.setText(friendly_name.text().strip() or saved_path.stem)

    def _build_rule(self) -> Rule:
        region = None
        if self.region_enabled.isChecked():
            region = (
                self.region_x.value(),
                self.region_y.value(),
                self.region_width.value(),
                self.region_height.value(),
            )
        macros = deepcopy(self.macro_builder.macros)
        actions = deepcopy(macros[0].actions) if macros else []
        saved_macros = (
            macros
            if len(macros) > 1
            or (macros and macros[0].name != "Default macro")
            else None
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
            actions=actions,
            macros=saved_macros,
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
    def __init__(self, storage: ApplicationStorage | None = None) -> None:
        super().__init__()
        self.setWindowTitle("Visual Macro Automation")
        self.resize(1060, 760)
        self.rules: list[Rule] = []
        self.profile_path: Path | None = None
        self.worker: MacroWorker | None = None
        self._has_error = False
        self._persistent_log_error_reported = False
        self._live_confirmed_this_session = False
        self._mode_change_in_progress = False
        try:
            self.storage: ApplicationStorage | None = storage or ApplicationStorage()
            self.storage.initialize()
        except StorageError as exc:
            self.storage = None
            self._storage_error = str(exc)
        else:
            self._storage_error = None
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
        self.simulation_input = QRadioButton("Simulation")
        self.simulation_input.setChecked(True)
        self.simulation_input.setToolTip("Actions are logged but not executed.")
        self.live_input = QRadioButton("Live Input")
        self.live_input.setToolTip("Actions send real mouse and keyboard input.")
        self.execution_mode_group = QButtonGroup(self)
        self.execution_mode_group.setExclusive(True)
        self.execution_mode_group.addButton(self.simulation_input)
        self.execution_mode_group.addButton(self.live_input)
        self.live_input.toggled.connect(self._live_mode_toggled)
        self.simulation_input.toggled.connect(self._mode_radio_changed)

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
        run_controls.addWidget(self.simulation_input)
        run_controls.addWidget(self.live_input)
        run_controls.addWidget(self.mode_label)
        run_controls.addWidget(self.start_button)
        run_controls.addWidget(self.stop_button)
        self.mode_help_label = QLabel(
            "Simulation: actions are logged but not executed.  "
            "Live Input: actions send real mouse and keyboard input."
        )
        self.mode_help_label.setStyleSheet("color: #aab1bc;")

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
        layout.addWidget(self.mode_help_label)
        layout.addWidget(self.rule_stack, 1)
        layout.addWidget(self.log_toggle)
        layout.addWidget(self.log_panel)
        self.setCentralWidget(content)
        self._refresh_rules()
        self._set_status("Stopped")
        self._update_mode_indicator()
        if self._storage_error:
            self._log_error(self._storage_error)
        else:
            self._restore_last_profile()

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
        dialog = RuleDialog(self, storage=self.storage)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            rule = dialog.rule()
            self.rules.append(rule)
            self._refresh_rules()
            self._log(f"Added rule: {rule.name}")

    def _edit_rule(self, row: int | None = None) -> None:
        row = self.rule_table.currentRow() if row is None else row
        if not 0 <= row < len(self.rules):
            return
        dialog = RuleDialog(self, self.rules[row], storage=self.storage)
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
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
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
        self._log(
            "Starting monitoring in "
            f"{'Simulation (actions logged, not executed)' if profile.simulation else 'Live Input (real mouse/keyboard input)'} mode."
        )
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
        for button in (
            self.add_button,
            self.test_button,
            self.start_button,
            self.simulation_input,
            self.live_input,
        ):
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
            "SIMULATION · logged only"
            if simulation
            else "● LIVE INPUT · real input"
        )
        self.mode_label.setStyleSheet(
            "color: #7ee0ae; font-weight: 700; padding: 5px;"
            if simulation
            else "color: #ff8178; background: #3a2022; font-weight: 800; padding: 5px;"
        )

    def _mode_radio_changed(self, checked: bool) -> None:
        if checked and not self._mode_change_in_progress:
            self._update_mode_indicator()
            self._log("Execution mode set to Simulation: actions are logged but not executed.")
            self._persist_ui_settings()

    def _live_mode_toggled(self, checked: bool) -> None:
        if not checked or self._mode_change_in_progress:
            return
        if not self._live_confirmed_this_session:
            answer = QMessageBox.warning(
                self,
                "Enable Live Input?",
                "Live Input sends real mouse clicks and keyboard presses to your desktop. "
                "Only enable it if you trust every configured rule and macro.",
                QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Yes,
                QMessageBox.StandardButton.Cancel,
            )
            if answer != QMessageBox.StandardButton.Yes:
                self._mode_change_in_progress = True
                self.simulation_input.setChecked(True)
                self._mode_change_in_progress = False
                self._update_mode_indicator()
                self._log(
                    "Live Input activation was cancelled. Simulation remains active; "
                    "actions are logged but not executed."
                )
                return
            self._live_confirmed_this_session = True
        self._update_mode_indicator()
        self._log("Execution mode set to Live Input: actions send real mouse and keyboard input.")
        self._persist_ui_settings()

    def _select_execution_mode(self, simulation: bool) -> bool:
        if simulation:
            self.simulation_input.setChecked(True)
            self._update_mode_indicator()
            if not self.simulation_input.signalsBlocked():
                self._log(
                    "Execution mode set to Simulation: actions are logged but not executed."
                )
                self._persist_ui_settings()
            return True
        self.live_input.setChecked(True)
        return self.live_input.isChecked()

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
        self._remember_profile()
        self._log(f"Loaded profile: {self.profile_path}")

    def _save_profile(self) -> None:
        path = self.profile_path
        if path is None:
            if self.storage is None:
                self._log_error("Application storage is unavailable; cannot save a managed profile.")
                return
            filename, _ = QFileDialog.getSaveFileName(
                self,
                "Save profile",
                str(self.storage.profiles_dir / "profile.json"),
                "JSON profiles (*.json)",
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
        self._remember_profile()
        self._log(f"Saved profile: {self.profile_path}")

    def _remember_profile(self) -> None:
        if self.storage is None or self.profile_path is None:
            return
        try:
            settings = self.storage.load_settings()
            settings["last_profile"] = str(self.profile_path)
            settings["interval"] = self.interval_input.value()
            settings["simulation"] = self.simulation_input.isChecked()
            self.storage.save_settings(settings)
        except StorageError as exc:
            self._log_error(f"Profile was saved, but settings could not be updated: {exc}")

    def _persist_ui_settings(self) -> None:
        if self.storage is None:
            return
        try:
            settings = self.storage.load_settings()
            settings["interval"] = self.interval_input.value()
            settings["simulation"] = self.simulation_input.isChecked()
            if self.profile_path is not None:
                settings["last_profile"] = str(self.profile_path)
            self.storage.save_settings(settings)
        except StorageError as exc:
            self._log_error(f"Execution mode changed, but settings could not be saved: {exc}")

    def _restore_last_profile(self) -> None:
        if self.storage is None:
            return
        try:
            settings = self.storage.load_settings()
            stored_interval = settings.get("interval", self.interval_input.value())
            stored_simulation = settings.get("simulation", self.simulation_input.isChecked())
            restored_settings = Profile(
                interval=stored_interval,
                simulation=stored_simulation,
            )
            self.interval_input.setValue(restored_settings.interval)
            if not self._select_execution_mode(restored_settings.simulation):
                self._log(
                    "Saved settings requested Live Input, but it was not confirmed. "
                    "Simulation remains active."
                )
            profile_value = settings.get("last_profile")
            if not isinstance(profile_value, str) or not profile_value:
                return
            path = Path(profile_value).expanduser()
            if not path.is_file():
                self._log_error(f"Last profile was not found; no data was removed: {path}")
                return
            profile = load_profile(path)
            self._apply_profile(profile)
            self.profile_path = path.resolve()
            self._log(f"Restored last profile: {self.profile_path}")
        except (OSError, ConfigurationError, StorageError) as exc:
            self._log_error(f"Could not restore the last profile: {exc}")

    def _apply_profile(self, profile: Profile) -> None:
        self.rules = profile.rules.copy()
        self.interval_input.setValue(profile.interval)
        if not self._select_execution_mode(profile.simulation):
            self._log(
                "Profile is configured for Live Input, but it was not confirmed. "
                "Simulation remains active."
            )
        else:
            self._log(
                "Profile execution mode: "
                f"{'Simulation (actions logged, not executed)' if profile.simulation else 'Live Input (real mouse/keyboard input)'}."
            )
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
                (2, _rule_macros_summary(rule)),
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
        if self.storage is not None:
            try:
                self.storage.append_log(message)
            except StorageError as exc:
                if not self._persistent_log_error_reported:
                    self._persistent_log_error_reported = True
                    self.log_panel.appendPlainText(
                        f"[{timestamp}] ERROR: Persistent activity log unavailable: {exc}"
                    )

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
        return f"Press key {action.get('key', '?')}"
    if kind == "key_down":
        return f"Hold key {action.get('key', '?')}"
    if kind == "key_up":
        return f"Release key {action.get('key', '?')}"
    if kind == "hotkey":
        return f"Press {'+'.join(action.get('keys', []))}"
    if kind == "type_text":
        text = action.get("text", "")
        preview = text.replace("\n", " ")
        return f"Type {preview[:32]!r}" + ("…" if len(preview) > 32 else "")
    if kind == "move":
        return f"Move mouse to ({action.get('x')}, {action.get('y')})"
    if kind == "scroll":
        return f"{action.get('direction', 'vertical').title()} scroll {action.get('amount')}"
    if kind == "delay":
        return f"Wait {action.get('seconds', '?')}s"
    if kind == "repeat":
        return f"Repeat {len(action.get('actions', []))} actions ×{action.get('count', '?')}"
    if kind == "wait_image":
        image = Path(action.get("template_path", "")).name or "image"
        return (
            f"Wait for image to {action.get('condition', 'appear')}: {image} "
            f"({action.get('timeout', '?')}s timeout)"
        )
    if kind == "if_image":
        image = Path(action.get("template_path", "")).name or "image"
        return (
            f"Branch on {image}: {len(action.get('then_actions', []))} detected / "
            f"{len(action.get('else_actions', []))} timeout actions"
        )
    return f"Unsupported action: {kind}"


def _common_keys() -> list[str]:
    return [
        "enter", "space", "tab", "esc", "backspace", "delete", "insert",
        "home", "end", "pageup", "pagedown", "up", "down", "left", "right",
        "ctrl", "alt", "shift", "win", "capslock",
        *(f"f{number}" for number in range(1, 13)),
        *"abcdefghijklmnopqrstuvwxyz",
        *"0123456789",
    ]


def _actions_summary(actions: list[dict[str, Any]]) -> str:
    if not actions:
        return "No actions"
    summary = " → ".join(_action_summary(action) for action in actions[:2])
    if len(actions) > 2:
        summary += f" → +{len(actions) - 2} more"
    return summary


def _rule_macros_summary(rule: Rule) -> str:
    if not rule.macros:
        return _actions_summary(rule.actions)
    names = ", ".join(macro.name for macro in rule.macros)
    action_count = sum(len(macro.actions) for macro in rule.macros)
    return f"{len(rule.macros)} macro(s): {names} · {action_count} action(s)"


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
