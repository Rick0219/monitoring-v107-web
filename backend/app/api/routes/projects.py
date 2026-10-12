import uuid
from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import update, delete, or_
from sqlalchemy.exc import IntegrityError
from sqlmodel import select
from app.api.deps import CurrentUser, SessionDep, get_current_active_superuser
from app.models import User, get_datetime_utc
from app.project_models import ProjectRecord, ProjectCreate, ProjectUpdate, ProjectMember, MemberAdd, MemberPermissions
from app.permissions import account_permissions, project_permissions, set_project_permissions
from app.permission_models import ProjectPermission

router = APIRouter(prefix="/projects", tags=["projects"])

def authorized_project(project_id: uuid.UUID, session: SessionDep, current_user: CurrentUser) -> ProjectRecord:
    project = session.get(ProjectRecord, project_id)
    if not project or (project.owner_id != current_user.id and not current_user.is_superuser
                       and session.get(ProjectMember, (project_id, current_user.id)) is None):
        raise HTTPException(404, "工程不存在或没有访问权限")
    return project

ProjectDep = Annotated[ProjectRecord, Depends(authorized_project)]

def require_features(*features):
    def check(project: ProjectDep, session: SessionDep, current_user: CurrentUser):
        if not set(features).intersection(project_permissions(session, project, current_user)):
            raise HTTPException(403, "当前账号没有此功能权限，请联系管理员")
        return project
    return check

EditProject = Annotated[ProjectRecord, Depends(require_features('data_entry'))]

def require_manager(project, user):
    if project.owner_id != user.id and not user.is_superuser:
        raise HTTPException(403, "仅工程创建人或管理员可以管理成员、删除工程")

def public(project, session, user=None):
    owner = session.get(User, project.owner_id)
    measurements = {key: rows for key, rows in project.payload.get("measurements", {}).items()
                    if key != "inclinometer_points"}
    return {k: getattr(project,k) for k in ("id","owner_id","name","description","location","revision","created_at","updated_at")} | {
        "owner_name": (owner.full_name or owner.email) if owner else "",
        "measurement_count": len(measurements),
        "row_count": sum(len(r) for r in measurements.values()),
        **({'permissions': project_permissions(session, project, user)} if user else {}),
    }

def save_project(session, project, revision, **values):
    result = session.execute(update(ProjectRecord).where(ProjectRecord.id==project.id, ProjectRecord.revision==revision).values(**values, revision=revision+1, updated_at=get_datetime_utc()).execution_options(synchronize_session=False))
    if result.rowcount != 1:
        session.rollback()
        raise HTTPException(409, "工程已被其他页面修改，请刷新后重试")
    session.commit()
    session.refresh(project)
    return project

@router.get("")
def mine(session: SessionDep, current_user: CurrentUser):
    joined = select(ProjectMember.project_id).where(ProjectMember.user_id == current_user.id)
    projects = session.exec(select(ProjectRecord).where(or_(ProjectRecord.owner_id==current_user.id, ProjectRecord.id.in_(joined))).order_by(ProjectRecord.updated_at.desc())).all()
    return {"data":[public(p,session,current_user) for p in projects],"count":len(projects)}

@router.get("/all")
def all_projects(session: SessionDep, admin: Annotated[User, Depends(get_current_active_superuser)]):
    projects = session.exec(select(ProjectRecord).order_by(ProjectRecord.updated_at.desc())).all()
    return {"data":[public(p,session,admin) for p in projects],"count":len(projects)}

@router.post("")
def create(body: ProjectCreate, session: SessionDep, current_user: CurrentUser):
    if 'data_entry' not in account_permissions(session, current_user):
        raise HTTPException(403, "当前账号没有数据录入权限，无法新建工程，请联系管理员")
    project = ProjectRecord(**body.model_dump(), owner_id=current_user.id)
    project.payload = {"version":1, "project":{"name":project.name}, "measurements":{}}
    session.add(project)
    session.commit()
    session.refresh(project)
    return public(project, session, current_user)

