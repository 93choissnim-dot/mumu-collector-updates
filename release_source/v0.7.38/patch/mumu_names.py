"""Read MuMu's own instance names and exact ADB endpoints, never guess by order.

MuMuManager documented read-only command: info -v all.
The name field is the user-assigned emulator name, not the Android app tab.
"""
import json
import hashlib
import locale
import os
import re
from pathlib import Path
import subprocess
import time
from collections import Counter
from collector import Halt


def decode_info(raw):
    if isinstance(raw, bytes):
        preferred=locale.getpreferredencoding(False).lower()
        # Single-byte Western encodings can silently turn Korean into mojibake.
        legacy=[preferred] if preferred in ('cp949','euc-kr','gbk','gb18030','cp936') else []
        for encoding in dict.fromkeys(['utf-8-sig', 'utf-16', *legacy, 'cp949', 'gb18030']):
            try:
                value=json.loads(raw.decode(encoding));break
            except (UnicodeError,ValueError):continue
        else:raise ValueError('MuMu 이름 정보를 읽을 수 없습니다.')
    else:value=json.loads(raw) if isinstance(raw,str) else raw
    return value


def records(value):
    if isinstance(value,list):
        for child in value:yield from records(child)
    elif isinstance(value,dict):
        if "name" in value and ("index" in value or "adb_port" in value):
            yield value
        else:
            for key,child in value.items():
                if isinstance(child,dict) and str(key).isdigit():child={"index":str(key),**child}
                yield from records(child)


def parse_instances(raw):
    value=decode_info(raw)
    found={};conflicts=set()
    def walk(item):
        if isinstance(item,list):
            for child in item:walk(child)
        elif isinstance(item,dict):
            if 'name' in item and 'adb_port' in item:
                name=item['name'];host=item.get('adb_host_ip','127.0.0.1')
                try:port=int(item['adb_port'])
                except (ValueError,TypeError):return
                if (not isinstance(name,str) or not name.strip() or host not in ('127.0.0.1','localhost')
                    or not 0<port<65536 or item.get('is_process_started') is False):return
                serial='127.0.0.1:'+str(port)
                name=name.strip()
                if serial in found and found[serial]!=name:conflicts.add(serial)
                found[serial]=name
            else:
                for child in item.values():walk(child)
    walk(value)
    return {serial:name for serial,name in found.items() if serial not in conflicts}


def instance_id(path,row):
    if 'index' not in row:return None
    identity=os.path.normcase(str(path))+'#'+str(row['index'])+'#'+str(row.get('created_timestamp',''))
    return hashlib.sha256(identity.encode('utf-8')).hexdigest()[:24]


def resolve_port(path,row,stop,attempt,deadline,boot_lookup,log):
    from mumu_manager import query,connected_endpoint,boot_id,local_endpoint
    existing=local_endpoint(row.get('adb_host_ip','127.0.0.1'),row.get('adb_port'))
    if existing or row.get('is_process_started') is not True:return row
    index=str(row.get('index',''))
    if not re.fullmatch(r'\d{1,8}',index):return row
    if row.get('adb_host_ip','127.0.0.1') not in ('127.0.0.1','localhost'):return row
    log(row.get('name','뮤뮤')+' / 연결 포트 별도 확인 중')
    entry={'index':index,'status':'pending','queries':[]}
    attempt.setdefault('port_queries',[]).append(entry)
    def ask(args):
        try:return query(path,args,stop,entry['queries'],deadline,timeout=4)
        except (OSError,ValueError,TimeoutError):return b''
    # Newer MuMu/Hyper-V info can omit adb_port even for running instances.
    # This official command explicitly addresses the VM index, not ADB order.
    endpoint=connected_endpoint(ask(['adb','-v',index,'-c','connect']))
    method='instance_connect'
    if not endpoint:
        detail=ask(['info','-v',index])
        try:details=list(records(decode_info(detail)))
        except (ValueError,UnicodeError):details=[]
        matches=[r for r in details if str(r.get('index',''))==index]
        if len(matches)==1:
            current=matches[0]
            if (current.get('is_process_started') is False or
                str(current.get('created_timestamp',''))!=str(row.get('created_timestamp',''))):
                entry['status']='instance_changed_or_stopped';return row
            endpoint=local_endpoint(current.get('adb_host_ip','127.0.0.1'),current.get('adb_port'))
            method='instance_info'
    if not endpoint:
        fingerprint=boot_id(ask(['adb','-v',index,'-c','shell cat /proc/sys/kernel/random/boot_id']))
        if fingerprint:
            try:endpoint=boot_lookup.match(fingerprint)
            except (Halt,OSError,TimeoutError) as exc:
                if stop.is_set():raise
                entry['match_error']=str(exc)
            method='boot_identity'
    if endpoint:
        entry.update(status='resolved',method=method,serial=endpoint)
        log(row.get('name','뮤뮤')+' / 연결 포트 확인 완료')
        return {**row,'adb_host_ip':'127.0.0.1','adb_port':int(endpoint.split(':')[1])}
    entry['status']='port_unresolved'
    log(row.get('name','뮤뮤')+' / 이름은 확인됐지만 연결 포트를 확인하지 못했습니다.')
    return row


