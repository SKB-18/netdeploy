"""Celery application initialization."""

from celery import Celery
from core.config import settings

celery_app = Celery(
    "netdeploy",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=["tasks.deployment"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_routes={
        "tasks.deployment.deploy_to_device": {"queue": "deploy"},
        "tasks.deployment.rollback_device": {"queue": "rollback"},
        "tasks.deployment.sync_device_state": {"queue": "sync"},
    },
)
