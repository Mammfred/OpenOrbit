"""On-map duel: the player's laser_damage path against the bot's ship._fire path.

The same ship (Goliath, 31 LF-3, 15 B02, 8 Iris, Havoc, Arrow, drone level 6, combat tree, x4).
The numbers from before the fix are fixed in this file: that path used x3 ammo, no skill HP or shield, and an 80% hit chance.

  python -I tools/duel_measure.py
"""
import os, random, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'server'))

from bot.state import Bot
from bot import personality as PS
from bot import catalog as K
from bot import weapons as WP
from bot import ship as SH
from bot import skill_build as SK
from bot import volley as VL
from bot import loadout_switch as LS
from world import World

LF3 = 'equipment_weapon_laser_lf-3'
B02 = 'equipment_generator_shield_sg3n-b02'
INTERVAL = 1.1

# Measured before the fix (ship._fire and value, mean of 400 salvos; the player is World.laser_damage).
BEFORE = {
    'bot_salvo': 13832.3, 'bot_hit': 0.8, 'bot_hp': 356000, 'bot_shield': 150000, 'bot_absorb': 0.8,
    'player_salvo': 22986.5, 'player_hit': 1.0, 'player_hp': 406000, 'player_shield': 187500, 'player_absorb': 0.92,
}


def ttk(hp, shield, absorb, dps):
    """Damage that has to land before the ship dies, divided by damage per second (same split as bot_damage and hurt_hero)."""
    if dps <= 0:
        return 0.0
    if absorb <= 0:
        return hp / dps
    shield_damage = shield / absorb
    leak = shield_damage * (1 - absorb)
    return (shield_damage + max(0.0, hp - leak)) / dps


def make_bot(level, ucb):
    r = random.Random(1)
    b = Bot({'no': 1, 'name': 'Equal', 'company': 1, 'personality': PS.generate_personality(r, 'hunter'),
             'credits': 8000000, 'uridium': 0, 'level': level, 'ep': 0, 'map': 4})
    b.smart = True
    b.permission = {'shop': True, 'pvp': True, 'rocket': True, 'custom_ammunition': True, 'extras': True, 'gate': True}
    b.hour = lambda: 0
    b.k['gear'] = {'ship': 'ship_goliath', 'laser': {LF3: 31}, 'shield': {B02: 15}, 'speed': {},
                   'drone': {'drone_iris': 8}, 'ammunition': 'ammunition_laser_lcb-10',
                   'drone_design': {'design': ['drone_designs_havoc'] * 8, 'appearance': [''] * 8},
                   'launcher': 'equipment_weapon_rocketlauncher_hst-1'}
    b.k['formation'] = 'drone_formation_f-02-ar'
    b.k['formations'] = ['drone_formation_default', 'drone_formation_f-02-ar', 'drone_formation_f-01-tu',
                         'drone_formation_f-3d-rg']
    stock = {'ammunition_laser_lcb-10': 50000, 'ammunition_laser_mcb-50': 8000,
             'ammunition_rocket_plt-2026': 200, 'ammunition_rocketlauncher_eco-10': 80}
    if ucb:
        stock['ammunition_laser_ucb-100'] = 12000
    b.k['stock'] = stock
    b.k['drone_level'] = 6
    b.loadout_changed()
    SK.spend(b)
    return b


class _Player:
    """For World.laser_damage: the bot's mods() dict, the same LF-3 layout."""

    def __init__(self, mods):
        self._m = mods
        self.d = {'drone_equipment': [[6, [LF3, LF3]] for _ in range(8)], 'drone_equipment_level': [],
                  'equipment': {'laser': [LF3] * 15}, 'equipment_level': {'laser': [0] * 15}}

    def mods(self):
        return self._m

    def lab_bonus(self, item):
        return 0


def player_salvo(mods, n=400):
    class W:
        pass
    w = W()
    w.p = _Player(mods)
    w.tech = type('T', (), {'laser_bonus': lambda self, now=None: 0})()
    w.anger = type('O', (), {'bonus': lambda self, ship, now: 0})()
    w.crit = False
    w.next_overdrive = 10 ** 12
    w.ramp = [1.0, 0]
    W.lasers = lambda self: [LF3] * 15
    W.laser_levels = lambda self: [(LF3, 0)] * 15
    W.drone_lasers = lambda self: [LF3] * 16
    shots = []
    for i in range(n):
        random.seed(i)
        w.crit = False
        dmg, _sh = World.laser_damage(w, 'ammunition_laser_ucb-100', pvp=True)
        shots.append(dmg)
    return sum(shots) / len(shots)


