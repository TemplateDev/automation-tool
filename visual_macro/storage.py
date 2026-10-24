from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

import cv2
import numpy as np


class StorageError(OSError):
    """Raised when application-managed data cannot be read or written safely."""


def default_data_directory(
    environ: dict[str, str] | None = None,
    platform_name: str | None = None,
    home: Path | None = None,
) -> Path:
    environment = os.environ if environ is None else environ
    system = os.name if platform_name is None else platform_name
    if system == "nt":
        base = environment.get("LOCALAPPDATA") or environment.get("APPDATA")
        if not base:
            raise StorageError("Windows did not provide LOCALAPPDATA or APPDATA.")
        return Path(base) / "VisualMacroAutomation"
    base = environment.get("XDG_DATA_HOME")
    if base:
        return Path(base) / "visual-macro-automation"
    return (home or Path.home()) / ".local" / "share" / "visual-macro-automation"


class ApplicationStorage:
    def __init__(self, root: str | Path | None = None) -> None:
        self.root = Path(root) if root is not None else default_data_directory()
        self.templates_dir = self.root / "templates"
        self.profiles_dir = self.root / "profiles"
        self.logs_dir = self.root / "logs"
        self.settings_path = self.root / "settings.json"
        self.log_path = self.logs_dir / "activity.log"

    def initialize(self) -> None:
        try:
            for directory in (self.templates_dir, self.profiles_dir, self.logs_dir):
                directory.mkdir(parents=True, exist_ok=True)
            if not self.settings_path.exists():
                try:
                    with self.settings_path.open("x", encoding="utf-8") as file:
                        json.dump({"version": 1}, file, indent=2)
                        file.write("\n")
                except FileExistsError:
                    pass
        except OSError as exc:
            raise StorageError(f"Could not initialize application storage at {self.root}: {exc}") from exc

    def load_settings(self) -> dict[str, Any]:
        self.initialize()
        try:
            with self.settings_path.open("r", encoding="utf-8") as file:
                settings = json.load(file)
        except (OSError, json.JSONDecodeError) as exc:
            raise StorageError(f"Could not read application settings at {self.settings_path}: {exc}") from exc
        if not isinstance(settings, dict):
            raise StorageError(f"Application settings must be a JSON object: {self.settings_path}")
        return settings

    def save_settings(self, settings: dict[str, Any]) -> None:
        if not isinstance(settings, dict):
            raise StorageError("Application settings must be a JSON object.")
        self.initialize()
        self._write_settings(settings)

    def _write_settings(self, settings: dict[str, Any]) -> None:
        temporary = self.settings_path.with_name(f"{self.settings_path.name}.{uuid.uuid4().hex}.tmp")
        try:
            with temporary.open("x", encoding="utf-8") as file:
                json.dump(settings, file, indent=2)
                file.write("\n")
            os.replace(temporary, self.settings_path)
        except (OSError, TypeError, ValueError) as exc:
            raise StorageError(f"Could not save application settings at {self.settings_path}: {exc}") from exc
        finally:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass

    def store_capture(self, image: np.ndarray, friendly_name: str) -> Path:
        encoded = self._encode_image(image, ".png")
        return self._store_bytes(encoded, friendly_name, ".png")

    def import_image(self, source: str | Path, friendly_name: str | None = None) -> Path:
        source_path = Path(source).expanduser()
        try:
            image_bytes = source_path.read_bytes()
        except OSError as exc:
            raise StorageError(f"Could not read image '{source_path}': {exc}") from exc
        extension = source_path.suffix.lower()
        if extension not in {".png", ".jpg", ".jpeg", ".bmp", ".webp"}:
            extension = ".png"
            decoded = self._decode_image(image_bytes, source_path)
            image_bytes = self._encode_image(decoded, extension)
        else:
            self._decode_image(image_bytes, source_path)
        return self._store_bytes(
            image_bytes,
            friendly_name or source_path.stem,
            extension,
        )

    @staticmethod
    def _decode_image(image_bytes: bytes, source: Path) -> np.ndarray:
        image = cv2.imdecode(np.frombuffer(image_bytes, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
        if image is None or image.size == 0 or image.shape[0] <= 0 or image.shape[1] <= 0:
            raise StorageError(f"Image is invalid or unreadable: {source}")
        return image

    @staticmethod
    def _encode_image(image: np.ndarray, extension: str) -> bytes:
        if not isinstance(image, np.ndarray) or image.size == 0:
            raise StorageError("The selected template image is empty or invalid.")
        try:
            success, encoded = cv2.imencode(extension, image)
        except cv2.error as exc:
            raise StorageError(f"Could not encode the selected template image: {exc}") from exc
        if not success or encoded.size == 0:
            raise StorageError("Could not encode the selected template image.")
        return encoded.tobytes()

    def _store_bytes(self, contents: bytes, friendly_name: str, extension: str) -> Path:
        self.initialize()
        stem = _safe_stem(friendly_name)
        for _attempt in range(10):
            destination = self.templates_dir / f"{stem}-{uuid.uuid4().hex[:12]}{extension}"
            created = False
            try:
                with destination.open("xb") as file:
                    created = True
                    file.write(contents)
                return destination
            except FileExistsError:
                continue
            except OSError as exc:
                if created:
                    try:
                        destination.unlink(missing_ok=True)
                    except OSError:
                        pass
                raise StorageError(f"Could not store template '{friendly_name}': {exc}") from exc
        raise StorageError(f"Could not allocate a unique filename for template '{friendly_name}'.")

    def append_log(self, message: str) -> None:
        self.initialize()
        timestamp = datetime.now().isoformat(timespec="seconds")
        try:
            with self.log_path.open("a", encoding="utf-8") as file:
                file.write(f"[{timestamp}] {message}\n")
        except OSError as exc:
            raise StorageError(f"Could not append to activity log {self.log_path}: {exc}") from exc


def _safe_stem(value: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9_-]+", "-", Path(value.strip()).stem).strip("-_")
    return stem[:60] or "template"
