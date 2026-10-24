from visual_macro.engine import RuleEngine
from visual_macro.models import Rule
from visual_macro.recognition import Detection


def _rule(*, cooldown: float = 0, repeat: bool = False) -> Rule:
    return Rule(
        id="button",
        name="Button",
        template_path="button.png",
        cooldown=cooldown,
        repeat=repeat,
    )


def _result(matched: bool) -> dict[str, Detection]:
    return {"button": Detection(confidence=0.95 if matched else 0.2, location=None, matched=matched)}


def test_new_presence_triggers_once_until_disappearance() -> None:
    engine = RuleEngine()
    rule = _rule()

    assert engine.evaluate([rule], _result(True), 0) == [rule]
    assert engine.evaluate([rule], _result(True), 1) == []
    assert engine.evaluate([rule], _result(False), 2) == []
    assert engine.evaluate([rule], _result(True), 3) == [rule]


def test_cooldown_suppresses_a_new_presence_until_next_appearance() -> None:
    engine = RuleEngine()
    rule = _rule(cooldown=5)

    assert engine.evaluate([rule], _result(True), 0) == [rule]
    assert engine.evaluate([rule], _result(False), 1) == []
    assert engine.evaluate([rule], _result(True), 2) == []
    assert engine.evaluate([rule], _result(False), 5) == []
    assert engine.evaluate([rule], _result(True), 6) == [rule]


def test_repeat_rule_triggers_while_present_after_cooldown() -> None:
    engine = RuleEngine()
    rule = _rule(cooldown=3, repeat=True)

    assert engine.evaluate([rule], _result(True), 0) == [rule]
    assert engine.evaluate([rule], _result(True), 2.9) == []
    assert engine.evaluate([rule], _result(True), 3) == [rule]
    assert engine.evaluate([rule], _result(False), 4) == []
    assert engine.evaluate([rule], _result(True), 5) == []
    assert engine.evaluate([rule], _result(True), 6) == [rule]
