# Fluff and Fold Clothes Inc

基于 FastAPI 的 Python 后端项目骨架。

## 项目结构

```text
app/
├── api/
│   ├── routes/
│   │   └── health.py
│   └── router.py
├── core/
│   └── config.py
└── main.py
tests/
└── test_health.py
```

## 本地运行

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
uvicorn app.main:app --reload
```

启动后可访问：

- API 文档：<http://127.0.0.1:8000/docs>
- 健康检查：<http://127.0.0.1:8000/api/v1/health>

## 运行测试

```powershell
pytest
```

