from PySide6.QtCore import QEventLoop, QTimer

from visual_macro.models import Macro, Profile, Rule
from visual_macro.worker import MacroWorker


def test_test_run_always_previews_actions_without_real_input(
    qapp, monkeypatch, tmp_path
) -> None:
    import cv2
    import numpy as np
    import visual_macro.worker as worker_module

    rng = np.random.default_rng(3)
    template = rng.integers(0, 255, size=(8, 9), dtype=np.uint8)
    screen = rng.integers(0, 255, size=(40, 50), dtype=np.uint8)
    screen[12:20, 17:26] = template
    frame = cv2.cvtColor(screen, cv2.COLOR_GRAY2BGR)
    template_path = tmp_path / "template.png"
    cv2.imwrite(str(template_path), template)

    class FakeCapture:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            return None

        def grab(self):
            return frame

    monkeypatch.setattr(worker_module, "ScreenCapture", FakeCapture)
    rule = Rule(
        id="target",
        name="Target",
        template_path=str(template_path),
        threshold=0.99,
        actions=[{"type": "click", "x": 100, "y": 200}],
    )
    worker = MacroWorker(Profile(simulation=False, rules=[rule]), once=True)
    messages: list[str] = []
    errors: list[str] = []
    worker.log_message.connect(messages.append)
    worker.error_message.connect(errors.append)
    loop = QEventLoop()
    worker.finished.connect(loop.quit)
    worker.start()
    QTimer.singleShot(3000, loop.quit)
    loop.exec()
    worker.wait()

    assert errors == []
    assert any("Recognized Target at (17, 12), confidence" in message for message in messages)
    assert "SIMULATION: click left at (100, 200) x1" in messages
    assert not any(message.startswith("Executing:") for message in messages)


def test_worker_passes_physical_detection_rect_to_relative_action(
    qapp, monkeypatch, tmp_path
) -> None:
    import cv2
    import numpy as np
    import visual_macro.worker as worker_module

    rng = np.random.default_rng(44)
    template = rng.integers(0, 255, size=(7, 8), dtype=np.uint8)
    screen = rng.integers(0, 255, size=(50, 60), dtype=np.uint8)
    screen[12:19, 17:25] = template
    frame = cv2.cvtColor(screen, cv2.COLOR_GRAY2BGR)
    template_path = tmp_path / "template.png"
    cv2.imwrite(str(template_path), template)

    class FakeCapture:
        origin = (-1920, -100)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            return None

        def grab(self):
            return frame

    monkeypatch.setattr(worker_module, "ScreenCapture", FakeCapture)
    rule = Rule(
        id="target",
        name="Target",
        template_path=str(template_path),
        threshold=0.99,
        region=(10, 8, 30, 25),
        actions=[
            {
                "type": "click_offset",
                "offset_x": -5,
                "offset_y": 2,
                "button": "middle",
                "clicks": 2,
            }
        ],
    )
    worker = MacroWorker(Profile(simulation=True, rules=[rule]), once=True)
    messages: list[str] = []
    errors: list[str] = []
    worker.log_message.connect(messages.append)
    worker.error_message.connect(errors.append)
    loop = QEventLoop()
    worker.finished.connect(loop.quit)
    worker.start()
    QTimer.singleShot(3000, loop.quit)
    loop.exec()
    worker.wait()

    assert errors == []
    assert any("Recognized Target at (-1903, -88)" in message for message in messages)
    assert (
        "SIMULATION: click middle at image center with offset (-1904, -83) x2"
        in messages
    )


def test_worker_runs_independent_named_macros_in_order(qapp) -> None:
    rule = Rule(
        id="multi",
        name="Multi",
        template_path="button.png",
        actions=[{"type": "press", "key": "enter"}],
        macros=[
            Macro("Submit", [{"type": "press", "key": "enter"}]),
            Macro("Wait", [{"type": "delay", "seconds": 0}]),
        ],
    )
    worker = MacroWorker(Profile(rules=[rule]), once=True)
    logs: list[str] = []
    actions: list[list[dict]] = []

    class FakeExecutor:
        stop_event = type(
            "Event",
            (),
            {"is_set": staticmethod(lambda: False)},
        )()

        def execute(self, current_actions, detection_rect=None):
            actions.append(current_actions)

    worker.log_message.connect(logs.append)
    worker._execute_rule_macros(rule, FakeExecutor(), (1, 2, 10, 20))

    assert logs == ["Running macro: Submit", "Running macro: Wait"]
    assert actions == [
        [{"type": "press", "key": "enter"}],
        [{"type": "delay", "seconds": 0}],
    ]


def test_worker_supplies_recognition_for_visual_condition_actions(
    qapp, monkeypatch, tmp_path
) -> None:
    import cv2
    import numpy as np
    import visual_macro.worker as worker_module

    rng = np.random.default_rng(73)
    template = rng.integers(0, 255, size=(8, 9), dtype=np.uint8)
    screen = rng.integers(0, 255, size=(40, 50), dtype=np.uint8)
    screen[12:20, 17:26] = template
    frame = cv2.cvtColor(screen, cv2.COLOR_GRAY2BGR)
    template_path = tmp_path / "condition.png"
    cv2.imwrite(str(template_path), template)

    class FakeCapture:
        origin = (-1920, 0)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            return None

        def grab(self):
            return frame

    monkeypatch.setattr(worker_module, "ScreenCapture", FakeCapture)
    condition = {
        "type": "if_image",
        "template_path": str(template_path),
        "threshold": 0.99,
        "timeout": 0,
        "interval": 0.05,
        "then_actions": [{"type": "click", "x": 11, "y": 22}],
        "else_actions": [{"type": "click", "x": 90, "y": 90}],
    }
    rule = Rule(
        id="target",
        name="Target",
        template_path=str(template_path),
        threshold=0.99,
        actions=[condition],
    )
    worker = MacroWorker(Profile(simulation=True, rules=[rule]), once=True)
    messages: list[str] = []
    errors: list[str] = []
    worker.log_message.connect(messages.append)
    worker.error_message.connect(errors.append)
    loop = QEventLoop()
    worker.finished.connect(loop.quit)
    worker.start()
    QTimer.singleShot(3000, loop.quit)
    loop.exec()
    worker.wait()

    assert errors == []
    assert "Image condition matched; running then branch." in messages
    assert "SIMULATION: click left at (11, 22) x1" in messages


def test_worker_reports_missing_condition_template_before_capture(
    qapp, monkeypatch, tmp_path
) -> None:
    import cv2
    import numpy as np
    import visual_macro.worker as worker_module

    main_template_path = tmp_path / "main.png"
    cv2.imwrite(
        str(main_template_path),
        np.random.default_rng(11).integers(0, 255, size=(8, 9), dtype=np.uint8),
    )
    capture_entered: list[bool] = []

    class FakeCapture:
        def __enter__(self):
            capture_entered.append(True)
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            return None

    monkeypatch.setattr(worker_module, "ScreenCapture", FakeCapture)
    rule = Rule(
        id="target",
        name="Target",
        template_path=str(main_template_path),
        actions=[
            {
                "type": "wait_image",
                "condition": "appears",
                "template_path": str(tmp_path / "missing.png"),
                "threshold": 0.8,
                "timeout": 2,
            }
        ],
    )
    worker = MacroWorker(Profile(rules=[rule]))
    errors: list[str] = []
    worker.error_message.connect(errors.append)

    worker.run()

    assert errors and "not found" in errors[0]
    assert capture_entered == []