@router.get("/{project_id}")
def read(project: ProjectDep, session: SessionDep, current_user: CurrentUser):
    return public(project, session, current_user)

@router.patch("/{project_id}")
def edit(body: ProjectUpdate, project: EditProject, session: SessionDep, current_user: CurrentUser):
    save_project(session, project, body.revision, **body.model_dump(exclude={"revision"}))
    return public(project, session, current_user)

@router.delete("/{project_id}")
def remove(project: ProjectDep, session: SessionDep, current_user: CurrentUser, revision: int):
    require_manager(project, current_user)
    result = session.execute(delete(ProjectRecord).where(ProjectRecord.id==project.id, ProjectRecord.revision==revision).execution_options(synchronize_session=False))
    if result.rowcount != 1:
        session.rollback()
        raise HTTPException(409, "工程已变更，请刷新")
    session.commit()
    # Retain inaccessible files for manual backup recovery; UUIDs are never reused.
    return {"message":"工程已删除"}

@router.get("/{project_id}/members")
def members(project: ProjectDep, session: SessionDep, current_user: CurrentUser):
    require_manager(project, current_user)
    joined = select(ProjectMember.user_id).where(ProjectMember.project_id == project.id)
    users = session.exec(select(User).where(or_(User.id == project.owner_id, User.id.in_(joined))).order_by(User.email)).all()
    data = [{"id": u.id, "email": u.email, "full_name": u.full_name,
             "is_active": u.is_active, "is_superuser": u.is_superuser,
             "is_owner": u.id == project.owner_id,
             "permissions": project_permissions(session, project, u),
             "inherits_permissions": session.get(ProjectPermission, (project.id, u.id)) is None} for u in users]
    return {"data": data, "count": len(data)}

@router.post("/{project_id}/members")
def add_member(body: MemberAdd, project: ProjectDep, session: SessionDep, current_user: CurrentUser):
    require_manager(project, current_user)
    if body.permissions is not None and not current_user.is_superuser:
        raise HTTPException(403, "只有管理员可以设置功能权限")
    user = session.exec(select(User).where(User.email == str(body.email).lower())).first()
    if not user or not user.is_active:
        raise HTTPException(422, "账号不存在或已停用，请先由管理员创建并启用账号")
    if user.id != project.owner_id and session.get(ProjectMember, (project.id, user.id)) is None:
        session.add(ProjectMember(project_id=project.id, user_id=user.id))
        try:
            session.flush()
        except IntegrityError:
            session.rollback()
            if session.get(ProjectMember, (project.id, user.id)) is None:
                raise
    if body.permissions is not None:
        set_project_permissions(session, project, user, body.permissions)
    session.commit()
    return {"message": "账号已加入工程"}

@router.patch("/{project_id}/members/{user_id}/permissions")
def change_member_permissions(user_id: uuid.UUID, body: MemberPermissions, project: ProjectDep, session: SessionDep, current_user: CurrentUser):
    if not current_user.is_superuser:
        raise HTTPException(403, "只有管理员可以设置功能权限")
    user = session.get(User, user_id)
    if not user or (user.id != project.owner_id and session.get(ProjectMember, (project.id, user_id)) is None):
        raise HTTPException(404, "该账号不在工程成员中")
    set_project_permissions(session, project, user, body.permissions)
    session.commit()
    return {'message': '工程权限已更新', 'permissions': project_permissions(session, project, user)}

@router.delete("/{project_id}/members/{user_id}")
def remove_member(user_id: uuid.UUID, project: ProjectDep, session: SessionDep, current_user: CurrentUser):
    require_manager(project, current_user)
    if user_id == project.owner_id:
        raise HTTPException(400, "工程创建人不能从成员中移除")
    member = session.get(ProjectMember, (project.id, user_id))
    if member is None:
        raise HTTPException(404, "该账号不在工程成员中")
    session.delete(member)
    # Retain admin-assigned restrictions across rejoining; ownership must not
    # let a user reset another account's privileges by removing and readding it.
    session.commit()
    return {"message": "成员已移除；管理员仍保留全部工程的访问权限"}
