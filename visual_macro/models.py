from __future__ import annotations

import json
import math
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


class ConfigurationError(ValueError):
    """Raised when a profile or rule contains invalid configuration."""


@dataclass
class Macro:
    name: str
    actions: list[dict[str, Any]]


@dataclass
class Rule:
    id: str
    name: str
    template_path: str
    threshold: float = 0.8
    region: tuple[int, int, int, int] | None = None
    cooldown: float = 1.0
    repeat: bool = False
    enabled: bool = True
    actions: list[dict[str, Any]] | None = None
    macros: list[Macro] | None = None

    def __post_init__(self) -> None:
        if self.actions is None:
            self.actions = []
        validate_rule(self)


@dataclass
class Profile:
    interval: float = 1.0
    simulation: bool = True
    rules: list[Rule] | None = None

    def __post_init__(self) -> None:
        if self.rules is None:
            self.rules = []
        validate_profile(self)


def validate_action(action: Any, _depth: int = 0) -> None:
    if not isinstance(action, dict):
        raise ConfigurationError("Each macro action must be a JSON object.")

    kind = action.get("type")
    if kind == "click":
        _integer(action.get("x"), "click x coordinate")
        _integer(action.get("y"), "click y coordinate")
        button = action.get("button", "left")
        if not isinstance(button, str) or button not in {"left", "right", "middle"}:
            raise ConfigurationError("Click button must be left, right, or middle.")
        clicks = action.get("clicks", 1)
        if not _is_integer(clicks) or not 1 <= clicks <= 10:
            raise ConfigurationError("Click count must be an integer from 1 to 10.")
    elif kind == "click_center":
        _validate_click_options(action)
    elif kind == "click_offset":
        _integer(action.get("offset_x"), "horizontal click offset")
        _integer(action.get("offset_y"), "vertical click offset")
        _validate_click_options(action)
    elif kind == "press":
        _validate_key(action.get("key"), "Press")
    elif kind in {"key_down", "key_up"}:
        _validate_key(action.get("key"), "Key hold/release")
    elif kind == "type_text":
        text = action.get("text")
        if not isinstance(text, str) or not text:
            raise ConfigurationError("A type-text action requires non-empty text.")
        if len(text) > 10000:
            raise ConfigurationError("Typed text cannot exceed 10,000 characters.")
        if not text.isascii():
            raise ConfigurationError(
                "Typed text must use ASCII characters; Unicode text is not supported by PyAutoGUI."
            )
    elif kind == "hotkey":
        keys = action.get("keys")
        if (
            not isinstance(keys, list)
            or len(keys) < 2
            or len(keys) > 5
            or any(not isinstance(key, str) for key in keys)
        ):
            raise ConfigurationError("A key combination requires between 2 and 5 keys.")
        for key in keys:
            _validate_key(key, "Key combination")
        if len({key.casefold() for key in keys}) != len(keys):
            raise ConfigurationError("A key combination cannot contain duplicate keys.")
    elif kind == "move":
        _integer(action.get("x"), "mouse X coordinate")
        _integer(action.get("y"), "mouse Y coordinate")
    elif kind == "scroll":
        direction = action.get("direction")
        if not isinstance(direction, str) or direction not in {"vertical", "horizontal"}:
            raise ConfigurationError("Scroll direction must be vertical or horizontal.")
        amount = action.get("amount")
        if not _is_integer(amount) or not -10000 <= amount <= 10000 or amount == 0:
            raise ConfigurationError("Scroll amount must be a non-zero integer from -10000 to 10000.")
    elif kind == "repeat":
        count = action.get("count")
        actions = action.get("actions")
        if not _is_integer(count) or not 1 <= count <= 100:
            raise ConfigurationError("Repeat count must be an integer from 1 to 100.")
        if not isinstance(actions, list) or not actions:
            raise ConfigurationError("A repeat action requires at least one nested action.")
        _validate_action_sequence(actions, depth=_depth + 1)
    elif kind == "wait_image":
        _validate_image_condition(action)
        condition = action.get("condition")
        if not isinstance(condition, str) or condition not in {"appears", "disappears"}:
            raise ConfigurationError("Image wait condition must be appears or disappears.")
    elif kind == "if_image":
        _validate_image_condition(action)
        then_actions = action.get("then_actions")
        else_actions = action.get("else_actions")
        if not isinstance(then_actions, list) or not isinstance(else_actions, list):
            raise ConfigurationError("Image branches must each be an action list.")
        _validate_action_sequence(then_actions, depth=_depth + 1)
        _validate_action_sequence(else_actions, depth=_depth + 1)
    elif kind == "delay":
        seconds = action.get("seconds")
        if not _is_number(seconds) or not 0 <= seconds <= 300:
            raise ConfigurationError("Delay seconds must be between 0 and 300.")
    else:
        raise ConfigurationError(f"Unsupported macro action type: {kind!r}.")


