from app.core.config import Settings


def test_render_postgres_url_uses_psycopg_driver():
    settings = Settings(
        SECRET_KEY="x" * 32,
        FIRST_SUPERUSER_PASSWORD="x" * 12,
        DATABASE_URL="postgresql://user:password@localhost:5432/monitoring",
    )

    assert settings.DATABASE_URL == (
        "postgresql+psycopg://user:password@localhost:5432/monitoring"
    )


def test_postgres_scheme_without_driver_is_normalized():
    settings = Settings(
        SECRET_KEY="x" * 32,
        FIRST_SUPERUSER_PASSWORD="x" * 12,
        DATABASE_URL="postgres://user:password@localhost:5432/monitoring",
    )

    assert settings.DATABASE_URL.startswith("postgresql+psycopg://")
