"""Recognition failures pause work temporarily without settling input outcomes."""
from datetime import datetime
import math
import time

RECHECK_SECONDS=300

def recognition_hold(entry,*,now=None):
    deadline=entry.get('retry_after')
    if deadline is None:
        try:
            stamp=datetime.fromisoformat(entry['updated_at'])
            if stamp.tzinfo is None:return True
            deadline=stamp.timestamp()+RECHECK_SECONDS
        except (KeyError,ValueError,TypeError):return True
    if type(deadline) not in (int,float) or not math.isfinite(deadline):return True
    return (time.time() if now is None else now)<deadline
