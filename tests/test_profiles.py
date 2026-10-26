import json

import pytest

from visual_macro.models import ConfigurationError, Macro, Profile, Rule, load_profile, save_profile


def test_profile_round_trip_keeps_rules_and_relative_template_paths(tmp_path) -> None:
    image_path = tmp_path / "assets" / "target.png"
    image_path.parent.mkdir()
    image_path.touch()
    profile_path = tmp_path / "profiles" / "default.json"
    profile = Profile(
        interval=0.5,
        simulation=True,
        rules=[
            Rule(
                id="target",
                name="Target",
                template_path=str(image_path),
                region=(1, 2, 30, 40),
                actions=[{"type": "click", "x": 100, "y": 200}],
            )
        ],
    )

    save_profile(profile, profile_path)
    data = json.loads(profile_path.read_text(encoding="utf-8"))
    loaded = load_profile(profile_path)

    assert data["rules"][0]["template_path"] == "../assets/target.png"
    assert loaded.interval == 0.5
    assert loaded.simulation is True
    assert loaded.rules[0].template_path == str(image_path)
    assert loaded.rules[0].region == (1, 2, 30, 40)


def test_profile_rejects_invalid_action_and_duplicate_rule_ids() -> None:
    with pytest.raises(ConfigurationError, match="Unsupported macro action"):
        Rule(
            id="bad",
            name="Bad",
            template_path="bad.png",
            actions=[{"type": "launch"}],
        )

    rule = Rule(id="duplicate", name="One", template_path="one.png")
    with pytest.raises(ConfigurationError, match="unique"):
        Profile(rules=[rule, Rule(id="duplicate", name="Two", template_path="two.png")])


def test_load_profile_reports_invalid_json(tmp_path) -> None:
    path = tmp_path / "broken.json"
    path.write_text("{", encoding="utf-8")

    with pytest.raises(ConfigurationError, match="Invalid JSON"):
        load_profile(path)


def test_load_profile_rejects_unsupported_version(tmp_path) -> None:
    path = tmp_path / "future.json"
    path.write_text(json.dumps({"version": 2}), encoding="utf-8")

    with pytest.raises(ConfigurationError, match="Unsupported profile version"):
        load_profile(path)


def test_existing_versionless_profile_keeps_supported_action_shapes(tmp_path) -> None:
    image_path = tmp_path / "button.png"
    image_path.touch()
    profile_path = tmp_path / "legacy.json"
    legacy = {
        "interval": 1.0,
        "simulation": True,
        "rules": [
            {
                "id": "legacy-button",
                "name": "Legacy button",
                "template_path": "button.png",
                "threshold": 0.8,
                "region": None,
                "cooldown": 1.0,
                "repeat": False,
                "enabled": True,
                "actions": [
                    {"type": "click", "x": 100, "y": 200, "button": "left", "clicks": 1},
                    {"type": "press", "key": "enter"},
                    {"type": "delay", "seconds": 0.5},
                ],
            }
        ],
    }
    profile_path.write_text(json.dumps(legacy), encoding="utf-8")

    loaded = load_profile(profile_path)

    assert loaded.rules[0].template_path == str(image_path)
    assert loaded.rules[0].actions == legacy["rules"][0]["actions"]


