"""Explicit per-player KST-day RED RUBY spending authorization."""
GUILD_PAID_STEP=50
GUILD_PAID_MAX=750
GUILD_DONATION_CHOICES={'0':0,'최대':GUILD_PAID_MAX}


def guild_donation_choice(value=0):
    """Never raise a legacy or malformed spending permission to maximum."""
    return '최대' if type(value) is int and value==GUILD_PAID_MAX else '0'


def guild_paid_limit(value=0):
    """Invalid or absent authorization grants no spending."""
    return value if type(value) is int and 0<=value<=GUILD_PAID_MAX and value%GUILD_PAID_STEP==0 else 0


def normalize_paid_limit(value):
    """Validate a settings entry; runtime authorization remains integer-only."""
    if isinstance(value,str):
        value=value.strip()
        if value.isascii() and value.isdecimal():value=int(value)
    if type(value) is not int or not 0<=value<=GUILD_PAID_MAX or value%GUILD_PAID_STEP:
        raise ValueError('빨간 루비 한도는 0~750 사이의 50 단위 정수여야 합니다.')
    return value


# v0.7.95 uses counts. Legacy budget helpers remain for old saved profiles.
GUILD_DONATION_MODES={'0회':'off','무료 기부':'free','4회':'four'}


def donation_mode(player):
    if 'guild_donation_mode' in player:
        value=player['guild_donation_mode']
        return value if isinstance(value,str) and value in GUILD_DONATION_MODES.values() else 'off'
    return 'four' if guild_donation_choice(player.get('guild_paid_limit',0))=='최대' else 'free'


def donation_mode_label(player):
    mode=donation_mode(player)
    return next(label for label,value in GUILD_DONATION_MODES.items() if value==mode)
