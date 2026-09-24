"""Conservative daily-page recognition from the user's recorded routes."""
import json
from pathlib import Path
import cv2
import numpy as np

DUNGEONS=('equipment','summon','stone','rune','relic','treasure','artifact')

def classify(names):
    has=lambda *keys: all(k in names for k in keys)
    if has('sweep_title','sweep_close'):return 'daily_sweep'
    if has('donate_title','donate_rewards'):return 'daily_donate'
    if has('relic_title','relic_list'):return 'daily_relic'
    for key in DUNGEONS:
        if has('room_'+key,'d_close'):return 'daily_room_'+key
    if 'pass_title' in names:
        for key in ('ad','keys','gear'):
            if 'pass_'+key in names:return 'daily_pass_'+key
    if has('shop_title','shop_tab'):return 'daily_shop'
    if has('guild_dungeon_rank','guild_fight') and any('guild_count_'+str(n) in names for n in range(4)):
        return 'daily_guild_dungeon'
    if has('raid_detail','raid_table'):return 'daily_raid_detail'
    if has('raid_title','raid_center'):return 'daily_raid_map'
    if has('guild_title','guild_tabs'):
        if 'guild_menu' in names:return 'daily_guild_menu'
        if 'guild_battle' in names:return 'daily_guild_battle'
    if has('dungeon_title','dungeon_tab') and any('card_'+key in names for key in DUNGEONS):return 'daily_dungeons'
    # Battle/result recognition is only actionable inside an entered combat route.
    if 'battle_result' in names:return 'daily_result'
    if has('battle_clear','battle_leave'):return 'daily_clear'
    if has('battle_skip','battle_auto') or 'raid_skip' in names:return 'daily_battle'
    return None

class DailyVision:
    def __init__(self,assets):
        p=Path(assets)
        self.specs=json.loads((p/'daily_templates.json').read_text(encoding='utf-8'))
        atlas=cv2.imdecode(np.fromfile(p/'daily_atlas.png',np.uint8),cv2.IMREAD_COLOR)
        if atlas is None:raise ValueError('일일 작업 인식 이미지가 없습니다.')
        self.templates={}
        for name,s in self.specs.items():
            x,y,r,b=s['tile'];color=atlas[y:b,x:r].copy()
            gray=cv2.cvtColor(color,cv2.COLOR_BGR2GRAY)
            self.templates[name]=(color,gray)

    def recognize(self,im):
        from vision import Match
        gray=cv2.cvtColor(im,cv2.COLOR_BGR2GRAY);found={};groups={}
        for name,s in self.specs.items():
            color,t=self.templates[name];h,w=t.shape
            x,y,r,b=s.get('search',s['box']);x=max(0,x-7);y=max(0,y-7);r=min(960,r+7);b=min(540,b+7)
            roi=gray[y:b,x:r]
            if roi.shape[0]<h or roi.shape[1]<w:continue
            _,score,_,loc=cv2.minMaxLoc(cv2.matchTemplate(roi,t,cv2.TM_CCOEFF_NORMED))
            xx,yy=x+loc[0],y+loc[1];patch=im[yy:yy+h,xx:xx+w];pg=gray[yy:yy+h,xx:xx+w]
            error=float(np.abs(patch.astype(float)-color.astype(float)).mean())
            light=float(pg.mean()/max(1,t.mean()));contrast=float(pg.std()/max(1,t.std()))
            # Numeric/button competition happens before acceptance. Two numerators
            # never count as the same state, even when most of the label matches.
            quality=float(score)-min(error,100)/500
            good=score>=s['threshold'] and .65<=contrast<=1.65 and .72<=light<=1.50
            if s.get('strict',True):good=good and error<=18
            result=(quality,good,Match('daily_'+s.get('alias',name),float(score),error,(xx+w/2,yy+h/2)))
            if s.get('group'):groups.setdefault(s['group'],[]).append(result)
            elif good:found[s.get('alias',name)]=result[2]
        for group,items in groups.items():
            canonical={}
            for item in items:
                name=item[2].name
                if name not in canonical or item[0]>canonical[name][0]:canonical[name]=item
            items=list(canonical.values())
            items.sort(key=lambda i:i[0],reverse=True)
            if items[0][1] and (len(items)==1 or items[0][0]-items[1][0]>=.025):
                match=items[0][2];found[match.name[6:]]=match
        return classify(found),{'daily_'+key:value for key,value in found.items()}
