"""Smarter play: a better player's decisions while grinding, spending and in PvP.

Pack setting ``smart`` (on by default, Behavior in the panel). When off, these functions are not called
and the bot stays as it was.

Grinding  ammo and map by net uridium (the same cost as uridium_rate.Meter: the shop price of the round fired).
          Expensive ammo stays unused when it costs more than it earns.
Spending  a real order: repair bot, a laser that fills a slot, Iris (Flax does not fill the hangar), an empty
          generator, a ship it can fill, a formation. A small reserve is kept for ammo.
PvP       EMP and a mine are not used together on every escape. SAB only when its own shield is low and the
          target still has shield to drain; otherwise hull ammo. x4 (UCB-100) is the sustained PvP round
          when the stock is there. It is not sold in the shop.
"""
import zlib

from . import catalog as K

RATE = 100


def enabled(bot):
    """Is smarter play on. Missing flag means on (the new behavior is the default)."""
    v = getattr(bot, 'smart', None)
    return True if v is None else bool(v)


def _style(bot):
    """0 saves EMP, 1 likes mines, 2 leads with Insta-Shield. Fixed per bot."""
    return zlib.crc32(('pvp|%s' % bot.name).encode()) % 3


def _score(c):
    """Gain / credit equivalent. Wealth is not in the denominator, so a million saved does not bury Iris."""
    return c[0] / max(1.0, c[2] * (RATE if c[1] == 'U' else 1))


def reserve(bot):
    """Ammo purse (credits, uridium). Shopping does not spend it; a thrifty bot keeps a slightly larger purse."""
    from . import weapons as WP
    t = bot.o('frugality')
    credits = WP.hourly_ammo(bot) * 10 * (0.12 + 0.22 * t)
    uridium = 350 + 900 * t
    return credits, uridium


def _money(bot):
    credits, uridium = reserve(bot)
    return {'C': bot.k['credits'] - credits - bot.clan_savings(), 'U': bot.k['uridium'] - uridium}


def _can_buy(money, c):
    return money.get(c[1], 0) >= c[2]


def _firing_share(dps, ehp):
    if dps <= 0:
        return 0.2
    ttk = max(1.0, ehp) / dps
    return min(0.72, max(0.12, ttk / (ttk + K.SEARCH_SEC + 6.0)))


def map_net(bot, map_id, value, courage):
    """The most profitable laser ammo on this map -> (net uridium/hour, loot, evaluation)."""
    from . import weapons as WP
    base = K.ITEMS['laser_ammo'].get(bot.k['gear'].get('ammunition'), {}).get('multiplier', 1) or 1
    dps1 = value['dps'] * (1 + value.get('npc_damage', 0)) / base
    nlas = max(1, value.get('laser') or 1)
    ehp_bot = max(1.0, value['ehp'])
    best = None
    for loot in (WP.LCB, WP.MCB25, WP.MCB50):
        dps = dps1 * (WP.multiplier(loot) or 1)
        r = K.evaluate_map(map_id, dps, ehp_bot, courage)
        kills = r.get('kills') or {}
        total = share = 0.0
        for tip, per_hour in kills.items():
            nv = K.npc_value(tip)
            if nv and per_hour:
                total += nv['ehp'] * per_hour
                share += per_hour
        mean_ehp = total / share if share else 8000.0
        unit = 0.0
        f = WP.price(loot)
        if f and f[0] == 'U':
            unit = float(f[1])
        cost = (3600.0 / K.LASER_INTERVAL) * nlas * _firing_share(dps, mean_ehp) * unit
        net = r['uridium_per_hour'] - cost - r['deaths_per_hour'] * 160.0
        if not r['targets'] and loot != WP.LCB:
            continue
        if best is None or net > best[0]:
            best = (net, loot, r)
    if best is None:
        r = K.evaluate_map(map_id, dps1, ehp_bot, courage)
        return r['uridium_per_hour'], WP.LCB, r
    return best


