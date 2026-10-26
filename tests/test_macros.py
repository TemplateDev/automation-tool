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


def test_simulation_plans_mouse_keyboard_and_repeat_actions_in_order() -> None:
    messages: list[str] = []
    MacroExecutor(True, messages.append).execute(
        [
            {"type": "move", "x": -20, "y": 45},
            {"type": "scroll", "direction": "horizontal", "amount": -2},
            {"type": "type_text", "text": "hello"},
            {"type": "hotkey", "keys": ["ctrl", "c"]},
            {"type": "key_down", "key": "shift"},
            {"type": "key_up", "key": "shift"},
            {
                "type": "repeat",
                "count": 2,
                "actions": [{"type": "press", "key": "enter"}],
            },
        ]
    )

    assert messages == [
        "SIMULATION: move mouse to (-20, 45)",
        "SIMULATION: scroll horizontal by -2",
        "SIMULATION: type text 'hello'",
        "SIMULATION: press key combination ctrl+c",
        "SIMULATION: hold key shift",
        "SIMULATION: release key shift",
        "SIMULATION: repeat sequence x2",
        "Sequence iteration 1/2",
        "SIMULATION: press key enter",
        "Sequence iteration 2/2",
        "SIMULATION: press key enter",
    ]


def test_live_keyboard_and_mouse_actions_use_mocked_pyautogui(monkeypatch) -> None:
    import sys
    from types import SimpleNamespace

    calls: list[tuple[str, tuple, dict]] = []

    def record(name):
        return lambda *args, **kwargs: calls.append((name, args, kwargs))

    fake_pyautogui = SimpleNamespace(
        moveTo=record("moveTo"),
        scroll=record("scroll"),
        hscroll=record("hscroll"),
        write=record("write"),
        hotkey=record("hotkey"),
        press=record("press"),
        keyDown=record("keyDown"),
        keyUp=record("keyUp"),
        click=record("click"),
    )
    monkeypatch.setitem(sys.modules, "pyautogui", fake_pyautogui)
    executor = MacroExecutor(False, lambda _message: None)
    executor.execute(
        [
            {"type": "move", "x": 10, "y": 20},
            {"type": "scroll", "direction": "vertical", "amount": 2},
            {"type": "scroll", "direction": "horizontal", "amount": -1},
            {"type": "type_text", "text": "Hi"},
            {"type": "hotkey", "keys": ["CTRL", "C"]},
            {"type": "press", "key": "ENTER"},
            {"type": "key_down", "key": "SHIFT"},
            {"type": "key_up", "key": "SHIFT"},
            {"type": "click", "x": 30, "y": 40, "clicks": 2},
        ]
    )

    assert [call[0] for call in calls] == [
        "moveTo", "scroll", "hscroll", "write", "hotkey", "press",
        "keyDown", "keyUp", "click",
    ]
    assert calls[4] == ("hotkey", ("ctrl", "c"), {})
    assert calls[6] == ("keyDown", ("shift",), {})


def test_live_type_text_maps_newlines_and_tabs_to_keys(monkeypatch) -> None:
    import sys
    from types import SimpleNamespace

    calls: list[tuple[str, str]] = []
    fake_pyautogui = SimpleNamespace(
        write=lambda text: calls.append(("write", text)),
        press=lambda key: calls.append(("press", key)),
    )
    monkeypatch.setitem(sys.modules, "pyautogui", fake_pyautogui)

    MacroExecutor(False, lambda _message: None).execute(
        [{"type": "type_text", "text": "one\ntwo\tend"}]
    )

    assert calls == [
        ("write", "one"),
        ("press", "enter"),
        ("write", "two"),
        ("press", "tab"),
        ("write", "end"),
    ]


def test_live_stop_releases_held_keys_and_prevents_later_actions(monkeypatch) -> None:
    import sys
    from types import SimpleNamespace

    calls: list[tuple[str, tuple]] = []
    stop = threading.Event()

    def key_down(key):
        calls.append(("down", (key,)))
        stop.set()

    fake_pyautogui = SimpleNamespace(
        keyDown=key_down,
        keyUp=lambda key: calls.append(("up", (key,))),
    )
    monkeypatch.setitem(sys.modules, "pyautogui", fake_pyautogui)
    MacroExecutor(False, lambda _message: None, stop).execute(
        [
            {"type": "key_down", "key": "ctrl"},
            {"type": "press", "key": "c"},
        ]
    )

    assert calls == [("down", ("ctrl",)), ("up", ("ctrl",))]


