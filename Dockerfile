FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv

COPY pyproject.toml ./
COPY app ./app
RUN pip install --no-cache-dir .

COPY alembic.ini ./
COPY migrations ./migrations

EXPOSE 8000
# 마이그레이션 → 시연용 시드(SEED_DEMO=false면 건너뜀, 이미 있으면 그대로) → 서버.
# 배포 플랫폼이 PORT를 주면 그 포트를 쓴다.
CMD ["sh", "-c", "alembic upgrade head && if [ \"${SEED_DEMO:-true}\" = true ]; then python -m app.seed; fi && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers"]
