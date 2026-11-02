"""When a roster is created, the top slice is built from the player's save.

Pack settings: top (off: the old generation) and top_percent (percent, default 10). The snapshot is taken when the
pack is created or the roster is regenerated (and when the setting is saved, for bots that have not entered the
game yet). A bot that is already playing does not follow the save afterwards: if the player changes ship, the
roster has to be regenerated. Most of the slice matches the save, a few are one step better, a few one step
behind. The rest of the roster is left alone.
"""
import json, os, random

from . import catalog as K

LADDER = ('equipment_weapon_laser_lf-1', 'equipment_weapon_laser_lf-2', 'equipment_weapon_laser_lf-3',
          'equipment_weapon_laser_lf-4')
DRONE_ORDER = ('drone_iris', 'drone_apis', 'drone_zeus', 'drone_flax')


def _level_table():
    p = os.path.join(K.HERE, 'data', 'levels.json')
    try:
        table = json.load(open(p, encoding='utf8'))['levels']
    except (OSError, ValueError, KeyError):
        table = [[1, 0]]
    return table


def ep_for(level):
    """The EP threshold of a level. Does not walk off the table."""
    table = _level_table()
    level = max(1, min(int(level), table[-1][0]))
    return level, int(dict(table).get(level, 0))


def _ship(loot):
    g = K.ITEMS['ships'].get(loot) or {}
    if g.get('hp') and not g.get('base'):
        return loot
    base = g.get('base')
    if base and (K.ITEMS['ships'].get(base) or {}).get('hp'):
        return base
    if g.get('hp'):
        return loot
    return 'ship_phoenix'


def _count(loots, accept):
    out = {}
    for loot in loots:
        if loot and accept(loot):
            out[loot] = out.get(loot, 0) + 1
    return out


def from_save(d):
    """A profile dict, or a ready reference {level, ep, gear, formation, formations} -> a checked reference, or None."""
    if not isinstance(d, dict):
        return None
    if isinstance(d.get('gear'), dict) and d.get('level'):
        return _fit_source(d)
    ships = d.get('ships') or {}
    ship = ships.get(str(d.get('active_ship') or ''))
    if ship is None and ships:
        ship = next(iter(ships.values()))
    items = d.get('items') or {}
    if ship is None:
        equipment = d.get('equipment') or {}
        if not equipment and not d.get('pilot'):
            return None
        lasers = _count(equipment.get('laser') or [], lambda l: l in K.ITEMS['lasers'])
        gens = equipment.get('generators') or []
        ship_loot = (d.get('ship') or {}).get('typeId') or 'ship_phoenix'
        drones = []
        cfg = {}
    else:
        cfg = (ship.get('configs') or {}).get(str(ship.get('active_config') or 1)) or {}

        def resolve(ids):
            return [items.get(str(i)) for i in (ids or []) if items.get(str(i))]

        lasers = _count(resolve(cfg.get('laser')), lambda l: l in K.ITEMS['lasers'] and not K.ITEMS['lasers'][l].get('pet_only'))
        gens = resolve(cfg.get('generators'))
        ship_loot = ship.get('lootId') or 'ship_phoenix'
        drone_cfg = (ship.get('drone_config') or {}).get(str(ship.get('active_config') or 1)) or {}
        drones = list(d.get('drones') or [])
        for x in drones:
            for loot in resolve(drone_cfg.get(str(x.get('uid')))):
                if loot in K.ITEMS['lasers'] and not K.ITEMS['lasers'][loot].get('pet_only'):
                    lasers[loot] = lasers.get(loot, 0) + 1
                elif loot in K.ITEMS['shield_generators'] or loot in K.ITEMS['speed_generators']:
                    gens.append(loot)
    shield = _count(gens, lambda l: l in K.ITEMS['shield_generators'])
    speed = _count(gens, lambda l: l in K.ITEMS['speed_generators'])
    drone = {}
    for x in drones:
        loot = x.get('lootId') if isinstance(x, dict) else x
        if loot in K.ITEMS['drones']:
            drone[loot] = drone.get(loot, 0) + 1
    import player_profile as PF
    formations = []
    for x in d.get('formations') or []:
        loot = x if isinstance(x, str) else PF.formation_loot(int(x or 0))
        if loot in K.ITEMS.get('formations', {}) and loot not in formations:
            formations.append(loot)
    if 'drone_formation_default' not in formations:
        formations.insert(0, 'drone_formation_default')
    chosen = d.get('formation')
    if not isinstance(chosen, str):
        chosen = PF.formation_loot(int(chosen or 0))
    pilot = d.get('pilot') or {}
    level = int(pilot.get('level') or PF.level_for(int(pilot.get('ep') or 0)) or 1)
    ep = int(pilot.get('ep') or 0)
    designs = []
    design_items = K.ITEMS['drone_designs']
    design_cfg = {}
    if ship:
        design_cfg = (ship.get('drone_design') or {}).get(str(ship.get('active_config') or 1)) or {}
    for x in drones:
        per = design_cfg.get(str(x.get('uid') if isinstance(x, dict) else '')) or {}
        iid = per.get('design') if isinstance(per, dict) else None
        loot = items.get(str(iid)) if iid else ''
        designs.append(loot if loot in design_items and design_items[loot].get('slot') == 'design' else '')
    skills = {}
    tree = d.get('skills') or {}
    if isinstance(tree, dict):
        for sid, lv in (tree.get('level') or {}).items():
            try:
                lv = int(lv)
            except (TypeError, ValueError):
                continue
            if lv > 0:
                skills[str(sid)] = lv
    levels = [int(x.get('level') or 1) for x in drones if isinstance(x, dict)]
    drone_level = int(round(sum(levels) / len(levels))) if levels else 1
    return _fit_source({'level': level, 'ep': ep, 'formation': chosen, 'formations': formations,
                        'designs': designs, 'skills': skills, 'drone_level': drone_level,
                        'gear': {'ship': _ship(ship_loot), 'laser': lasers, 'shield': shield, 'speed': speed,
                                 'drone': drone, 'ammunition': K.AMMO[0]}})


