"""Top slice: a roster built from a sample save.

  python -I tools/top_bots_test.py

The player is a Goliath, 12 LF-3, 6 Iris, 2 Flax, level 14. 40 bots, 10% top.
Most match, a few are one step better, a few one step behind. The rest are unmarked.
"""
import os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'server'))

from bot import appearance as AP
from bot import catalog as K
from bot import personality as PS
from bot import top_bots as TP

SAMPLE = {
    'level': 14,
    'ep': 40960000,
    'formation': 'drone_formation_f-02-ar',
    'formations': ['drone_formation_default', 'drone_formation_f-02-ar'],
    'gear': {
        'ship': 'ship_goliath',
        'laser': {'equipment_weapon_laser_lf-3': 12},
        'shield': {'equipment_generator_shield_sg3n-b02': 10},
        'speed': {'equipment_generator_speed_g3n-7900': 5},
        'drone': {'drone_iris': 6, 'drone_flax': 2},
        'ammunition': 'ammunition_laser_lcb-10',
    },
    'designs': ['drone_designs_havoc'] * 8,
}

# The save file's shape (profile.d): the same gear, the parser has to read this too.
PROFILE = {
    'pilot': {'level': 14, 'ep': 40960000, 'userName': 'Sample'},
    'active_ship': '1',
    'formation': 2,
    'formations': ['drone_formation_default', 'drone_formation_f-02-ar'],
    'items': {
        '1': 'equipment_weapon_laser_lf-3',
        '2': 'equipment_generator_shield_sg3n-b02',
        '3': 'equipment_generator_speed_g3n-7900',
        '9': 'drone_designs_havoc',
    },
    'ships': {'1': {
        'lootId': 'ship_goliath', 'active_config': 1,
        'configs': {'1': {'laser': ['1'] * 10, 'generators': ['2'] * 8 + ['3'] * 4}},
        'drone_config': {'1': {'10': ['1'], '11': ['1']}},
        'drone_design': {'1': {str(i): {'design': '9'} for i in list(range(1, 7)) + [10, 11]}},
    }},
    'drones': [{'uid': i, 'lootId': 'drone_iris', 'level': 1} for i in range(1, 7)]
              + [{'uid': 10, 'lootId': 'drone_flax', 'level': 1}, {'uid': 11, 'lootId': 'drone_flax', 'level': 1}],
}


def expect(name, got, want):
    if got != want:
        raise SystemExit('failed: %s\n  got: %r\n  want: %r' % (name, got, want))


def valid(gear):
    g = K.ITEMS['ships'][gear['ship']]
    drones = sum(gear['drone'].values())
    slots = g['laser'] + sum(K.ITEMS['drones'][l].get('slot', 1) * n for l, n in gear['drone'].items())
    if sum(gear['laser'].values()) > slots:
        return False
    if sum(gear['shield'].values()) + sum(gear['speed'].values()) > g['generators']:
        return False
    if drones > K.ITEMS['max_drones']:
        return False
    if gear['ship'] != 'ship_goliath':
        return False
    return True


