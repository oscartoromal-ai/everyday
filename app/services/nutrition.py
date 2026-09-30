"""Nutrition: what Oscar eats, a day at a time, kept as Markdown files.

The files are the record (Oscar's call, 2026-09-30), in the folder
`[nutrition].dir` names: `plan.md` (his plan, its daily targets in its front
matter), `meals/` (recipes), and `log/YYYY-MM-DD.md`, one per day. Claude
writes them from Nutrition's chat; Oscar can edit them by hand too.

A day's file carries what was eaten (or is planned) in its YAML front matter,
meal by meal and item by item with each item's nutrients, and its notes and
recommendation as Markdown under it. The app reads both and never stores a
total: totals are summed from the items, so they cannot drift from them.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

# The nutrients every item carries, in the order they are shown, with their
# words and units.
NUTRIENTS: dict[str, tuple[str, str]] = {
    "kcal": ("Energy", "kcal"),
    "protein_g": ("Protein", "g"),
    "fat_g": ("Fat", "g"),
    "sat_fat_g": ("Saturated fat", "g"),
    "carbs_g": ("Carbs", "g"),
    "fibre_g": ("Fibre", "g"),
}


class NutritionFileError(Exception):
    """A nutrition file that cannot be read as the format says."""


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Item(_Strict):
    food: str = Field(min_length=1)
    amount: str = ""
    # No amount was given, so a typical one was assumed.
    assumed: bool = False
    kcal: float = Field(ge=0)
    protein_g: float = Field(ge=0)
    fat_g: float = Field(ge=0)
    sat_fat_g: float = Field(ge=0)
    carbs_g: float = Field(ge=0)
    fibre_g: float = Field(ge=0)

    @model_validator(mode="after")
    def _saturated_within_fat(self) -> Item:
        if self.sat_fat_g > self.fat_g:
            raise ValueError("sat_fat_g is part of fat_g, so it cannot be more")
        return self


class Meal(_Strict):
    name: str = Field(min_length=1)
    status: Literal["eaten", "planned"] = "eaten"
    items: list[Item] = Field(min_length=1)


class DayFrontMatter(_Strict):
    date: date
    meals: list[Meal] = []


class Target(_Strict):
    """A daily target: a figure to aim for, a floor, or a ceiling."""

    aim: float | None = Field(default=None, gt=0)
    min: float | None = Field(default=None, gt=0)
    max: float | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def _one_kind(self) -> Target:
        if sum(v is not None for v in (self.aim, self.min, self.max)) != 1:
            raise ValueError("a target is exactly one of aim, min or max")
        return self

    @property
    def kind(self) -> str:
        return "aim" if self.aim is not None else "min" if self.min is not None else "max"

    @property
    def value(self) -> float:
        return next(v for v in (self.aim, self.min, self.max) if v is not None)


class PlanFrontMatter(BaseModel):
    # plan.md's front matter may hold more than targets; only they are read.
    targets: dict[Literal[tuple(NUTRIENTS)], Target] = {}  # type: ignore[valid-type]


@dataclass
class DayLog:
    day: date
    meals: list[Meal]
    body: str

    def totals(self, *, planned: bool) -> dict[str, float]:
        """The day's nutrients summed: what was eaten, or with what is planned too."""
        sums = dict.fromkeys(NUTRIENTS, 0.0)
        for meal in self.meals:
            if meal.status == "planned" and not planned:
                continue
            for item in meal.items:
                for key in NUTRIENTS:
                    sums[key] += getattr(item, key)
        return sums

    @property
    def has_planned(self) -> bool:
        return any(meal.status == "planned" for meal in self.meals)


def log_path(folder: Path, day: date) -> Path:
    return folder / "log" / f"{day.isoformat()}.md"


def split_front_matter(text: str) -> tuple[dict, str]:
    """A Markdown file's YAML front matter (between two `---` lines at its
    top) and the Markdown after it."""
    text = text.lstrip("﻿")
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        raise NutritionFileError("it has no front matter (a --- line first)")
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            head, body = "".join(lines[1:index]), "".join(lines[index + 1:])
            break
    else:
        raise NutritionFileError("its front matter has no closing --- line")
    try:
        data = yaml.safe_load(head)
    except yaml.YAMLError as exc:
        raise NutritionFileError(f"its front matter is not valid YAML: {exc}") from None
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise NutritionFileError("its front matter is not a set of fields")
    return data, body


def _explain(exc: ValidationError) -> str:
    """Pydantic's errors in a line each, naming where in the front matter."""
    lines = []
    for error in exc.errors():
        where = ".".join(str(part) for part in error["loc"]) or "front matter"
        lines.append(f"{where}: {error['msg']}")
    return "; ".join(lines)


def parse_day(text: str, day: date) -> DayLog:
    data, body = split_front_matter(text)
    try:
        front = DayFrontMatter.model_validate(data)
    except ValidationError as exc:
        raise NutritionFileError(_explain(exc)) from None
    if front.date != day:
        raise NutritionFileError(f"its date is {front.date}, not {day}")
    return DayLog(day=day, meals=front.meals, body=body.strip())


def read_day(folder: Path, day: date) -> DayLog | None:
    """The day's log, or None when nothing is logged that day. Raises
    NutritionFileError when the file is there but cannot be read."""
    path = log_path(folder, day)
    if not path.exists():
        return None
    return parse_day(path.read_text(encoding="utf-8"), day)


def read_targets(folder: Path) -> dict[str, Target]:
    """The daily targets from plan.md's front matter; none without it."""
    path = folder / "plan.md"
    if not path.exists():
        return {}
    data, _ = split_front_matter(path.read_text(encoding="utf-8"))
    try:
        return PlanFrontMatter.model_validate(data).targets
    except ValidationError as exc:
        raise NutritionFileError(_explain(exc)) from None
