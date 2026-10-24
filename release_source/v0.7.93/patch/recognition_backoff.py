"""Recognition failures pause work temporarily without settling input outcomes."""
from datetime import datetime
import math
import time

RECHECK_SECONDS=300

def recognition_hold(entry,*,now=None):
    # Invalid cooldown metadata cannot make recognition-only holds permanent.
    # Input uncertainty is checked separately and is never resolved here.
    deadline=entry.get('retry_after')
    if deadline is None:
        try:
            stamp=datetime.fromisoformat(entry['updated_at'])
            if stamp.tzinfo is None:return False
            deadline=stamp.timestamp()+RECHECK_SECONDS
        except (KeyError,ValueError,TypeError):return False
    if type(deadline) not in (int,float) or not math.isfinite(deadline):return False
    return (time.time() if now is None else now)<deadline