def main():
    source = TP.from_save(SAMPLE)
    expect('level', source['level'], 14)
    expect('iris', source['gear']['drone'].get('drone_iris'), 6)
    parsed = TP.from_save(PROFILE)
    expect('parsed ship', parsed['gear']['ship'], 'ship_goliath')
    expect('parsed iris', parsed['gear']['drone'].get('drone_iris'), 6)
    expect('parsed lasers', sum(parsed['gear']['laser'].values()), 12)  # 10 on the ship + 2 on drones
    expect('formation', parsed['formation'], 'drone_formation_f-02-ar')
    expect('Havoc in the save', parsed['designs'], ['drone_designs_havoc'] * 8)

    roster = PS.generate_roster(42, 40, lang='en')
    expect('off marks nothing', TP.mark(roster, 0, 42), [])
    expect('nobody marked', any(x.get('top') for x in roster), False)
    chosen = TP.mark(roster, 10, 42)
    expect('10% of 40 bots', len(chosen), 4)
    roles = sorted(x['top'] for x in chosen)
    expect('roles', roles, ['close', 'close', 'lower', 'upper'])
    expect('the rest unmarked', sum(1 for x in roster if not x.get('top')), 36)

    print('sample: Goliath, LF-3 x12, Iris x6, Flax x2, level 14')
    print('%-16s %-6s %6s %5s %5s %s' % ('name', 'role', 'level', 'LF-3', 'Iris', 'slots'))
    for b in chosen:
        k = {'company': b['company']}
        v = TP.apply(k, source, b['top'])
        gear = v['gear']
        if not valid(gear):
            raise SystemExit('invalid gear: %s %s' % (b['name'], gear))
        slots = K.ITEMS['ships'][gear['ship']]['laser'] + sum(
            K.ITEMS['drones'][l].get('slot', 1) * n for l, n in gear['drone'].items())
        print('%-16s %-6s %6d %5d %5d %d/%d' % (
            b['name'], b['top'], v['level'], gear['laser'].get('equipment_weapon_laser_lf-3', 0),
            gear['drone'].get('drone_iris', 0), sum(gear['laser'].values()), slots))
        if b['top'] == 'close':
            expect(b['name'] + ' level', v['level'], 14)
            expect(b['name'] + ' iris', gear['drone'].get('drone_iris'), 6)
            expect(b['name'] + ' lasers', gear['laser'].get('equipment_weapon_laser_lf-3'), 12)
        elif b['top'] == 'upper':
            expect(b['name'] + ' level', v['level'], 15)
            expect(b['name'] + ' lasers', sum(gear['laser'].values()), 13)
        elif b['top'] == 'lower':
            expect(b['name'] + ' level', v['level'], 13)
            expect(b['name'] + ' lasers', gear['laser'].get('equipment_weapon_laser_lf-3'), 11)
        n = sum(gear['drone'].values())
        worn = (gear.get('drone_design') or {}).get('design') or []
        expect(b['name'] + ' Havoc', worn, ['drone_designs_havoc'] * n)
        expect(b['name'] + ' set', K.drone_set(gear).get('drone_laser'), 0.1)
        expect(b['name'] + ' x4 stock', k['stock'].get('ammunition_laser_ucb-100', 0) >= 12000, True)
        expect(b['name'] + ' launcher', gear.get('launcher'), 'equipment_weapon_rocketlauncher_hst-1')
    _shopping()
    print('OK.')


def _shopping():
    """A bot with drones and money wants one design set on its next purchase."""
    import random
    from bot.state import Bot
    from bot.goals import shopping as SH
    r = random.Random(1)
    b = Bot({'no': 1, 'name': 'Hunt', 'company': 1, 'personality': PS.generate_personality(r, 'hunter'),
             'credits': 0, 'uridium': 250000, 'level': 12, 'ep': 10240000, 'map': 1})
    b.smart = True
    b.permission = {'shop': True, 'extras': True, 'pvp': True, 'rocket': True, 'cargo': True, 'technology': True}
    b.hour = lambda: 0
    b.k['gear'] = {'ship': 'ship_goliath', 'laser': {'equipment_weapon_laser_lf-3': 31},
                   'shield': {'equipment_generator_shield_sg3n-b02': 15}, 'speed': {},
                   'drone': {'drone_iris': 8}, 'ammunition': 'ammunition_laser_lcb-10',
                   'extras': {'equipment_extra_repbot_rep-1': 1},
                   'drone_design': {'design': [''] * 8, 'appearance': [''] * 8}}
    b.k['formations'] = ['drone_formation_default', 'drone_formation_f-02-ar', 'drone_formation_f-05-pi',
                         'drone_formation_f-01-tu', 'drone_formation_f-04-st', 'drone_formation_f-3d-dr']
    b.k['formation'] = 'drone_formation_f-02-ar'
    b.loadout_changed()
    expect('hunter wants Havoc', AP.drone_preference(b), 'drone_designs_havoc')
    pick = SH.candidate(b)[0]
    expect('purchase Havoc', None if not pick else pick[3], 'drone_designs_havoc')
    b.k['personality']['traits']['aggression'] = 0.2
    b.k['personality']['traits']['risk'] = 0.2
    b.k['personality']['archetype'] = 'grinder'
    expect('careful wants Hercules', AP.drone_preference(b), 'drone_designs_hercules')
    _gates()