def _fit_source(d):
    import player_profile as PF
    gear = _fit(d['gear'])
    level, base = ep_for(d.get('level') or 1)
    ep = int(d.get('ep') or base)
    if PF.level_for(ep) != level:
        ep = base
    formations = [f for f in (d.get('formations') or []) if f in K.ITEMS.get('formations', {})]
    if 'drone_formation_default' not in formations:
        formations.insert(0, 'drone_formation_default')
    chosen = d.get('formation') if d.get('formation') in formations else 'drone_formation_default'
    chosen = _fit_formation(chosen, formations, gear)
    designs = [t for t in (d.get('designs') or []) if t in K.ITEMS['drone_designs']
               and K.ITEMS['drone_designs'][t].get('slot') == 'design']
    _wear_designs(gear, designs)
    return {'level': level, 'ep': ep, 'gear': gear, 'formation': chosen, 'formations': formations,
            'designs': designs, 'skills': dict(d.get('skills') or {}),
            'drone_level': int(d.get('drone_level') or 1)}


def _slots(gear):
    g = K.ITEMS['ships'][_ship(gear.get('ship'))]
    drone_slots = sum((K.ITEMS['drones'].get(l) or {}).get('slot', 1) * n for l, n in (gear.get('drone') or {}).items())
    return g['laser'] + drone_slots, g['generators']


def _fit(gear):
    """Pulls the ship, the slots and the drone limit into range. Extra lasers and generators drop from the weakest."""
    gear = {k: (dict(v) if isinstance(v, dict) else v) for k, v in gear.items()}
    gear['ship'] = _ship(gear.get('ship'))
    drones = K.ITEMS['drones']
    order = []
    for loot, n in (gear.get('drone') or {}).items():
        if loot not in drones:
            continue
        order += [loot] * int(n)
    order.sort(key=lambda l: DRONE_ORDER.index(l) if l in DRONE_ORDER else 9)
    single, kept = set(), []
    for loot in order:
        if drones[loot].get('single') and loot in single:
            continue
        if len(kept) >= K.ITEMS['max_drones']:
            break
        kept.append(loot)
        if drones[loot].get('single'):
            single.add(loot)
    gear['drone'] = {}
    for loot in kept:
        gear['drone'][loot] = gear['drone'].get(loot, 0) + 1
    laser_slots, gen_slots = _slots(gear)
    lasers = K.ITEMS['lasers']
    gear['laser'] = _trim(gear.get('laser') or {}, max(1, laser_slots),
                          lambda l: lasers[l]['damage'] if l in lasers and not lasers[l].get('pet_only') else -1)
    gear['shield'] = _trim(gear.get('shield') or {}, gen_slots, lambda l: (K.ITEMS['shield_generators'].get(l) or {}).get('shield', -1))
    left = gen_slots - sum(gear['shield'].values())
    gear['speed'] = _trim(gear.get('speed') or {}, max(0, left), lambda l: (K.ITEMS['speed_generators'].get(l) or {}).get('speed', -1))
    gear['ammunition'] = gear.get('ammunition') if gear.get('ammunition') in K.ITEMS['laser_ammo'] else K.AMMO[0]
    if gear.get('drone_design'):
        gear['drone_design'] = dict(gear['drone_design'])
    return gear


