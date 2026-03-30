"""
API 启动入口
运行: python run_api.py
"""
import uvicorn
import sys
from pathlib import Path

# 确保项目根目录在 Python 路径中
sys.path.insert(0, str(Path(__file__).parent))

if __name__ == "__main__":
    print("=" * 60)
    print("SoftDoc Pipeline - API Server")
    print("=" * 60)
    print()
    print("API 地址: http://localhost:8000")
    print("API 文档: http://localhost:8000/docs")
    print()
    print("按 Ctrl+C 停止服务器")
    print("=" * 60)

    uvicorn.run(
        "api.server:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        reload_dirs=["api", "modules"]
    )
