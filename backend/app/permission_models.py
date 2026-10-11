import uuid
from typing import Literal
from sqlalchemy import Column, JSON
from sqlmodel import SQLModel, Field

Permission = Literal['data_entry', 'database_data', 'database_charts', 'analysis', 'reports']
ALL_PERMISSIONS = ['data_entry', 'database_data', 'database_charts', 'analysis', 'reports']

def normalize_permissions(values):
    granted = set(values)
    # Read legacy stored grants without widening their write privileges.
    if 'database' in granted:
        granted.update(('database_data', 'database_charts'))
    if 'database_edit' in granted:
        granted.add('database_data')
    return [p for p in ALL_PERMISSIONS if p in granted]

class AccountPermission(SQLModel, table=True):
    user_id: uuid.UUID = Field(foreign_key='user.id', primary_key=True, ondelete='CASCADE')
    permissions: list[str] = Field(sa_column=Column(JSON, nullable=False))

class ProjectPermission(SQLModel, table=True):
    project_id: uuid.UUID = Field(foreign_key='projectrecord.id', primary_key=True, ondelete='CASCADE')
    user_id: uuid.UUID = Field(foreign_key='user.id', primary_key=True, ondelete='CASCADE')
    permissions: list[str] = Field(sa_column=Column(JSON, nullable=False))
