import threading

from visual_macro.macros import MacroExecutor


def test_simulation_logs_actions_without_sending_input() -> None:
    messages: list[str] = []
    executor = MacroExecutor(simulation=True, log=messages.append, stop_event=threading.Event())

    executor.execute(
        [
            {"type": "click", "x": 10, "y": 20},
            {"type": "press", "key": "enter"},
            {"type": "delay", "seconds": 0},
        ]
    )

    assert messages == [
        "SIMULATION: click left at (10, 20) x1",
        "SIMULATION: press key enter",
        "SIMULATION: delay 0 seconds",
    ]


def test_stop_during_macro_prevents_later_actions() -> None:
    stop_event = threading.Event()
    messages: list[str] = []

    def log(message: str) -> None:
        messages.append(message)
        stop_event.set()

    executor = MacroExecutor(simulation=True, log=log, stop_event=stop_event)

    executor.execute(
        [
            {"type": "press", "key": "enter"},
            {"type": "click", "x": 10, "y": 20},
        ]
    )

    assert messages == ["SIMULATION: press key enter"]


def test_stop_interrupts_in_progress_macro_wait() -> None:
    stop_event = threading.Event()
    waiting = threading.Event()
    messages: list[str] = []

    def log(message: str) -> None:
        messages.append(message)
        waiting.set()

    executor = MacroExecutor(True, log, stop_event)
    actions = [
        {"type": "delay", "seconds": 10},
        {"type": "press", "key": "enter"},
    ]
    worker = threading.Thread(target=executor.execute, args=(actions,))
    worker.start()
    assert waiting.wait(timeout=1)
    stop_event.set()
    worker.join(timeout=1)

    assert not worker.is_alive()
    assert messages == ["SIMULATION: delay 10 seconds"]


def test_live_input_is_mocked_and_receives_configured_click(monkeypatch) -> None:
    import sys
    from types import SimpleNamespace

    calls: list[tuple[tuple, dict]] = []
    fake_pyautogui = SimpleNamespace(
        click=lambda *args, **kwargs: calls.append((args, kwargs)),
        press=lambda *args, **kwargs: calls.append((args, kwargs)),
    )
    monkeypatch.setitem(sys.modules, "pyautogui", fake_pyautogui)
    executor = MacroExecutor(simulation=False, log=lambda _message: None)

    executor.execute([{"type": "click", "x": 10, "y": 20, "button": "right", "clicks": 2}])

    assert calls == [((), {"x": 10, "y": 20, "button": "right", "clicks": 2})]
