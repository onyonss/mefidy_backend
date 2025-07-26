from celery import shared_task
from django.utils import timezone
from electionapp.models import Election
import logging

logger = logging.getLogger(__name__)

@shared_task
def close_expired_elections():
    now = timezone.now()
    closed_count = Election.objects.filter(enddate__lt=now, statut="ouvert").update(statut="ferme")
    logger.info(f"[DEBUG] {now}: Closed {closed_count} elections")