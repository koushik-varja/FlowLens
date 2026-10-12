from __future__ import annotations

from typing import Annotated, Any, Literal, Union
from pydantic import BaseModel, Field, field_validator, model_validator


class Condition(BaseModel):
    field: Literal["priority", "value", "customer_type", "region", "department", "channel"]
    op: Literal["eq", "neq", "lt", "lte", "gt", "gte", "in"] = "eq"
    value: Any


class ActivitySpeedup(BaseModel):
    type: Literal["activity_speedup"] = "activity_speedup"
    activity: str = Field(min_length=1, max_length=200)
    reduction_fraction: float = Field(gt=0, le=0.95)


class RemoveActivity(BaseModel):
    type: Literal["remove_activity"] = "remove_activity"
    activity: str = Field(min_length=1, max_length=200)


class AddResourceCapacity(BaseModel):
    type: Literal["add_resource_capacity"] = "add_resource_capacity"
    activity: str = Field(min_length=1, max_length=200)
    additional_capacity: int = Field(ge=1, le=100)
    service_fraction: float = Field(default=0.35, gt=0, le=1)


class AutomateEligibleCases(BaseModel):
    type: Literal["automate_eligible_cases"] = "automate_eligible_cases"
    activity: str = Field(min_length=1, max_length=200)
    conditions: list[Condition] = Field(min_length=1)
    reduction_fraction: float = Field(default=0.8, gt=0, le=1)
    processing_effort_saved_minutes: float | None = Field(default=None, ge=0)


class ParallelizeActivities(BaseModel):
    type: Literal["parallelize_activities"] = "parallelize_activities"
    first_activity: str = Field(min_length=1, max_length=200)
    second_activity: str = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def distinct(self):
        if self.first_activity == self.second_activity:
            raise ValueError("Parallelized activities must be distinct")
        return self


class RouteCases(BaseModel):
    type: Literal["route_cases"] = "route_cases"
    conditions: list[Condition] = Field(min_length=1)
    from_activity: str = Field(min_length=1, max_length=200)
    to_activity: str = Field(min_length=1, max_length=200)


class ChangeSLA(BaseModel):
    type: Literal["change_sla"] = "change_sla"
    hours: float = Field(gt=0)


class ChangePriorityRouting(BaseModel):
    type: Literal["change_priority_routing"] = "change_priority_routing"
    priority: str = Field(min_length=1, max_length=50)
    activity: str = Field(min_length=1, max_length=200)
    reduction_fraction: float = Field(gt=0, le=0.95)


TransformationAction = Annotated[
    Union[
        ActivitySpeedup,
        RemoveActivity,
        AddResourceCapacity,
        AutomateEligibleCases,
        ParallelizeActivities,
        RouteCases,
        ChangeSLA,
        ChangePriorityRouting,
    ],
    Field(discriminator="type"),
]


class ScenarioDefinition(BaseModel):
    name: str = Field(default="Scenario", min_length=1, max_length=120)
    actions: list[TransformationAction] = Field(default_factory=list, max_length=30)
    runs: int = Field(default=200, ge=20, le=2000)
    sla_hours: float = Field(default=48, gt=0)
    seed: int = 42
    cohort_size: int | None = Field(default=None, ge=10, le=1000)

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        return value.strip()