_KEY_NAMES = {
    "accept", "add", "alt", "altleft", "altright", "apps", "backspace",
    "browserback", "browserfavorites", "browserforward", "browserhome",
    "browserrefresh", "browsersearch", "browserstop", "capslock", "clear",
    "convert", "ctrl", "ctrlleft", "ctrlright", "decimal", "del", "delete",
    "divide", "down", "end", "enter", "esc", "escape", "execute", "final",
    "fn", "hanguel", "hangul", "hanja", "help", "home", "insert", "junja",
    "kana", "kanji", "launchapp1", "launchapp2", "launchmail", "left",
    "menu", "modechange", "multiply", "nexttrack", "nonconvert", "numlock",
    "pagedown", "pageup", "pause", "pgdn", "pgup", "playpause", "prevtrack",
    "print", "printscreen", "prntscrn", "return", "right", "scrolllock",
    "select", "separator", "shift", "shiftleft", "shiftright", "sleep", "space",
    "stop", "subtract", "tab", "up", "volumedown", "volumemute", "volumeup",
    "win", "winleft", "winright",
}
_KEY_NAMES.update(f"f{number}" for number in range(1, 25))
_KEY_NAMES.update(f"num{number}" for number in range(10))
_KEY_NAMES.update("abcdefghijklmnopqrstuvwxyz0123456789")


def _validate_key(value: Any, label: str) -> None:
    if not isinstance(value, str) or value.casefold() not in _KEY_NAMES:
        raise ConfigurationError(
            f"{label} action requires a supported key (for example enter, space, ctrl, or a)."
        )


def _validate_image_condition(action: dict[str, Any]) -> None:
    template_path = action.get("template_path")
    if not isinstance(template_path, str) or not template_path.strip():
        raise ConfigurationError("An image condition requires a template path.")
    threshold = action.get("threshold")
    if not _is_number(threshold) or not 0 <= threshold <= 1:
        raise ConfigurationError("Image condition threshold must be between 0 and 1.")
    timeout = action.get("timeout")
    if not _is_number(timeout) or not 0 <= timeout <= 300:
        raise ConfigurationError("Image condition timeout must be between 0 and 300 seconds.")
    interval = action.get("interval", 0.25)
    if not _is_number(interval) or not 0.05 <= interval <= 10:
        raise ConfigurationError("Image condition polling interval must be between 0.05 and 10 seconds.")


def _validate_action_sequence(actions: list[Any], depth: int) -> None:
    if depth > 5:
        raise ConfigurationError("Nested action sequences may be no more than 5 levels deep.")
    for action in actions:
        if not isinstance(action, dict):
            raise ConfigurationError("Each macro action must be a JSON object.")
        validate_action(action, _depth=depth)


def _validate_click_options(action: dict[str, Any]) -> None:
    button = action.get("button", "left")
    if not isinstance(button, str) or button not in {"left", "right", "middle"}:
        raise ConfigurationError("Click button must be left, right, or middle.")
    clicks = action.get("clicks", 1)
    if not _is_integer(clicks) or not 1 <= clicks <= 10:
        raise ConfigurationError("Click count must be an integer from 1 to 10.")


