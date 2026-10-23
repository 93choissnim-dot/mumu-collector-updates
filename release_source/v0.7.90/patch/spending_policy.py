"""Explicit per-player KST-day RED RUBY spending authorization."""
GUILD_PAID_STEP=50
GUILD_PAID_MAX=750


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