def test_existing_absolute_template_paths_load_without_migration_or_copy(tmp_path) -> None:
    image_path = tmp_path / "user-owned.png"
    image_path.write_bytes(b"user data")
    profile_path = tmp_path / "absolute.json"
    profile_path.write_text(
        json.dumps(
            {
                "rules": [
                    {
                        "id": "absolute",
                        "name": "Absolute",
                        "template_path": str(image_path),
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    loaded = load_profile(profile_path)

    assert loaded.rules[0].template_path == str(image_path)
    assert image_path.read_bytes() == b"user data"


def test_relative_click_actions_round_trip_without_changing_existing_action_shapes(tmp_path) -> None:
    profile_path = tmp_path / "relative.json"
    actions = [
        {"type": "click_center", "button": "right", "clicks": 2},
        {
            "type": "click_offset",
            "offset_x": -7,
            "offset_y": 12,
            "button": "middle",
            "clicks": 3,
        },
        {"type": "click", "x": 100, "y": 200},
    ]
    profile = Profile(
        rules=[Rule(id="relative", name="Relative", template_path="image.png", actions=actions)]
    )

    save_profile(profile, profile_path)
    loaded = load_profile(profile_path)

    assert loaded.rules[0].actions == actions


def test_new_mouse_keyboard_and_repeat_actions_round_trip(tmp_path) -> None:
    profile_path = tmp_path / "action-library.json"
    actions = [
        {"type": "move", "x": -200, "y": 40},
        {"type": "scroll", "direction": "horizontal", "amount": -3},
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
    profile = Profile(
        rules=[Rule(id="new-actions", name="New actions", template_path="image.png", actions=actions)]
    )

    save_profile(profile, profile_path)

    assert load_profile(profile_path).rules[0].actions == actions


def test_visual_condition_actions_round_trip(tmp_path) -> None:
    profile_path = tmp_path / "conditions.json"
    spinner_path = str(tmp_path / "spinner.png")
    ready_path = str(tmp_path / "ready.png")
    actions = [
        {
            "type": "wait_image",
            "condition": "disappears",
            "template_path": spinner_path,
            "threshold": 0.9,
            "timeout": 5,
            "interval": 0.1,
        },
        {
            "type": "if_image",
            "template_path": ready_path,
            "threshold": 0.85,
            "timeout": 2,
            "interval": 0.2,
            "then_actions": [{"type": "press", "key": "enter"}],
            "else_actions": [{"type": "type_text", "text": "not ready"}],
        },
    ]
    profile = Profile(
        rules=[Rule(id="conditions", name="Conditions", template_path="main.png", actions=actions)]
    )

    save_profile(profile, profile_path)

    raw = json.loads(profile_path.read_text(encoding="utf-8"))
    loaded = load_profile(profile_path).rules[0].actions
    assert raw["rules"][0]["actions"][0]["template_path"] == "spinner.png"
    assert loaded == actions


@pytest.mark.parametrize(
    "action, message",
    [
        ({"type": "move", "x": True, "y": 2}, "integer"),
        ({"type": "scroll", "direction": "diagonal", "amount": 2}, "direction"),
        ({"type": "scroll", "direction": [], "amount": 2}, "direction"),
        ({"type": "scroll", "direction": "vertical", "amount": 0}, "non-zero"),
        ({"type": "press", "key": "arbitrary command"}, "supported key"),
        ({"type": "type_text", "text": "café"}, "ASCII"),
        ({"type": "hotkey", "keys": ["ctrl"]}, "2 and 5"),
        ({"type": "repeat", "count": 0, "actions": [{"type": "press", "key": "a"}]}, "Repeat count"),
        ({"type": "repeat", "count": 2, "actions": []}, "at least one"),
        (
            {
                "type": "wait_image",
                "condition": "visible",
                "template_path": "image.png",
                "threshold": 0.8,
                "timeout": 1,
            },
            "appears or disappears",
        ),
        (
            {
                "type": "if_image",
                "template_path": "image.png",
                "threshold": 1.1,
                "timeout": 1,
                "then_actions": [],
                "else_actions": [],
            },
            "threshold",
        ),
    ],
)
def test_action_validation_rejects_invalid_new_action_settings(action, message) -> None:
    from visual_macro.models import validate_action

    with pytest.raises(ConfigurationError, match=message):
        validate_action(action)


def test_named_macros_round_trip_and_keep_legacy_actions_for_older_readers(tmp_path) -> None:
    profile_path = tmp_path / "macros.json"
    first_actions = [{"type": "press", "key": "enter"}]
    second_actions = [{"type": "delay", "seconds": 0.25}]
    rule = Rule(
        id="macro-rule",
        name="Macro rule",
        template_path="button.png",
        actions=first_actions,
        macros=[
            Macro("Submit", first_actions),
            Macro("Wait", second_actions),
        ],
    )

    save_profile(Profile(rules=[rule]), profile_path)
    raw_rule = json.loads(profile_path.read_text(encoding="utf-8"))["rules"][0]
    loaded = load_profile(profile_path).rules[0]

    assert raw_rule["actions"] == first_actions
    assert raw_rule["macros"] == [
        {"name": "Submit", "actions": first_actions},
        {"name": "Wait", "actions": second_actions},
    ]
    assert [(macro.name, macro.actions) for macro in loaded.macros] == [
        ("Submit", first_actions),
        ("Wait", second_actions),
    ]


def test_rule_rejects_invalid_or_duplicate_macro_names() -> None:
    action = [{"type": "press", "key": "enter"}]
    with pytest.raises(ConfigurationError, match="unique"):
        Rule(
            id="duplicate-macros",
            name="Duplicate macros",
            template_path="button.png",
            macros=[Macro("Run", action), Macro("run", action)],
        )
