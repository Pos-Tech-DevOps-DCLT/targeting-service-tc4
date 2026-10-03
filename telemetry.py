"""
Instrumentação OpenTelemetry padronizada do ToggleMaster (Fase 4).

Arquivo IDÊNTICO nos 3 serviços Python (flag, targeting, analytics) — se
alterar aqui, replique nos outros.

Envia traces, métricas e logs via OTLP/HTTP para o OTel Collector do cluster,
que roteia para APM (traces), Prometheus (métricas) e Loki (logs).

Configuração 100% por variáveis de ambiente padrão do OTel (definidas no
ConfigMap/Deployment do chart, em infra-tc4):
  OTEL_SERVICE_NAME, OTEL_EXPORTER_OTLP_ENDPOINT, OTEL_RESOURCE_ATTRIBUTES...

Sem OTEL_EXPORTER_OTLP_ENDPOINT definido (dev local, testes unitários) nada
é instrumentado e o serviço roda exatamente como antes.

Por que não usar só `opentelemetry-instrument gunicorn ...`? O gunicorn faz
fork dos workers depois que o agente inicializa o SDK no processo master:
os workers herdariam o mesmo service.instance.id e as métricas de cada um
colidiriam no Prometheus. Por isso o SDK é iniciado por worker, no hook
post_fork (ver gunicorn.conf.py), com o PID no service.instance.id.
"""
import importlib.util
import logging
import os
import socket

log = logging.getLogger(__name__)

_tracer_provider = None
_meter_provider = None
_logger_provider = None


def _enabled():
    if os.getenv("OTEL_SDK_DISABLED", "false").lower() == "true":
        return False
    return bool(os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"))


def _has(module):
    return importlib.util.find_spec(module) is not None


def setup_telemetry():
    """Inicializa providers + auto-instrumentação. Chamar ANTES de importar o app."""
    global _tracer_provider, _meter_provider, _logger_provider
    if _tracer_provider is not None or not _enabled():
        return

    from opentelemetry import metrics, trace
    from opentelemetry._logs import set_logger_provider
    from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
    from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk._logs import LoggerProvider
    from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    # Resource.create já incorpora OTEL_SERVICE_NAME e OTEL_RESOURCE_ATTRIBUTES.
    pod = os.getenv("K8S_POD_NAME", socket.gethostname())
    resource = Resource.create({"service.instance.id": f"{pod}-{os.getpid()}"})

    # Exporters leem endpoint/protocolo/headers das env vars OTEL_EXPORTER_OTLP_*.
    _tracer_provider = TracerProvider(resource=resource)
    _tracer_provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(_tracer_provider)

    _meter_provider = MeterProvider(
        resource=resource,
        metric_readers=[PeriodicExportingMetricReader(OTLPMetricExporter())],
    )
    metrics.set_meter_provider(_meter_provider)

    _logger_provider = LoggerProvider(resource=resource)
    _logger_provider.add_log_record_processor(BatchLogRecordProcessor(OTLPLogExporter()))
    set_logger_provider(_logger_provider)

    _instrument_libraries()
    log.info("OpenTelemetry inicializado (pid %s)", os.getpid())


def _instrument_libraries():
    """Auto-instrumenta só as bibliotecas que o serviço de fato usa."""
    from opentelemetry.instrumentation.flask import FlaskInstrumentor

    # /health é chamado pelos probes do k8s a cada 10-15s: só gera ruído.
    FlaskInstrumentor().instrument(excluded_urls="health")

    if _has("requests") and _has("opentelemetry.instrumentation.requests"):
        from opentelemetry.instrumentation.requests import RequestsInstrumentor
        RequestsInstrumentor().instrument()

    if _has("psycopg2") and _has("opentelemetry.instrumentation.psycopg2"):
        from opentelemetry.instrumentation.psycopg2 import Psycopg2Instrumentor
        # skip_dep_check: o pacote instalado é o psycopg2-binary.
        Psycopg2Instrumentor().instrument(skip_dep_check=True)

    if _has("botocore") and _has("opentelemetry.instrumentation.botocore"):
        from opentelemetry.instrumentation.botocore import BotocoreInstrumentor
        BotocoreInstrumentor().instrument()


def attach_log_handler():
    """
    Envia os logs do `logging` também via OTLP (com trace_id/span_id de
    correlação). Chamar DEPOIS de importar o app: o logging.basicConfig do
    app.py só configura o stdout se o root logger ainda não tiver handlers.
    """
    if _logger_provider is None:
        return
    from opentelemetry.sdk._logs import LoggingHandler

    handler = LoggingHandler(level=logging.INFO, logger_provider=_logger_provider)
    logging.getLogger().addHandler(handler)
    # Logs do próprio gunicorn (boot, timeouts de worker) não propagam ao root.
    logging.getLogger("gunicorn.error").addHandler(handler)


def shutdown_telemetry():
    """Faz flush do que estiver em buffer antes do worker sair."""
    for provider in (_tracer_provider, _meter_provider, _logger_provider):
        if provider is not None:
            provider.shutdown()