def _trim(counts, limit, score):
    lst = []
    for loot, n in counts.items():
        if score(loot) < 0:
            continue
        lst += [loot] * max(0, int(n))
    lst.sort(key=score, reverse=True)
    out = {}
    for loot in lst[:max(0, limit)]:
        out[loot] = out.get(loot, 0) + 1
    return out


def _wear_designs(gear, designs):
    """The player's drone designs. If they are all the same set (Havoc or Hercules), every drone of the bot wears it."""
    n = sum((gear.get('drone') or {}).values())
    filled = [t for t in designs if t]
    if not n or not filled:
        return
    if len(set(filled)) == 1 and len(filled) == len(designs):
        chosen = filled[0]
        worn = [chosen] * n
    else:
        from collections import Counter
        chosen = Counter(filled).most_common(1)[0][0]
        worn = (filled + [chosen] * n)[:n]
    gear['drone_design'] = {'design': worn, 'appearance': [''] * n}


def _fit_formation(chosen, formations, gear):
    n = sum((gear.get('drone') or {}).values())
    rules = K.ITEMS.get('formation_rules') or {}

    def ok(loot):
        return loot in formations and n >= (rules.get(loot) or {}).get('min_drones', 0)

    if ok(chosen):
        return chosen
    for loot in formations:
        if ok(loot):
            return loot
    return 'drone_formation_default'


def _best_laser(lasers):
    table = K.ITEMS['lasers']
    return max(lasers, key=lambda l: table.get(l, {}).get('damage', 0))


def _next_laser(loot):
    if loot not in LADDER:
        return None
    i = LADDER.index(loot)
    nxt = LADDER[i + 1] if i + 1 < len(LADDER) else None
    return nxt if nxt in K.ITEMS['lasers'] else None


def _add_one(counts, loot):
    counts[loot] = counts.get(loot, 0) + 1


def _drop_one(counts, loot):
    if counts.get(loot, 0) <= 1:
        counts.pop(loot, None)
    else:
        counts[loot] -= 1


def apply_step(source, step):
    """step: 'close' matches the save, 'upper' is one notch better, 'lower' one notch behind. Slots stay valid."""
    import player_profile as PF
    gear = _fit(source['gear'])
    level = int(source['level'])
    if step == 'upper':
        _better(gear)
        level += 1
    elif step == 'lower':
        _worse(gear)
        level -= 1
    gear = _fit(gear)
    _wear_designs(gear, source.get('designs') or [])
    level, ep = ep_for(level)
    if step == 'close':
        ep = max(ep, int(source.get('ep') or ep))
        level = PF.level_for(ep)
        _, base = ep_for(level)
        if PF.level_for(ep) != level:
            ep = base
    formations = list(source.get('formations') or ['drone_formation_default'])
    chosen = _fit_formation(source.get('formation'), formations, gear)
    return {'level': level, 'ep': ep, 'gear': gear, 'formation': chosen, 'formations': formations,
            'skills': dict(source.get('skills') or {}), 'drone_level': int(source.get('drone_level') or 1)}


def _better(gear):
    laser_slots, gen_slots = _slots(gear)
    lasers = gear.setdefault('laser', {})
    if sum(lasers.values()) < laser_slots and lasers:
        _add_one(lasers, _best_laser(lasers))
        return
    if lasers:
        weak = min(lasers, key=lambda l: K.ITEMS['lasers'].get(l, {}).get('damage', 0))
        nxt = _next_laser(weak)
        if nxt:
            _drop_one(lasers, weak)
            _add_one(lasers, nxt)
            return
    drone = gear.setdefault('drone', {})
    if drone.get('drone_iris', 0) and sum(drone.values()) < K.ITEMS['max_drones']:
        _add_one(drone, 'drone_iris')
        return
    if sum(gear.get('shield', {}).values()) + sum(gear.get('speed', {}).values()) < gen_slots and gear.get('shield'):
        best = max(gear['shield'], key=lambda l: K.ITEMS['shield_generators'][l]['shield'])
        _add_one(gear['shield'], best)


def _worse(gear):
    lasers = gear.get('laser') or {}
    if sum(lasers.values()) > 1:
        _drop_one(lasers, _best_laser(lasers))
        return
    drone = gear.get('drone') or {}
    if drone.get('drone_iris', 0):
        _drop_one(drone, 'drone_iris')
        return
    if drone:
        _drop_one(drone, next(iter(drone)))
        return
    if gear.get('shield'):
        _drop_one(gear['shield'], next(iter(gear['shield'])))
    elif gear.get('speed'):
        _drop_one(gear['speed'], next(iter(gear['speed'])))


