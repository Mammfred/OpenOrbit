"""Galaxy Gates: the generator (energy, spin, part, multiplier) and the gate run (the player's rules and tables: galaxy_gates.py,
data/gates.json).

  energy    comes from bonus boxes and rewards (resource_extra-energy); otherwise 100 U per spin (quester and rich bots)
  spin      the probabilities are the game's: ammo 67, Xenomit 12, voucher 3, part 13, Nano Hull 4, daily disc 1; the part of Alpha/Beta/Gamma
            goes to one of the three; a duplicate part raises the multiplier (up to 5), with the game's "duplicate to the missing one" share
  run       when a gate is built the bot (if strong enough) moves to the gate map (leaves your map); time and success come from the
            waves' aliens: total HP / the bot's damage, damage taken / the bot's HP x number of lives. On success the gate's reward and its
            aliens' kill rewards; on failure the gate (with its parts) is lost. The Kronos part comes from the other gates.
State bot.k['kapi'] = {'parca': {gate: count}, 'kurulu': [gate ...], 'carpan': n, 'kronos': count}.
"""
import json, math, os, random

from . import catalog as K

D = json.load(open(os.path.join(K.HERE, 'data', 'gates.json'), encoding='utf8'))
GATES = D['gates']
ABG = ('alpha', 'beta', 'gamma')
ORDER = ('alpha', 'beta', 'gamma', 'lambda', 'hades', 'delta', 'epsilon', 'kappa', 'zeta', 'streuner')


def _sources():
    """Chance-table item -> gates. A first-clear guarantee and a higher probability come first."""
    found = {}
    for key, gate in GATES.items():
        reward = gate.get('reward') or {}
        if not isinstance(reward, dict):
            continue
        for row in reward.get('chance') or []:
            loot = row.get('item')
            if not loot or not isinstance(loot, str):
                continue
            found.setdefault(loot, []).append((0 if row.get('first_guaranteed') else 1, -float(row.get('probability') or 0), key))
    out = {}
    for loot, rows in found.items():
        rows.sort()
        seen = []
        for row in rows:
            if row[2] not in seen:
                seen.append(row[2])
        out[loot] = tuple(seen)
    return out


SOURCE = None


def sources():
    global SOURCE
    if SOURCE is None:
        SOURCE = _sources()
    return SOURCE
ENERGY = 'resource_extra-energy'
PROBABILITY = {c: w for c, w in D['probability']}            # 1 ammo, 2 resource, 3 voucher, 4 part, 5 special, 6 log
_difficulty = {}


def state(bot):
    return bot.k.setdefault('gate', {'part': {}, 'built': [], 'multiplier': 0, 'kronos': 0})


def stock(bot):
    from . import weapons as WP
    return WP.stock(bot)


def difficulty(gate):
    """The gate's waves -> ([(wave's total HP+shield, damage per second of those hitting at the same time)], kill rewards)."""
    if gate in _difficulty:
        return _difficulty[gate]
    import ast
    waves = GATES[gate].get('waves') or []
    if isinstance(waves, str):
        waves = ast.literal_eval(waves)
    out, reward = [], {}
    for d in waves:
        ehp = dps = 0.0
        for u in d.get('alien_spawns', []):
            n = u.get('count', 1)
            ehp += n * (u.get('hp', 0) + u.get('shield', 0))
            dps += min(n, 2) * u.get('damage', 0) * K.COMBAT['npc_hit_chance'] * 0.6 / K.NPC_INTERVAL  # the player pulls them one by one, escapes out of range
            for k, v in (u.get('reward') or {}).items():
                reward[k] = reward.get(k, 0) + v * n
        out.append((ehp, dps))
    _difficulty[gate] = (out, reward)
    return _difficulty[gate]


def estimate(bot, gate):
    """Run estimate -> (time s, expected number of deaths). In a gate players use their best ammo (the strongest in stock x2-x4);
    between waves the shield refills and the ship is repaired."""
    from . import weapons as WP
    waves, _ = difficulty(gate)
    d = bot.value()
    s = WP.stock(bot)
    multiplier = max([WP.multiplier(c) for c in ('ammunition_laser_ucb-100', WP.MCB50, WP.MCB25, WP.LCB) if s.get(c, 0) > 1000] or [1])
    dps = max(1.0, d['dps'] * multiplier * 1.15)                 # rockets
    duration = death = 0.0
    for ehp, incoming_dps in waves:
        t = ehp / dps
        duration += t
        death += t * incoming_dps / max(1.0, d['ehp'] * 3)
    return duration, death