def read_instances(executable,stop,log,details=None,diagnostic_path=None,target_id=None,manager_path=None):
    from adb_device import mumu_locations
    from mumu_paths import related_roots, executable_candidates
    from mumu_manager import query,BootLookup
    from datetime import datetime
    if manager_path is not None and target_id is not None:
        path=Path(manager_path)
        roots=related_roots(path.parent)
        candidates=[path] if path.is_file() else []
    else:
        roots,_=mumu_locations()
        if executable:
            roots=[*related_roots(Path(executable).resolve().parent),*roots]
        roots=list(dict.fromkeys(roots))
        candidates=executable_candidates(roots,('MuMuManager.exe',))
    diagnostic={'created_at':datetime.now().astimezone().isoformat(),
        'roots':[str(p) for p in roots], 'candidates':[str(p) for p in candidates],
        'attempts':[], 'status':'checking'}
    found={};conflicts=set();identities={}
    try:
        if not candidates:
            log('뮤뮤 이름 조회 도구를 찾지 못했습니다. 설치 경로 확인 결과를 진단에 저장합니다.')
        total_deadline=time.monotonic()+60
        boot_lookup=BootLookup(executable,roots,stop,total_deadline)
        for path in candidates:
            if stop.is_set():raise Halt('사용자가 중지했습니다.')
            if time.monotonic()>=total_deadline:
                diagnostic['search_timeout']=True
                log('뮤뮤 이름 조회: 전체 확인 시간이 초과되었습니다.')
                break
            attempt={'path':str(path),'queries':[]};diagnostic['attempts'].append(attempt)
            try:
                value=decode_info(query(path,['info','-v','all'],stop,attempt['queries'],total_deadline))
                raw_rows=list(records(value))
                attempt.update(records=len(raw_rows),running=sum(r.get('is_process_started') is True for r in raw_rows),
                    missing_ports=sum('adb_port' not in r for r in raw_rows))
                if not raw_rows:attempt['response']=json.dumps(value,ensure_ascii=False)[:4000]
                rows=[]
                for row in raw_rows:
                    if target_id is not None and instance_id(path,row)!=target_id:continue
                    rows.append(resolve_port(path,row,stop,attempt,total_deadline,boot_lookup,log))
                names=parse_instances(rows)
                attempt.update(valid_names=len(names),
                    rows=[{k:r[k] for k in ('name','index','adb_port','adb_host_ip',
                        'created_timestamp','is_process_started','error_code') if k in r}
                        for r in rows[:100]])
                for row in rows:
                    try:serial='127.0.0.1:'+str(int(row.get('adb_port',0)))
                    except (ValueError,TypeError):continue
                    if serial not in names or 'index' not in row:continue
                    if row.get('is_process_started') is False:continue
                    if row.get('adb_host_ip','127.0.0.1') not in ('127.0.0.1','localhost'):continue
                    identity_fields=(str(row['index']),str(row.get('created_timestamp','')))
                    if serial in identities and identities[serial]!=identity_fields:
                        conflicts.add(serial);continue
                    identities[serial]=identity_fields
                    if details is not None and serial not in details:
                        details[serial]={'name':names[serial],'serial':serial,'instance_id':instance_id(path,row),
                                         'manager_path':str(path)}
                for serial,name in names.items():
                    if serial in found and found[serial]!=name:conflicts.add(serial)
                    found[serial]=name
                if not names:
                    log('뮤뮤 이름 조회: 연결 가능한 창 정보 없음 / '+str(path))
                elif details is not None and not any(s in details for s in names):
                    log('뮤뮤 이름 조회: 이름은 있으나 창 식별 번호가 없습니다 / '+str(path))
                else:log('뮤뮤 창 이름 확인: '+str(len(names))+'개 / '+str(path))
            except (OSError,ValueError,TimeoutError) as exc:
                attempt['error']=str(exc)
                log('뮤뮤 창 이름 확인 실패: '+str(exc)+' / '+str(path))
        result={serial:name for serial,name in found.items() if serial not in conflicts}
        if details is not None:
            for serial in list(details):
                if serial not in result:details.pop(serial)
        diagnostic.update(status='ok' if (details if details is not None else result) else
            ('manager_not_found' if not candidates else 'no_usable_instances'),
            names=len(result),identified=len(details) if details is not None else None,
            conflicts=sorted(conflicts))
        if not result:log('뮤뮤 창 이름을 확인하지 못했습니다. 진단 파일 저장으로 조회 결과를 확인할 수 있습니다.')
        return result
    except Halt:
        diagnostic['status']='cancelled';raise
    finally:
        if diagnostic_path is not None:
            target=Path(diagnostic_path);temp=target.with_suffix('.tmp')
            try:
                temp.write_text(json.dumps(diagnostic,ensure_ascii=False,indent=2),encoding='utf-8')
                temp.replace(target)
            except OSError as exc:log('뮤뮤 조회 진단 저장 실패: '+str(exc))


