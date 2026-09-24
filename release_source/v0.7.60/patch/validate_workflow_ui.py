"""Actual footer routing and no stale success on a synthetic Windows desktop."""
import copy
import time
from pathlib import Path
from unittest.mock import patch
from PIL import ImageGrab
from ui_layout import fit_window
from daily_state import korea_day
from run_journal import RunJournal
from action_state import ActionState,account_scope


def check(app,output):
    from app import DATA
    root=app.root
    original=copy.deepcopy(app.players);states=copy.deepcopy(app.fleet_states);config=app.config.get('run_scope','regular')
    ident='workflow-preview';scope=account_scope(ident)
    app.players={ident:{'name':'미리보기 계정','enabled':True,'minutes':60,'selected':{'farm':True,'wood':True},'daily_selected':{'daily_dungeons':True},'serial':'127.0.0.1:16384'}}
    app.view_id=ident;app.device_reports={'127.0.0.1:16384':{'instance_id':ident,'image':None,'state':'unknown','package':'com.nns.genesis'}}
    journal=RunJournal(DATA/'run_progress.json');journal.begin(scope,['farm','wood','daily_dungeons'])
    journal.result(scope,'farm','collected')
    ActionState(DATA/'action_state.json',scope).reserve('daily_dungeons') # daily uses its step ledger instead; result below must still hold.
    journal.result(scope,'daily_dungeons','attempted')
    app.history.record(ident,'wood','collected')
    app.fleet_states={};app.config['run_scope']='all';app.scope_value.set('전체')
    fit_window(root,(680,800));root.update();app.apply_layout();app.render_roster(force=True);root.update()
    assert app.detail_results['wood'].cget('text')=='이번 실행 대기'
    assert app.resume_bar.winfo_ismapped() and app.resume_button.winfo_ismapped()
    assert len(app.workflow_plan['safe'])==1 and len(app.workflow_plan['held'])==1
    assert app.resume_button.winfo_rooty()>app.detail_panel.winfo_rooty()
    assert not any(app.more_menu.entrycget(i,'label')=='미완료 작업 이어하기' for i in range(app.more_menu.index('end')+1))
    ImageGrab.grab(window=root.winfo_id()).save(Path(output).with_name('review-workflow.png'))
    app.resume_button.invoke();root.update()
    assert app.resume_window.winfo_exists() and app.resume_confirm_button.cget('state')=='normal'
    ImageGrab.grab(window=app.resume_window.winfo_id()).save(Path(output).with_name('review-resume.png'))
    with patch.object(app,'launch') as launch:
        app.resume_confirm_button.invoke();root.update()
        assert launch.call_args.args==('resume',{ident:['wood']})
    with patch.object(app,'save'):
        app.change_scope('일일 작업')
    root.update()
    assert app.once_button.cget('state')=='normal' and app.start_button.cget('state')=='disabled'
    with patch.object(app,'save'):
        app.change_scope('전체')
    root.update()
    assert app.start_button.cget('state')=='normal'
    app.worker_pending=999;app.pause_allowed=True;app.run_mode='once';app.stop.clear();app.active_instance=ident
    app.set_busy(True);root.update()
    assert not app.resume_bar.winfo_ismapped() and not app.scope_selector.winfo_ismapped()
    assert app.pause_button.winfo_ismapped() and app.stop_button.winfo_ismapped()
    app.stop.pause();app.render_roster(force=True);root.update()
    ImageGrab.grab(window=root.winfo_id()).save(Path(output).with_name('review-workflow-paused.png'))
    app.stop.resume();app.worker_pending=None;app.active_instance=None;app.set_busy(False)
    app.players=original;app.fleet_states=states;app.config['run_scope']=config
    from ui_workflow import SCOPES
    app.scope_value.set(next(k for k,v in SCOPES.items() if v==config))
    app.view_id=next(iter(original),None);app.render_roster(force=True);root.update()
