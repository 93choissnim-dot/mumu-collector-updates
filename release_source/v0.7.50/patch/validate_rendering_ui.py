"""Exercise the Windows crash boundary: repeated settings creation and scaling."""
import copy
import customtkinter as ctk
from customtkinter.windows.widgets.core_rendering import CTkCanvas,DrawEngine
from ui_layout import fit_window
from validate_run_controls_ui import descendants


def check(app):
    root=app.root
    assert DrawEngine.preferred_drawing_method=='polygon_shapes'
    saved=copy.deepcopy(app.players)
    ident=next(iter(app.players))
    for index,scale in enumerate((1.,1.25,1.5,1.,1.5,1.25)):
        ctk.set_widget_scaling(scale);ctk.set_window_scaling(scale)
        fit_window(root);root.update();app.apply_layout();root.update()
        root.after(0,app.render_fleet_status)
        app.fleet_dialog(ident);root.update();editor=app.settings_editor
        assert editor.ready and editor.window is app.fleet_window
        editor.window.geometry('720x520' if index%2 else '880x660')
        fit_window(editor.window,(720,600));root.update()
        editor.interval_presets._dropdown_callback('2시간')
        editor.task_checks['farm'].toggle();root.update()
        canvases=[w for w in descendants(editor.window) if isinstance(w,CTkCanvas)]
        assert canvases and all(not w._aa_circle_canvas_ids for w in canvases)
        # Native polygons and lines replace the custom font glyph draw path.
        for canvas in canvases:
            for item in canvas.find_all():
                if canvas.type(item)=='text':
                    assert 'CustomTkinter_shapes_font' not in canvas.itemcget(item,'font')
        assert editor.save_button.winfo_ismapped()
        editor.window.destroy();root.update()
        assert app.players==saved,'Rendering stress saved an uncommitted draft'
    ctk.set_widget_scaling(1);ctk.set_window_scaling(1)
    fit_window(root);root.update();app.apply_layout();root.update()
