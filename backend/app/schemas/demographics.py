"""Demographics value-object schema used inside Interview payloads.

The enum values are the canonical source of truth — they must match
``SPEC.md`` -> ``Demographics JSONB schema`` exactly. The frontend
regenerates its TS types from ``/openapi.json``, so renaming any value
here is a breaking API change.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Gender(StrEnum):
    """Interviewee gender. See SPEC.md."""

    male = "male"
    female = "female"
    non_binary = "non_binary"
    prefer_not_to_say = "prefer_not_to_say"


class Income(StrEnum):
    """Household income bracket (USD)."""

    under_25k = "under_25k"
    band_25k_50k = "25k_50k"
    band_50k_100k = "50k_100k"
    band_100k_200k = "100k_200k"
    over_200k = "over_200k"
    prefer_not_to_say = "prefer_not_to_say"


class MaritalStatus(StrEnum):
    """Interviewee marital status."""

    single = "single"
    married = "married"
    divorced = "divorced"
    widowed = "widowed"
    prefer_not_to_say = "prefer_not_to_say"


class JobRole(StrEnum):
    """Interviewee role bucket."""

    engineer = "engineer"
    designer = "designer"
    product_manager = "product_manager"
    marketing = "marketing"
    sales = "sales"
    operations = "operations"
    customer_support = "customer_support"
    founder_executive = "founder_executive"
    student = "student"
    other = "other"


class Industry(StrEnum):
    """Interviewee industry bucket."""

    saas_software = "saas_software"
    ecommerce_retail = "ecommerce_retail"
    finance_fintech = "finance_fintech"
    healthcare = "healthcare"
    education = "education"
    media_entertainment = "media_entertainment"
    manufacturing = "manufacturing"
    government_nonprofit = "government_nonprofit"
    hospitality_travel = "hospitality_travel"
    other = "other"


class DemographicsSchema(BaseModel):
    """Demographics block attached to every Interview row.

    Every field is required; the frontend renders dropdowns for each
    enum. ``country`` is stored as ISO 3166-1 alpha-2 (e.g. ``US``,
    ``IN``); we accept either case and normalize to uppercase before
    validation so the downstream consumers always see a canonical code.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=200)
    gender: Gender
    age: int = Field(ge=13, le=120)
    income: Income
    marital_status: MaritalStatus
    country: str = Field(min_length=2, max_length=2, pattern="^[A-Za-z]{2}$")
    job_role: JobRole
    industry: Industry

    @field_validator("country", mode="before")
    @classmethod
    def _uppercase_country(cls, value: object) -> object:
        """Normalize ISO-3166 alpha-2 codes to uppercase before length/pattern checks."""
        if isinstance(value, str):
            return value.upper()
        return value