def test_invalid_later_action_is_rejected_before_any_input(monkeypatch) -> None:
    import sys
    from types import SimpleNamespace

    calls: list[str] = []
    monkeypatch.setitem(
        sys.modules,
        "pyautogui",
        SimpleNamespace(click=lambda **_kwargs: calls.append("click")),
    )
    executor = MacroExecutor(False, lambda _message: None)

    import pytest
    with pytest.raises(ValueError, match="Unsupported macro action type"):
        executor.execute(
            [
                {"type": "click", "x": 1, "y": 2},
                {"type": "run_shell"},
            ]
        )

    assert calls == []


def test_stop_during_repeat_wait_prevents_remaining_iterations() -> None:
    stop_event = threading.Event()
    waiting = threading.Event()
    messages: list[str] = []

    def log(message: str) -> None:
        messages.append(message)
        if "delay" in message:
            waiting.set()

    executor = MacroExecutor(True, log, stop_event)
    actions = [
        {
            "type": "repeat",
            "count": 4,
            "actions": [{"type": "delay", "seconds": 10}],
        }
    ]
    worker = threading.Thread(target=executor.execute, args=(actions,))
    worker.start()
    assert waiting.wait(timeout=1)
    stop_event.set()
    worker.join(timeout=1)

    assert not worker.is_alive()
    assert messages.count("Sequence iteration 1/4") == 1
    assert "Sequence iteration 2/4" not in messages


def test_wait_for_image_appearance_and_disappearance_uses_callback() -> None:
    messages: list[str] = []
    observations = iter([False, True, True, False])

    def image_check(_action):
        return next(observations)

    actions = [
        {
            "type": "wait_image",
            "condition": "appears",
            "template_path": "ready.png",
            "threshold": 0.8,
            "timeout": 1,
            "interval": 0.05,
        },
        {
            "type": "wait_image",
            "condition": "disappears",
            "template_path": "ready.png",
            "threshold": 0.8,
            "timeout": 1,
            "interval": 0.05,
        },
    ]
    MacroExecutor(True, messages.append, image_check=image_check).execute(actions)

    assert messages == [
        "SIMULATION: wait until image appears (ready.png)",
        "Image condition satisfied: appears.",
        "SIMULATION: wait until image disappears (ready.png)",
        "Image condition satisfied: disappears.",
    ]


def test_image_condition_runs_the_correct_branch_in_simulation() -> None:
    messages: list[str] = []
    action = {
        "type": "if_image",
        "template_path": "ready.png",
        "threshold": 0.9,
        "timeout": 0,
        "interval": 0.1,
        "then_actions": [{"type": "press", "key": "enter"}],
        "else_actions": [{"type": "press", "key": "esc"}],
    }

    MacroExecutor(True, messages.append, image_check=lambda _action: False).execute([action])

    assert messages == [
        "SIMULATION: check image ready.png (threshold 90%, timeout 0s)",
        "Image condition timed out; running else branch.",
        "SIMULATION: press key esc",
    ]


def test_visual_condition_timeout_and_cancellation_are_safe() -> None:
    stop_event = threading.Event()
    waiting = threading.Event()
    messages: list[str] = []

    def image_check(_action):
        waiting.set()
        return False

    executor = MacroExecutor(
        True,
        messages.append,
        stop_event,
        image_check=image_check,
    )
    actions = [
        {
            "type": "wait_image",
            "condition": "appears",
            "template_path": "never.png",
            "threshold": 0.8,
            "timeout": 10,
            "interval": 0.05,
        },
        {"type": "press", "key": "enter"},
    ]
    worker = threading.Thread(target=executor.execute, args=(actions,))
    worker.start()
    assert waiting.wait(timeout=1)
    stop_event.set()
    worker.join(timeout=1)

    assert not worker.is_alive()
    assert messages == ["SIMULATION: wait until image appears (never.png)"]


def test_condition_requires_callback_and_preflights_before_input(monkeypatch) -> None:
    import sys
    from types import SimpleNamespace

    clicks: list[str] = []
    monkeypatch.setitem(
        sys.modules,
        "pyautogui",
        SimpleNamespace(click=lambda **_kwargs: clicks.append("click")),
    )
    action = {
        "type": "if_image",
        "template_path": "ready.png",
        "threshold": 0.8,
        "timeout": 1,
        "then_actions": [{"type": "press", "key": "enter"}],
        "else_actions": [{"type": "unknown"}],
    }

    import pytest
    with pytest.raises(ValueError, match="Unsupported macro action type"):
        MacroExecutor(False, lambda _message: None, image_check=lambda _action: True).execute(
            [{"type": "click", "x": 1, "y": 2}, action]
        )
    assert clicks == []

    action["else_actions"] = []
    with pytest.raises(ValueError, match="recognition callback"):
        MacroExecutor(True, lambda _message: None).execute([action])
