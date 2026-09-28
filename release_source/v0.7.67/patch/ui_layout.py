"""Fit logical Tk client sizes to a monitor's physical work area."""
import os


def work_area(root):
    if os.name=='nt':
        try:
            import ctypes
            from ctypes import wintypes as w
            class MonitorInfo(ctypes.Structure):
                _fields_=[('size',w.DWORD),('monitor',w.RECT),('work',w.RECT),('flags',w.DWORD)]
            user=ctypes.windll.user32
            user.MonitorFromWindow.argtypes=[w.HWND,w.DWORD];user.MonitorFromWindow.restype=w.HANDLE
            user.GetMonitorInfoW.argtypes=[w.HANDLE,ctypes.POINTER(MonitorInfo)];user.GetMonitorInfoW.restype=w.BOOL
            info=MonitorInfo();info.size=ctypes.sizeof(info)
            if user.GetMonitorInfoW(user.MonitorFromWindow(root.winfo_id(),2),ctypes.byref(info)):
                r=info.work;return r.left,r.top,r.right,r.bottom
        except (OSError,AttributeError):pass
    return 0,0,root.winfo_screenwidth(),root.winfo_screenheight()


def fit_size(area,scale,preferred,minimum):
    left,top,right,bottom=area
    available=(max(1,int((right-left-24)/scale)),max(1,int((bottom-top-60)/scale)))
    size=tuple(min(max(preferred[i],minimum[i]),available[i]) for i in (0,1))
    limits=tuple(min(minimum[i],available[i]) for i in (0,1))
    return size,limits


def preferred_size(config):
    value=config.get('window_size')
    if (isinstance(value,(list,tuple)) and len(value)==2
            and all(type(x) is int and 430<=x<=5000 for x in value)):
        return tuple(value)
    return (680,800)


def window_size(root):
    if root.state()!='normal':return None
    scale=root._get_window_scaling()
    width,height=round(root.winfo_width()/scale),round(root.winfo_height()/scale)
    return [width,height] if width>=430 and height>=300 else None


def fit_window(root,preferred=(680,800),minimum=(620,430)):
    area=work_area(root);scale=root._get_window_scaling()
    size,limits=fit_size(area,scale,preferred,minimum)
    root.minsize(*limits)
    root.geometry(f'{size[0]}x{size[1]}{area[0]+12:+d}{area[1]+12:+d}')
    return size
