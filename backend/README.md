# V1.07 Web 后端

以根目录 README.md 和 backend/requirements.txt 为当前版本说明。原模板说明保存在 upstream/support/backend-README.md。

Python 3.12，FastAPI + SQLModel；运行目录为 backend：

```powershell
..\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8007
..\.venv\Scripts\python.exe -m pytest tests
```

根目录 install.ps1 安装依赖；start.ps1 构建检查后启动。所有工程接口共用 ProjectDep，不要新增跳过 owner_id 检查的工程子资源。不要在内存中复用全局 ProjectService。

原模板未使用的路由、迁移和邮件代码已归档至 upstream/inactive-backend。新版路由仅 accounts、projects、workspace，参见 app/main.py。

