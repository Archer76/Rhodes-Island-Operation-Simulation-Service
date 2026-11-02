import json
import pathlib
import sqlite3

def main():
    conn = sqlite3.connect('data/enemydb.sqlite')
    c = conn.cursor()
    c.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [r[0] for r in c.fetchall()]
    print(f"Tables in enemydb.sqlite: {tables}")
    c.execute("SELECT page, prts_id, name, index_code FROM enemy LIMIT 10")
    for r in c.fetchall():
        print("Sample row:", r)

    c.execute("SELECT prts_id, name FROM enemy")
    db_enemies = {r[0]: r[1] for r in c.fetchall() if r[0]}

    hs_dir = pathlib.Path('data/gamedata/map.ark-nights.com/levels/activities/act31side')
    hs_enemies = set()
    for p in hs_dir.glob('level_*.json'):
        data = json.loads(p.read_text(encoding='utf-8'))
        for wave in data.get('waves', []):
            for frag in wave.get('fragments', []):
                for act in frag.get('actions', []):
                    if act.get('actionType') == 'SPAWN':
                        hs_enemies.add(act.get('key'))

    print(f"Total unique enemies required by Huai Shu Li: {len(hs_enemies)}")
    for e in sorted(hs_enemies):
        if e in db_enemies:
            print(f"  [OK] {e}: {db_enemies[e]}")
        else:
            print(f"  [MISSING] {e}")

    missing = hs_enemies - set(db_enemies.keys())
    if missing:
        print(f"\nCRITICAL: {len(missing)} enemies missing from enemydb.sqlite: {missing}")
    else:
        print("\nALL Huai Shu Li enemies are 100% present in enemydb.sqlite!")

if __name__ == '__main__':
    main()
