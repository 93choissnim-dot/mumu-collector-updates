"""Exercise real per-player draft settings, selection and endpoint identity."""
from mumu_names import name_options
from vision import LABELS


def reports_fixture():
    return {s:{'instance_id':i,'window_name':n,'package':'com.nng.genesis.onestore',
        'image':None,'state':'unknown','model':'뮤뮤','error':'','package_error':''}
        for s,i,n in [('127.0.0.1:16384','test-a','본캐'),('127.0.0.1:16416','test-b','부캐')]}


def check(app):
    root=app.root;reports=reports_fixture()
    app.players={};app.view_id=None;app.device_reports=reports
    app.device_options=name_options(list(reports),reports)
    app.sync_players(reports,'127.0.0.1:16384');app.select_player('test-a')
    app.fleet_dialog('test-a');root.update();editor=app.settings_editor
    editor.minutes.set('17');editor.tasks['farm'].set(False)
    editor.select('test-b');editor.minutes.set('31');editor.tasks['training'].set(True)
    editor.select('test-a')
    assert editor.minutes.get()=='17' and not editor.tasks['farm'].get()
    assert app.players['test-a']['minutes']!=17
    assert editor.apply();root.update()
    assert app.players['test-a']['minutes']==17 and app.players['test-a']['selected']['farm'] is False
    assert app.players['test-b']['minutes']==31 and app.players['test-b']['selected']['training']
    assert not app.players['test-a']['selected'].get('training')
    # Viewing another player cannot write hidden fields back to saved settings.
    app.minutes.set('999');app.selected['farm'].set(True)
    app.select_player('test-b');app.select_player('test-a');app.save()
    assert app.players['test-a']['minutes']==17 and not app.players['test-a']['selected']['farm']
    app.events.put(('device_checked',('127.0.0.1:16416',reports['127.0.0.1:16416'])));app.poll()
    assert app.chosen_serial()=='127.0.0.1:16384'
    moved=dict(reports['127.0.0.1:16384']);moved['window_name']='본캐 새 이름'
    app.events.put(('device_checked',('127.0.0.1:16448',moved)));app.poll()
    assert app.chosen_serial()=='127.0.0.1:16448' and app.serial_value.get()=='본캐 새 이름'
    assert '127.0.0.1:16384' not in app.device_reports
    app.fleet_dialog('test-a');root.update();editor=app.settings_editor
    editor.minutes.set('0');assert not editor.apply()
    assert app.players['test-a']['minutes']==17
    app.fleet_window.destroy()
    app.players={};app.device_reports={};app.device_options={};app.view_id=None
    app.serial_value.set('');app.update_fleet_summary()
    missing={s:{**r,'window_name':'','instance_id':None} for s,r in reports.items()}
    app.events.put(('connected',('adb.exe',list(missing),missing,'')));app.poll()
    assert not app.device_options and not app.players
    assert app.connection_text.get()=='뮤뮤 창 연결 확인 필요'
    assert '진단 파일' in app.finish_text


if __name__=='__main__':
    import customtkinter as ctk
    from app import App
    root=ctk.CTk();app=App(root,autoconnect=False,tray=False)
    try:check(app);print('Per-player settings and preview routing passed')
    finally:app.closing=True;app.update_stop.set();root.destroy()
