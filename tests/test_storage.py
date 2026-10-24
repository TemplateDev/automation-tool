import json
from pathlib import Path

import cv2
import numpy as np
import pytest

from visual_macro.storage import ApplicationStorage, StorageError, default_data_directory


def test_windows_application_data_directory_prefers_local_appdata(tmp_path) -> None:
    root = default_data_directory(
        {"LOCALAPPDATA": str(tmp_path / "local"), "APPDATA": str(tmp_path / "roaming")},
        platform_name="nt",
    )

    assert root == tmp_path / "local" / "VisualMacroAutomation"


def test_storage_initializes_expected_layout_and_settings(tmp_path) -> None:
    storage = ApplicationStorage(tmp_path / "data")

    storage.initialize()

    assert storage.templates_dir.is_dir()
    assert storage.profiles_dir.is_dir()
    assert storage.logs_dir.is_dir()
    assert json.loads(storage.settings_path.read_text(encoding="utf-8")) == {"version": 1}
    storage.append_log("started")
    assert "started" in storage.log_path.read_text(encoding="utf-8")


def test_settings_save_and_load_preserves_existing_values(tmp_path) -> None:
    storage = ApplicationStorage(tmp_path / "data")
    storage.save_settings({"version": 1, "last_profile": "sample.json"})

    assert storage.load_settings()["last_profile"] == "sample.json"


def test_captured_templates_have_unique_safe_names_and_valid_image_data(tmp_path) -> None:
    storage = ApplicationStorage(tmp_path / "data")
    image = np.full((12, 15, 3), 90, dtype=np.uint8)

    first = storage.store_capture(image, "../A Friendly Name")
    second = storage.store_capture(image, "../A Friendly Name")

    assert first.parent == storage.templates_dir
    assert first.name.startswith("A-Friendly-Name-")
    assert first != second
    assert cv2.imread(str(first)) is not None


def test_imported_image_is_copied_into_managed_storage(tmp_path) -> None:
    storage = ApplicationStorage(tmp_path / "data")
    source = tmp_path / "external.png"
    cv2.imwrite(str(source), np.arange(20 * 25, dtype=np.uint8).reshape(20, 25))

    managed = storage.import_image(source, "Friendly Icon")

    assert managed.parent == storage.templates_dir
    assert managed.name.startswith("Friendly-Icon-")
    assert managed.read_bytes() == source.read_bytes()
    source.unlink()
    assert cv2.imread(str(managed)) is not None


def test_import_missing_or_invalid_image_reports_a_clear_error(tmp_path) -> None:
    storage = ApplicationStorage(tmp_path / "data")
    with pytest.raises(StorageError, match="Could not read image"):
        storage.import_image(tmp_path / "missing.png")

    invalid = tmp_path / "invalid.png"
    invalid.write_bytes(b"not an image")
    with pytest.raises(StorageError, match="invalid or unreadable"):
        storage.import_image(invalid)


def test_empty_capture_is_rejected_and_storage_write_failures_are_reported(tmp_path) -> None:
    storage = ApplicationStorage(tmp_path / "data")
    with pytest.raises(StorageError, match="empty or invalid"):
        storage.store_capture(np.array([]), "Empty")

    blocked_root = tmp_path / "blocked"
    blocked_root.mkdir()
    (blocked_root / "templates").write_text("not a directory", encoding="utf-8")
    blocked = ApplicationStorage(blocked_root)
    with pytest.raises(StorageError, match="Could not initialize application storage"):
        blocked.store_capture(np.zeros((4, 4, 3), dtype=np.uint8), "Blocked")


def test_settings_parse_failure_does_not_overwrite_user_data(tmp_path) -> None:
    storage = ApplicationStorage(tmp_path / "data")
    storage.initialize()
    storage.settings_path.write_text("{ damaged", encoding="utf-8")
    before = storage.settings_path.read_bytes()

    with pytest.raises(StorageError, match="Could not read application settings"):
        storage.load_settings()

    assert storage.settings_path.read_bytes() == before


def test_filename_collision_is_retried_without_overwriting_existing_template(
    tmp_path, monkeypatch
) -> None:
    storage = ApplicationStorage(tmp_path / "data")
    storage.initialize()
    collision = storage.templates_dir / "Button-aaaaaaaaaaaa.png"
    collision.write_bytes(b"preserve")
    values = iter(["aaaaaaaaaaaa", "bbbbbbbbbbbb"])
    monkeypatch.setattr(
        "visual_macro.storage.uuid.uuid4",
        lambda: type("UUID", (), {"hex": next(values)})(),
    )

    result = storage.store_capture(np.zeros((4, 4, 3), dtype=np.uint8), "Button")

    assert result.name == "Button-bbbbbbbbbbbb.png"
    assert collision.read_bytes() == b"preserve"


def test_managed_profile_round_trip_uses_stable_relative_template_reference(tmp_path) -> None:
    from visual_macro.models import Profile, Rule, load_profile, save_profile

    storage = ApplicationStorage(tmp_path / "data")
    template = storage.store_capture(np.zeros((8, 8, 3), dtype=np.uint8), "Button")
    profile_path = storage.profiles_dir / "default.json"
    profile = Profile(rules=[Rule(id="button", name="Button", template_path=str(template))])

    save_profile(profile, profile_path)
    saved = json.loads(profile_path.read_text(encoding="utf-8"))
    restored = load_profile(profile_path)

    assert saved["rules"][0]["template_path"] == f"../templates/{template.name}"
    assert Path(restored.rules[0].template_path) == template
