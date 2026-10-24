from PySide6.QtCore import QEventLoop, QTimer

from visual_macro.models import Profile, Rule
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