class _Die:
    """A fixed roll: the gate's first-clear and single-spin branches."""

    def __init__(self, v):
        self.v = v

    def random(self):
        return self.v

    def randint(self, a, b):
        return a

    def choice(self, s):
        return s[0]


def _strong(archetype):
    """Gear that can clear Zeta and Kappa (UCB-100, LF-4)."""
    import random
    from bot.state import Bot
    r = random.Random(3)
    b = Bot({'no': 3, 'name': 'Gate', 'company': 1, 'personality': PS.generate_personality(r, archetype),
             'credits': 0, 'uridium': 800000, 'level': 18, 'ep': 200000000, 'map': 1})
    b.smart = True
    b.permission = {'shop': True, 'gate': True, 'extras': True}
    b.hour = lambda: 0
    b.k['gear'] = {'ship': 'ship_goliath',
                   'laser': {'equipment_weapon_laser_lf-4': 40},
                   'shield': {'equipment_generator_shield_sg3n-b02': 15}, 'speed': {},
                   'drone': {'drone_iris': 8}, 'ammunition': 'ammunition_laser_ucb-100'}
    b.k['stock']['ammunition_laser_ucb-100'] = 80000
    b.loadout_changed()
    return b


_BEFORE = {}


def _on_sale(listed):
    """World Editor: Havoc and Hercules for sale, or not. The price cache follows the shop stamp."""
    import shop as SH
    for loot in (AP.HAVOC, AP.HERCULES):
        if listed:
            old = _BEFORE.get(loot)
            if old is None:
                SH.WORLD_SHOP.pop(loot, None)
            else:
                SH.WORLD_SHOP[loot] = old
        else:
            _BEFORE[loot] = SH.WORLD_SHOP.get(loot)
            SH.WORLD_SHOP[loot] = {'on_sale': False}


