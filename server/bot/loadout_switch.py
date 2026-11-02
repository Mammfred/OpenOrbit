"""Two setups. 1: the personality's generator share and the attack formation. 2: shield generators
(shield_share 0.95) and a defensive formation it owns (Dome, Turtle, Heart, Crab). It switches back when the
pressure drops. Once every eight seconds, like a player's config change.
"""
DEFENSE = ('drone_formation_f-3d-rg', 'drone_formation_f-01-tu', 'drone_formation_f-11-he', 'drone_formation_f-10-cr')
COOLDOWN = 8.0


def _owns(bot, loot):
    return loot == 'drone_formation_default' or loot in (bot.k.get('formations') or ())


def _attack(bot):
    from . import appearance as AP
    wanted = AP.formation_preference(bot)
    return wanted if _owns(bot, wanted) else (bot.k.get('formation') or 'drone_formation_default')


def _defense(bot):
    return next((f for f in DEFENSE if _owns(bot, f)), None)


def announce(w, n):
    """When the formation changes the drone string is sent again."""
    from . import appearance as AP
    from . import ship as SH
    SH._broadcast(w, AP.messages(n), n.id)


def apply(w, n, now, ratio, attackers):
    """Setup 2 under pressure, setup 1 otherwise. True if it changed."""
    b = n.bot
    if now < b.k.get('config_at', 0):
        return False
    pressure = bool(attackers) and (ratio < 0.62 or (len(attackers) >= 2 and ratio < 0.8))
    number = 2 if pressure else 1
    formation = _defense(b) if pressure else _attack(b)
    old_number = b.k.get('config_no', 1)
    old_formation = b.k.get('formation')
    if number == old_number and (not formation or formation == old_formation):
        return False
    b.k['config_no'] = number
    b.k['config_at'] = now + COOLDOWN
    if formation and formation != old_formation:
        b.k['formation'] = formation
    b.loadout_changed()
    d = b.value()
    n.hp = min(d['hp'], n.hp)
    n.shield = min(d['shield'], n.shield)
    if formation and formation != old_formation and w is not None:
        announce(w, n)
    b.event('config', number=number, formation=b.k.get('formation') or '')
    return True
