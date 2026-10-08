"""Free summons/store controls from recorded game UI; no OCR or guessed inputs."""
import json
from pathlib import Path
import cv2
import numpy as np

PAGES={'free_summon_'+k for k in ('character','skill','pet')}|{'free_summon_'+stage+'_'+k for stage in ('result','reveal') for k in ('character','skill','pet')}|{'free_store','free_store_dialog'}|{'free_store_confirm_'+k for k in ('ruby','ruby_ad','cube_ad')}

class FreeDailyVision:
    def __init__(self,assets):
        p=Path(assets);self.specs=json.loads((p/'free_daily_controls.json').read_text())
        atlas=cv2.imdecode(np.fromfile(p/'free_daily_controls.png',np.uint8),1)
        self.refs={k:atlas[s['tile'][1]:s['tile'][3],s['tile'][0]:s['tile'][2]] for k,s in self.specs.items()}
        self.gray={k:cv2.cvtColor(v,cv2.COLOR_BGR2GRAY) for k,v in self.refs.items()}
        import base64
        variants_path=p/'native_shop_variants.json'
        native=json.loads(variants_path.read_text())['free'] if variants_path.exists() else {}
        self.scaled={}
        for key,ref in self.gray.items():
            scales=((1.,.94,1.06) if key.startswith('modal_') else
                    (1.,.97,1.03) if key=='result_reveal' or key.startswith('result_ticket_') else (1.,))
            variants=[]
            for scale in scales:
                t=cv2.resize(ref,None,fx=scale,fy=scale) if scale!=1 else ref
                q=t.astype(float);mean=q.mean()
                variants.append((t,q-mean,max(mean,1)))
            for encoded in native.get(key,[]):
                t=cv2.imdecode(np.frombuffer(base64.b64decode(encoded),np.uint8),0)
                q=t.astype(float);mean=q.mean()
                variants.append((t,q-mean,max(mean,1)))
            self.scaled[key]=tuple(variants)
        # Combat-power toasts cover the gem's middle, not its lower silhouette.
        # Keep the exact title/X/literal-free gates and the same matching limits.
        for key,height in (('modal_ruby_item',35),('modal_ruby_ad_item',24)):
            lower=key+'_lower';self.specs[lower]={'roi':[391,256,570,327]}
            self.gray[lower]=self.gray[key][-height:]
            variants=[]
            for t,_,_ in self.scaled[key]:
                t=t[-height:];q=t.astype(float)
                variants.append((t,q-q.mean(),max(q.mean(),1)))
            self.scaled[lower]=tuple(variants)
        self.diagnostics={}
    def recognize(self,image):
        from vision import Match
        gray=cv2.cvtColor(image,cv2.COLOR_BGR2GRAY);cache={};found={};self.diagnostics={}
        def get(key,roi=None):
            ck=(key,tuple(roi) if roi else None)
            if ck in cache:return cache[ck]
            x,y,r,b=roi or self.specs[key]['roi'];area=gray[y:b,x:r];ref=self.gray[key];best=None
            for t,centered,reference_mean in self.scaled[key]:
                h,w=t.shape
                if area.shape[0]<h or area.shape[1]<w:continue
                scoremap=cv2.matchTemplate(area,t,cv2.TM_CCOEFF_NORMED)
                _,score,_,(xx,yy)=cv2.minMaxLoc(scoremap)
                a=area[yy:yy+h,xx:xx+w].astype(float);mean=a.mean()
                error=float(np.abs((a-mean)-centered).mean())
                light=float(mean/reference_mean)
                if score>=.91 and error<=16 and .68<light<1.4:
                    value=(score,error,(x+xx+w/2,y+yy+h/2))
                    if best is None or value[0]>best[0]:best=value
            self.diagnostics[str(ck)]=best
            cache[ck]=best;return best
        def emit(key,value,point=None):
            name='daily_free_'+key;found[name]=Match(name,value[0],value[1],point or value[2])
        def marker(key,ref,roi=None,point=None):
            value=get(ref,roi)
            if value:emit(key,value,point)
            return value
        def counter(result=False):
            roi=[619,478,669,509] if result else [251,483,324,513]
            candidates=[(get('count_main_zero' if n==0 and not result else 'count_'+str(n),roi),n) for n in (0,1,2)]
            candidates=sorted([(v,n) for v,n in candidates if v],reverse=True)
            if not candidates or (len(candidates)>1 and candidates[0][0][0]-candidates[1][0][0]<.025):return None
            v,n=candidates[0];emit('count_'+str(n),v);return n
        # Modal detection precedes the dimmed store background. Partial modal
        # identity never exposes a background product as an actionable page.
        close=get('modal_close');ruby=get('modal_ruby');cube=get('modal_cube')
        if close and (ruby or cube):
            marker('dialog_close','modal_close')
            ad=get('modal_ad_free');plain=get('modal_plain_free')
            if cube and get('modal_cube_item') and ad:
                emit('confirm_cube_ad',ad);return 'free_store_confirm_cube_ad',found
            if ruby and (get('modal_ruby_ad_item') or get('modal_ruby_ad_item_lower')) and ad:
                emit('confirm_ruby_ad',ad);return 'free_store_confirm_ruby_ad',found
            if ruby and (get('modal_ruby_item') or get('modal_ruby_item_lower')) and plain and not ad:
                emit('confirm_ruby',plain);return 'free_store_confirm_ruby',found
            return 'free_store_dialog',found
        def main_control(key):
            # Mixed ticket/ruby prices widen the final button and move the
            # first free button left by about 20px. Stay inside that button;
            # keep every existing match/brightness/ambiguity gate unchanged.
            x,y,r,b=self.specs[key]['roi']
            return get(key,[x-24,y,r,b])
        if get('summon_info'):
            types=[k for k in ('character','skill','pet') if get('title_'+k)]
            if len(types)==1:
                k=types[0];marker('identity_'+k,'title_'+k)
                n=counter();free=main_control('free_11' if k=='character' else 'free_33')
                if free and main_control('summon_ad') and n in (1,2) and main_control('summon_enabled'):
                    emit('summon',free,(230,500))
                # Tab navigation requires the destination's literal text.
                for tab,point in [('character',(67,75)),('skill',(209,75)),('pet',(351,75))]:
                    # Page title + paired information controls establish the
                    # invariant tab bar even when its selected underline varies.
                    emit('tab_'+tab,get('summon_info'),point)
                emit('home',get('summon_info'),(919,28))
                return 'free_summon_'+k,found
        if get('result_reveal'):
            types=[k for k in ('character','skill','pet') if get('result_ticket_'+k)]
            if len(types)==1:
                k=types[0]
                marker('identity_'+k,'result_ticket_'+k)
                marker('reveal','result_reveal',point=(480,505))
                return 'free_summon_reveal_'+k,found
        if get('result_confirm'):
            types=[k for k in ('character','skill','pet') if get('result_ticket_'+k)]
            if len(types)==1:
                k=types[0];counter(True);marker('result_close','result_confirm')
                return 'free_summon_result_'+k,found
        if get('store_header') and get('store_home'):
            marker('home','store_home');emit('tab_currency',get('store_header'),(100,83));emit('tab_general',get('store_header'),(100,267))
            # Selected tab text is dark on gold, unlike the unselected light label.
            for name,box in [('general',(73,251,155,278)),('currency',(73,70,141,98))]:
                x,y,r,b=box;patch=image[y:b,x:r]
                bg=np.median(patch.reshape(-1,3),axis=0)
                if bg.mean()>110 and bg[2]>bg[0]*1.08:
                    emit('selected_'+name,get('store_header'))
            for col in range(3):
                left=255+225*col;right=min(920,left+210)
                for top,bottom in ((65,300),(275,495)):
                    for title,item in [('card_ruby','ruby'),('card_cube','cube_ad')]:
                        if item=='ruby' and 'daily_free_selected_currency' not in found:continue
                        if item=='cube_ad' and 'daily_free_selected_general' not in found:continue
                        titlematch=get(title,[left,top,right,bottom])
                        if not titlematch and item=='ruby':titlematch=get('card_ruby_ad_title',[left,top,right,bottom])
                        if not titlematch:continue
                        tx,ty=titlematch[2]
                        if ty>384:continue
                        ad=get('card_ad_free',[left,int(ty+105),right,min(493,int(ty+169))])
                        plain=get('card_free',[left,int(ty+105),right,min(493,int(ty+169))])
                        one=get('card_one',[left,max(57,int(ty-39)),right,int(ty)]) or get('card_one_ad',[left,max(57,int(ty-39)),right,int(ty)])
                        zero=get('card_zero',[left,max(57,int(ty-39)),right,int(ty)])
                        if one:
                            if ad:emit('open_'+('ruby_ad' if item=='ruby' else item),ad)
                            elif plain and item=='ruby':emit('open_ruby',plain)
                        if zero and item=='ruby':
                            adicon=get('card_ad_icon',[left,int(ty+20),right,min(490,int(ty+115))])
                            rubyicon=get('card_ruby_icon',[left,int(ty+20),right,min(490,int(ty+115))])
                            if adicon:emit('done_ruby_ad',zero)
                            elif rubyicon:emit('done_ruby',zero)
            if 'daily_free_selected_general' in found and get('cube_paid') and not get('card_cube'):
                marker('cube_absent','cube_paid')
            return 'free_store',found
        return None,found
