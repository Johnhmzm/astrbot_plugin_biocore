# -*- coding: utf-8 -*-
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from biocore_memory.event import event_graph as G


def _ev(eid, note):
    return {'event_id': eid, 'note': note}


def test_shared_entity_links_events():
    events = [_ev('a', '叶楠生日八月十八'), _ev('b', '给叶楠买生日蛋糕'),
              _ev('c', '今天风很大'), _ev('d', '豆包不爱进猫包')]
    graph, stats = G.build_graph(events)
    assert graph['a']['b'] >= 1
    assert 'c' not in graph or 'a' not in graph.get('c', {})


def test_common_terms_do_not_link():
    events = [_ev('a', '用户今天很累'), _ev('b', '用户今天也累'),
              _ev('c', '用户今天还行'), _ev('d', '用户今天睡了')]
    graph, _stats = G.build_graph(events)
    # '今天'/'用户' appear in every event -> dropped, no edges
    assert graph == {} or all(not v for v in graph.values())


def test_neighbours_capped_per_seed_and_deduped():
    graph = {'a': {'b': 3, 'c': 2, 'd': 1}, 'b': {'a': 3}, 'c': {'a': 2}, 'd': {'a': 1}}
    got = G.neighbors(graph, ['a'], per_seed=2)
    assert got == ['b', 'c']
    assert len(G.neighbors(graph, ['a', 'b'], per_seed=3)) == len(set(G.neighbors(graph, ['a', 'b'], per_seed=3)))


def test_expand_puts_seeds_first():
    events = [_ev('a', '叶楠生日八月十八'), _ev('b', '给叶楠买生日蛋糕'), _ev('c', '风大')]
    picked, stats = G.expand(events, ['a'], per_seed=1)
    assert picked[0]['event_id'] == 'a'
    assert stats['neighbours'] >= 1


if __name__ == '__main__':
    for name, fn in sorted(globals().items()):
        if name.startswith('test_') and callable(fn):
            fn()
            print('OK', name)
    print('all event-graph tests passed')
