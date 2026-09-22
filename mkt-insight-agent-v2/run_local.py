"""Local development server — runs FastAPI directly without AgentBase SDK.

Usage: python run_local.py
Then: curl http://127.0.0.1:8080/health
"""
from __future__ import annotations

import uvicorn
from dotenv import load_dotenv

load_dotenv()

from app.api.server import create_app

app = create_app()

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8080, log_level="info")