def validate_rule(rule: Rule) -> None:
    for field_name in ("id", "name", "template_path"):
        value = getattr(rule, field_name)
        if not isinstance(value, str) or not value.strip():
            raise ConfigurationError(f"Rule {field_name} must be a non-empty string.")

    if not _is_number(rule.threshold) or not 0 <= rule.threshold <= 1:
        raise ConfigurationError("Rule threshold must be between 0 and 1.")
    if not _is_number(rule.cooldown) or rule.cooldown < 0:
        raise ConfigurationError("Rule cooldown must be a non-negative number.")
    if not isinstance(rule.repeat, bool) or not isinstance(rule.enabled, bool):
        raise ConfigurationError("Rule repeat and enabled values must be booleans.")
    if rule.region is not None:
        if (
            not isinstance(rule.region, (tuple, list))
            or len(rule.region) != 4
            or any(not _is_integer(value) for value in rule.region)
        ):
            raise ConfigurationError("Rule region must contain four integers: x, y, width, height.")
        x, y, width, height = rule.region
        if x < 0 or y < 0 or width <= 0 or height <= 0:
            raise ConfigurationError("Rule region coordinates must be non-negative and size positive.")
        rule.region = tuple(rule.region)
    if not isinstance(rule.actions, list):
        raise ConfigurationError("Rule actions must be a list.")
    for action in rule.actions:
        validate_action(action)
    if rule.macros is not None:
        if not isinstance(rule.macros, list) or not rule.macros:
            raise ConfigurationError("Rule macros must contain at least one macro.")
        if any(not isinstance(macro, Macro) for macro in rule.macros):
            raise ConfigurationError("Each rule macro must be a Macro.")
        for macro in rule.macros:
            if not isinstance(macro.name, str) or not macro.name.strip():
                raise ConfigurationError("Macro name must be a non-empty string.")
            if not isinstance(macro.actions, list):
                raise ConfigurationError(f"Actions for macro '{macro.name}' must be a list.")
            for action in macro.actions:
                validate_action(action)
        names = [macro.name.casefold() for macro in rule.macros]
        if len(names) != len(set(names)):
            raise ConfigurationError("Macro names must be unique within a rule.")


def validate_profile(profile: Profile) -> None:
    if not _is_number(profile.interval) or not 0.1 <= profile.interval <= 3600:
        raise ConfigurationError("Capture interval must be between 0.1 and 3600 seconds.")
    if not isinstance(profile.simulation, bool):
        raise ConfigurationError("Simulation mode must be a boolean.")
    if not isinstance(profile.rules, list) or any(not isinstance(rule, Rule) for rule in profile.rules):
        raise ConfigurationError("Profile rules must be a list of rules.")
    identifiers = [rule.id for rule in profile.rules]
    if len(identifiers) != len(set(identifiers)):
        raise ConfigurationError("Rule IDs must be unique.")
    for rule in profile.rules:
        validate_rule(rule)


def rule_from_dict(data: Any, base_dir: Path) -> Rule:
    if not isinstance(data, dict):
        raise ConfigurationError("Each rule must be a JSON object.")
    region = data.get("region")
    if region is not None and not isinstance(region, (list, tuple)):
        raise ConfigurationError("Rule region must be an array or null.")
    template_path = data.get("template_path")
    if not isinstance(template_path, str):
        raise ConfigurationError("Rule template_path must be a string.")
    macros_data = data.get("macros")
    if macros_data is not None and (
        not isinstance(macros_data, list) or not macros_data
    ):
        raise ConfigurationError("Rule macros must be a non-empty array.")
    macros = None
    if macros_data is not None:
        macros = []
        for macro_data in macros_data:
            if not isinstance(macro_data, dict):
                raise ConfigurationError("Each macro must be a JSON object.")
            macros.append(
                Macro(
                    name=macro_data.get("name"),
                    actions=_resolve_action_paths(
                        macro_data.get("actions"),
                        base_dir,
                    ),
                )
            )
    path = Path(template_path).expanduser()
    if not path.is_absolute():
        path = base_dir / path
    return Rule(
        id=data.get("id"),
        name=data.get("name"),
        template_path=str(path.resolve()),
        threshold=data.get("threshold", 0.8),
        region=tuple(region) if region is not None else None,
        cooldown=data.get("cooldown", 1.0),
        repeat=data.get("repeat", False),
        enabled=data.get("enabled", True),
        actions=_resolve_action_paths(
            data.get(
                "actions",
                macros[0].actions if macros is not None else [],
            ),
            base_dir,
        ),
        macros=macros,
    )


