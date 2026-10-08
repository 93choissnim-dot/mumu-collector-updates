"""One migration retry of affected free requests; never infer past success."""
import re
from datetime import datetime,timezone

FREE_SLOTS={'farm':{'claim'},'wood':{'claim'},'mine':{'claim'},
            'ranking':{'claim'},'excavation':{'claim'},'autumn':{'claim'},
            'worldboss':{'cerberus','kraken','void'}}

def eligible(task,slot,request,*,now=None):
    if slot not in FREE_SLOTS.get(task,()) or not isinstance(request,dict):return False
    if not isinstance(request.get('id'),str) or not request['id']:return False
    version=request.get('version')
    if not isinstance(version,str) or not re.fullmatch(r'0\.7\.\d+',version):return False
    patch=int(version.rsplit('.',1)[1])
    if not 1<=patch<70:
        if not (((patch in {77,78} and task in {'worldboss','ranking','excavation'})
                 or (patch==85 and task=='excavation'))
                and request.get('action')==slot):return False
    try:
        at=datetime.fromisoformat(request['requested_at'])
        if at.tzinfo is None:return False
        return at<=(now or datetime.now(timezone.utc))
    except (ValueError,TypeError,KeyError):return False
