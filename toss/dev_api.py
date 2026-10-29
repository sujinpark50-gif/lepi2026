"""로컬 개발용 엔진 서버. npm run dev의 /api 프록시가 이 서버로 온다.

실행: python toss/dev_api.py  (Lepi 폴더의 .env에서 ANTHROPIC_API_KEY를 읽는다)
"""
import os
import sys
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "api"))

env_file = ROOT / ".env"
if env_file.exists():
    for line in env_file.read_text(encoding="utf-8").splitlines():
        key, _, value = line.partition("=")
        if key.strip() and value.strip() and not key.strip().startswith("#"):
            os.environ.setdefault(key.strip(), value.strip())

import index  # noqa: E402  (환경 변수를 읽은 뒤에 불러온다)

port = int(os.environ.get("LEPI_DEV_PORT", "8787"))
print(f"레피 엔진 개발 서버: http://127.0.0.1:{port}/api")
ThreadingHTTPServer(("127.0.0.1", port), index.handler).serve_forever()
