from sqlalchemy import event
from sqlmodel import Session, SQLModel, create_engine, select
from app import crud
from app.core.config import settings
from app.models import User, UserCreate

settings.STORAGE_DIR.mkdir(parents=True, exist_ok=True)
connect_args = {"check_same_thread": False, "timeout": 30} if settings.DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(settings.DATABASE_URL, connect_args=connect_args, pool_pre_ping=True)
if settings.DATABASE_URL.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def sqlite_pragmas(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=WAL")

def init_db(session: Session) -> None:
    SQLModel.metadata.create_all(session.get_bind())
    if not session.exec(select(User).where(User.email == settings.FIRST_SUPERUSER)).first():
        crud.create_user(session=session, user_create=UserCreate(email=settings.FIRST_SUPERUSER, password=settings.FIRST_SUPERUSER_PASSWORD, is_superuser=True, full_name="系统管理员"))

