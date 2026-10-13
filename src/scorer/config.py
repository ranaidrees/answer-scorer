"""Settings, the rubric loader (FR-2) and the prompt loader with its hash registry (FR-3).

Rubrics and prompts are read server side, relative to `SCORER_ROOT`. A caller can never
supply or alter either. Both loaders fail fast: a broken rubric or a prompt file whose
hash does not match the registry raises before any model call.
"""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

LEVEL_COUNT = 5

_COMPETENCY_ID = re.compile(r"[a-z][a-z0-9_]{0,63}")
_PROMPT_VERSION = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")


class UnknownCompetencyError(LookupError):
    """No rubric exists for the requested competency id."""


class RubricError(ValueError):
    """A rubric file is missing a field or does not follow the FR-2 schema."""


class PromptError(ValueError):
    """The prompt registry or a prompt file is missing, unreadable or does not match."""


def _env(name: str, default: str | None = None) -> str | None:
    """Read one environment variable; an empty value counts as unset."""
    value = os.environ.get(name, "").strip()
    return value or default


def _from_env(name: str, default: str | None = None):
    return lambda: _env(name, default)


class Settings(BaseModel):
    """Configuration read from the environment when constructed with no arguments.

    Secrets are kept out of `repr`, so a settings object can never print one by accident.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", protected_namespaces=())

    scorer_root: Path = Field(default_factory=lambda: Path(_env("SCORER_ROOT") or Path.cwd()))
    scorer_prompt_version: str | None = Field(default_factory=_from_env("SCORER_PROMPT_VERSION"))
    model_deployment: str = Field(default_factory=_from_env("MODEL_DEPLOYMENT", "scorer-mini"))
    model_version: str = Field(default_factory=_from_env("MODEL_VERSION", "2026-03-17"))
    foundry_endpoint: str | None = Field(default_factory=_from_env("FOUNDRY_ENDPOINT"))
    answer_hash_salt: str | None = Field(default_factory=_from_env("ANSWER_HASH_SALT"), repr=False)
    demo_token: str | None = Field(default_factory=_from_env("DEMO_TOKEN"), repr=False)
    applicationinsights_connection_string: str | None = Field(
        default_factory=_from_env("APPLICATIONINSIGHTS_CONNECTION_STRING"), repr=False
    )

    @classmethod
    def from_env(cls) -> Settings:
        return cls()

    @property
    def rubrics_dir(self) -> Path:
        return self.scorer_root / "rubrics"

    @property
    def prompts_dir(self) -> Path:
        return self.scorer_root / "prompts" / "scorer"

    @property
    def config_dir(self) -> Path:
        return self.scorer_root / "config"


# --- Rubrics (FR-2) ---------------------------------------------------------------------


class RubricLevel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    level: int | None = None
    label: str = Field(min_length=1)
    descriptors: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def _descriptors_have_text(self) -> RubricLevel:
        if not self.label.strip() or any(not item.strip() for item in self.descriptors):
            raise ValueError("label and every descriptor must contain text")
        return self


class Rubric(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    definition: str = Field(min_length=1)
    levels: list[RubricLevel] = Field(min_length=LEVEL_COUNT, max_length=LEVEL_COUNT)

    @model_validator(mode="after")
    def _levels_in_order(self) -> Rubric:
        if not self.name.strip() or not self.definition.strip():
            raise ValueError("name and definition must contain text")
        for position, level in enumerate(self.levels, start=1):
            if level.level is not None and level.level != position:
                raise ValueError(f"level {level.level} is out of order at position {position}")
        return self

    def label_for(self, score: int) -> str:
        return self.levels[score - 1].label


def _read_rubric(path: Path) -> Rubric:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as error:
        raise RubricError(f"rubric {path.name} cannot be read: {type(error).__name__}") from error
    try:
        rubric = Rubric.model_validate(data)
    except ValidationError as error:
        problems = "; ".join(
            f"{'.'.join(str(part) for part in item['loc']) or 'rubric'}: {item['msg']}"
            for item in error.errors()
        )
        raise RubricError(f"rubric {path.name} is not valid: {problems}") from error
    if rubric.id != path.stem:
        raise RubricError(f"rubric {path.name} has id {rubric.id!r}; it must match the file name")
    return rubric


def load_rubric(competency_id: str, settings: Settings) -> Rubric:
    """Load and validate `rubrics/<competency_id>.yaml`. The id can never name a path."""
    if not isinstance(competency_id, str) or not _COMPETENCY_ID.fullmatch(competency_id):
        raise UnknownCompetencyError("unknown competency")
    path = settings.rubrics_dir / f"{competency_id}.yaml"
    if not path.is_file():
        raise UnknownCompetencyError("unknown competency")
    return _read_rubric(path)


def load_all_rubrics(settings: Settings) -> dict[str, Rubric]:
    """Load every rubric, for start-up validation. No rubrics at all is an error."""
    paths = sorted(settings.rubrics_dir.glob("*.yaml"))
    if not paths:
        raise RubricError("no rubric files found")
    return {path.stem: _read_rubric(path) for path in paths}


# --- Prompts (FR-3) ---------------------------------------------------------------------


@dataclass(frozen=True)
class Prompt:
    version: str
    text: str
    sha256: str


def prompt_sha256(text: str) -> str:
    """SHA-256 of a prompt's text as UTF-8 with LF line endings.

    Line endings are normalised so that a checkout with CRLF endings hashes the same as
    the committed file. Any other change to the text changes the hash.
    """
    normalised = text.replace("\r\n", "\n").replace("\r", "\n")
    return hashlib.sha256(normalised.encode("utf-8")).hexdigest()


def load_registry(settings: Settings) -> tuple[str, dict[str, str]]:
    """Return the committed active version and the version to SHA-256 map."""
    path = settings.prompts_dir / "registry.yaml"
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as error:
        raise PromptError(f"prompt registry cannot be read: {type(error).__name__}") from error
    if not isinstance(data, dict):
        raise PromptError("prompt registry must be a mapping")
    active, hashes = data.get("active"), data.get("sha256")
    if not isinstance(active, str) or not isinstance(hashes, dict) or not hashes:
        raise PromptError("prompt registry needs `active` and a `sha256` mapping")
    if not all(isinstance(key, str) and isinstance(value, str) for key, value in hashes.items()):
        raise PromptError("prompt registry hashes must be strings")
    return active, dict(hashes)


def load_prompt(settings: Settings) -> Prompt:
    """Load the active prompt and verify its file against the registry hash.

    `SCORER_PROMPT_VERSION` overrides the registry's `active` version only when set.
    """
    active, hashes = load_registry(settings)
    version = settings.scorer_prompt_version or active
    if not _PROMPT_VERSION.fullmatch(version) or version not in hashes:
        raise PromptError(f"prompt version {version!r} is not in the registry")
    path = settings.prompts_dir / f"{version}.md"
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise PromptError(f"prompt file for {version!r} cannot be read") from error
    digest = prompt_sha256(text)
    if digest != hashes[version].strip().lower():
        raise PromptError(
            f"prompt {version!r} does not match its registry hash; "
            "a changed prompt needs a new version"
        )
    return Prompt(version=version, text=text.replace("\r\n", "\n"), sha256=digest)
