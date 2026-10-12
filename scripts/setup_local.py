"""Provision an isolated local installation. Does not print passwords."""
import json
import secrets
from pathlib import Path
from dotenv import dotenv_values

ROOT=Path(__file__).resolve().parents[1]
environment=ROOT/".env"
data=ROOT/"data"
data.mkdir(exist_ok=True)
existing=dotenv_values(environment) if environment.exists() else {}
if not existing.get("SECRET_KEY") or existing.get("SECRET_KEY")=="changethis":
    password=secrets.token_urlsafe(15)
    settings={
        "SECRET_KEY":secrets.token_urlsafe(48),
        "FIRST_SUPERUSER":"admin@example.com",
        "FIRST_SUPERUSER_PASSWORD":password,
        "PROJECT_NAME":"监测工作台 V1.07",
        "DATABASE_URL":"sqlite:///"+(data/"monitoring.db").as_posix(),
        "FRONTEND_HOST":"http://localhost:5173",
        "AI_BASE_URL":"","AI_MODEL":"","AI_API_KEY":"","AI_TIMEOUT":"90",
    }
    environment.write_text("\n".join(k+"="+json.dumps(v,ensure_ascii=False) for k,v in settings.items())+"\n",encoding="utf-8")
    (data/"首次登录.txt").write_text("本机访问：http://127.0.0.1:8007\n管理员账号：admin@example.com\n初始密码："+password+"\n请登录后修改密码。此文件包含初始登录凭据，不要分享或提交 Git。\n",encoding="utf-8")
    print("Initial administrator credentials saved to data/首次登录.txt")
else:
    print("Existing environment retained.")

