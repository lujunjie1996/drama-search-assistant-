#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
if [ ! -f .env ]; then
  cp .env.example .env
  echo "已创建 .env，请编辑 API_KEY 和 ALLOWED_DOWNLOAD_HOSTS 后重新运行。"
  ${EDITOR:-nano} .env
fi
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
echo "启动后打开 http://127.0.0.1:8000/"
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
