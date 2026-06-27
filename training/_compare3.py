import sys, json
sys.path.insert(0, '../src')
from aidnd.inference import ModelManager
from aidnd.inference.agents import PROMPTS

mgr = ModelManager()
rows = [json.loads(l) for l in open('data/narrator/eval.jsonl')]


def mode_of(r):
    u = next(m['content'] for m in r['messages'] if m['role'] == 'user')
    return u.split('Mode:', 1)[1].split('—', 1)[0].strip()


by = {}
for r in rows:
    by.setdefault(mode_of(r), []).append(r)

MODELS = [('ТЕКУЩ·9B-tune', 'aidnd-narrator'), ('голая·9B', 'qwen3.5:9b'), ('14B', 'qwen3:14b')]


def run(tag, sysm, usr):
    try:
        resp = mgr.client.chat(tag, [{'role': 'system', 'content': sysm}, {'role': 'user', 'content': usr}])
        return (resp.get('content') or '').replace('**', '').strip()
    except Exception as e:
        return 'ERR %s' % e


# ---- общение (dialogue/greeting) + обстановка (ambient/outcome) ----
PICK = [('dialogue', 2), ('greeting', 1), ('ambient', 2), ('outcome', 1)]
for mode, k in PICK:
    for r in by[mode][:k]:
        sysm = next(m['content'] for m in r['messages'] if m['role'] == 'system')
        usr = next(m['content'] for m in r['messages'] if m['role'] == 'user')
        gold = next(m['content'] for m in r['messages'] if m['role'] == 'assistant')
        situ = [l for l in usr.splitlines() if l.startswith(('NPC:', 'Situation:', 'The player says', 'Resolved'))]
        print('\n' + '=' * 78)
        print('РЕЖИМ: %s' % mode)
        for l in situ[:3]:
            print('  · ' + l[:110])
        for label, tag in MODELS:
            print('  [%-12s] %s' % (label, run(tag, sysm, usr)[:240]), flush=True)
        print('  [%-12s] %s' % ('GOLD', gold[:240]))

# ---- описания локаций (новый forge_location) ----
LOCS = [('Постоялый двор «Каменный Холм»', 'building', 'inn'),
        ('Рыночная площадь Фэндалина', 'room', 'shop, board'),
        ('Логово Крэгмо', 'site', 'combat')]
for name, kind, aff in LOCS:
    user = (f'Локация «{name}» (тип: {kind}; аффордансы: {aff}). Мир: фронтир Фэндалина (D&D).\n'
            'Опиши это место для рассказчика: облик и планировка, что видно/слышно/пахнет, чем место живёт. '
            '3-5 предложений, устойчивый антураж (без сиюминутных событий и без имён конкретных NPC).')
    print('\n' + '#' * 78)
    print('ОПИСАНИЕ ЛОКАЦИИ: %s' % name)
    for label, tag in MODELS:
        print('  [%-12s] %s' % (label, run(tag, PROMPTS['location_writer'], user)[:280]), flush=True)