def laser(bot, ehp=0.0, pvp=False, shield=0.0, own=1.0):
    """Ammo from stock. Net uridium in PvE. In PvP, SAB only to refill its own shield; otherwise hull ammo."""
    from . import weapons as WP
    s = WP.stock(bot)
    if pvp:
        return _pvp_laser(bot, s, shield, own)
    courage = max(0.0, min(1.0, 0.3 + 0.6 * bot.o('risk') + 0.2 * bot.mood['confidence'] - 0.3))
    _net, plan, _r = map_net(bot, bot.game_map, bot.value(), courage)
    if ehp and plan == WP.LCB and s.get(WP.MCB25, 0) > 0:
        dps1 = bot.value()['dps'] / (K.ITEMS['laser_ammo'].get(bot.k['gear'].get('ammunition'), {}).get('multiplier', 1) or 1)
        if dps1 > 0 and ehp / dps1 > 50:
            nlas = max(1, bot.value().get('laser') or 1)
            gap = ehp / dps1 - ehp / (dps1 * 2)
            bill = (gap / K.LASER_INTERVAL) * nlas * 0.5
            if gap > bill * 8:
                plan = WP.MCB25
    if s.get(plan, 0) > 0:
        return plan
    for loot in (WP.LCB, WP.MCB25, WP.MCB50, WP.UCB, WP.RSB):
        if s.get(loot, 0) > 0:
            return loot
    return None


def _pvp_laser(bot, s, shield, own):
    """x4 is the sustained PvP round when at least 200 are in stock. SAB only to refill its own shield."""
    from . import weapons as WP
    style = _style(bot)
    if _sab_needed(bot, shield, own) and s.get(WP.SAB, 0) > 0:
        return WP.SAB
    if s.get(WP.UCB, 0) >= 200:
        return WP.UCB
    if style == 1 and s.get(WP.RSB, 0) > 0:
        return WP.RSB
    for c in (WP.MCB50, WP.MCB25, WP.RSB, WP.LCB):
        if s.get(c, 0) > 0:
            return c
    return None


def _sab_needed(bot, target_shield, own):
    """Own shield is damaged and the target still has shield to drain. A full shield does not want SAB."""
    if target_shield <= 0.2 or own >= 0.82:
        return False
    threshold = 0.32 + 0.28 * (1 - bot.o('frugality')) + 0.06 * (_style(bot) - 1)
    return own < threshold


def rocket(bot, pvp=False):
    """Uridium rockets are not burned while grinding. In PvP, the strongest one in hand."""
    from . import weapons as WP
    if not bot.permission.get('rocket', True):
        return None
    s = WP.stock(bot)
    owned = [r for r in reversed(WP.ROCKETS) if s.get(r, 0) > 0]
    if pvp:
        return owned[0] if owned else None
    for r in owned:
        f = WP.price(r)
        if not f or f[0] != 'U':
            return r
    return None


