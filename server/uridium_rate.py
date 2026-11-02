"""Net uridium per hour: uridium earned in the session minus the shop cost of ammo fired.

A player session counts through player_profile.gain (income) and player_profile.use_ammo (shots); the price
is bound with shop.buy_price (world price, shop multiplier, Premium and Shop Discount included).
A bot can feed the same Meter from its own earn / spend points: bot.uridium_rate = Meter(price=...).

Credit ammo (LCB-10 at 10 C, R-310 at 100 C) does not mix into uridium. The shop exchange rate
(prices.json rate = 100, 1 U = 100 credits) is for pack valuation; the player does not convert LCB-10
into uridium at that rate. The credit cost is kept separately as credits per hour.

A type's cost is the sum of the unit prices of the rounds fired of that type, rounded up the way a shop
purchase is (shop.buy: ceil(unit * count)). Across many shots this is the same as buying that type once.
"""
import math, threading, time

# Drawing from the Uridium Bank is a copy of income already counted (it is bought with credits). An auction refund is not income.
NOT_INCOME = frozenset(('title_uridium_bank', 'auction_bookMoneyBack'))
# Combat ammo that is fired or dropped. Gate CPUs and emotes do not enter the income account.
_PREFIX = ('ammunition_laser_', 'ammunition_rocket_', 'ammunition_rocketlauncher_', 'ammunition_mine_',
           'ammunition_specialammo_', 'ammunition_slug_', 'ammunition_spool_')
_SKIP = ('ammunition_specialammo_emote_', 'ammunition_ggportal_')
CURRENCY = {'uridium': 'uridium', 'U': 'uridium', 'real': 'uridium',
            'credits': 'credits', 'C': 'credits', 'virtual': 'credits'}


def counts(loot):
    """Should this loot count as a shot (laser, rocket, mine, special ammo, cannon round)."""
    loot = str(loot or '')
    if loot.startswith(_SKIP):
        return False
    return loot.startswith(_PREFIX)


def income_counts(reason, uridium):
    """Should the uridium in profile.gain enter this meter as gross income."""
    if not uridium or uridium <= 0:
        return False
    return reason not in NOT_INCOME


def purchase(amount):
    """The amount the shop charges (same ceiling as shop.Shop.buy)."""
    if not amount or amount <= 0:
        return 0
    return int(math.ceil(float(amount) - 1e-9))


def short_name(loot):
    """ammunition_laser_mcb-50 -> MCB-50."""
    name = str(loot or '').rsplit('_', 1)[-1]
    return name.upper()


def _hourly(amount, seconds):
    if seconds < 1:
        return None
    return round(amount * 3600.0 / seconds, 1)


def _count(n):
    n = float(n)
    return int(n) if abs(n - round(n)) < 1e-6 else round(n, 2)


class Meter:
    """A player's or a bot's session meter. price(loot) -> (currency, unit) or None.

    currency: 'uridium' / 'U' / 'real' or 'credits' / 'C' / 'virtual'. The unit is the purchase price
    at that moment (discount and multiplier already applied). None: not in the shop, the count stays, the cost is 0.
    """

    def __init__(self, price=None):
        self.lock = threading.Lock()
        self.price = price
        self.generation = 0
        self.started = None
        self.ended = None
        self.uridium = 0.0
        self.kinds = {}

    def bind(self, price, now=None):
        """A new game connection: the meter resets. -> generation (stop asks for the same generation; an old session does not stop the new one)."""
        with self.lock:
            self.generation += 1
            self.price = price
            self.started = time.time() if now is None else now
            self.ended = None
            self.uridium = 0.0
            self.kinds = {}
            return self.generation

    def stop(self, generation=None, now=None):
        """The session closed: the clock freezes. None if the generation does not match (a new session has taken its place)."""
        with self.lock:
            if generation is not None and generation != self.generation:
                return None
            if self.started is not None and self.ended is None:
                self.ended = time.time() if now is None else now
            return self._summary(self.ended if self.ended is not None else now)

    def earn(self, uridium):
        """Gross uridium (positive only). Not recorded if there is no session or it is frozen."""
        if not uridium or uridium <= 0:
            return
        with self.lock:
            if self.started is None or self.ended is not None:
                return
            self.uridium += float(uridium)

    def fired(self, loot, n=1):
        """n shots. The cost comes from the price function at that moment (later price changes do not rewrite old shots)."""
        if not loot or not n or n <= 0:
            return
        with self.lock:
            if self.started is None or self.ended is not None:
                return
            currency = self._price(loot)
            row = self.kinds.get(loot)
            if row is None:
                row = self.kinds[loot] = {'count': 0.0, 'uridium': 0.0, 'credits': 0.0, 'unknown': 0.0}
            row['count'] += float(n)
            if currency is None:
                row['unknown'] += float(n)
                return
            kind, unit = currency
            row[kind] += float(unit) * float(n)

    def summary(self, now=None):
        with self.lock:
            return self._summary(now)

    def _price(self, loot):
        fn = self.price
        if fn is None:
            return None
        try:
            pr = fn(loot)
        except Exception:
            return None
        if not pr or not isinstance(pr, (tuple, list)) or len(pr) < 2:
            return None
        kind = CURRENCY.get(pr[0])
        if not kind:
            return None
        try:
            unit = float(pr[1])
        except (TypeError, ValueError):
            return None
        if unit < 0:
            return None
        return kind, unit

    def _seconds(self, now):
        if self.started is None:
            return 0.0
        end = self.ended if self.ended is not None else (time.time() if now is None else now)
        return max(0.0, float(end) - float(self.started))

    def _summary(self, now):
        seconds = self._seconds(now)
        ammo = []
        u_sum = c_sum = shots = 0
        for loot, row in self.kinds.items():
            u, c = purchase(row['uridium']), purchase(row['credits'])
            u_sum += u
            c_sum += c
            shots += row['count']
            ammo.append({'loot': loot, 'name': short_name(loot), 'count': _count(row['count']),
                         'uridium': u, 'credits': c, 'unknown': row['unknown'] > 0 and u == 0 and c == 0})
        ammo.sort(key=lambda r: (-r['uridium'], -r['credits'], -r['count'], r['name']))
        gross = round(self.uridium, 2)
        net = round(gross - u_sum, 2)
        return {'open': self.started is not None, 'running': self.started is not None and self.ended is None,
                'seconds': round(seconds, 1), 'uridium': gross, 'ammo_uridium': u_sum, 'ammo_credits': c_sum,
                'net_uridium': net, 'shots': _count(shots),
                'hourly': {'net_uridium': _hourly(net, seconds), 'uridium': _hourly(gross, seconds),
                           'ammo_uridium': _hourly(u_sum, seconds), 'ammo_credits': _hourly(c_sum, seconds)},
                'ammo': ammo}


def log_line(summary):
    """One line for the server log."""
    if not summary:
        return ''
    s = summary.get('hourly') or {}

    def g(v):
        return '—' if v is None else ('%g' % v)

    return 'net uridium %s U/h (gross %s, ammo %s U + %s C, %s s)' % (
        g(s.get('net_uridium')), g(s.get('uridium')), g(s.get('ammo_uridium')), g(s.get('ammo_credits')),
        g(summary.get('seconds')))
