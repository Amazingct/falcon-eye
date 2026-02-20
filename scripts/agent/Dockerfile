FROM python:3.11-slim
WORKDIR /app
RUN pip install --no-cache-dir openai anthropic python-telegram-bot httpx fastapi uvicorn
COPY . .
CMD ["python", "main.py"]
