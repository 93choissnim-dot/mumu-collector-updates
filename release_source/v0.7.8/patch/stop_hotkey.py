"""Saved Windows stop shortcut with exact modifiers and edge detection."""
MODIFIERS = {'Ctrl': 0x11, 'Alt': 0x12, 'Shift': 0x10}
KEYS = {**{'F'+str(n): 0x6f+n for n in range(1, 13)},
        **{c: ord(c) for c in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'},
        'Esc': 0x1b, 'Space': 0x20, 'Pause': 0x13, 'Tab': 0x09,
        'Enter': 0x0d, 'Backspace': 0x08, 'Delete': 0x2e,
        'Home': 0x24, 'End': 0x23, 'Insert': 0x2d,
        'Up': 0x26, 'Down': 0x28, 'Left': 0x25, 'Right': 0x27}
ALIASES = {'Escape': 'Esc', 'space': 'Space', 'Return': 'Enter'}


def normalize(value):
    parts = str(value).split('+')
    if not parts or parts[-1] not in KEYS or len(set(parts)) != len(parts):
        raise ValueError('사용할 수 없는 중지 키입니다.')
    if any(p not in MODIFIERS for p in parts[:-1]):
        raise ValueError('사용할 수 없는 조합 키입니다.')
    return '+'.join([m for m in MODIFIERS if m in parts[:-1]] + [parts[-1]])


def from_tk_event(event):
    key = ALIASES.get(event.keysym, event.keysym)
    if len(key) == 1:
        key = key.upper()
    if key not in KEYS:
        return None
    mods = [name for name, bit in [('Ctrl', 0x4), ('Alt', 0x20000), ('Shift', 0x1)] if event.state & bit]
    return normalize('+'.join(mods + [key]))


class StopHotkey:
    def __init__(self, value='F8'):
        try:
            self.value = normalize(value)
        except ValueError:
            self.value = 'F8'
        self._down = False
        self._armed = False

    def reset(self):
        self._down = False
        self._armed = False

    def poll(self, pressed):
        parts = self.value.split('+')
        key_down = bool(pressed(KEYS[parts[-1]]))
        if not self._armed:
            self._armed = not key_down
            return False
        down = key_down and all(bool(pressed(vk)) == (name in parts[:-1]) for name, vk in MODIFIERS.items())
        fired = down and not self._down
        self._down = down
        return fired
