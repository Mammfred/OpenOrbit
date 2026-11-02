"""The shot on the map (ship._fire). The same account as world.World.laser_damage: ship lasers separate from
drone lasers (drone level and Havoc only on the drone share), formation, skill tree, lab, ammo multiplier.
Ammo that only hits shields (SAB) comes back as the second number.

catalog.values is the abstract power. This is the damage that actually leaves the ship.
"""
import random

from . import catalog as K
from . import skill_build as SK


def _formation(bot):
    loot = bot.k.get('formation') or ''
    owned = bot.k.get('formations') or ()
    if not loot or (loot != 'drone_formation_default' and loot not in owned):
        return {}
    f = dict(K.ITEMS['formations'].get(loot) or {})
    f.pop('id', None)
    return f


def mods(bot):
    """Formation + set design + skills. Keys match player_profile.mods."""
    out = _formation(bot)
    for k, v in K.drone_set(bot.k['gear']).items():
        out[k] = out.get(k, 0) + v
    for k, v in SK.mods(bot).items():
        out[k] = out.get(k, 0) + v
    return out


def drone_level(bot):
    """1..6. The top slice copies the save's drone level; otherwise it comes from aliens killed."""
    v = bot.k.get('drone_level')
    if v:
        return max(1, min(6, int(v)))
    from . import appearance as AP
    return AP.drone_level(bot)


def _split(bot):
    """Base damage of fitted lasers, the best ones in the ship slots, the rest on drones -> (ship, drones)."""
    gear = bot.k['gear']
    ship = K.ITEMS['ships'].get(gear.get('ship')) or K.ITEMS['ships']['ship_phoenix']
    lasers = K.ITEMS['lasers']
    all_damage = sorted((lasers[l]['damage'] for l, n in (gear.get('laser') or {}).items() for _ in range(n) if l in lasers), reverse=True)
    slots = ship['laser'] + sum(K.ITEMS['drones'].get(d, {}).get('slot', 1) * n for d, n in (gear.get('drone') or {}).items())
    all_damage = all_damage[:slots]
    ship_part = all_damage[:ship['laser']]
    return ship_part, all_damage[len(ship_part):]


def shot(bot, ammo, pvp=False, rng=None):
    """One salvo -> (hull damage, shield-only damage). Random 0.76-1.0, as for the player."""
    rng = rng or random
    ship_part, drone_part = _split(bot)
    m = mods(bot)
    level = K.ITEMS['drone_levels'][drone_level(bot) - 1]
    ship_d = sum(ship_part)
    drone_d = sum(drone_part) * (1 + level['laser'] + m.get('drone_laser', 0))
    base = ship_d + drone_d
    if pvp:
        base *= 1 + m.get('laser', 0) + m.get('pvp_laser', 0) + m.get('pvp_damage', 0)
    else:
        base *= 1 + m.get('laser', 0) + m.get('npc', 0) + m.get('npc_laser', 0)
    lab = 0.0
    body = getattr(bot, 'body', None)
    if body is not None and getattr(body, 'lab_shot', None):
        lab = body.lab_shot
    base *= 1 + lab
    from . import loot as LT
    base *= 1 + LT.booster_share(bot, 'DAMAGE')
    a = K.ITEMS['laser_ammo'].get(ammo or '', {})
    multiplier = a.get('pvp_multiplier', a.get('multiplier', 1)) if pvp else a.get('multiplier', 1)
    roll = rng.uniform(*K.ITEMS['damage_random'])
    flat = 0
    if not pvp and multiplier:
        lasers = K.ITEMS['lasers']
        flat = sum(lasers[l].get('alien_extra', 0) for l, n in (bot.k['gear'].get('laser') or {}).items() for _ in range(n) if l in lasers)
    return int(base * multiplier * roll) + flat, int(base * a.get('shield_multiplier', 0) * roll)


def hit_chance(bot):
    """Laser hit chance: base 0.8, plus Electro-Optics (the same multiplier as the player's shot)."""
    m = mods(bot)
    return min(1.0, K.COMBAT['laser_hit_chance'] * (1 + m.get('hit_chance', 0) + m.get('laser_hit_chance', 0)))


def rocket_factor(bot):
    m = mods(bot)
    return max(0.25, 1 + m.get('rocket', 0))


def apply_value(bot, d):
    """Writes the skill tree onto value()'s HP, shield and absorb. The salvo's damage is shot(); dps is not changed here."""
    m = SK.mods(bot)
    if not m:
        return d
    d['hp'] = d['hp'] * (1 + m.get('hp', 0)) + m.get('hp_flat', 0)
    d['shield'] *= max(0.0, 1 + m.get('shield', 0))
    d['absorb'] = min(0.95, d.get('absorb', 0) + m.get('absorb', 0))
    d['ehp'] = d['hp'] + d['shield'] * 2.5 * min(1.0, d['absorb'] + 0.2)
    d['power'] = K.power_score(d['dps'], d['ehp'])
    return d
