FROM python:3.11-slim
WORKDIR /app
RUN pip install --no-cache-dir langgraph langchain-anthropic langchain-openai python-telegram-bot httpx fastapi uvicorn pydantic
COPY . .
CMD ["python", "main.py"]
