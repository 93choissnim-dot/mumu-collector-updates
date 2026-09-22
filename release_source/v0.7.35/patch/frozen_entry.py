"""Standalone EXE entry; Python and all dependencies are bundled."""
import ctypes
import json
import os
from pathlib import Path
import sys
import traceback


def health_check(output,full_ui=True):
    import faulthandler
    import customtkinter as ctk
    from app import App
    from vision import Vision
    from version import VERSION
    from windows_shortcuts import write_link,read_link
    from PIL import ImageGrab
    output=Path(output).resolve();output.parent.mkdir(parents=True,exist_ok=True)
    def checkpoint(stage):
        print('HEALTH_CHECK '+stage,flush=True)
        output.with_suffix('.progress.json').write_text(json.dumps({'stage':stage,'full_ui':full_ui,'version':VERSION}),encoding='utf-8')
    checkpoint('vision')
    vision = Vision()
    # Verify the new navigation module and modal assets in the packaged EXE.
    from start_navigation import prepare_start
    import numpy as np
    frame = np.full((540, 960, 3), 115, dtype=np.uint8)
    for name in ('exit_title', 'exit_cancel', 'exit_confirm'):
        x1, y1, x2, y2 = vision.specs[name]['box']
        frame[y1:y2, x1:x2] = vision.templates[name][0]
    modal = vision.recognize(frame)
    assert callable(prepare_start) and modal.state == 'exit_dialog'
    assert all(name in modal.matches for name in ('exit_title', 'exit_cancel', 'exit_confirm'))
    from daily_actions import SWEEP_DUNGEONS
    from daily_state import DAILY_TASKS
    assert SWEEP_DUNGEONS=={'equipment','summon'} and len(DAILY_TASKS)==3
    assert len(vision.daily.specs)>=100
    from daily_state import DAILY_STEPS
    from daily_execution import DailyExecution
    from execution_trace import ExecutionTrace
    from donation_evidence import changed_counter
    assert sum(map(len,DAILY_STEPS.values()))==16
    assert callable(DailyExecution.daily_run_step) and callable(changed_counter)
    assert ExecutionTrace().snapshot()['run_id']
    from validate_autumn import event_frame,PAGE
    autumn=vision.recognize(event_frame(vision.autumn,*PAGE,'autumn_empty','autumn_zero'))
    assert autumn.state=='autumn' and 'autumn_empty' in autumn.matches and 'autumn_active' not in autumn.matches
    from input_safety import verified_tap
    from action_state import ActionState,account_scope
    from validate_overlays import composite
    top=vision.recognize(composite(vision,'main_menu','main_character','main_pet','top_pass','top_event','top_worldboss'))
    assert all('top_'+k in top.matches for k in ('pass','event','worldboss'))
    guard=ActionState();guard.reserve('autumn');guard.reset('autumn')
    assert guard.pending('autumn') and callable(verified_tap) and account_scope('legacy','')=='legacy'
    # Exercise the actual observation/cache boundaries in the frozen package.
    import unittest
    from validate_efficiency import ObservationTests,RecognitionCostTests,DiscoveryAndIdleTests
    suite=unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromTestCase(case)
        for case in (ObservationTests,RecognitionCostTests,DiscoveryAndIdleTests))
    result=unittest.TestResult();suite.run(result)
    assert result.wasSuccessful(),(result.errors,result.failures)
    from validate_update_network import NetworkTests
    from validate_world_boss import RouteTests
    from validate_daily_dialogs import DialogVisionTests,GuildCoinFlowTests
    from validate_daily_transitions import TransitionTests,NativeControlTests
    from validate_audit import FacilityRecoveryTests,SweepAndWorkshopTests,UpdateRecoveryTests
    from validate_navigation_recovery import ExitGeometryTests,NavigationChangeTests
    from validate_daily_execution import BoundaryTests,EvidenceTests,DailyExecutionTests
    suite=unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromTestCase(case)
        for case in (NetworkTests,RouteTests,DialogVisionTests,GuildCoinFlowTests,
                     BoundaryTests,EvidenceTests,DailyExecutionTests,TransitionTests,NativeControlTests,
                     FacilityRecoveryTests,SweepAndWorkshopTests,UpdateRecoveryTests,ExitGeometryTests,NavigationChangeTests))
    result=unittest.TestResult();suite.run(result)
    assert result.wasSuccessful(),(result.errors,result.failures)
    native=np.full((540,960,3),110,np.uint8)
    for name in ('guild_title','guild_tabs','guild_menu','guild_donate_open'):
        x,y,r,b=vision.daily.specs[name]['box'];native[y:b,x:r]=vision.daily.templates[name][0]
    native=np.clip(native.astype(float)*[1.22065,1.17493,1.12426]+[22.12782,2.31765,-4.33370],0,255).astype(np.uint8)
    native_screen=vision.recognize(native)
    assert native_screen.state=='daily_guild_menu'
    assert 'daily_guild_donate_open' in native_screen.matches
    assert 'daily_guild_attended' not in native_screen.matches
    # Package-level regression: tactics is not needed to open boss ranking.
    boss_frame=np.full((540,960,3),110,np.uint8)
    for name in ('x_boss_mission','x_boss_rank_open','x_boss_supply'):
        x,y,r,b=vision.specs[name]['box'];boss_frame[y:b,x:r]=vision.templates[name][0]
    assert vision.recognize(boss_frame).state=='boss'
    from world_boss import WorldBossActions
    assert callable(WorldBossActions.open_boss_selection)
    root=ctk.CTk()
    if not full_ui:root.withdraw()
    trace=output.with_suffix('.threads.log').open('w',encoding='utf-8')
    faulthandler.enable(file=trace,all_threads=True)
    faulthandler.dump_traceback_later(25,repeat=True,file=trace)
    app=None
    try:
        checkpoint('startup_ui')
        app=App(root,autoconnect=False,tray=False);app.config['update_check']=False
        root.update()
        assert app.start_button.winfo_exists() and app.pause_button.winfo_exists()
        assert app.stop_button.cget('state')=='disabled'
        assert app.fleet_button.cget('command') is not None
        if full_ui:
            checkpoint('fleet_ui')
            from validate_fleet_ui import check
            check(app)
            checkpoint('run_controls_ui')
            from validate_run_controls_ui import check as check_run_controls
            check_run_controls(app,output)
            checkpoint('workspace_ui')
            from validate_workspace_ui import check as check_workspace
            check_workspace(app,output)
            checkpoint('improvements_ui')
            from validate_improvements_ui import check as check_improvements
            check_improvements(app,output)
        checkpoint('tray')
        app.setup_tray()
        import time
        deadline=time.monotonic()+5
        # Tray image encoding can trigger cyclic GC of discarded Tk fonts.
        # Tk only services those cross-thread destructors inside mainloop();
        # repeated update() calls leave them waiting and falsely fail startup.
        def await_tray():
            if app.tray_ready or time.monotonic()>=deadline:root.quit()
            else:root.after(25,await_tray)
        root.after(0,await_tray)
        root.mainloop()
        if not app.tray_ready:faulthandler.dump_traceback(file=trace,all_threads=True)
        assert app.tray is not None and app.tray_ready,'Tray initialization failed'
        if full_ui:
            checkpoint('taskbar_ui')
            from validate_taskbar_ui import check as check_taskbar
            check_taskbar(app)
        app.tray.close();app.tray=None
        if full_ui:
            app.updates_dialog();root.update()
            ImageGrab.grab().save(output.with_suffix('.png'))
        checkpoint('shortcut')
        test_link=output.with_suffix('.lnk');exe=Path(sys.executable).resolve()
        write_link(test_link,exe,'',exe.parent,exe)
        target,args=read_link(test_link)
        assert Path(target).resolve()==exe and args==''
    finally:
        if app is not None:
            app.closing=True;app.update_stop.set();app.stop.set()
            if getattr(app,'tray',None) is not None:app.tray.close()
            if getattr(app,'hotkey_listener',None) is not None:app.hotkey_listener.close()
        root.destroy()
        faulthandler.cancel_dump_traceback_later();faulthandler.disable();trace.close()
    checkpoint('complete')
    output.write_text(json.dumps({'ok':True,'version':VERSION,'frozen':bool(getattr(sys,'frozen',False)),
        'ui':True,'startup_ui':True,'full_ui_checks':full_ui,'fleet_ui':full_ui,'run_controls_ui':full_ui,
        'workspace_ui':full_ui,'game_theme_ui':full_ui,'improvements_ui':full_ui,'taskbar_ui':full_ui,'start_navigation':True,'daily_tasks':True,'tray':True,'shortcut':True,
        'daily_native_color':True,'worldboss_recovery':True,'daily_step_recovery':True,'diagnostic_trace':True,'autumn_rewards':True,'input_safety':True,'pass_icon_identity':True,'efficiency_safety':True,
        'worldboss_plan':True,'update_retry':True,
        'native_exit_recovery':True,'rotating_workshop':True,'cross_feature_audit':True,'daily_animation_recovery':True,'guild_native_controls':True,'daily_dialogs':True,'combat_transitions':True,'first_failure_evidence':True,
        'bits':ctypes.sizeof(ctypes.c_void_p)*8},ensure_ascii=False),encoding='utf-8')