def resupply(bot):
    """LCB-10 is mandatory. Uridium ammo only when the map plan selects it and it does not delay the next Iris."""
    from . import weapons as WP
    if not bot.permission.get('shop', True):
        return {}
    s = WP.stock(bot)
    t = bot.o('frugality')
    hourly = WP.hourly_ammo(bot)
    bought = {}

    def buy(loot, count, share):
        f = WP.price(loot)
        if not f:
            return
        purse = 'credits' if f[0] == 'C' else 'uridium'
        budget = bot.k[purse] * share
        count = int(min(count, budget // max(float(f[1]), 1e-9)))
        if count > 0 and bot.pay(f[0], count * f[1]):
            WP.add(bot, loot, count)
            bought[loot] = count

    if s.get(WP.LCB, 0) < hourly * (0.45 + 0.4 * t):
        buy(WP.LCB, hourly * (1.5 + t), 0.45)
    if bot.permission.get('rocket', True) and sum(s.get(r, 0) for r in WP.ROCKETS[:2]) < 40:
        for r in (WP.ROCKETS[1], WP.ROCKETS[0]):
            f = WP.price(r)
            if f and f[0] == 'C' and bot.k['credits'] > f[1] * 80:
                buy(r, 80 + 120 * (1 - t), 0.08)
                break
    courage = max(0.0, min(1.0, 0.3 + 0.6 * bot.o('risk')))
    _net, plan, _r = map_net(bot, bot.game_map, bot.value(), courage)
    iris = _iris_price(bot)
    before_iris = iris is not None and bot.k['uridium'] < iris[1] * (1.15 + 0.4 * t)
    if not before_iris and plan == WP.MCB25 and s.get(WP.MCB25, 0) < 400 and bot.k['uridium'] > 2500:
        buy(WP.MCB25, 800 + 400 * (1 - t), 0.08)
    if not before_iris and plan == WP.MCB50 and s.get(WP.MCB50, 0) < 300 and bot.k['uridium'] > 8000:
        buy(WP.MCB50, 600, 0.06)
    if (not before_iris and bot.permission.get('pvp', True) and bot.o('aggression') > 0.55 and bot.level >= 8
            and s.get('ammunition_specialammo_emp-01', 0) < 2 and bot.k['uridium'] > 12000):
        buy('ammunition_specialammo_emp-01', 3, 0.04)
    if (not before_iris and bot.permission.get('mine', True) and bot.o('aggression') + bot.o('risk') > 0.9
            and bot.level >= 8 and sum(s.get(m, 0) for m in WP.MINES) < 4 and bot.k['uridium'] > 10000):
        buy(WP.MINES[0], 8, 0.04)
    if bought:
        bot.ist('resupply')
    return bought


def _iris_price(bot):
    drones = bot.k['gear'].get('drone') or {}
    n = drones.get('drone_iris', 0)
    if n >= 8:
        return None
    if sum(drones.values()) >= K.ITEMS['max_drones'] and drones.get('drone_flax', 0) < 1:
        return None
    return K.price('drone_iris', n)


def prepare_purchase(bot):
    """If the hangar is full of Flax and Iris is affordable, one Flax is dropped (2 slots beat 1)."""
    if not enabled(bot):
        return False
    drones = bot.k['gear'].setdefault('drone', {})
    if sum(drones.values()) < K.ITEMS['max_drones'] or drones.get('drone_flax', 0) < 1:
        return False
    f = _iris_price(bot)
    if not f or not _can_buy(_money(bot), (0, f[0], f[1], 'drone_iris')):
        return False
    drones['drone_flax'] -= 1
    if drones['drone_flax'] <= 0:
        del drones['drone_flax']
    bot.loadout_changed()
    bot.event('sold_drone', item='drone_flax')
    return True


def _uridium_locked(bot, money):
    """Until the first Iris, uridium does not go to a ship, a generator or a CPU."""
    f = _iris_price(bot)
    if not f:
        return False
    iris_n = (bot.k['gear'].get('drone') or {}).get('drone_iris', 0)
    if iris_n < 1:
        return True
    if money['U'] >= f[1]:
        return False
    from .goals.shopping import income
    horizon = 0.7 + bot.o('frugality')
    return f[1] <= bot.k['uridium'] + income(bot)['U'] * horizon


def purchase(bot):
    """(buy now, saving for) in the same shape as shopping.candidate."""
    from . import extras as EX
    from .goals.shopping import candidates
    all_items = candidates(bot)
    if not all_items and _iris_price(bot) is None:
        return None, None
    money = _money(bot)
    locked = _uridium_locked(bot, money)
    power = max(1.0, bot.value()['power'])

    def ok(c, uridium_free=True):
        if not _can_buy(money, c):
            return False
        if not uridium_free and c[1] == 'U':
            return False
        return True

    def best(lst):
        return max(lst, key=_score) if lst else None

    iris_n = (bot.k['gear'].get('drone') or {}).get('drone_iris', 0)
    if EX.repair_level(bot) == 0:
        rep = [c for c in all_items if c[3] in EX.ORDER and ok(c) and (iris_n >= 1 or c[1] != 'U')]
        if rep:
            return best(rep), None
    lasers = _laser_candidates(bot, all_items, money)
    if lasers:
        return best(lasers), None
    drone = _drone_candidate(bot, all_items, money, power)
    if drone:
        return drone, None
    if bot.value().get('gen', 0) < bot.value().get('gen_slot', 0):
        gens = [c for c in all_items if (c[3] in K.ITEMS['shield_generators'] or c[3] in K.ITEMS['speed_generators'])
                and ok(c, not locked)]
        if gens:
            return best(gens), None
    formation = _formation(bot, money, locked)
    if formation:
        return formation, None
    design = _design(bot, money, locked, power)
    if design:
        return design, None
    ships = [c for c in all_items if c[3].startswith('ship_') and '_design' not in c[3] and ok(c, not locked) and _ship_ok(bot, c[3])]
    if ships:
        return best(ships), None
    other = []
    for c in all_items:
        if not ok(c, not locked) or c[0] < 0.25:
            continue
        if c[3] in ('drone_apis', 'drone_zeus') and iris_n < 4 and _iris_price(bot):
            continue
        if c[3] in EX.ORDER or c[3].startswith('ship_') or c[3] in ('drone_flax', 'drone_iris'):
            continue
        if c[3] in K.ITEMS['lasers'] or c[3] in K.ITEMS['shield_generators'] or c[3] in K.ITEMS['speed_generators']:
            continue
        other.append(c)
    chosen = best(other)
    saving = _saving(bot, all_items, money)
    if chosen is None and bot.r.random() < 0.04 * (1 - bot.o('frugality')):
        owned = [c for c in all_items if ok(c, not locked) and not c[3].startswith('ship_') and c[3] != 'drone_flax'
                 and 'sll-' not in c[3] and 'mp-1' not in c[3]]
        chosen = bot.r.choice(owned) if owned else None
    return chosen, saving


def _laser_candidates(bot, all_items, money):
    lasers = K.ITEMS['lasers']
    iris_n = (bot.k['gear'].get('drone') or {}).get('drone_iris', 0)
    owned = [c for c in all_items if c[3] in lasers and not lasers[c[3]].get('pet_only') and _can_buy(money, c)]
    have = bot.k['gear'].get('laser') or {}
    good = sum(v for k, v in have.items() if k.rsplit('_', 1)[-1] in ('lf-2', 'lf-3', 'lf-4', 'lf-5'))
    uridium = [c for c in owned if c[1] == 'U' and 'laser_lf-' in c[3]]
    if iris_n < 1:
        uridium = [] if good >= 2 else [c for c in uridium if c[3].rsplit('_', 1)[-1] == 'lf-2']
    elif good >= 2:
        uridium = [c for c in uridium if c[3].rsplit('_', 1)[-1] != 'lf-2']
    d = bot.value()
    empty = d.get('laser', 0) < d.get('laser_slots', 1)
    fitted = K.outfit(bot.k['gear'], bot.shield_share())['laser']
    weakest = min(fitted) if fitted else 0

    def keep(candidates, empty_only):
        if not candidates:
            return []
        top = max(lasers[c[3]]['damage'] for c in candidates)
        out = []
        for c in candidates:
            damage = lasers[c[3]]['damage']
            if damage < top * 0.9:
                continue
            if not empty and damage < weakest * 1.18:
                continue
            if empty_only and not empty:
                continue
            out.append(c)
        return out

    chosen = keep(uridium, False)
    if chosen:
        return chosen
    credits = [c for c in owned if c[1] == 'C' and 'mp-1' not in c[3]]
    return keep(credits, True)


def _drone_candidate(bot, all_items, money, power):
    iris = [c for c in all_items if c[3] == 'drone_iris' and _can_buy(money, c)]
    if iris:
        return max(iris, key=_score)
    f = _iris_price(bot)
    drones = bot.k['gear'].get('drone') or {}
    if f and _can_buy(money, (0, f[0], f[1], 'drone_iris')) and sum(drones.values()) >= K.ITEMS['max_drones'] and drones.get('drone_flax', 0) >= 1:
        return (max(1.0, power * 0.12), f[0], f[1], 'drone_iris')
    if drones.get('drone_flax', 0) < 2:
        flax = [c for c in all_items if c[3] == 'drone_flax' and c[2] <= 250000 and _can_buy(money, c)]
        if flax and not iris:
            return max(flax, key=_score)
    return None


def _ship_ok(bot, loot):
    ship = K.ITEMS['ships'].get(loot) or {}
    owned = sum((bot.k['gear'].get('laser') or {}).values())
    new = ship.get('laser') or 0
    if new > owned + 2:
        return False
    return True


def _design(bot, money, locked, power):
    """One Havoc or Hercules, only if the shop still sells it."""
    from . import appearance as AP
    if locked:
        return None
    AP.place_designs(bot)
    n = sum((bot.k['gear'].get('drone') or {}).values())
    if n < 2:
        return None
    loot = AP.drone_preference(bot)
    if AP.designs_missing(bot, loot) <= 0:
        return None
    f = K.price(loot)
    if not f or not _can_buy(money, (0, f[0], f[1], loot)):
        return None
    return (max(0.4, power * 0.06), f[0], f[1], loot)


def _formation(bot, money, locked):
    n = sum((bot.k['gear'].get('drone') or {}).values())
    if n < 4:
        return None
    owned = set(bot.k.get('formations') or ())
    if bot.o('risk') < 0.34:
        order = ('drone_formation_f-01-tu', 'drone_formation_f-02-ar')
    elif bot.archetype in ('grinder', 'trader') or bot.o('ambition') > 0.62:
        order = ('drone_formation_f-3d-dr',)
    elif bot.o('aggression') > 0.65:
        order = ('drone_formation_f-02-ar', 'drone_formation_f-05-pi', 'drone_formation_f-01-tu')
    else:
        order = ('drone_formation_f-02-ar', 'drone_formation_f-01-tu')
    rules = K.ITEMS.get('formation_rules') or {}
    power = max(1.0, bot.value()['power'])
    for loot in order:
        if loot in owned:
            continue
        rule = rules.get(loot) or {}
        if rule.get('calendar') or n < rule.get('min_drones', 0):
            continue
        f = K.price(loot)
        if not f or (locked and f[0] == 'U') or not _can_buy(money, (0, f[0], f[1], loot)):
            continue
        bonus = K.ITEMS['formations'].get(loot) or {}
        gain = power * (0.45 * max(0.0, bonus.get('laser', 0)) + 0.4 * max(0.0, bonus.get('npc', 0) + bonus.get('npc_laser', 0))
                        + 0.2 * max(0.0, bonus.get('shield', 0)) + 0.08)
        return (max(gain, 0.4), f[0], f[1], loot)
    return None


def _saving(bot, all_items, money):
    f = _iris_price(bot)
    if f and not _can_buy(money, (0, f[0], f[1], 'drone_iris')):
        return (1.0, f[0], f[1], 'drone_iris')
    left = [c for c in all_items if not _can_buy(money, c) and c[0] > 0.5]
    return max(left, key=lambda c: c[0], default=None)


def apply_formation(bot, d):
    """The selected formation's combat share. NPC damage is a separate key used while grinding."""
    loot = bot.k.get('formation') or ''
    owned = bot.k.get('formations') or ()
    if not loot or (loot != 'drone_formation_default' and loot not in owned):
        d.setdefault('npc_damage', 0.0)
        return d
    f = K.ITEMS['formations'].get(loot) or {}
    d['dps'] *= max(0.25, 1 + f.get('laser', 0))
    d['hp'] *= max(0.25, 1 + f.get('hp', 0))
    d['shield'] *= max(0.0, 1 + f.get('shield', 0))
    d['speed'] *= max(0.25, 1 + f.get('speed', 0))
    d['absorb'] = min(0.95, d.get('absorb', 0) + f.get('absorb', 0))
    d['ehp'] = d['hp'] + d['shield'] * 2.5 * min(1.0, d['absorb'] + 0.2)
    d['npc_damage'] = f.get('npc', 0) + f.get('npc_laser', 0)
    d['power'] = K.power_score(d['dps'], d['ehp'])
    return d


def _pvp_power(bot):
    from . import extras as EX
    from . import technology as TECH
    return max(0.5, bot.value()['power']) * EX.pvp_factor(bot) * TECH.pvp_factor(bot)


def _skill(bot, ratio):
    if not enabled(bot):
        return 0.0
    from . import extras as EX
    s = 0.03
    if 0.72 < ratio < 1.4:
        s += 0.07 + 0.04 * bot.o('rivalry')
        if EX.var(bot, EX.ISH):
            s += 0.03
    elif ratio >= 1.4:
        s += 0.02
    return s


def win_chance(a, b):
    """a's chance of winning the duel. On equal gear the smarter side is about 60-65%."""
    ga, gb = _pvp_power(a), _pvp_power(b)
    pa = ga ** 1.5 / (ga ** 1.5 + gb ** 1.5)
    pa = 0.08 + 0.84 * pa
    pa += _skill(a, ga / gb) - _skill(b, gb / ga)
    return min(0.93, max(0.07, pa))


def encounter(a, b, y, now):
    """abstract_sim.encounter when either bot is playing smarter."""
    from . import extras as EX
    from . import weapons as WP
    from . import abstract_sim as S
    ga, gb = _pvp_power(a), _pvp_power(b)
    ratio = gb / ga
    if ratio < 0.62 and b.r.random() < 1 - b.o('risk') and EX.cloak(b):
        b.ist('hidden')
        return ('fled', b, a)
    mine_b = WP.pick_mine(b)
    if enabled(b):
        flee = ratio < 0.84 and b.r.random() < (0.2 + 0.75 * (1 - b.o('risk')) * (1 - ratio) - 0.25 * b.mood['anger'])
        mined = False
        if flee and mine_b and b.r.random() < (0.35 if _style(b) == 0 else 0.7):
            mined = bool(WP.spend(b, mine_b, 1))
        faster = 0.28 * (b.value()['speed'] > a.value()['speed'])
        if flee and b.r.random() < 0.38 + faster + 0.18 * mined:
            b.memory.event(a.name, 'insult', now, multiplier=0.5)
            b.mood.it(anger=0.1, confidence=-0.05)
            return ('fled', b, a)
    else:
        flee = ratio < 0.8 and b.r.random() < (1 - b.o('risk')) * (1 - ratio) + 0.2 * (1 - b.o('aggression'))
        if flee and b.r.random() < 0.55 + 0.25 * (b.value()['speed'] > a.value()['speed']) + 0.15 * bool(mine_b and WP.spend(b, mine_b, 1)):
            b.memory.event(a.name, 'insult', now, multiplier=0.5)
            b.mood.it(anger=0.1, confidence=-0.05)
            return ('fled', b, a)
    pa = win_chance(a, b)
    winner, loser = (a, b) if a.r.random() < pa else (b, a)
    S.pvp_reward(winner, loser, y, now)
    S.death(loser, y, reason='player', killer=winner.name, now=now)
    return ('won', winner, loser)


def escape_items(w, n, now):
    """While fleeing: EMP, mine, cloak, Insta-Shield by the situation, not all three at once."""
    from . import active_items as AC
    from . import ship as SH
    b = n.bot
    d = b.value()
    ratio = (n.hp + n.shield) / max(1, d['hp'] + d['shield'])
    style = _style(b)
    players = [u for u, t in n.attacker.items() if now - t < 6 and SH._player(w, u) is not None]
    bots = [u for u, t in n.attacker.items() if now - t < 6 and u in w.npcs and w.npcs[u].bot is not None]
    if not players and not bots:
        return
    crowd = len(players) + len(bots) >= 2
    close = _close(w, n, now, players + bots, 650)
    if style == 1:
        emp = ratio < 0.22 or crowd
    elif style == 2:
        emp = (ratio < 0.35 or crowd) and b.r.random() < 0.55
    else:
        emp = ratio < 0.38 or crowd or (close and b.r.random() < 0.45)
    if emp and (players or bots):
        AC.emp(w, n, now)
    if ratio < 0.3 and style != 0 and b.r.random() < 0.75:
        AC.insta_shield(w, n, now)
    elif ratio < 0.18 and b.r.random() < 0.5:
        AC.insta_shield(w, n, now)
    if b.o('risk') < 0.55 and b.r.random() < (0.45 if style == 2 else 0.75):
        AC.cloak(w, n, now)
    if close and b.r.random() < (0.8 if style == 1 else 0.45):
        nx, ny = n.mover.pos(now)
        SH.drop_mine(w, n, nx, ny, now)


def in_fight(w, n, now, ratio, attackers):
    """During a fight: EMP when the shield drops, Insta-Shield as the hull melts."""
    from . import active_items as AC
    from . import ship as SH
    b = n.bot
    players = [u for u in attackers if SH._player(w, u) is not None or (u in w.npcs and w.npcs[u].bot is not None)]
    pvp_target = n.target is not None and ((n.target in w.npcs and w.npcs[n.target].bot is not None) or SH._player(w, n.target) is not None)
    if not players and not pvp_target:
        return
    style = _style(b)
    if ratio > 0.72 and not (len(players) >= 2):
        return
    if n.shield <= 0 and 0.3 < ratio < 0.7 and style != 1 and b.r.random() < 0.55 + 0.25 * b.o('rivalry'):
        AC.emp(w, n, now)
        return
    if len(players) >= 2 and ratio < 0.55 and b.r.random() < 0.7:
        AC.emp(w, n, now)
        return
    if ratio < 0.34 and b.r.random() < (0.8 if style == 2 else 0.45):
        AC.insta_shield(w, n, now)


def _close(w, n, now, uids, reach):
    from . import ship as SH
    if not uids:
        return False
    nx, ny = n.mover.pos(now)
    for u in uids:
        pos = SH._position(w, u, now)
        if pos and (pos[0] - nx) ** 2 + (pos[1] - ny) ** 2 <= reach ** 2:
            return True
    return False


def hp_ratio(w, uid):
    """The target's remaining HP+shield share (1: full)."""
    from . import ship as SH
    o = SH._player(w, uid)
    if o is not None:
        g = o.p.d.get('ship') or {}
        mx = (g.get('hitMax') or 0) + (g.get('shieldMax') or 0)
        return ((g.get('hitPoints') or 0) + (g.get('shield') or 0)) / mx if mx else 1.0
    m = w.npcs.get(uid)
    if m is not None and m.bot is not None:
        d = m.bot.value()
        return (m.hp + m.shield) / max(1, d['hp'] + d['shield'])
    return 1.0
