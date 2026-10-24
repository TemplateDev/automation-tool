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
