# electionsystem/jwt_custom.py
import logging
logger = logging.getLogger(__name__)
logger.info("Loading jwt_custom.py")  # Add this to check if file is imported

def custom_payload_handler(user, token=None):
    payload = {
        'user_id': user.id,
        'username': user.username,
        'is_staff': user.is_staff,
        'is_superuser': user.is_superuser,
    }
    logger.info(f"JWT Payload for {user.username}: {payload}")
    return payload