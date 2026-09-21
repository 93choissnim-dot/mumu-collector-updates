"""Merge explicit profile edits without overwriting newer roster selections."""
import copy
from task_catalog import TASK_LABELS
from ui_state import selected_tasks, validate_profile


def profile_values(player):
    return {'enabled':bool(player.get('enabled')), 'minutes':float(player.get('minutes',60)),
            'selected':{task:task in selected_tasks(player) for task in TASK_LABELS},
            'restore_sleep':True,'daily_profile':player.get('daily_profile','')}


def merge_profiles(current, original, draft):
    merged=copy.deepcopy(current)
    for ident, values in draft.items():
        if ident not in current:
            raise ValueError('목록이 변경되었습니다. 설정창을 다시 열어 주세요.')
        before=profile_values(original[ident]);after=profile_values(values)
        latest=profile_values(current[ident]);result=copy.deepcopy(latest)
        def change(container,key,old,new,live):
            if new==old:return
            if live!=old and live!=new:
                raise ValueError(current[ident].get('name','뮤뮤')+': 다른 화면에서 같은 설정이 변경되었습니다. 설정창을 다시 열어 주세요.')
            container[key]=new
        for field in ('enabled','minutes','daily_profile'):
            change(result,field,before[field],after[field],latest[field])
        for task in TASK_LABELS:
            change(result['selected'],task,before['selected'][task],after['selected'][task],latest['selected'][task])
        merged[ident].update(validate_profile(result))
    return merged


def copy_settings(draft,source,targets,fields):
    fields=set(fields)&{'selected','minutes'}
    if source not in draft or not fields:raise ValueError('복사할 설정을 선택해 주세요.')
    targets=[key for key in dict.fromkeys(targets) if key in draft and key!=source]
    if not targets:raise ValueError('적용할 뮤뮤를 선택해 주세요.')
    # Includes the explicit training choice; run inclusion is never copied.
    for key in targets:
        for field in fields:draft[key][field]=copy.deepcopy(draft[source][field])
    return len(targets)
