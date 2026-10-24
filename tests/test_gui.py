from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtGui import QCloseEvent

from visual_macro.gui import ActionBuilder, ActionDialog, MainWindow, RuleDialog
from visual_macro.models import Profile, Rule


def test_action_dialog_edits_existing_profile_action_shape(qapp) -> None:
    dialog = ActionDialog(
        action={"type": "click", "x": 11, "y": 22, "button": "right", "clicks": 2}
    )
    dialog.x_input.setValue(34)

    assert dialog.action() == {
        "type": "click",
        "x": 34,
        "y": 22,
        "button": "right",
        "clicks": 2,
    }


def test_fixed_action_editor_preserves_negative_monitor_coordinates(qapp) -> None:
    dialog = ActionDialog(
        action={"type": "click", "x": -320, "y": -40, "button": "left", "clicks": 1}
    )

    assert dialog.action()["x"] == -320
    assert dialog.action()["y"] == -40


def test_action_dialog_creates_center_and_offset_actions(qapp) -> None:
    center = ActionDialog()
    center.type_input.setCurrentIndex(center.type_input.findData("click_center"))
    center.center_button_input.setCurrentText("middle")
    center.center_clicks_input.setValue(2)
    assert center.action() == {
        "type": "click_center",
        "button": "middle",
        "clicks": 2,
    }

    offset = ActionDialog()
    offset.type_input.setCurrentIndex(offset.type_input.findData("click_offset"))
    offset.offset_x_input.setValue(-12)
    offset.offset_y_input.setValue(5)
    assert offset.action() == {
        "type": "click_offset",
        "offset_x": -12,
        "offset_y": 5,
        "button": "left",
        "clicks": 1,
    }


def test_action_builder_duplicates_reorders_and_removes_actions(qapp) -> None:
    builder = ActionBuilder(
        [
            {"type": "press", "key": "enter"},
            {"type": "delay", "seconds": 0.5},
        ]
    )
    builder.action_list.selectRow(0)
    builder._duplicate_action()
    builder._move_action(1)
    builder._remove_action()

    assert builder.actions == [
        {"type": "press", "key": "enter"},
        {"type": "delay", "seconds": 0.5},
    ]


def test_rule_editor_uses_percent_and_existing_action_dictionaries(qapp, tmp_path) -> None:
    image_path = tmp_path / "sample.png"
    image_path.touch()
    rule = Rule(
        id="sample",
        name="Sample",
        template_path=str(image_path),
        threshold=0.87,
        region=(1, 2, 30, 40),
        actions=[{"type": "press", "key": "enter"}],
    )
    dialog = RuleDialog(rule=rule)
    assert dialog.threshold_input.value() == 87
    assert dialog.advanced_region.isHidden()
    dialog.advanced_toggle.setChecked(True)
    dialog.threshold_input.setValue(91)

    edited = dialog.rule()

    assert edited.threshold == 0.91
    assert edited.region == (1, 2, 30, 40)
    assert edited.actions == [{"type": "press", "key": "enter"}]


def test_main_window_status_summary_and_simulation_default(qapp) -> None:
    window = MainWindow()
    rule = Rule(
        id="one",
        name="One",
        template_path="one.png",
        actions=[{"type": "click", "x": 1, "y": 2}],
    )
    window._apply_profile(Profile(simulation=True, rules=[rule]))

    assert window.status_indicator.text().endswith("Stopped")
    assert window.simulation_input.isChecked()
    assert window.total_label.text() == "Rules: 1"
    assert window.enabled_label.text() == "Enabled: 1"
    assert window.rule_table.item(0, 1).text() == "80%"
    assert window.rule_stack.currentWidget() is window.rule_table
    window._on_worker_error("test failure")
    assert window.status_indicator.text().endswith("Error")
    window.close()


def test_window_shutdown_requests_stop_and_waits(qapp) -> None:
    class FakeWorker:
        stopped = False
        waited = False

        def stop(self):
            self.stopped = True

        def wait(self):
            self.waited = True

    window = MainWindow()
    worker = FakeWorker()
    window.worker = worker
    event = QCloseEvent()

    window.closeEvent(event)

    assert worker.stopped and worker.waited
    assert event.isAccepted()
    window.worker = None
    window.close()


def test_start_stop_returns_status_to_stopped(qapp, monkeypatch, tmp_path) -> None:
    import cv2
    import numpy as np
    import visual_macro.worker as worker_module

    template_path = tmp_path / "template.png"
    cv2.imwrite(str(template_path), np.arange(64, dtype=np.uint8).reshape(8, 8))

    class FakeCapture:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            return None

        def grab(self):
            return np.zeros((40, 50, 3), dtype=np.uint8)

    monkeypatch.setattr(worker_module, "ScreenCapture", FakeCapture)
    window = MainWindow()
    window.rules = [Rule(id="target", name="Target", template_path=str(template_path))]
    window._refresh_rules()
    window._start_monitoring()
    worker = window.worker
    assert worker is not None
    assert window.status_indicator.text().endswith("Running")

    loop = QEventLoop()
    worker.finished.connect(loop.quit)
    QTimer.singleShot(50, window._stop_monitoring)
    QTimer.singleShot(3000, loop.quit)
    loop.exec()
    worker.wait()
    qapp.processEvents()

    assert window.status_indicator.text().endswith("Stopped")
    assert window.worker is None
    window.close()
