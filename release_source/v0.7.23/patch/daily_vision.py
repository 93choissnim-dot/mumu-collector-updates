"""Conservative daily-page recognition from the user's recorded routes."""
import json
from pathlib import Path
import cv2
import numpy as np

DUNGEONS=('equipment','summon','stone','rune','relic','treasure','artifact')
# Only fixed page labels establish exposure; reward buttons and counters never
# calibrate themselves (which could turn a disabled button into an active one).
EXPOSURE_ANCHORS=(('guild_title','guild_tabs'),
    ('pass_title','pass_ad'),('pass_title','pass_keys'),('pass_title','pass_gear'),
    ('dungeon_title','dungeon_tab'),('sweep_title','sweep_close'),
    ('donate_title','donate_rewards'),('relic_list','relic_close'),
    ('shop_title','shop_tab'),('guild_dungeon_rank','guild_fight'),
    ('raid_detail','raid_table'),('raid_title','raid_center'))+tuple(
    ('room_'+key,'d_close') for key in DUNGEONS)

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

    def exposure(self,located):
        candidates=[]
        for names in EXPOSURE_ANCHORS:
            if any(n not in located or located[n][0]<.94 for n in names):continue
            # The opaque ranking label is the exposure reference on the guild
            # dungeon page. Fight supplies shape context only, never its color:
            # an action button must not calibrate its own enabled state.
            references=names[:1] if names==('guild_dungeon_rank','guild_fight') else names
            # Keep the original paired reference when it fits. If animated
            # title artwork invalidates that fit, the stable close control is
            # a second independent option. Both page shapes remain required.
            reference_sets=[references]
            if len(names)==2 and names[0].startswith('room_') and names[1]=='d_close':
                reference_sets.append(('d_close',))
            for references in reference_sets:
                reference=[];observed=[]
                for name in references:
                    color=self.templates[name][0];patch=located[name][1]
                    reference.append(cv2.GaussianBlur(color,(3,3),.7)[2:-2,2:-2].reshape(-1,3))
                    observed.append(cv2.GaussianBlur(patch,(3,3),.7)[2:-2,2:-2].reshape(-1,3))
                a=np.concatenate(reference).astype(np.float32);b=np.concatenate(observed).astype(np.float32)
                if np.any(a.var(axis=0)<9):continue
                gain=np.mean((a-a.mean(0))*(b-b.mean(0)),0)/a.var(0)
                offset=b.mean(0)-gain*a.mean(0)
                error=float(np.abs(b-(gain*a+offset)).mean())
                if np.all((gain>=.85)&(gain<=1.40)) and np.all(np.abs(offset)<=45) and error<=8:
                    candidates.append((error,names,references,gain,offset))
        if not candidates:return None
        error,names,references,gain,offset=min(candidates,key=lambda c:c[0])
        return gain,offset,{'anchors':list(references),'context':list(names),'gain':gain.tolist(),'offset':offset.tolist(),'error':error}

    @staticmethod
    def count_ink(color):
        # Pale lettering over a moving gold/brown scene. Suppress chromatic
        # background pixels; do not use the background as a digit feature.
        f=color.astype(np.float32)
        return np.clip((f.min(2)-.75*f.max(2)+10)/30,0,1)

    def guild_counter(self,im,exposure,found):
        from vision import Match
        if not exposure or not {'guild_dungeon_rank','guild_fight'}<=found.keys():return
        if any('guild_count_'+str(n) in found for n in range(4)):return
        gain,offset,_=exposure
        names=['guild_count_'+str(n) for n in range(4)]+['guild_zero_after_loot']
        candidates={}
        for name in names:
            spec=self.specs[name];x,y,r,b=spec['box'];color=self.templates[name][0]
            # Keep the scan local to the known counter; compare the numerator
            # independently so a matching '/3' cannot decide the count.
            roi=im[y-3:b+3,x-3:r+3]
            observed=self.count_ink(np.clip((roi.astype(np.float32)-offset)/gain,0,255))
            template=self.count_ink(color);h,w=template.shape
            if template[:,:10].std()<.02:continue
            _,score,_,loc=cv2.minMaxLoc(cv2.matchTemplate(observed,template,cv2.TM_CCOEFF_NORMED))
            xx,yy=loc;patch=observed[yy:yy+h,xx:xx+w]
            numerator=float(cv2.matchTemplate(patch[:,:10],template[:,:10],cv2.TM_CCOEFF_NORMED)[0,0])
            quality=min(float(score),numerator)
            canonical=spec.get('alias',name)
            candidate=(quality,float(score),numerator,(x-3+xx+w/2,y-3+yy+h/2))
            if canonical not in candidates or quality>candidates[canonical][0]:candidates[canonical]=candidate
        ranked=sorted(candidates.items(),key=lambda item:item[1][0],reverse=True)
        if len(ranked)<2:return
        name,(quality,score,numerator,center)=ranked[0];margin=quality-ranked[1][1][0]
        accepted=score>=.82 and numerator>=.82 and margin>=.10
        self.diagnostics['_guild_counter_ink']={'winner':name,'score':score,'numerator':numerator,'margin':margin,'accepted':accepted}
        if accepted:found[name]=Match('daily_'+name,score,0,center)

    def recognize(self,im):
        from vision import Match
        gray=cv2.cvtColor(im,cv2.COLOR_BGR2GRAY);found={};groups={};located={}
        self.diagnostics={}
        for name,s in self.specs.items():
            color,t=self.templates[name];h,w=t.shape
            x,y,r,b=s.get('search',s['box']);x=max(0,x-7);y=max(0,y-7);r=min(960,r+7);b=min(540,b+7)
            roi=gray[y:b,x:r]
            if roi.shape[0]<h or roi.shape[1]<w:continue
            best=None
            # Carousel focus briefly scales card labels. The captured equipment
            # reference was selected; settled cards are about 5 percent larger.
            for scale in ((.95,1.,1.05) if name.startswith('card_') or name=='donate_50' else (1.,)):
                needle=cv2.resize(t,None,fx=scale,fy=scale) if scale!=1 else t
                hh,ww=needle.shape
                if roi.shape[0]<hh or roi.shape[1]<ww:continue
                _,score,_,loc=cv2.minMaxLoc(cv2.matchTemplate(roi,needle,cv2.TM_CCOEFF_NORMED))
                if best is None or score>best[0]:best=(float(score),loc,ww,hh)
            if best is None:continue
            score,loc,ww,hh=best;xx,yy=x+loc[0],y+loc[1];patch=im[yy:yy+hh,xx:xx+ww]
            if (ww,hh)!=(w,h):patch=cv2.resize(patch,(w,h))
            located[name]=(score,patch,xx,yy,ww,hh)
        exposure=self.exposure(located)
        self.diagnostics['_exposure']=exposure[2] if exposure else {'anchors':[]}
        for name,(score,patch,xx,yy,ww,hh) in located.items():
            s=self.specs[name];color,t=self.templates[name];h,w=t.shape
            raw_error=float(np.abs(patch.astype(float)-color.astype(float)).mean())
            if exposure:
                patch=np.clip((patch.astype(np.float32)-exposure[1])/exposure[0],0,255).astype(np.uint8)
            pg=cv2.cvtColor(patch,cv2.COLOR_BGR2GRAY)
            error=float(np.abs(patch.astype(float)-color.astype(float)).mean())
            light=float(pg.mean()/max(1,t.mean()));contrast=float(pg.std()/max(1,t.std()))
            # Numeric/button competition happens before acceptance. Two numerators
            # never count as the same state, even when most of the label matches.
            quality=float(score)-min(error,100)/500
            good=score>=s['threshold'] and .65<=contrast<=1.65 and .72<=light<=1.50
            if s.get('strict',True):good=good and error<=18
            self.diagnostics[name]={'score':float(score),'raw_mae':raw_error,'mae':error,
                'light':light,'contrast':contrast,'accepted':bool(good)}
            result=(quality,good,Match('daily_'+s.get('alias',name),float(score),error,(xx+ww/2,yy+hh/2)))
            if s.get('group'):groups.setdefault(s['group'],[]).append(result)
            elif good:found[s.get('alias',name)]=result[2]
        for group,items in groups.items():
            canonical={}
            for item in items:
                name=item[2].name
                if name not in canonical or item[0]>canonical[name][0]:canonical[name]=item
            items=list(canonical.values())
            items.sort(key=lambda i:i[0],reverse=True)
            self.diagnostics['_group_'+group]={'winner':items[0][2].name,
                'margin':items[0][0]-items[1][0] if len(items)>1 else None}
            if items[0][1] and (len(items)==1 or items[0][0]-items[1][0]>=.025):
                match=items[0][2];found[match.name[6:]]=match
        self.guild_counter(im,exposure,found)
        return classify(found),{'daily_'+key:value for key,value in found.items()}