# ------------------------------------------------------------------------------------------------------------ generator
def draw(bot, gate, n):
    """n spins (energy first, then 100 U) -> the number done."""
    st = state(bot)
    s = stock(bot)
    crafted = 0
    for _ in range(n):
        if s.get(ENERGY, 0) > 0:
            s[ENERGY] -= 1
        elif not bot.pay('U', D['energy_price'] * bot.game_settings.multiplier('shop_price')):
            break
        crafted += 1
        _draw(bot, st, gate)
        if gate in st['built'] or (gate in ABG and all(k in st['built'] for k in ABG)):
            break
    if s.get(ENERGY) == 0:
        s.pop(ENERGY, None)
    if crafted:
        bot.ist('gate_draw', crafted)
    return crafted


def _draw(bot, st, gate):
    from . import weapons as WP
    r = bot.r
    cat = r.choices(list(PROBABILITY), weights=list(PROBABILITY.values()))[0]
    if cat == 4:
        k = r.choice([x for x in ABG if x not in st['built']] or [gate]) if gate in ABG else gate
        total = GATES[k]['part']
        var = st['part'].get(k, 0)
        missing = (total - var) / total
        new_ = r.random() < missing + (1 - missing) * 0.5 or st['multiplier'] >= D['max_multiplier']
        if new_:
            earn = 1 + (st['multiplier'] if st['multiplier'] >= D['max_multiplier'] else 0)
            st['multiplier'] = 0 if earn > 1 else st['multiplier']
            st['part'][k] = min(total, var + earn)
            if st['part'][k] >= total and k not in st['built']:
                st['built'].append(k)
                bot.event('gate_set_up', gate=GATES[k]['name'])
        else:
            st['multiplier'] = min(D['max_multiplier'], st['multiplier'] + 1)
        return
    if cat == 1:
        loot, _, count = r.choice(D['ammunition'])
        WP.add(bot, loot, count)
    elif cat == 2:
        bot.k.setdefault('cargo', {})
        bot.k['cargo']['3'] = bot.k['cargo'].get('3', 0) + r.randint(*D['xenomit'])
    elif cat == 3:
        stock(bot)['resource_jumpvoucher'] = stock(bot).get('resource_jumpvoucher', 0) + 1
    elif cat == 6:
        stock(bot)['resource_logfile'] = stock(bot).get('resource_logfile', 0) + 1


def wanted_gate(bot):
    """If the preferred design is not in the shop and the set is short, the gate the bot can clear.
    If it is for sale, None: it is bought and the gate order does not change."""
    from . import appearance as AP
    if not bot.permission.get('gate', True) or AP.drone_count(bot) < 1:
        return None
    AP.place_designs(bot)
    loot = AP.drone_preference(bot)
    if K.price(loot) or AP.designs_missing(bot, loot) <= 0:
        return None
    for key in sources().get(loot) or ():
        gate = GATES.get(key)
        if not gate or gate.get('not_producible'):
            continue
        if estimate(bot, key)[1] < gate['hp']:
            return key
    return None


def target_gate(bot):
    """The gate to collect parts for. A design gate (if the bot can clear it) jumps the queue; otherwise the players' order."""
    st = state(bot)
    priority = wanted_gate(bot)
    order = ((priority,) + ORDER) if priority else ORDER
    seen = set()
    for k in order:
        if not k or k in seen:
            continue
        seen.add(k)
        if k in st['built'] or GATES[k].get('not_producible'):
            continue
        if estimate(bot, k)[1] < GATES[k]['hp'] * 1.5:
            return k
    return None


