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
    ('raid_detail','raid_table'),('raid_title','raid_center'),
    ('shop_confirm_title','shop_confirm_close'))+tuple(
    ('room_'+key,'d_close') for key in DUNGEONS)

def classify(names):
    has=lambda *keys: all(k in names for k in keys)
    if has('pass_purchase_gear_context','pass_gear_purchase'):return 'daily_pass_gear'
    if has('shop_confirm_title','shop_confirm_item','shop_confirm_close'):return 'daily_shop_confirm'
    if has('sweep_title','sweep_close'):return 'daily_sweep'
    if has('donate_title','donate_rewards'):return 'daily_donate'
    if has('relic_title','relic_list'):return 'daily_relic'
    for key in DUNGEONS:
        if has('room_'+key,'d_close'):return 'daily_room_'+key
    if 'pass_title' in names:
        for key in ('ad','keys','gear'):
            if 'pass_'+key in names:return 'daily_pass_'+key
    if has('shop_title','shop_tab'):return 'daily_shop'
    # Stable page controls identify the page; the changing counter is checked
    # separately (and again before a fight), never used as page identity.
    if has('guild_dungeon_rank','guild_fight'):
        return 'daily_guild_dungeon'
    # Both workshop labels are generic '공방' crops: names rotate weekly.
    # Map label search is confined to the middle banner; detail is header-only.
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
        from pass_purchase import PassPurchaseVision
        self.pass_purchase=PassPurchaseVision(p)
        self.specs=json.loads((p/'daily_templates.json').read_text(encoding='utf-8'))
        atlas=cv2.imdecode(np.fromfile(p/'daily_atlas.png',np.uint8),cv2.IMREAD_COLOR)
        if atlas is None:raise ValueError('일일 작업 인식 이미지가 없습니다.')
        combat=cv2.imdecode(np.fromfile(p/'combat_controls.png',np.uint8),cv2.IMREAD_COLOR)
        if combat is None:raise ValueError('전투 종료 인식 이미지가 없습니다.')
        guild_confirm=cv2.imdecode(np.fromfile(p/'guild_confirm.png',np.uint8),cv2.IMREAD_COLOR)
        if guild_confirm is None:raise ValueError('길드 무료 구매 확인 이미지가 없습니다.')
        raid_controls=cv2.imdecode(np.fromfile(p/'raid_native_controls.png',np.uint8),cv2.IMREAD_COLOR)
        if raid_controls is None:raise ValueError('공방 인식 이미지가 없습니다.')
        dungeon_controls=cv2.imdecode(np.fromfile(p/'dungeon_native_controls.png',np.uint8),cv2.IMREAD_COLOR)
        if dungeon_controls is None:raise ValueError('던전 입장 인식 이미지가 없습니다.')
        atlases={'combat_controls':combat,'guild_confirm':guild_confirm,'raid_native_controls':raid_controls,
                 'dungeon_native_controls':dungeon_controls}
        self.templates={};self.scaled={};self.reference_stats={}
        # Locate modal identities before any broad carousel search.
        self.search_order=[n for n in self.specs if not n.startswith('card_')]+[n for n in self.specs if n.startswith('card_')]
        for name in self.search_order:
            s=self.specs[name]
            x,y,r,b=s['tile'];color=atlases.get(s.get('atlas'),atlas)[y:b,x:r].copy()
            gray=cv2.cvtColor(color,cv2.COLOR_BGR2GRAY)
            self.templates[name]=(color,gray)
            scales=(.95,1.,1.05) if name.startswith('card_') or name=='donate_50' else (1.,)
            self.scaled[name]=tuple(cv2.resize(gray,None,fx=s,fy=s) if s!=1 else gray for s in scales)
            if s.get('blur'):
                self.scaled[name]=tuple(cv2.GaussianBlur(t,(3,3),.7) for t in self.scaled[name])
            self.reference_stats[name]=(max(1,gray.mean()),max(1,gray.std()),color.astype(float))
        # Share only label shapes across recorded rasterization variants.
        # Each control retains its own strict color/contrast reference and
        # competition, including enabled/disabled relic controls.
        for name,s in self.specs.items():
            for variant in s.get('shape_variants',[]):
                gray=self.templates[variant][1]
                if s.get('blur'):gray=cv2.GaussianBlur(gray,(3,3),.7)
                self.scaled[name]+= (gray,)

    def exposure(self,located):
        candidates=[]
        for names in EXPOSURE_ANCHORS:
            # Native downsampling softens small titles. A pass title may use
            # its existing identity threshold only beside an independently
            # strong membership heading; paired color fitting stays bounded.
            if any(n not in located or located[n][0] < (
                    self.specs[n]['threshold'] if (
                        names==('guild_dungeon_rank','guild_fight') and n=='guild_fight' or
                        names==('raid_detail','raid_table') and n=='raid_detail' or
                        names[0]=='pass_title' and n=='pass_title')
                    else .94) for n in names):continue
            # The opaque ranking label is the exposure reference on the guild
            # dungeon page. Fight supplies shape context only, never its color:
            # an action button must not calibrate its own enabled state.
            references=names[:1] if names==('guild_dungeon_rank','guild_fight') else (
                ('raid_table',) if names==('raid_detail','raid_table') else names)
            # Keep the original paired reference when it fits. If animated
            # title artwork invalidates that fit, the stable close control is
            # a second independent option. Both page shapes remain required.
            reference_sets=[references]
            if len(names)==2 and names[0].startswith('room_') and names[1]=='d_close':
                reference_sets.append(('d_close',))
            for references in reference_sets:
                from recognition_common import fit_exposure
                # Compare exposure at the same spatial frequency used for these
                # labels' shape check; resampling must not look like a color cast.
                smooth=lambda n,im:cv2.GaussianBlur(im,(3,3),.7) if self.specs[n].get('blur') else im
                gain,offset,error,variance=fit_exposure([smooth(n,self.templates[n][0]) for n in references],
                                                       [smooth(n,located[n][1]) for n in references])
                if np.any(variance<9):continue
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
        names=[n for n,s in self.specs.items() if s.get('alias',n) in {'guild_count_'+str(i) for i in range(4)}]
        normalized=np.clip((im.astype(np.float32)-offset)/gain,0,255).astype(np.uint8)
        def strokes(color):
            # White letter strokes are locally brighter than the moving scene.
            # A small top-hat removes smooth background variation without storing
            # any new diagnostic-image reference.
            gray=cv2.cvtColor(color,cv2.COLOR_BGR2GRAY)
            return cv2.morphologyEx(gray,cv2.MORPH_TOPHAT,np.ones((5,5),np.uint8)).astype(np.float32)
        for method,transform,threshold,digit_threshold,min_margin in (
                ('ink',self.count_ink,.82,.82,.10),('strokes',strokes,.88,.90,.12)):
            candidates={}
            for name in names:
                spec=self.specs[name];x,y,r,b=spec['box'];color=self.templates[name][0]
                observed=transform(normalized[y-3:b+3,x-3:r+3]);template=transform(color)
                h,w=template.shape
                if template[:,:10].std()<.02:continue
                _,score,_,loc=cv2.minMaxLoc(cv2.matchTemplate(observed,template,cv2.TM_CCOEFF_NORMED))
                xx,yy=loc;patch=observed[yy:yy+h,xx:xx+w]
                numerator=float(cv2.matchTemplate(patch[:,:10],template[:,:10],cv2.TM_CCOEFF_NORMED)[0,0])
                quality=min(float(score),numerator);canonical=spec.get('alias',name)
                candidate=(quality,float(score),numerator,(x-3+xx+w/2,y-3+yy+h/2))
                if canonical not in candidates or quality>candidates[canonical][0]:candidates[canonical]=candidate
            ranked=sorted(candidates.items(),key=lambda item:item[1][0],reverse=True)
            if len(ranked)<2:continue
            name,(quality,score,numerator,center)=ranked[0];margin=quality-ranked[1][1][0]
            accepted=score>=threshold and numerator>=digit_threshold and margin>=min_margin
            self.diagnostics['_guild_counter_'+method]={'winner':name,'score':score,'numerator':numerator,'margin':margin,'accepted':accepted}
            if accepted:
                found[name]=Match('daily_'+name,score,0,center);return

    def guild_loot_counter(self,im,exposure,found):
        from vision import Match
        names=('guild_loot_zero','guild_loot_10','guild_loot_20','guild_loot_30')
        if not exposure or not {'guild_dungeon_rank','guild_fight'}<=found.keys():return
        if any(n in found for n in names):return
        gain,offset,_=exposure
        normalized=np.clip((im.astype(np.float32)-offset)/gain,0,255).astype(np.uint8)
        def strokes(color):
            gray=cv2.cvtColor(color,cv2.COLOR_BGR2GRAY)
            return cv2.morphologyEx(gray,cv2.MORPH_TOPHAT,np.ones((5,5),np.uint8)).astype(np.float32)
        candidates=[]
        for name in names:
            x,y,r,b=self.specs[name]['box'];template=strokes(self.templates[name][0])
            observed=strokes(normalized[y-3:b+3,x-3:r+3]);h,w=template.shape
            _,score,_,loc=cv2.minMaxLoc(cv2.matchTemplate(observed,template,cv2.TM_CCOEFF_NORMED))
            xx,yy=loc;patch=observed[yy:yy+h,xx:xx+w]
            # Compare the complete x0/x10/x20/x30 suffix independently. The
            # shared Korean label or a trailing zero cannot establish a count.
            number=float(cv2.matchTemplate(patch[:,36:],template[:,36:],cv2.TM_CCOEFF_NORMED)[0,0])
            candidates.append((min(float(score),number),name,float(score),number,(x-3+xx+w/2,y-3+yy+h/2)))
        candidates.sort(reverse=True)
        quality,name,score,number,center=candidates[0];margin=quality-candidates[1][0]
        accepted=score>=.90 and number>=.90 and margin>=.12
        self.diagnostics['_guild_loot_strokes']={'winner':name,'score':score,'number':number,'margin':margin,'accepted':accepted}
        if accepted:found[name]=Match('daily_'+name,score,0,center)

    def recognize(self,im):
        from vision import Match
        gray=cv2.cvtColor(im,cv2.COLOR_BGR2GRAY);found={};groups={};located={}
        blurred=cv2.GaussianBlur(gray,(3,3),.7)
        self.diagnostics={}
        shaped=lambda n:n in located and located[n][0]>=self.specs[n]['threshold']
        for name in self.search_order:
            s=self.specs[name]
            # Rasterization references supply shapes only. They cannot emit a
            # match or replace the original control's calibrated enabled color.
            if s.get('reference_only'):continue
            # A card can only establish a dungeon-list page together with both
            # list labels. Do not run seven wide three-scale searches elsewhere.
            if name.startswith('card_'):
                covered=any(shaped('room_'+k) and shaped('d_close') for k in DUNGEONS) or (
                    shaped('sweep_title') and shaped('sweep_close'))
                if covered or not all(shaped(n) for n in ('dungeon_title','dungeon_tab')):
                    self.diagnostics[name]={'accepted':False,'rejection':'page_context'}
                    continue
            color,t=self.templates[name];h,w=t.shape
            x,y,r,b=s.get('search',s['box']);x=max(0,x-7);y=max(0,y-7);r=min(960,r+7);b=min(540,b+7)
            roi=(blurred if s.get('blur') else gray)[y:b,x:r]
            if roi.shape[0]<h or roi.shape[1]<w:continue
            best=None
            # Carousel focus briefly scales card labels. The captured equipment
            # reference was selected; settled cards are about 5 percent larger.
            for needle in self.scaled[name]:
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
            reference_mean,reference_std,reference_color=self.reference_stats[name]
            raw_error=float(np.abs(patch.astype(float)-reference_color).mean())
            raw_color=patch.astype(float).mean(axis=(0,1))
            if exposure:
                patch=np.clip((patch.astype(np.float32)-exposure[1])/exposure[0],0,255).astype(np.uint8)
            pg=cv2.cvtColor(patch,cv2.COLOR_BGR2GRAY)
            error=float(np.abs(patch.astype(float)-reference_color).mean())
            light=float(pg.mean()/reference_mean);contrast=float(pg.std()/reference_std)
            # Numeric/button competition happens before acceptance. Two numerators
            # never count as the same state, even when most of the label matches.
            quality=float(score)-min(error,100)/500
            # The translucent auto-skill label brightens over the moving battle
            # scene. It supplies context only: SKIP retains its input threshold,
            # and both independent shapes are still required for daily_battle.
            max_light=1.65 if name=='battle_auto' else 1.50
            good=score>=s['threshold'] and .65<=contrast<=1.65 and .72<=light<=max_light
            if s.get('strict',True):good=good and error<=18
            if name=='raid_fight':
                # Graying a disabled control preserves its label and can pass
                # an averaged RGB error. Require each calibrated color channel.
                good=good and bool(np.all(np.abs(patch.astype(float)-reference_color).mean(axis=(0,1))<=18))
            if name=='d_enter':
                # The enabled entry surface has a blue tint even in the old
                # reference. A grayscale disabled button retains its shape and
                # may pass averaged RGB error. Check original pixels so page
                # exposure cannot manufacture that tint; keep strict MAE above.
                reference_tint=float((reference_color[:,:,0]-reference_color[:,:,2]).mean())
                good=good and raw_color[0]-raw_color[2]>=reference_tint*.5
            self.diagnostics[name]={'score':float(score),'raw_mae':raw_error,'mae':error,
                'light':light,'contrast':contrast,'accepted':bool(good)}
            result=(quality,good,Match('daily_'+s.get('alias',name),float(score),error,(xx+ww/2,yy+hh/2)))
            if s.get('group'):groups.setdefault(s['group'],[]).append(result)
            elif good:found[s.get('alias',name)]=result[2]
        for group,items in groups.items():
            canonical={}
            for item in items:
                name=item[2].name
                # A rejected color variant must not hide a fully verified
                # variant of the same number. Different numbers still compete
                # below, including rejected candidates, to reject ambiguity.
                if name not in canonical or (item[1],item[0])>(canonical[name][1],canonical[name][0]):
                    canonical[name]=item
            items=list(canonical.values())
            items.sort(key=lambda i:i[0],reverse=True)
            self.diagnostics['_group_'+group]={'winner':items[0][2].name,
                'margin':items[0][0]-items[1][0] if len(items)>1 else None}
            if items[0][1] and (len(items)==1 or items[0][0]-items[1][0]>=.025):
                match=items[0][2];found[match.name[6:]]=match
        self.guild_counter(im,exposure,found)
        self.guild_loot_counter(im,exposure,found)
        self.pass_purchase.recognize(im,found)
        return classify(found),{'daily_'+key:value for key,value in found.items()}
