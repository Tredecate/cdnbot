import sys
import logging

from .config import settings


logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("cdnbot")

def debug_log(message, level: int = 1):
    if level <= settings.debug_level:
        caller = sys._getframe(1).f_code.co_name
        logger.info(f"[{caller}]: {message}")