def generator(bot):
    """At decision time: spins if it has energy; a quester and a rich bot also with uridium (permission 'gate', from level 10)."""
    if not bot.permission.get('gate', True) or bot.level < 10:
        return 0
    k = target_gate(bot)
    if not k:
        return 0
    n = stock(bot).get(ENERGY, 0)
    t = bot.o('frugality')
    price = D['energy_price']
    if bot.o('ambition') + bot.o('rivalry') > 1.1 and bot.k['uridium'] > price * 300 * (1 + 2 * t):
        n += int(bot.k['uridium'] * 0.15 // price)
    elif wanted_gate(bot) == k:
        # a cautious bot also spins for the set; it keeps an ammo purse, at most 40 spins per decision
        spare = price * (40 + 100 * t)
        extra = bot.k['uridium'] - spare
        if extra > price * 10:
            n += int(min(extra * 0.2, price * 40) // price)
    return draw(bot, k, min(n, 200)) if n else 0


# ------------------------------------------------------------------------------------------------------------ run
def run_result(bot, gate, rng=random):
    """Result of the run -> (did it succeed, time s)."""
    duration, death = estimate(bot, gate)
    death = rng.gauss(death, 0.3 * death + 0.2)
    return death < GATES[gate]['hp'], duration * rng.uniform(1.1, 1.6) + 120


def grant_reward(bot, gate, speed=1.0):
    """The gate's completion reward and its aliens' kill rewards; the Kronos part."""
    from . import weapons as WP
    o = GATES[gate].get('reward') or {}
    if isinstance(o, str):
        import ast
        o = ast.literal_eval(o)
    _, aliens = difficulty(gate)
    bot.reward('quest', speed, ep=o.get('ep', 0) + aliens.get('ep', 0), honor=o.get('honor', 0) + aliens.get('honor', 0),
             uridium=o.get('uridium', 0) + aliens.get('uridium', 0), credits=aliens.get('credits', 0))
    for loot, n in (o.get('ammunition') or {}).items():
        WP.add(bot, loot, n)
    if o.get('xenomit'):
        bot.k.setdefault('cargo', {})
        bot.k['cargo']['3'] = bot.k['cargo'].get('3', 0) + o['xenomit']
    s = stock(bot)
    for loot, n in (('resource_logfile', o.get('log_disk', 0)), ('resource_jumpvoucher', o.get('voucher', 0)),
                    ('resource_booty-key', (o.get('booty') or {}).get('green_key', 0))):
        if n:
            s[loot] = s.get(loot, 0) + n
    st = state(bot)
    _chance(bot, o.get('chance'), gate not in st.get('done', []))
    if gate != 'kronos':
        st['kronos'] = min(GATES['kronos']['part'], st['kronos'] + 1)
        if st['kronos'] >= GATES['kronos']['part'] and 'kronos' not in st['built']:
            st['built'].append('kronos')
    if gate not in st.setdefault('done', []):
        st['done'].append(gate)                      # gate ring (appearance.rings)
    bot.ist('gate_done')
    bot.event('gate_done', gate=GATES[gate]['name'])


def record_duration(save, key, sec):
    """The gate's completion time (statistics; player request 2026-10-30) -> save['gate_times'][key] {best, last, number} (s)."""
    d = save.setdefault('gate_times', {}).setdefault(key, {'best': 0, 'last': 0, 'number': 0})
    sec = int(max(1, sec))
    d.update(last=sec, number=d['number'] + 1, best=min(d['best'], sec) if d['best'] else sec)
    return d


def _chance_count(bot, row):
    a = int(row.get('count') or 1)
    b = row.get('max_count')
    return bot.r.randint(a, int(b)) if b else a


def _chance(bot, rows, first):
    """The player's gate chance (world finish): one item from a single spin, the others each on their own.
    A first-clear guarantee drops. A design goes to stock and is not mixed into another set."""
    import settings as SET
    rows = [s for s in rows or [] if isinstance(s, dict) and s.get('item')]
    single = [s for s in rows if s.get('single_spin')]
    roll, pick = bot.r.random(), None
    for s in single:
        roll -= SET.chance('drop', float(s.get('probability') or 0), 'gate')
        if roll < 0:
            pick = s
            break
    for s in rows:
        if s.get('single_spin'):
            hit = s is pick
        else:
            p = SET.chance('drop', float(s.get('probability') or 0), 'gate')
            hit = bool(first and s.get('first_guaranteed')) or bot.r.random() < p
        if not hit or s.get('item') in ('gem_pack', 'ore_pack'):
            continue
        loot = bot.r.choice(s['options']) if s.get('item') == 'design_choice' and s.get('options') else s['item']
        if loot:
            bot.add(loot, _chance_count(bot, s))


def can_run(bot):
    """A built and passable gate or None. The gate of an unfinished set, if it is built, jumps the queue."""
    st = state(bot)
    priority = wanted_gate(bot)
    order = [priority] if priority and priority in st['built'] else []
    order.extend(k for k in st['built'] if k not in order)
    for k in order:
        if estimate(bot, k)[1] < GATES[k]['hp']:
            return k
    return None
