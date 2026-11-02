"""Smarter bots against the old behavior: the same pilot, the same hours.

  python -I tools/bot_sim.py

Grinding net uridium per hour (uridium_rate.Meter: earnings minus the ammo cost), the gear after 72 hours
(Iris, lasers, ship, power) and the chance of winning a fair PvP fight. If smarter play falls behind, the
exit code is 1. The game server is not started.
"""
import os, random, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'server'))

from bot.state import Bot
from bot import personality as PS
from bot import brain as BR
from bot import weapons as WP
from bot import abstract_sim as AB
from bot.goals import shopping as SH
from bot.goals.shopping import Shopping
from bot import smart as SM
import uridium_rate as UR

HOURS = 72
SEEDS = ((1, 'grinder'), (2, 'hunter'), (3, 'grinder'), (5, 'quester'), (7, 'trader'))


class Clock:
    """The slice of a manager that abstract farming expects. Booty and events stay off (permissions)."""

    def __init__(self):
        self.now = 0.0
        self.mode = 'normal'
        self.on_map = {}

    def speed(self, bot):
        return 1.0

    def npc_killed(self, *a, **k):
        pass

    def bot_died(self, *a, **k):
        pass

    def map_changed(self, *a, **k):
        pass

    def setting(self, name, default=None):
        return default


def make_bot(seed, archetype, smart):
    r = random.Random(seed)
    b = Bot({'no': seed, 'name': 'P%d' % seed, 'company': 1, 'personality': PS.generate_personality(r, archetype),
             'credits': 8000, 'uridium': 400, 'level': 1, 'ep': 0, 'map': 1})
    b.permission = {'shop': True, 'extras': True, 'pvp': True, 'rocket': True, 'cargo': True, 'technology': True,
                    'custom_ammunition': True, 'mine': True, 'booty': False, 'event': False, 'lab': False,
                    'skylab': False, 'gate': False}
    b.smart = smart
    b.hour = lambda: 0.0
    b.uridium_rate = UR.Meter(price=WP.price)
    b.uridium_rate.bind(WP.price, now=0.0)
    return b


def play_hour(b, y, smart):
    """One hour: map, grind, ammo, shopping (the decision round in the game)."""
    b.smart = smart
    candidates = BR.map_candidates(b, b.value(), y)
    if not candidates:
        return
    b.k['map'] = candidates[0][1]
    if not WP.pick_laser(b):
        WP.add(b, WP.LCB, 500)
    AB.farm(b, 3600, y)
    WP.resupply(b)
    ctx = type('C', (), {})()
    ctx.shopping = SH.candidate(b)
    Shopping().start(b, ctx)


def summary(b, hours):
    d = b.value()
    v = b.uridium_rate.summary(now=hours * 3600)
    lasers = b.k['gear'].get('laser') or {}
    return {
        'net': (v.get('hourly') or {}).get('net_uridium'),
        'gross': (v.get('hourly') or {}).get('uridium'),
        'ammo': (v.get('hourly') or {}).get('ammo_uridium'),
        'u': int(b.k['uridium']),
        'c': int(b.k['credits']),
        'power': round(d['power'], 1),
        'lv': b.level,
        'ship': b.k['gear']['ship'].replace('ship_', ''),
        'iris': (b.k['gear'].get('drone') or {}).get('drone_iris', 0),
        'flax': (b.k['gear'].get('drone') or {}).get('drone_flax', 0),
        'lasers': sum(lasers.values()),
        'lf3': lasers.get('equipment_weapon_laser_lf-3', 0),
        'form': (b.k.get('formation') or '-').replace('drone_formation_', ''),
        'map': b.game_map,
    }


def run(smart):
    rows = []
    for seed, archetype in SEEDS:
        y = Clock()
        b = make_bot(seed, archetype, smart)
        b.hour = lambda y=y: y.now
        for h in range(1, HOURS + 1):
            y.now = h * 3600.0
            play_hour(b, y, smart)
        s = summary(b, HOURS)
        s['arch'] = archetype
        rows.append(s)
    return rows


def _g(v):
    return '-' if v is None else ('%g' % v)


def write_grind(old, new):
    print('Grinding, %d hours, the same pilots (net U/h = earnings - ammo cost)' % HOURS)
    print('%-8s %6s %6s %8s %5s %5s %4s %4s %s' % ('type', 'old', 'new', 'U old', 'U new', 'Iris', 'LF-3', 'power', 'ship'))
    for e, n in zip(old, new):
        print('%-8s %6s %6s %8d %6d  %d->%d  %2d  %5.1f  %s' % (
            e['arch'], _g(e['net']), _g(n['net']), e['u'], n['u'], e['iris'], n['iris'], n['lf3'], n['power'], n['ship']))
        print('         ammo U/h %s -> %s, flax %d->%d, formation %s, level %d' % (
            _g(e['ammo']), _g(n['ammo']), e['flax'], n['flax'], n['form'], n['lv']))


