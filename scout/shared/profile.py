from __future__ import annotations

from pathlib import Path

from scout.shared.schemas import Profile


def load_profile(path: str | Path) -> Profile:
    profile_path = Path(path)
    if not profile_path.is_file():
        raise FileNotFoundError(f"profile file not found: {profile_path}")
    return Profile.model_validate_json(profile_path.read_text(encoding="utf-8"))
