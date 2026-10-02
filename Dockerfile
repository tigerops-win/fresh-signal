FROM python:3.12-slim
WORKDIR /app
COPY server.py ./server.py
COPY data/ ./data/
EXPOSE 8000
CMD ["python", "server.py"]