def pvp():
    """Equal gear: the smarter side's win chance (the old logic takes no skill share)."""
    a = make_bot(11, 'hunter', True)
    b = make_bot(11, 'hunter', False)
    for bot in (a, b):
        bot.k['gear']['ship'] = 'ship_goliath'
        bot.k['gear']['laser'] = {'equipment_weapon_laser_lf-3': 10}
        bot.k['gear']['drone'] = {'drone_iris': 4}
        bot.k['gear']['shield'] = {'equipment_generator_shield_sg3n-b02': 8}
        bot.k.setdefault('formations', ['drone_formation_default'])
        bot.loadout_changed()
    pa = SM.win_chance(a, b)
    rng = random.Random(0)
    wins = sum(rng.random() < pa for _ in range(400))
    weak = make_bot(12, 'grinder', True)
    weak.loadout_changed()
    pa_weak = SM.win_chance(weak, b)
    sab = _sab_checks(a)
    return pa, wins / 400.0, pa_weak, sab


def _sab_checks(bot):
    """SAB only when its own shield is low and the target still has shield. Three clear cases."""
    WP.add(bot, WP.SAB, 40)
    WP.add(bot, WP.MCB50, 400)

    def pick(target, own):
        return SM.laser(bot, pvp=True, shield=target, own=own) == WP.SAB

    return {'full': pick(1.0, 1.0), 'empty_target': pick(0.0, 0.15), 'own_low': pick(0.8, 0.15)}


def design_path():
    """A 72 hour grind does not finish a gate. Unlisted, a design comes from the gate; listed, the gate order does not change."""
    import shop as SH
    from bot import appearance as AP
    from bot import catalog as K
    from bot import galaxy_gates as GT
    before = {loot: SH.WORLD_SHOP.get(loot) for loot in (AP.HAVOC, AP.HERCULES)}
    try:
        for loot in (AP.HAVOC, AP.HERCULES):
            SH.WORLD_SHOP[loot] = {'on_sale': False}
        b = make_bot(3, 'hunter', True)
        b.permission['gate'] = True
        b.k['level'] = 18
        b.k['gear'] = {'ship': 'ship_goliath', 'laser': {'equipment_weapon_laser_lf-4': 40},
                       'shield': {'equipment_generator_shield_sg3n-b02': 15}, 'speed': {},
                       'drone': {'drone_iris': 8}, 'ammunition': 'ammunition_laser_ucb-100'}
        b.k['stock']['ammunition_laser_ucb-100'] = 80000
        b.k['uridium'] = 900000
        b.loadout_changed()
        if K.price(AP.HAVOC) is not None:
            raise SystemExit('unlisted Havoc still has a price')
        if GT.wanted_gate(b) != 'zeta':
            raise SystemExit('hunter did not pick Zeta: %r' % GT.wanted_gate(b))
        GT.grant_reward(b, 'zeta')
        if AP.designs_owned(b, AP.HAVOC) < 1:
            raise SystemExit('the first Zeta did not give Havoc')
        for loot in (AP.HAVOC, AP.HERCULES):
            if before[loot] is None:
                SH.WORLD_SHOP.pop(loot, None)
            else:
                SH.WORLD_SHOP[loot] = before[loot]
        if not K.price(AP.HAVOC):
            raise SystemExit('Havoc has no price once the shop lists it again')
        if GT.wanted_gate(b) is not None:
            raise SystemExit('still forcing a gate while it is for sale')
    finally:
        for loot, old in before.items():
            if old is None:
                SH.WORLD_SHOP.pop(loot, None)
            else:
                SH.WORLD_SHOP[loot] = old
    print('Designs: unlisted, the first Zeta gives Havoc and the hunter picks Zeta; listed, the gate order does not change.')


def main():
    design_path()
    print('Old behavior (smart off) ...')
    old = run(False)
    print('Smarter play ...')
    new = run(True)
    print()
    write_grind(old, new)

    def avg(rows, key):
        xs = [s[key] for s in rows if s[key] is not None]
        return sum(xs) / len(xs) if xs else 0.0

    net_old, net_new = avg(old, 'net'), avg(new, 'net')
    iris_old, iris_new = avg(old, 'iris'), avg(new, 'iris')
    power_old, power_new = avg(old, 'power'), avg(new, 'power')
    pa, rate, pa_weak, sab = pvp()
    print()
    print('Average net U/h: old %s, new %s' % (_g(round(net_old, 1)), _g(round(net_new, 1))))
    print('Average Iris: old %g, new %g' % (iris_old, iris_new))
    print('Average power: old %g, new %g' % (round(power_old, 1), round(power_new, 1)))
    print('PvP, same ship: smarter side win chance %d%% (%d%% of 400 duels)' % (round(pa * 100), round(rate * 100)))
    print('Weak smarter bot against a strong old one: win chance %d%%' % round(pa_weak * 100))
    print('SAB: own shield full %s, target shield empty %s, own low and target has shield %s' % (
        'yes' if sab['full'] else 'no', 'yes' if sab['empty_target'] else 'no', 'yes' if sab['own_low'] else 'no'))
    errors = []
    if not (net_new > net_old * 1.08):
        errors.append('net uridium did not rise (%s -> %s)' % (net_old, net_new))
    if not (iris_new > iris_old and iris_new >= 1):
        errors.append('Iris was not bought (old %g, new %g)' % (iris_old, iris_new))
    if not (0.55 <= pa <= 0.80):
        errors.append('PvP chance %g is outside %g-%g' % (pa, 0.55, 0.80))
    if pa_weak > 0.45:
        errors.append('the weak bot beats the strong one too often (%g)' % pa_weak)
    if sab['full'] or sab['empty_target'] or not sab['own_low']:
        errors.append('SAB in the wrong case: %s' % sab)
    if errors:
        print('FAILED:')
        for h in errors:
            print(' -', h)
        return 1
    print('OK.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
