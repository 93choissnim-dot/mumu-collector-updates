"""Frozen desktop smoke check for the read-only account overview at 680 px."""
import copy
import tempfile
import unittest
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch
from PIL import ImageGrab
from action_state import ActionState
from daily_state import ManualQuestLedger,korea_day
from run_journal import RunJournal
from ui_layout import fit_window


class FooterLayoutTests(unittest.TestCase):
    def test_idle_without_backlog_does_not_add_a_footer_row(self):
        from unittest.mock import Mock
        from ui_workflow import WorkflowUI
        app=SimpleNamespace(scope_selector=Mock(),refresh_workflow=lambda:None,
            workflow_plan={'safe':[],'held':[]},workflow_error='',config={},
            resume_bar=Mock(),resume_hint=Mock(),resume_button=Mock(),
            start_button=Mock(),once_button=Mock())
        WorkflowUI.sync_workflow(app,False)
        app.resume_bar.grid.assert_not_called()
        self.assertFalse(app._resume_visible)


def check(app,output):
    root=app.root;original=copy.deepcopy(app.players);view=app.view_id
    states=copy.deepcopy(app.fleet_states);scope=app.config.get('run_scope','regular')
    ident='today-preview';disabled='today-disabled';day=korea_day()
    players={ident:{'name':'오늘 작업 계정','enabled':True,'minutes':60,
        'selected':{'farm':True,'wood':True},'daily_selected':{'daily_guild':True},'serial':''},
        disabled:{'name':'사용 안 하는 계정','enabled':False,'minutes':60,
        'selected':{'farm':True},'daily_selected':{},'serial':''}}
    try:
        with tempfile.TemporaryDirectory() as temporary,patch('app.DATA',Path(temporary)):
            data=Path(temporary);journal=RunJournal(data/'run_progress.json')
            journal.begin(ident,['farm','wood','daily_guild']);journal.result(ident,'farm','collected')
            ledger=ManualQuestLedger(data/'daily_manual.json')
            ledger.checkpoint(ident,'daily_guild','attendance','done',values={'attendance':'done'})
            ledger.checkpoint(ident,'daily_guild','donation','uncertain',pending='donate_free')
            ledger.checkpoint(ident,'daily_guild','donation','running',pending=None,resolution_source='donation_counter_changed')
            ledger.checkpoint(ident,'daily_guild','donation','uncertain',pending='donate_50')
            ledger.checkpoint(ident,'daily_guild','donation','running',pending=None,resolution_source='donation_counter_changed')
            ledger.checkpoint(ident,'daily_guild','donation','uncertain',pending='donate_50',values={'donation_paid':9})
            ActionState(data/'action_state.json',disabled).reserve('farm')
            before={p.name:p.read_bytes() for p in data.glob('*.json')}
            app.players=players;app.view_id=ident;app.fleet_states={};app.config['run_scope']='regular'
            app.scope_value.set('일반 작업');app.refresh_workflow(force=True)
            fit_window(root,(680,800));root.update();app.apply_layout();app.render_roster(force=True);root.update()
            assert app.today_button.winfo_ismapped()
            assert app.today_button.master is app.run_info
            assert app.today_button.winfo_height()<=app.run_target.winfo_height(), 'Overview button enlarged the information line'
            assert app.today_button.winfo_rootx()>=app.count_label.winfo_rootx()+app.count_label.winfo_width()
            assert app.today_button.winfo_rootx()+app.today_button.winfo_width()<=root.winfo_rootx()+root.winfo_width()
            assert app.today_button.winfo_rooty()+app.today_button.winfo_height()<=root.winfo_rooty()+root.winfo_height()
            app.today_button.invoke();root.update()
            report=app.today_report;assert report['day']==day
            active=report['accounts'][0];rows={r['task']:r for r in active['tasks']}
            assert rows['farm']['status']=='done' and rows['wood']['status']=='unrun'
            assert rows['daily_guild']['status']=='uncertain'
            assert active['donation']['ruby_confirmed']==50
            assert not report['accounts'][1]['enabled']
            assert report['accounts'][1]['tasks'][0]['status']=='uncertain'
            ImageGrab.grab(window=app.today_window.winfo_id()).save(Path(output).with_name('review-today-overview.png'))
            fit_window(app.today_window,(680,560),(520,380));root.update();app.today_render();root.update()
            assert app.today_body.winfo_width()>300
            for card in app.today_body.winfo_children():
                for widget in card.winfo_children():
                    assert widget.winfo_rootx()+widget.winfo_width()<=app.today_window.winfo_rootx()+app.today_window.winfo_width()
            ImageGrab.grab(window=app.today_window.winfo_id()).save(Path(output).with_name('review-today-overview-680.png'))
            assert {p.name:p.read_bytes() for p in data.glob('*.json')}==before,'Overview changed execution records'
            app.today_window.destroy()
    finally:
        win=getattr(app,'today_window',None)
        if win is not None and win.winfo_exists():win.destroy()
        app.players=original;app.view_id=view;app.fleet_states=states;app.config['run_scope']=scope
        from ui_workflow import SCOPES
        app.scope_value.set(next(k for k,v in SCOPES.items() if v==scope))
        app.refresh_workflow(force=True);app.render_roster(force=True);root.update()
