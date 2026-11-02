"""Checks the net-uridium-per-hour meter (stdlib). The game server is not started.

  python -I tools/uridium_rate_test.py

Shop prices are read from the showcase in data/defaults/responses.json (LCB-10, MCB-25, MCB-50, SAB-50,
RSB-75, R-310, PLT-2021, PLT-2026) and a one-hour session is made up. Exits if a number does not match.
Credit ammo is not taken out of uridium. UCB-100 is free if it is not in the showcase (no made-up price).
"""
import json, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'server'))
import uridium_rate as UR

RESPONSES = os.path.join(ROOT, 'server', 'data', 'defaults', 'responses.json')
# Unit price in the showcase (currency virtual = credits, real = uridium). The Premium discount is not in this file;
# a live session applies it separately with shop.buy_price. This check uses the showcase price.
EXPECTED = {
    'ammunition_laser_lcb-10': ('credits', 10.0),
    'ammunition_laser_mcb-25': ('uridium', 0.5),
    'ammunition_laser_mcb-50': ('uridium', 1.0),
    'ammunition_laser_sab-50': ('uridium', 1.0),
    'ammunition_laser_rsb-75': ('uridium', 5.0),
    'ammunition_rocket_r-310': ('credits', 100.0),
    'ammunition_rocket_plt-2026': ('credits', 500.0),
    'ammunition_rocket_plt-2021': ('uridium', 5.0),
}


def showcase(path):
    """Ammo in ShopItemListCommand -> (uridium|credits, unit)."""
    with open(path, encoding='utf8') as fh:
        replies = json.load(fh)
    out = {}
    for entry in replies.get('ShopItemListRequest', []):
        for message in entry.get('response', []):
            if message.get('_m') != 'ShopItemListCommand':
                continue
            for item in message.get('itemList', []):
                loot = item.get('lootId') or ''
                if not loot.startswith('ammunition_'):
                    continue
                price = (item.get('price') or [None])[0]
                currency = item.get('currency')
                if price is None or currency not in ('real', 'virtual'):
                    continue
                out[loot] = ('uridium' if currency == 'real' else 'credits', float(price))
    return out


def expect(name, got, want):
    if got != want:
        raise SystemExit('failed: %s\n  got: %r\n  want: %r' % (name, got, want))


def main():
    if not os.path.isfile(RESPONSES):
        raise SystemExit('showcase missing: %s' % RESPONSES)
    shop = showcase(RESPONSES)
    for loot, want in EXPECTED.items():
        expect('showcase ' + loot, shop.get(loot), want)
    expect('UCB-100 not in the showcase', 'ammunition_laser_ucb-100' in shop, False)

    expect('bank is not income', UR.income_counts('title_uridium_bank', 500), False)
    expect('refund is not income', UR.income_counts('auction_bookMoneyBack', 10), False)
    expect('a spend is not income', UR.income_counts('repair_ship', -40), False)
    expect('a kill is income', UR.income_counts('bonus_abschussAlien', 8), True)
    expect('gate CPU does not count', UR.counts('ammunition_ggportal_astral-cpu'), False)
    expect('an emote does not count', UR.counts('ammunition_specialammo_emote_alien-cheers'), False)
    expect('UCB counts', UR.counts('ammunition_laser_ucb-100'), True)
    expect('a rocket counts', UR.counts('ammunition_rocket_plt-3030'), True)
    expect('a mine counts', UR.counts('ammunition_mine_acm-01'), True)

    # One hour: 10,000 U earned, 800 MCB-50 (1 U), 100 RSB-75 (5 U), 3 MCB-25 (0.5 U -> ceiling 2 U),
    # 4,000 LCB-10 (10 C), 20 R-310 (100 C), 10 UCB-100 (not in the showcase).
    price = lambda loot: shop.get(loot)
    meter = UR.Meter()
    generation = meter.bind(price, now=1_000.0)
    meter.earn(10000)
    meter.earn(-50)                              # a spend does not enter the gross
    meter.fired('ammunition_laser_mcb-50', 800)
    meter.fired('ammunition_laser_rsb-75', 100)
    meter.fired('ammunition_laser_mcb-25', 3)      # 1.5 U -> the shop charges 2 U
    meter.fired('ammunition_laser_lcb-10', 4000)
    meter.fired('ammunition_rocket_r-310', 20)
    meter.fired('ammunition_laser_ucb-100', 10)
    summary = meter.summary(now=4_600.0)
    expect('duration', summary['seconds'], 3600.0)
    expect('gross', summary['uridium'], 10000)
    expect('ammo U', summary['ammo_uridium'], 800 + 500 + 2)
    expect('ammo C', summary['ammo_credits'], 4000 * 10 + 20 * 100)
    expect('net', summary['net_uridium'], 10000 - 1302)
    expect('net/h', summary['hourly']['net_uridium'], 8698.0)
    expect('gross/h', summary['hourly']['uridium'], 10000.0)
    expect('U/h', summary['hourly']['ammo_uridium'], 1302.0)
    expect('C/h', summary['hourly']['ammo_credits'], 42000.0)
    ucb = next(row for row in summary['ammo'] if row['loot'] == 'ammunition_laser_ucb-100')
    expect('UCB free', (ucb['count'], ucb['uridium'], ucb['unknown']), (10, 0, True))

    # Half an hour: the same total, the hourly rate doubles.
    half = meter.summary(now=2_800.0)
    expect('half hour net/h', half['hourly']['net_uridium'], 17396.0)
    expect('half hour C/h', half['hourly']['ammo_credits'], 84000.0)

    # Premium 5%: MCB-50 unit 0.95. 1 shot ceilings to 1 U, 1000 shots are 950 U (one purchase).
    discounted = UR.Meter()
    discounted.bind(lambda loot: ('uridium', 0.95) if loot.endswith('mcb-50') else None, now=0.0)
    discounted.fired('ammunition_laser_mcb-50', 1)
    expect('one shot ceiling', discounted.summary(now=10).get('ammo_uridium'), 1)
    thousand = UR.Meter()
    thousand.bind(lambda loot: ('U', 0.95), now=0.0)
    thousand.earn(1000)
    thousand.fired('ammunition_laser_mcb-50', 1000)
    out = thousand.summary(now=3600)
    expect('a thousand shots 950', out['ammo_uridium'], 950)
    expect('net 50', out['net_uridium'], 50)

    # Two MCB-25 (0.5 + 0.5) are 1 U as one purchase.
    pair = UR.Meter()
    pair.bind(lambda loot: ('real', 0.5), now=0.0)
    pair.fired('ammunition_laser_mcb-25', 2)
    expect('two x2 = 1 U', pair.summary(now=60)['ammo_uridium'], 1)

    # A frozen meter does not record new income; an old generation does not stop the new one.
    frozen = meter.stop(generation, now=4_600.0)
    expect('net when frozen', frozen['net_uridium'], 8698)
    expect('frozen', frozen['running'], False)
    meter.earn(99999)
    expect('no income while frozen', meter.summary()['uridium'], 10000)
    new = meter.bind(price, now=9_000.0)
    expect('old generation does not touch it', meter.stop(generation, now=9_100.0), None)
    expect('new one is empty', meter.summary(now=9_100.0)['uridium'], 0)
    expect('new generation', new != generation, True)

    print(UR.log_line(frozen))
    print('ammo:')
    for row in frozen['ammo']:
        print('  %-32s x%-6s  %s U   %s C%s' % (row['name'], row['count'], row['uridium'], row['credits'],
                                                '  (not in the shop)' if row['unknown'] else ''))
    print('ok')


if __name__ == '__main__':
    main()
