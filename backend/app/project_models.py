import uuid
from typing import Literal
from datetime import datetime
from pydantic import BaseModel, ConfigDict, EmailStr, Field as PField, field_validator
from sqlalchemy import Column, JSON
from sqlmodel import SQLModel, Field
from app.models import get_datetime_utc
from app.permission_models import Permission

class ProjectRecord(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    owner_id: uuid.UUID = Field(foreign_key="user.id", index=True, ondelete="CASCADE")
    name: str = Field(max_length=120)
    description: str = ""
    location: str = ""
    revision: int = 1
    payload: dict = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    created_at: datetime = Field(default_factory=get_datetime_utc)
    updated_at: datetime = Field(default_factory=get_datetime_utc)

class StrictInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

class ProjectMember(SQLModel, table=True):
    project_id: uuid.UUID = Field(foreign_key="projectrecord.id", primary_key=True, ondelete="CASCADE")
    user_id: uuid.UUID = Field(foreign_key="user.id", primary_key=True, ondelete="CASCADE")

class MemberAdd(StrictInput):
    email: EmailStr
    permissions: list[Permission] | None = None

class MemberPermissions(StrictInput):
    permissions: list[Permission] | None

class ChartPreference(SQLModel, table=True):
    project_id: uuid.UUID = Field(foreign_key="projectrecord.id", primary_key=True, ondelete="CASCADE")
    user_id: uuid.UUID = Field(foreign_key="user.id", primary_key=True, ondelete="CASCADE")
    measurement_key: str = Field(primary_key=True, max_length=150)
    settings: dict = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))

class ChartSettings(StrictInput):
    measurement_key: str = PField(min_length=1, max_length=150)
    mode: Literal["top10", "all", "custom"] = "top10"
    points: list[str] = PField(default_factory=list, max_length=20000)
    display: Literal["daily", "bar", "history"] = "daily"
    end_date: str = PField(default="", max_length=40)

class DatabaseDate(StrictInput):
    measurement_key: str = PField(min_length=1, max_length=150)
    end_date: str = PField(default="", max_length=40)

class ProjectCreate(StrictInput):
    name: str = PField(min_length=1, max_length=120)
    description: str = PField(default="", max_length=2000)
    location: str = PField(default="", max_length=200)

class ProjectUpdate(ProjectCreate):
    revision: int = PField(ge=1)

class DataWrite(StrictInput):
    revision: int = PField(ge=1)
    measurement_key: str = PField(min_length=1, max_length=150)
    rows: list[dict] = PField(max_length=20000)

class TwinSceneWrite(StrictInput):
    revision: int = PField(ge=1)
    scene: dict

class DatabaseWrite(DataWrite):
    date: str = PField(min_length=1, max_length=40)

class LevelAdjustmentMapping(StrictInput):
    adjusted_point: str = PField(min_length=1, max_length=120)
    database_point: str = PField(min_length=1, max_length=120)
    enabled: bool = True

class LevelAdjustmentApplyRequest(StrictInput):
    revision: int = PField(ge=1)
    import_id: str = PField(pattern=r"^[0-9a-f]{32}$")
    measurement_key: str = PField(min_length=1, max_length=150)
    observed_date: str = PField(min_length=1, max_length=40)
    weight_mode: Literal["distance", "station"]
    allow_out_of_tolerance: bool = False
    mappings: list[LevelAdjustmentMapping] = PField(max_length=20000)

class Scope(StrictInput):
    measurement_key: str = "__all__"
    start_date: str = ""
    end_date: str = ""
    point: str = ""

class Ask(Scope):
    question: str = PField(min_length=1, max_length=4000)
    mode: str = "hybrid"

    @field_validator("mode")
    @classmethod
    def mode_allowed(cls, value):
        if value not in {"hybrid","documents","data"}:
            raise ValueError("问答范围无效")
        return value


class ProjectModelSettings(StrictInput):
    revision: int = PField(ge=1)
    base_url: str = PField(default="", max_length=500)
    model: str = PField(default="", max_length=200)
    api_key: str | None = PField(default=None, max_length=500)
    clear_api_key: bool = False
    timeout: int = PField(default=90, ge=1, le=300)
