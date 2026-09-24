"""Use a supported larger display mode on the disposable Windows UI runner."""
import ctypes
import struct

user=ctypes.windll.user32
user.SetProcessDPIAware()
current=(user.GetSystemMetrics(0),user.GetSystemMetrics(1))
choices=[]
for index in range(1000):
    mode=ctypes.create_string_buffer(220)  # DEVMODEW
    struct.pack_into('<H',mode,68,220)
    if not user.EnumDisplaySettingsW(None,index,mode):break
    width,height=struct.unpack_from('<II',mode,172)
    if 1280<=width<=1920 and 900<=height<=1200:
        choices.append((abs(width-1920)+abs(height-1080),mode))
if choices:
    mode=min(choices,key=lambda item:item[0])[1]
    result=user.ChangeDisplaySettingsW(mode,0)
    print('Desktop mode request:',result)
print('Desktop review area:',current,'->',(user.GetSystemMetrics(0),user.GetSystemMetrics(1)))
