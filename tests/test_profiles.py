import json

import pytest

from visual_macro.models import ConfigurationError, Profile, Rule, load_profile, save_profile


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
