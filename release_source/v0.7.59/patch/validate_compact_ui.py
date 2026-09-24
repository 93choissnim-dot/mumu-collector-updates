"""Actual desktop bounds and persistence at the approved compact window size."""
from pathlib import Path
import time
import customtkinter as ctk
from PIL import ImageGrab
from ui_layout import window_size,fit_window


def check(app,output):
    root=app.root
    app.config['update_check']=False
    original_players=app.players
    ident=next(iter(app.players),None)
    if ident:app.players={ident:app.players[ident]};app.view_id=ident
    app.compact_details=True
    for scale in (1.,1.25,1.5):
        ctk.set_widget_scaling(scale);ctk.set_window_scaling(scale)
        deadline=time.monotonic()+1.1
        while time.monotonic()<deadline:root.update();time.sleep(.01)
        fit_window(root,(680,800),(620,430));root.update();app.apply_layout();app.render_roster(force=True);root.update()
        for widget in (app.once_button,app.start_button,app.daily_button,app.connect_button,app.update_button,app.more_button,app.detail_name,app.connection_badge):
            assert widget.winfo_ismapped(),('compact hidden',widget.cget('text'))
            assert widget.winfo_rootx()>=root.winfo_rootx(),('compact left',widget.cget('text'))
            assert widget.winfo_rootx()+widget.winfo_width()<=root.winfo_rootx()+root.winfo_width()+2,('compact right',widget.cget('text'))
            assert widget.winfo_rooty()+widget.winfo_height()<=root.winfo_rooty()+root.winfo_height()+2,('compact bottom',widget.cget('text'))
        assert app.detail_name.winfo_width()>80,'Player name clipped'
        assert app.detail_tasks._parent_canvas.winfo_height()>80,'Task results clipped'
        assert app.stop_button.cget('fg_color')!=app.start_button.cget('fg_color')
        assert window_size(root)[0]<=680
        if scale==1.:
            ImageGrab.grab(window=root.winfo_id()).save(Path(output).with_name('review-compact-680.png'))
            app.save()
            from app import CONFIG
            import json
            assert json.loads(CONFIG.read_text(encoding='utf-8'))['window_size']==window_size(root)
    ctk.set_widget_scaling(1);ctk.set_window_scaling(1)
    deadline=time.monotonic()+1.1
    while time.monotonic()<deadline:root.update();time.sleep(.01)
    app.players=original_players
    fit_window(root,(1220,820));root.update();app.render_roster(force=True);root.update()
