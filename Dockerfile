# ── Estágio de build ────────────────────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# ── Estágio final ────────────────────────────────────────────────────────────
FROM python:3.11-slim

WORKDIR /app

# Usuário não-root com HOME próprio: os pacotes do pip --user precisam ficar
# num diretório legível pelo appuser (/root não é). Mesmo padrão do
# flag-service e da imagem publicada b30409b-fix2 (correção que estava só no ECR).
RUN addgroup --system appgroup && adduser --system --ingroup appgroup --home /home/appuser appuser

COPY --from=builder --chown=appuser:appgroup /root/.local /home/appuser/.local
# telemetry.py + gunicorn.conf.py: instrumentacao OpenTelemetry (Fase 4)
COPY --chown=appuser:appgroup app.py telemetry.py gunicorn.conf.py ./

ENV HOME=/home/appuser
ENV PATH=/home/appuser/.local/bin:$PATH

USER appuser

EXPOSE 8003

# Roda com gunicorn em produção
CMD ["gunicorn", "--bind", "0.0.0.0:8003", "--workers", "2", "app:app"]
