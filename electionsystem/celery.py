import os
from celery import Celery

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'electionsystem.settings')
app = Celery('electionsystem')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()