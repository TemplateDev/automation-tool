from __future__ import annotations

import json
import sys
import uuid
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from visual_macro.models import ConfigurationError, Profile, Rule, load_profile, save_profile
from visual_macro.worker import MacroWorker


class RuleDialog(QDialog):
    def __init__(self, parent=None, rule: Rule | None = None, template_path: str = "") -> None:
        super().__init__(parent)
        self.setWindowTitle("Edit Rule" if rule else "Add Image Rule")
        self._rule_id = rule.id if rule else str(uuid.uuid4())

        self.name_input = QLineEdit(rule.name if rule else (Path(template_path).stem or "New rule"))
        self.template_input = QLineEdit(rule.template_path if rule else template_path)
        self.template_input.setReadOnly(True)
        self.browse_button = QPushButton("Choose image…")
        self.browse_button.clicked.connect(self._browse_template)

        self.threshold_input = QDoubleSpinBox()
        self.threshold_input.setRange(0, 1)
        self.threshold_input.setSingleStep(0.01)
        self.threshold_input.setDecimals(3)
        self.threshold_input.setValue(rule.threshold if rule else 0.8)

        self.region_input = QLineEdit(
            ",".join(str(value) for value in rule.region) if rule and rule.region else ""
        )
        self.region_input.setPlaceholderText("Optional: x,y,width,height")

        self.cooldown_input = QDoubleSpinBox()
        self.cooldown_input.setRange(0, 3600)
        self.cooldown_input.setDecimals(2)
        self.cooldown_input.setValue(rule.cooldown if rule else 1.0)

        self.repeat_input = QCheckBox("Repeat while image remains visible")
        self.repeat_input.setChecked(rule.repeat if rule else False)
        self.enabled_input = QCheckBox("Enabled")
        self.enabled_input.setChecked(rule.enabled if rule else True)

        actions = rule.actions if rule else []
        self.actions_input = QPlainTextEdit(json.dumps(actions, indent=2))
        self.actions_input.setPlaceholderText(
            '[{"type":"click","x":100,"y":200}, {"type":"press","key":"enter"}, {"type":"delay","seconds":0.5}]'
        )
        self.actions_input.setMinimumHeight(110)

        form = QFormLayout()
        form.addRow("Rule name", self.name_input)
        template_row = QHBoxLayout()
        template_row.addWidget(self.template_input)
        template_row.addWidget(self.browse_button)
        form.addRow("Image template", template_row)
        form.addRow("Confidence threshold", self.threshold_input)
        form.addRow("Screen region", self.region_input)
        form.addRow("Cooldown (seconds)", self.cooldown_input)
        form.addRow("", self.repeat_input)
        form.addRow("", self.enabled_input)
        form.addRow("Macro actions (JSON)", self.actions_input)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._validate_and_accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def _browse_template(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Choose image template",
            "",
            "Image files (*.png *.jpg *.jpeg *.bmp *.webp);;All files (*.*)",
        )
        if path:
            self.template_input.setText(path)
            if not self.name_input.text().strip():
                self.name_input.setText(Path(path).stem)

    def _validate_and_accept(self) -> None:
        try:
            self._build_rule()
        except (ConfigurationError, json.JSONDecodeError, ValueError) as exc:
            QMessageBox.warning(self, "Invalid rule", str(exc))
            return
        self.accept()

    def _build_rule(self) -> Rule:
        region_text = self.region_input.text().strip()
        region = None
        if region_text:
            parts = [part.strip() for part in region_text.split(",")]
            if len(parts) != 4:
                raise ConfigurationError("Region must be entered as x,y,width,height.")
            try:
                region = tuple(int(part) for part in parts)
            except ValueError as exc:
                raise ConfigurationError("Region coordinates must be whole numbers.") from exc
        actions = json.loads(self.actions_input.toPlainText() or "[]")
        if not isinstance(actions, list):
            raise ConfigurationError("Macro actions must be a JSON array.")
        return Rule(
            id=self._rule_id,
            name=self.name_input.text().strip(),
            template_path=self.template_input.text().strip(),
            threshold=self.threshold_input.value(),
            region=region,
            cooldown=self.cooldown_input.value(),
            repeat=self.repeat_input.isChecked(),
            enabled=self.enabled_input.isChecked(),
            actions=actions,
        )

    def rule(self) -> Rule:
        return self._build_rule()


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Visual Macro Automation")
        self.resize(980, 680)
        self.rules: list[Rule] = []
        self.profile_path: Path | None = None
        self.worker: MacroWorker | None = None

        self.interval_input = QDoubleSpinBox()
        self.interval_input.setRange(0.1, 3600)
        self.interval_input.setDecimals(2)
        self.interval_input.setValue(1.0)
        self.simulation_input = QCheckBox("Simulation mode (do not send input)")
        self.simulation_input.setChecked(True)

        self.rule_table = QTableWidget(0, 7)
        self.rule_table.setHorizontalHeaderLabels(
            ["Name", "Template", "Threshold", "Region", "Cooldown", "Repeat", "Enabled"]
        )
        self.rule_table.horizontalHeader().setStretchLastSection(True)
        self.rule_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.rule_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.rule_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.rule_table.cellDoubleClicked.connect(lambda _row, _column: self._edit_rule())

        self.add_button = QPushButton("Add Template…")
        self.edit_button = QPushButton("Edit Rule")
        self.delete_button = QPushButton("Delete Rule")
        self.test_button = QPushButton("Test Rule")
        self.start_button = QPushButton("Start")
        self.stop_button = QPushButton("Stop")
        self.stop_button.setEnabled(False)
        self.load_button = QPushButton("Load Profile…")
        self.save_button = QPushButton("Save Profile")
        self.add_button.clicked.connect(self._add_rule)
        self.edit_button.clicked.connect(self._edit_rule)
        self.delete_button.clicked.connect(self._delete_rule)
        self.test_button.clicked.connect(self._test_rule)
        self.start_button.clicked.connect(self._start_monitoring)
        self.stop_button.clicked.connect(self._stop_monitoring)
        self.load_button.clicked.connect(self._load_profile)
        self.save_button.clicked.connect(self._save_profile)

        self.log_panel = QPlainTextEdit()
        self.log_panel.setReadOnly(True)
        self.log_panel.setPlaceholderText("Recognition results, macro actions, and errors appear here.")
        self.status_label = QLabel("Ready")

        settings = QHBoxLayout()
        settings.addWidget(QLabel("Capture interval (seconds)"))
        settings.addWidget(self.interval_input)
        settings.addWidget(self.simulation_input)
        settings.addStretch(1)

        controls = QHBoxLayout()
        for button in (
            self.add_button,
            self.edit_button,
            self.delete_button,
            self.test_button,
            self.start_button,
            self.stop_button,
            self.load_button,
            self.save_button,
        ):
            controls.addWidget(button)

        layout = QVBoxLayout()
        layout.addLayout(settings)
        layout.addWidget(self.rule_table)
        layout.addLayout(controls)
        layout.addWidget(QLabel("Activity log"))
        layout.addWidget(self.log_panel, 1)
        layout.addWidget(self.status_label)
        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)

    def _add_rule(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Add image template",
            "",
            "Image files (*.png *.jpg *.jpeg *.bmp *.webp);;All files (*.*)",
        )
        if not path:
            return
        dialog = RuleDialog(self, template_path=path)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.rules.append(dialog.rule())
            self._refresh_rules()
            self._log(f"Added rule: {self.rules[-1].name}")

    def _edit_rule(self) -> None:
        row = self.rule_table.currentRow()
        if not 0 <= row < len(self.rules):
            self._log_error("Select a rule to edit.")
            return
        dialog = RuleDialog(self, self.rules[row])
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.rules[row] = dialog.rule()
            self._refresh_rules()
            self.rule_table.selectRow(row)
            self._log(f"Updated rule: {self.rules[row].name}")

    def _delete_rule(self) -> None:
        row = self.rule_table.currentRow()
        if not 0 <= row < len(self.rules):
            self._log_error("Select a rule to delete.")
            return
        removed = self.rules.pop(row)
        self._refresh_rules()
        self._log(f"Deleted rule: {removed.name}")

    def _test_rule(self) -> None:
        row = self.rule_table.currentRow()
        if not 0 <= row < len(self.rules):
            self._log_error("Select a rule to test.")
            return
        rule = self.rules[row]
        if not rule.enabled:
            self._log_error(f"Cannot test disabled rule: {rule.name}.")
            return
        self._launch_worker([rule], once=True)
        self._log(f"Testing rule: {rule.name}")

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
        profile = Profile(
            interval=self.interval_input.value(),
            simulation=self.simulation_input.isChecked(),
            rules=rules,
        )
        self.worker = MacroWorker(profile, rules, once)
        self.worker.log_message.connect(self._log)
        self.worker.error_message.connect(self._log_error)
        self.worker.finished.connect(self._worker_finished)
        self._set_running_controls(True)
        self.status_label.setText("Testing…" if once else "Monitoring…")
        self.worker.start()

    def _stop_monitoring(self) -> None:
        if self.worker is not None:
            self._log("Stopping…")
            self.worker.stop()

    def _worker_finished(self) -> None:
        self.worker = None
        self._set_running_controls(False)
        self.status_label.setText("Ready")

    def _set_running_controls(self, running: bool) -> None:
        for button in (
            self.add_button,
            self.edit_button,
            self.delete_button,
            self.test_button,
            self.start_button,
            self.load_button,
            self.save_button,
        ):
            button.setEnabled(not running)
        self.stop_button.setEnabled(running)
        self.rule_table.setEnabled(not running)
        self.interval_input.setEnabled(not running)
        self.simulation_input.setEnabled(not running)

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
        if self.profile_path is None:
            path, _ = QFileDialog.getSaveFileName(
                self, "Save profile", "", "JSON profiles (*.json)"
            )
            if not path:
                return
            self.profile_path = Path(path).resolve()
            if self.profile_path.suffix.lower() != ".json":
                self.profile_path = self.profile_path.with_suffix(".json")
        try:
            profile = Profile(
                interval=self.interval_input.value(),
                simulation=self.simulation_input.isChecked(),
                rules=self.rules.copy(),
            )
            save_profile(profile, self.profile_path)
        except (OSError, ConfigurationError) as exc:
            self._log_error(f"Could not save profile: {exc}")
            return
        self._log(f"Saved profile: {self.profile_path}")

    def _apply_profile(self, profile: Profile) -> None:
        self.rules = profile.rules.copy()
        self.interval_input.setValue(profile.interval)
        self.simulation_input.setChecked(profile.simulation)
        self._refresh_rules()

    def _refresh_rules(self) -> None:
        self.rule_table.setRowCount(len(self.rules))
        for row, rule in enumerate(self.rules):
            values = [
                rule.name,
                rule.template_path,
                f"{rule.threshold:.3f}",
                ",".join(str(value) for value in rule.region) if rule.region else "Full screen",
                f"{rule.cooldown:g}s",
                "Yes" if rule.repeat else "No",
                "Yes" if rule.enabled else "No",
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.rule_table.setItem(row, column, item)
        self.rule_table.resizeColumnsToContents()

    def _log(self, message: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_panel.appendPlainText(f"[{timestamp}] {message}")

    def _log_error(self, message: str) -> None:
        self._log(f"ERROR: {message}")

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.worker is not None:
            self.worker.stop()
            self.worker.wait()
        event.accept()


def main() -> int:
    from PySide6.QtWidgets import QApplication

    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec()