def _gates():
    """If the shop sells it, it is bought. Unlisted, Zeta gives Havoc and Kappa gives Hercules; the bot picks that gate and does not mix the set."""
    import random
    from bot.state import Bot
    from bot.goals import shopping as SH
    from bot import galaxy_gates as GT
    expect('Havoc gate', GT.sources().get(AP.HAVOC), ('zeta',))
    expect('Hercules gate', GT.sources().get(AP.HERCULES), ('kappa',))
    try:
        _on_sale(False)
        expect('not for sale', K.price(AP.HAVOC), None)
        expect('Hercules neither', K.price(AP.HERCULES), None)
        r = random.Random(1)
        hunter = Bot({'no': 9, 'name': 'Hunt2', 'company': 1, 'personality': PS.generate_personality(r, 'hunter'),
                      'credits': 0, 'uridium': 900000, 'level': 14, 'ep': 40960000, 'map': 1})
        hunter.smart = True
        hunter.permission = {'shop': True, 'gate': True}
        hunter.hour = lambda: 0
        hunter.k['gear'] = {'ship': 'ship_goliath', 'laser': {'equipment_weapon_laser_lf-3': 31},
                            'shield': {'equipment_generator_shield_sg3n-b02': 15}, 'speed': {},
                            'drone': {'drone_iris': 8}, 'ammunition': 'ammunition_laser_lcb-10',
                            'extras': {'equipment_extra_repbot_rep-1': 1}}
        hunter.k['formations'] = ['drone_formation_default', 'drone_formation_f-02-ar', 'drone_formation_f-05-pi',
                                  'drone_formation_f-01-tu', 'drone_formation_f-04-st', 'drone_formation_f-3d-dr']
        hunter.loadout_changed()
        pick = SH.candidate(hunter)[0]
        expect('not bought while unlisted', pick[3] in (AP.HAVOC, AP.HERCULES), False)

        b = _strong('hunter')
        expect('hunter Zeta', GT.wanted_gate(b), 'zeta')
        expect('parts Zeta', GT.target_gate(b), 'zeta')
        b.k['personality']['traits']['aggression'] = 0.2
        b.k['personality']['traits']['risk'] = 0.2
        b.k['personality']['archetype'] = 'grinder'
        expect('careful Kappa', GT.wanted_gate(b), 'kappa')
        expect('parts Kappa', GT.target_gate(b), 'kappa')

        weak = Bot({'no': 4, 'name': 'Weak', 'company': 1, 'personality': PS.generate_personality(r, 'hunter'),
                    'credits': 0, 'uridium': 0, 'level': 12, 'ep': 10240000, 'map': 1})
        weak.permission = {'gate': True}
        weak.smart = True
        weak.k['gear']['drone'] = {'drone_iris': 2}
        weak.loadout_changed()
        expect('a weak bot does not pick Zeta', GT.wanted_gate(weak), None)

        b = _strong('hunter')
        st = GT.state(b)
        st['built'] = ['alpha', 'zeta']
        expect('run Zeta', GT.can_run(b), 'zeta')
        GT.grant_reward(b, 'zeta')
        expect('first Zeta Havoc', AP.designs_owned(b, AP.HAVOC) >= 1, True)
        expect('Zeta done', 'zeta' in st.get('done', []), True)
        before = AP.designs_owned(b, AP.HAVOC)
        b.r = _Die(0.99)
        GT.grant_reward(b, 'zeta')
        expect('the second Zeta is not guaranteed', AP.designs_owned(b, AP.HAVOC), before)

        b = _strong('hunter')
        b.r = _Die(0.0)
        for _ in range(8):
            GT.grant_reward(b, 'zeta')
        worn = (b.k['gear'].get('drone_design') or {}).get('design') or []
        expect('eight Havoc', worn, [AP.HAVOC] * 8)
        expect('Havoc set', K.drone_set(b.k['gear']).get('drone_laser'), 0.1)
        expect('set complete, gate done', GT.wanted_gate(b), None)

        b = _strong('grinder')
        b.k['personality']['traits']['aggression'] = 0.2
        b.k['personality']['traits']['risk'] = 0.2
        b.k['gear']['drone_design'] = {'design': [AP.HERCULES] * 8, 'appearance': [''] * 8}
        b.loadout_changed()
        for _ in range(7):
            AP.gain_design(b, AP.HAVOC)
        expect('seven Havoc does not mix', (b.k['gear'].get('drone_design') or {}).get('design'), [AP.HERCULES] * 8)
        expect('Havoc in stock', AP.design_stock(b).get(AP.HAVOC), 7)
        b.k['personality']['traits']['aggression'] = 0.9
        b.k['personality']['traits']['risk'] = 0.8
        b.k['personality']['archetype'] = 'hunter'
        AP.gain_design(b, AP.HAVOC)
        expect('the eighth swaps the set', (b.k['gear'].get('drone_design') or {}).get('design'), [AP.HAVOC] * 8)
        expect('the old set is in stock', AP.design_stock(b).get(AP.HERCULES), 8)
        expect('no mixed bonus', K.drone_set(b.k['gear']).get('hp'), None)

        b = _strong('grinder')
        b.k['personality']['traits']['aggression'] = 0.2
        b.k['personality']['traits']['risk'] = 0.2
        b.r = _Die(0.0)
        GT.grant_reward(b, 'kappa')
        expect('Kappa Hercules', AP.designs_owned(b, AP.HERCULES) >= 1, True)
        b = _strong('grinder')
        b.k['personality']['traits']['aggression'] = 0.2
        b.k['personality']['traits']['risk'] = 0.2
        b.r = _Die(0.4)
        GT.grant_reward(b, 'kappa')
        expect('single spin LF-4', b.k['gear']['laser'].get('equipment_weapon_laser_lf-4'), 41)
        expect('LF-4 is not Hercules', AP.designs_owned(b, AP.HERCULES), 0)
        print('Gates: Zeta Havoc (first clear guaranteed), Kappa Hercules (one spin). Not bought while unlisted.')
    finally:
        _on_sale(True)


if __name__ == '__main__':
    main()