def name_options(devices,reports):
    """Only real, unique names are selectable; duplicate names cannot pick a wrong VM."""
    counts=Counter(reports[s].get('window_name','') for s in devices)
    return {reports[s]['window_name']:s for s in devices
            if reports[s].get('window_name') and counts[reports[s]['window_name']]==1}


def name_issues(devices,reports):
    names=[reports[s].get('window_name','') for s in devices]
    messages=[]
    if any(not n for n in names):
        messages.append('뮤뮤 창과 연결 정보를 맞추지 못했습니다. 조회 결과는 진단 파일에 저장됩니다.')
    if any(n and count>1 for n,count in Counter(names).items()):
        messages.append('같은 이름의 뮤뮤가 있습니다. 해당 창의 이름을 다르게 지정하고 다시 연결해 주세요.')
    return messages


def read_catalog(executable,stop,log,diagnostic_path=None,target_id=None,manager_path=None):
    details={}
    read_instances(executable,stop,log,details,diagnostic_path,target_id,manager_path)
    return details


class CatalogLookup:
    """Cache only manager locations; query live identity and endpoint every time."""
    def __init__(self):self.paths={}
    def read(self,executable,stop,log,ident):
        hint=self.paths.get(ident)
        if hint:
            current=read_catalog(executable,stop,log,target_id=ident,manager_path=hint)
            matches=[p for p in current.values() if p.get('instance_id')==ident]
            if len(matches)==1:return current
            self.paths.pop(ident,None)
        current=read_catalog(executable,stop,log,target_id=ident)
        matches=[p for p in current.values() if p.get('instance_id')==ident]
        if len(matches)==1 and matches[0].get('manager_path'):
            self.paths[ident]=matches[0]['manager_path']
        return current