def roles(n):
    """Roles in the slice: mostly close, a few upper, a few lower."""
    if n <= 0:
        return []
    if n == 1:
        return ['close']
    if n == 2:
        return ['upper', 'lower']
    upper = max(1, int(round(n * 0.2)))
    lower = max(1, int(round(n * 0.2)))
    while upper + lower >= n:
        if upper >= lower and upper > 1:
            upper -= 1
        elif lower > 1:
            lower -= 1
        else:
            break
    return ['upper'] * upper + ['close'] * (n - upper - lower) + ['lower'] * lower


def mark(roster, percent, seed):
    """Marks the most ambitious / competitive slice (stable for a seed). percent is a percentage. -> the marked rows."""
    for x in roster:
        x.pop('top', None)
    try:
        percent = float(percent or 0)
    except (TypeError, ValueError):
        percent = 0
    if percent <= 0 or not roster:
        return []
    n = int(round(len(roster) * percent / 100.0))
    n = max(0, min(len(roster), n))
    if n <= 0:
        return []
    r = random.Random('top|%s' % seed)

    def score(b):
        o = ((b.get('personality') or {}).get('traits') or {})
        return (o.get('ambition', 0) * 0.55 + o.get('rivalry', 0) * 0.35 + o.get('patience', 0) * 0.1, r.random())

    chosen = sorted(roster, key=score, reverse=True)[:n]
    for b, role in zip(chosen, roles(n)):
        b['top'] = role
    return chosen


def apply(k, source, step):
    """Writes the variant onto a bot record. The purse is enough to play, not the player's bank."""
    v = apply_step(source, step if step in ('upper', 'lower', 'close') else 'close')
    k['gear'] = v['gear']
    k['level'] = v['level']
    k['ep'] = v['ep']
    k['formation'] = v['formation']
    k['formations'] = list(v['formations'])
    k['credits'] = 40000 + 12000 * v['level']
    k['uridium'] = 2000 + 350 * v['level']
    k.setdefault('stock', {})
    # x4 is not in the shop (gates and booty). The top slice starts with a combat stock;
    # a tree in the save is copied, otherwise skill_build.spend fills one from the level.
    st = k['stock']
    st['ammunition_laser_lcb-10'] = max(int(st.get('ammunition_laser_lcb-10', 0)), 8000)
    st['ammunition_laser_ucb-100'] = max(int(st.get('ammunition_laser_ucb-100', 0)), 12000)
    st['ammunition_laser_rsb-75'] = max(int(st.get('ammunition_laser_rsb-75', 0)), 1500)
    st['ammunition_rocket_plt-2026'] = max(int(st.get('ammunition_rocket_plt-2026', 0)), 250)
    st['ammunition_rocketlauncher_eco-10'] = max(int(st.get('ammunition_rocketlauncher_eco-10', 0)), 120)
    if not k['gear'].get('launcher'):
        k['gear']['launcher'] = 'equipment_weapon_rocketlauncher_hst-1'
    if v.get('skills'):
        k['skills'] = {'level': dict(v['skills']), 'points': 0, 'converted': 0, 'level_points': 0}
        k['skills_copied'] = True
    else:
        k.pop('skills_copied', None)
    if v.get('drone_level'):
        k['drone_level'] = int(v['drone_level'])
    k['top_applied'] = step
    return v


def save_source():
    """The active save's profile -> a reference, or None (no save: the slice is not built, the roster stays as it was)."""
    import paths as PTH
    path = PTH.profile_path()
    if not path or not os.path.isfile(path):
        return None
    try:
        with open(path, encoding='utf8') as fh:
            d = json.load(fh)
    except (OSError, ValueError):
        return None
    return from_save(d)


def on_server(y, force=False):
    """Dresses a new bot (or, in simple mode, every launch) in the save's variant. A saved bot that has progressed is left alone."""
    source = y.package.get('top_source')
    if not source:
        return 0
    by_no = {x.get('no'): x for x in y.package.get('roster') or []}
    n = 0
    for b in y.bots:
        row = by_no.get(b.k.get('no'))
        if not row or not row.get('top'):
            continue
        if not force and b.k.get('top_applied'):
            continue
        apply(b.k, source, row['top'])
        from . import skill_build as SK
        SK.spend(b)
        b.loadout_changed()
        n += 1
    return n