def profile_from_dict(data: Any, base_dir: Path) -> Profile:
    if not isinstance(data, dict):
        raise ConfigurationError("Profile root must be a JSON object.")
    version = data.get("version", 1)
    if type(version) is not int or version != 1:
        raise ConfigurationError(f"Unsupported profile version: {version!r}.")
    rules = data.get("rules", [])
    if not isinstance(rules, list):
        raise ConfigurationError("Profile rules must be an array.")
    return Profile(
        interval=data.get("interval", 1.0),
        simulation=data.get("simulation", True),
        rules=[rule_from_dict(rule, base_dir) for rule in rules],
    )


def load_profile(path: str | Path) -> Profile:
    profile_path = Path(path).expanduser().resolve()
    try:
        with profile_path.open("r", encoding="utf-8") as file:
            data = json.load(file)
    except json.JSONDecodeError as exc:
        raise ConfigurationError(f"Invalid JSON in profile: {exc}") from exc
    return profile_from_dict(data, profile_path.parent)


def save_profile(profile: Profile, path: str | Path) -> None:
    validate_profile(profile)
    profile_path = Path(path).expanduser().resolve()
    profile_path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "version": 1,
        "interval": profile.interval,
        "simulation": profile.simulation,
        "rules": [_rule_to_dict(rule, profile_path.parent) for rule in profile.rules],
    }
    temporary_path = profile_path.with_name(profile_path.name + ".tmp")
    try:
        with temporary_path.open("w", encoding="utf-8") as file:
            json.dump(data, file, indent=2)
            file.write("\n")
        os.replace(temporary_path, profile_path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def _rule_to_dict(rule: Rule, base_dir: Path) -> dict[str, Any]:
    data = asdict(rule)
    if rule.macros is None:
        data.pop("macros", None)
    else:
        data["actions"] = asdict(rule.macros[0])["actions"]
        data["macros"] = [asdict(macro) for macro in rule.macros]
    data["actions"] = _serialize_action_paths(data["actions"], base_dir)
    if "macros" in data:
        for macro in data["macros"]:
            macro["actions"] = _serialize_action_paths(macro["actions"], base_dir)
    template = Path(rule.template_path).expanduser()
    if template.is_absolute():
        try:
            data["template_path"] = Path(os.path.relpath(template, base_dir)).as_posix()
        except ValueError:
            data["template_path"] = str(template)
    if rule.region is not None:
        data["region"] = list(rule.region)
    return data


def _resolve_action_paths(actions: Any, base_dir: Path) -> Any:
    if not isinstance(actions, list):
        return actions
    resolved: list[Any] = []
    for action in actions:
        if not isinstance(action, dict):
            resolved.append(action)
            continue
        item = dict(action)
        if item.get("type") in {"wait_image", "if_image"}:
            image_path = Path(item["template_path"]).expanduser()
            if not image_path.is_absolute():
                image_path = base_dir / image_path
            item["template_path"] = str(image_path.resolve())
        for key in ("actions", "then_actions", "else_actions"):
            if key in item:
                item[key] = _resolve_action_paths(item[key], base_dir)
        resolved.append(item)
    return resolved


def _serialize_action_paths(actions: Any, base_dir: Path) -> Any:
    if not isinstance(actions, list):
        return actions
    serialized: list[Any] = []
    for action in actions:
        if not isinstance(action, dict):
            serialized.append(action)
            continue
        item = dict(action)
        if item.get("type") in {"wait_image", "if_image"}:
            image_path = Path(item["template_path"]).expanduser()
            if image_path.is_absolute():
                try:
                    item["template_path"] = Path(
                        os.path.relpath(image_path, base_dir)
                    ).as_posix()
                except ValueError:
                    item["template_path"] = str(image_path)
        for key in ("actions", "then_actions", "else_actions"):
            if key in item:
                item[key] = _serialize_action_paths(item[key], base_dir)
        serialized.append(item)
    return serialized


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _is_integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _integer(value: Any, label: str) -> None:
    if not _is_integer(value):
        raise ConfigurationError(f"{label.capitalize()} must be an integer.")
