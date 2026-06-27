"""Celery application.

A4 decouples the (slow) audit work from the HTTP request: ``POST /audits``
enqueues a task and returns immediately; a worker processes it and writes the
result to the DB, which the client polls via ``GET /audits/{id}``.

A broker is optional. When ``CELERY_TASK_ALWAYS_EAGER`` is true (the default),
tasks run inline in the calling process — so the app works with no Redis at all
(tests, simple single-process deploys). Compose/prod set it false and run
``celery -A api.celery_app worker``.
"""

from celery import Celery

from .config import settings

celery_app = Celery(
    "geo_audit",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["api.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_always_eager=settings.celery_eager,
    # The task records its outcome in the DB (status column), not via Celery's
    # result backend — so ignore results entirely. This also means eager runs
    # never touch the broker/backend (no Redis needed for inline execution).
    task_ignore_result=True,
    task_eager_propagates=False,
    timezone="UTC",
)
