"""Pilot skill tree (the same table as skill_tree.py). Points: a base that grows with level (in place of gate
log disks; a bot does not refine Seprom) plus log disks in stock. Spending follows a combat order, with the
player's prerequisites.

bot.k['skills'] = {'level': {id: rank}, 'points': n, 'converted': n, 'level_points': n}.
If the top slice copied the save's tree, skills_copied: the level base is not added.
"""
import skill_tree as ST

# Wanted rank. The order fills as prerequisites open: hull, shield, PvP damage, hit chance, rockets.
WANTED = (('18a', 2), ('13', 1), ('17', 5), ('22a', 2), ('18b', 3), ('8', 5), ('19', 5), ('22b', 3),
          ('6', 5), ('20', 3), ('21a', 2), ('11', 5), ('16a', 2))


def tree(bot):
    skills = bot.k.get('skills')
    if not isinstance(skills, dict):
        skills = {}
        bot.k['skills'] = skills
    skills.setdefault('level', {})
    skills.setdefault('points', 0)
    skills.setdefault('converted', 0)
    skills.setdefault('level_points', 0)
    return skills


def _profile(bot):
    """skill_tree.mods and requirements_met read a profile; this is a thin one over the bot record."""
    class P:
        pass
    p = P()
    p.d = {'skills': tree(bot)}
    return p


def mods(bot):
    """Skill bonuses (a ratio, or absolute HP for Ship Hull). If II is open, I does not count."""
    return ST.mods(_profile(bot))


def _base(bot):
    """Research points by level. None before level 6; the combat core is filled in the low 20s."""
    if bot.k.get('skills_copied'):
        return 0
    return max(0, min(36, (bot.level - 6) * 2))


def _convert_disks(bot, skills):
    """Log disks in stock become points at the player's table (skill_tree.Abilities.convert)."""
    from . import galaxy_gates as GT
    s = GT.stock(bot)
    table = ST.Y['log_disk']
    while s.get('resource_logfile', 0) > 0:
        n = skills['converted']
        need = table[n] if n < len(table) else -1
        if need <= 0 or s.get('resource_logfile', 0) < need:
            break
        s['resource_logfile'] -= need
        if not s['resource_logfile']:
            del s['resource_logfile']
        skills['points'] += 1
        skills['converted'] += 1


def spend(bot):
    """If there are points, raises the next skill one rank. Credits are paid when it has them; Seprom is not refined."""
    skills = tree(bot)
    extra = _base(bot) - skills['level_points']
    if extra > 0:
        skills['points'] += extra
        skills['level_points'] += extra
    _convert_disks(bot, skills)
    profile = _profile(bot)
    changed = False
    for _ in range(40):
        if skills['points'] <= 0:
            break
        chosen = None
        for sid, want in WANTED:
            skill = ST.SKILLS.get(sid)
            cur = skills['level'].get(sid, 0)
            if not skill or cur >= want or cur >= len(skill['values']):
                continue
            if skills['points'] < skill['cost'][cur]['points'] or not ST.requirements_met(profile, sid):
                continue
            chosen = sid
            break
        if not chosen:
            break
        skill = ST.SKILLS[chosen]
        cur = skills['level'].get(chosen, 0)
        cost = skill['cost'][cur]
        skills['points'] -= cost['points']
        if bot.k['credits'] >= cost['credits']:
            bot.pay('C', cost['credits'])
        skills['level'][chosen] = cur + 1
        changed = True
    if changed:
        bot.loadout_changed()
    return changed
