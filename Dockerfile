# Опциональный контейнер только для gatekeeper (DSH/OpenCode остаются на хосте)
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV GATEKEEPER_HOST=0.0.0.0
ENV ENV=production
EXPOSE 8787
CMD ["python", "scripts/run_gatekeeper.py"]
