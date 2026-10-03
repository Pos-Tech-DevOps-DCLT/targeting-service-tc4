# ── Estágio de build ────────────────────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# ── Estágio final ────────────────────────────────────────────────────────────
FROM python:3.11-slim

WORKDIR /app

COPY --from=builder /root/.local /root/.local
# telemetry.py + gunicorn.conf.py: instrumentacao OpenTelemetry (Fase 4)
COPY app.py telemetry.py gunicorn.conf.py ./

ENV PATH=/root/.local/bin:$PATH

RUN addgroup --system appgroup && adduser --system --ingroup appgroup appuser
USER appuser

EXPOSE 8003

CMD ["gunicorn", "--bind", "0.0.0.0:8003", "--workers", "2", "app:app"]
