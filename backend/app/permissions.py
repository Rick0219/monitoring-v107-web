from app.permission_models import AccountPermission, ProjectPermission, ALL_PERMISSIONS, normalize_permissions

def account_permissions(session, user):
    if user.is_superuser:
        return list(ALL_PERMISSIONS)
    record = session.get(AccountPermission, user.id)
    # Existing accounts retain their previous capabilities until an admin edits them.
    return normalize_permissions(record.permissions if record else ALL_PERMISSIONS)

def project_permissions(session, project, user):
    if user.is_superuser:
        return list(ALL_PERMISSIONS)
    record = session.get(ProjectPermission, (project.id, user.id))
    return normalize_permissions(record.permissions) if record else account_permissions(session, user)

def set_account_permissions(session, user, values):
    record = session.get(AccountPermission, user.id) or AccountPermission(user_id=user.id, permissions=[])
    record.permissions = normalize_permissions(values)
    session.add(record)

def set_project_permissions(session, project, user, values):
    record = session.get(ProjectPermission, (project.id, user.id))
    if values is None:
        if record:
            session.delete(record)
    else:
        record = record or ProjectPermission(project_id=project.id, user_id=user.id, permissions=[])
        record.permissions = normalize_permissions(values)
        session.add(record)
