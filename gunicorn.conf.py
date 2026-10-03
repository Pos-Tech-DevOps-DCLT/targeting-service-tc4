# Carregado automaticamente pelo gunicorn (./gunicorn.conf.py no WORKDIR).
# Os parâmetros de bind/workers continuam no CMD do Dockerfile; aqui ficam só
# os hooks que inicializam o OpenTelemetry em cada worker (ver telemetry.py).
import telemetry


def post_fork(server, worker):
    # Antes do worker importar o app: as instrumentações precisam estar
    # ativas quando Flask/psycopg2/boto3 forem carregados.
    telemetry.setup_telemetry()


def post_worker_init(worker):
    telemetry.attach_log_handler()


def worker_exit(server, worker):
    telemetry.shutdown_telemetry()
