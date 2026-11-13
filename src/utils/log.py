import reprlib
import sys
import logging

from utils import settings


logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("cdnbot")


class BytesOnlyRepr(reprlib.Repr):

  def __init__(self, max_bytes: int = 20):
    super().__init__()
    self.max_bytes = max_bytes
    # Disable container item limits so lists/dicts aren't truncated
    self.maxlist = 10**6
    self.maxdict = 10**6
    self.maxtuple = 10**6
    self.maxset = 10**6
    self.maxstring = 4000  # Leave regular strings (mostly) alone
    self.maxlevel = 50  # Allow deep nesting
    self.maxother = 10**6  # Allow other types to be fully represented

  def repr_bytes(self, x: bytes, level: int) -> str:
    if len(x) <= self.max_bytes:
      return repr(x)
    return repr(x[: self.max_bytes])[:-1] + "...'"


log_repr = BytesOnlyRepr(max_bytes=20)

def debug_log(message, level: int = 1):
    if level <= settings.debug_level:
        caller = sys._getframe(1).f_code.co_name
        formatted = log_repr.repr(message)
        logger.info(f"[{caller}]: {formatted}")