def main():
    data=Path(os.environ.get('LOCALAPPDATA',str(Path.home())))/'MumuCollector';data.mkdir(parents=True,exist_ok=True)
    if len(sys.argv)>=3 and sys.argv[1]=='--health-check':
        health_check(sys.argv[2],full_ui='--full-ui-checks' in sys.argv);return
    if len(sys.argv)>=3 and sys.argv[1]=='--update-worker':
        from exe_updater import worker
        worker(sys.argv[2],recover='--recover' in sys.argv);return
    from instance_lock import InstanceLock
    lock=InstanceLock(data/'collector.lock')
    if not lock.acquire():
        ctypes.windll.user32.MessageBoxW(None,'이미 실행 중인 창키 도우미를 사용해 주세요.','창키 도우미',0x40);return
    try:
        from exe_updater import recover_pending,cleanup_updates
        if recover_pending(data):return
        cleanup_updates(data)
        from app import main as app_main
        app_main(lock)
    finally:lock.release()


if __name__=='__main__':
    try:main()
    except Exception:
        data=Path(os.environ.get('LOCALAPPDATA',str(Path.home())))/'MumuCollector';data.mkdir(parents=True,exist_ok=True)
        log=data/'exe_error.log';log.write_text(traceback.format_exc(),encoding='utf-8')
        if len(sys.argv)==1:ctypes.windll.user32.MessageBoxW(None,'실행 오류가 발생했습니다.\n기록: '+str(log),'창키 도우미',0x10)
        sys.exit(1)