def bot_salvo(b, n=400):
    shots = []
    for i in range(n):
        random.seed(i + 1000)          # the player's crit consumes one extra random; a separate stream, the same formula on average
        hull, _shield = SH._fire(b, pvp=True, ammo=WP.UCB)
        shots.append(hull)
    return sum(shots) / len(shots)


def show(name, salvo, hit, hp, shield, absorb, other_hp, other_shield, other_absorb):
    dps = salvo * hit / INTERVAL
    print('%-22s salvo %7.0f  hit %4.0f%%  hp %6d  shield %6d  absorb %.2f  dps %6.0f  ttk %5.1f s' % (
        name, salvo, hit * 100, hp, shield, absorb, dps, ttk(other_hp, other_shield, other_absorb, dps)))
    return dps


def main():
    print('Before (x3, no skills, 80% hit):')
    o = BEFORE
    show('bot MCB-50', o['bot_salvo'], o['bot_hit'], o['bot_hp'], o['bot_shield'], o['bot_absorb'],
         o['player_hp'], o['player_shield'], o['player_absorb'])
    show('player UCB-100', o['player_salvo'], o['player_hit'], o['player_hp'], o['player_shield'], o['player_absorb'],
         o['bot_hp'], o['bot_shield'], o['bot_absorb'])

    bot = make_bot(22, True)
    d = bot.value()
    player = player_salvo(VL.mods(bot))
    salvo = bot_salvo(bot)
    print()
    print('After (same gear, x4, skill tree, drone 6, Havoc):')
    dps_b = show('bot UCB-100', salvo, VL.hit_chance(bot), d['hp'], d['shield'], d['absorb'],
                 d['hp'], d['shield'], d['absorb'])
    dps_p = show('player UCB-100', player, VL.hit_chance(bot), d['hp'], d['shield'], d['absorb'],
                 d['hp'], d['shield'], d['absorb'])
    ratio = salvo / player
    print('salvo ratio bot/player %.3f' % ratio)
    print('PvP ammo', WP.pick_laser(bot, 0, True, 1.0, 1.0))

    weak = make_bot(8, False)
    print('level 8, no x4: ammo %s, hp %d, shield %d' % (
        WP.pick_laser(weak, 0, True, 1.0, 1.0), int(weak.value()['hp']), int(weak.value()['shield'])))

    class N:
        pass
    n = N()
    n.bot = bot
    n.hp, n.shield = 100000, 20000
    bot.k['config_at'] = 0
    LS.apply(None, n, 10, 0.3, [1])
    print('under pressure config', bot.k.get('config_no'), bot.k.get('formation'),
          'shield share %.2f' % bot.shield_share())

    errors = []
    if not (0.90 <= ratio <= 1.10):
        errors.append('salvo ratio %.3f' % ratio)
    if WP.pick_laser(bot, 0, True, 1.0, 1.0) != WP.UCB:
        errors.append('x4 was not selected')
    if abs(d['hp'] - 406000) > 1000 or abs(d['shield'] - 187500) > 1000:
        errors.append('hp/shield %s %s' % (d['hp'], d['shield']))
    if bot.k.get('config_no') != 2 or bot.k.get('formation') != 'drone_formation_f-3d-rg':
        errors.append('config did not change')
    if WP.pick_laser(weak, 0, True, 1.0, 1.0) == WP.UCB:
        errors.append('a bot with no x4 stock selected x4')
    if dps_b <= 0 or dps_p <= 0:
        errors.append('no dps')
    # The previous on-map measurement was about 28 s against 29 s. Keep that band.
    bot_ttk = ttk(d['hp'], d['shield'], d['absorb'], dps_b)
    player_ttk = ttk(d['hp'], d['shield'], d['absorb'], dps_p)
    print('time to kill: bot %.1f s, player %.1f s' % (bot_ttk, player_ttk))
    if not (24 <= bot_ttk <= 34 and 24 <= player_ttk <= 34):
        errors.append('ttk left the 28 s band (%.1f / %.1f)' % (bot_ttk, player_ttk))
    if errors:
        print('FAILED:')
        for h in errors:
            print(' -', h)
        return 1
    print('OK.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
