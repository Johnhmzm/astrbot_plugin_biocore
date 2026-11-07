# -*- coding: utf-8 -*-
"""Event layer: build events, summarise them, and recall whole events.

Off by default: every entry point checks flags['event_layer'] and returns an
empty result without calling any model when the switch is off, so existing
behaviour is unchanged.
"""
from __future__ import annotations

import hashlib
import inspect
import json
import math
import time

FLAG_KEY = 'event_layer'
_DEFAULT_RERANK = None


def set_default_rerank(fn):
    """Register the rerank used when a caller does not pass one (None = off)."""
    global _DEFAULT_RERANK
    _DEFAULT_RERANK = fn
    return fn


def get_default_rerank():
    return _DEFAULT_RERANK
OVERVIEW_MAX = 30
CHRONICLE_TOKENS = 1200


def enabled(flags=None):
    data = flags if isinstance(flags, dict) else {}
    raw = data.get(FLAG_KEY)
    if raw is None and isinstance(data.get('switches'), dict):
        raw = data['switches'].get(FLAG_KEY)
    return bool(raw)


def _dbg(msg):
    """Temporary trace of the two-stage funnel (BIOCORE_DEBUG_EV=1)."""
    import os
    import sys
    if os.environ.get('BIOCORE_DEBUG_EV'):
        print('[ev-dbg] ' + str(msg), file=sys.stderr)


def _tokens(text):
    return max(1, int(len(str(text or '')) / 1.5))


def _entry_text(entry):
    return str((entry or {}).get('text') or '')


def _turn(entry, index):
    try:
        return int((entry or {}).get('turn'))
    except Exception:
        return index + 1


def _cos(a, b):
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = float(sum(x * y for x, y in zip(a, b)))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na <= 0 or nb <= 0:
        return 0.0
    return dot / (na * nb)


def _partition(segments, turns):
    """Clip overlapping model ranges into one contiguous, gap-free partition."""
    turns = sorted(turns)
    if not turns:
        return []
    first, last = turns[0], turns[-1]
    known = set(turns)
    events, cursor = [], first
    for start, end in sorted(segments, key=lambda s: (s[0], s[1])):
        s = max(int(start), cursor)
        e = min(int(end), last)
        if e < s:
            continue
        events.append({'start': s, 'end': e})
        cursor = e + 1
    if not events:
        events = [{'start': first, 'end': last}]
    events[0]['start'] = first
    events[-1]['end'] = last
    merged = []
    for ev in events:
        if merged and ev['start'] <= merged[-1]['end']:
            merged[-1]['end'] = max(merged[-1]['end'], ev['end'])
            continue
        merged.append({'start': ev['start'], 'end': ev['end']})
    for i in range(len(merged) - 1):
        if merged[i]['end'] + 1 < merged[i + 1]['start']:
            merged[i]['end'] = merged[i + 1]['start'] - 1
    out = []
    for ev in merged:
        members = [t for t in range(ev['start'], ev['end'] + 1) if t in known]
        if members:
            out.append({'start': members[0], 'end': members[-1], 'members': members})
    return out


VECTOR_JUMP = 0.55
DAY_SECONDS = 86400.0
TIME_GAP = 3600.0


def _rule_segments(entries, trace=None):
    """Vectors drive the cut; time only breaks a day-boundary or fills in."""
    segments, current = [], [entries[0]]
    for index, (prev, cur) in enumerate(zip(entries, entries[1:]), 1):
        gap = float(cur.get('ts') or 0.0) - float(prev.get('ts') or 0.0)
        has_vec = bool(prev.get('vector')) and bool(cur.get('vector'))
        jump = None
        if has_vec:
            jump = 1.0 - _cos(prev.get('vector'), cur.get('vector'))
            cut = jump > VECTOR_JUMP or gap > DAY_SECONDS
            reason = ('jump' if jump > VECTOR_JUMP else ('day' if gap > DAY_SECONDS else ''))
        else:
            cut = gap > TIME_GAP
            reason = 'time' if cut else ''
        if trace is not None:
            trace.append({'turn': _turn(cur, index), 'jump': None if jump is None else round(jump, 4),
                          'gap': round(gap, 1), 'cut': cut, 'reason': reason,
                          'by': 'vector' if has_vec else 'time'})
        if cut:
            segments.append(current)
            current = [cur]
        else:
            current.append(cur)
    segments.append(current)
    return [(_turn(seg[0], 0), _turn(seg[-1], 0)) for seg in segments]


MERGE_SMALL_MAX = 2
MERGE_TARGET_MIN = 3
MERGE_TARGET_MAX = 6
MERGE_SIM = 0.25


def _same_topic(left, right, sim=MERGE_SIM):
    a, b = left.get('vector'), right.get('vector')
    if not a or not b:
        return True
    return _cos(a, b) >= sim


def _merge_small_events(events, by_turn, *, small=MERGE_SMALL_MAX, min_turns=MERGE_TARGET_MIN,
                        max_turns=MERGE_TARGET_MAX, sim=MERGE_SIM):
    """Fold events of <= small turns into a neighbour so most events cover 3-6 turns.

    Adjacency is preserved: every merged event still covers a contiguous,
    non-overlapping range and the union of ranges is unchanged.
    """
    groups = [[ev] for ev in events]

    def size(group):
        return sum(len(ev['members']) for ev in group)

    i = 0
    while i < len(groups):
        group = groups[i]
        if size(group) > small or len(group) > 1:
            i += 1
            continue
        moved = False
        if i + 1 < len(groups):
            nxt = groups[i + 1]
            if size(group) + size(nxt) <= max_turns and _same_topic(group[-1], nxt[0], sim):
                groups[i:i + 2] = [group + nxt]
                moved = True
        if not moved and i > 0:
            prev = groups[i - 1]
            if size(prev) + size(group) <= max_turns and _same_topic(prev[-1], group[0], sim):
                groups[i - 1:i + 1] = [prev + group]
                moved = True
                i -= 1
        i += 1
    out = []
    for group in groups:
        members = [turn for ev in group for turn in ev['members']]
        out.append(_make_event(members, by_turn))
    return out


def build_events(entries, *, llm=None, flags=None, max_turns=15, trace=None, merge_small=False):
    """Group entries into events covering every turn exactly once."""
    if not enabled(flags):
        return []
    rows = [dict(e) for e in (entries or []) if isinstance(e, dict)]
    if not rows:
        return []
    rows.sort(key=lambda e: (float(e.get('ts') or 0.0), _turn(e, 0)))
    for i, entry in enumerate(rows):
        entry['_idx'] = i
    if llm is not None:
        prompt = ('下面是一段对话，每行是“轮号|角色|文本”。请按“一件事”切分事件，通常 3–15 轮，'
                  '同一件事跨轮不要拆开。只输出 JSON 数组：[{"start": 轮号, "end": 轮号}]，不要解释。\n\n'
                  + '\n'.join('%s|%s|%s' % (_turn(e, i), e.get('role') or 'user', _entry_text(e))
                               for i, e in enumerate(rows)))
        try:
            data = json.loads(llm(prompt) or '[]')
        except Exception:
            data = None
        segments = []
        for item in (data or []):
            if isinstance(item, dict) and item.get('start') is not None and item.get('end') is not None:
                segments.append((int(item['start']), int(item['end'])))
        if not segments:
            segments = _rule_segments(rows, trace)
    else:
        segments = _rule_segments(rows, trace)
    turns = [_turn(e, i) for i, e in enumerate(rows)]
    parts = _partition(segments, turns)
    by_turn = {}
    for entry in rows:
        by_turn.setdefault(_turn(entry, entry.get('_idx', 0)), []).append(entry)
    events = []
    for part in parts:
        members = part['members']
        if len(members) > max_turns:
            step = max_turns
            for i in range(0, len(members), step):
                chunk = members[i:i + step]
                events.append(_make_event(chunk, by_turn))
        else:
            events.append(_make_event(members, by_turn))
    if merge_small:
        events = _merge_small_events(events, by_turn)
    return events


def _make_event(members, by_turn):
    entries = []
    for turn in members:
        entries.extend(by_turn.get(turn) or [])
    text = '\n'.join('%s：%s' % (e.get('role') or 'user', _entry_text(e)) for e in entries)
    digest = hashlib.sha1(('%s|%s|%s' % (members[0], members[-1], text[:64])).encode('utf-8')).hexdigest()[:10]
    vectors = [e.get('vector') for e in entries if e.get('vector')]
    vector = []
    if vectors:
        dim = len(vectors[0])
        vector = [sum(v[i] for v in vectors) / len(vectors) for i in range(dim)]
    return {'event_id': 'EV_%s' % digest, 'start': members[0], 'end': members[-1],
            'members': list(members), 'entries': entries,
            'text': text, 'tokens': _tokens(text), 'vector': vector}


def summarize_event(event, *, llm=None, flags=None):
    """Overview always; chronicle only when the raw text is big."""
    if not enabled(flags) or not event:
        return {}
    text = str(event.get('text') or '')
    result = {'overview': '', 'chronicle': ''}
    if not text.strip():
        return result
    if llm is None:
        result['overview'] = text.replace('\n', ' ')[:OVERVIEW_MAX]
        return result
    prompt = ('下面是一段对话。为它写一段不超过 80 字的笔记：'
              '先说这段里关于同一个人、同一件事出现过哪些说法（按先后），'
              '再说明这些说法是后者取代前者，还是几种并存、谁也没让谁失效；'
              '最后一句概括这段在讲什么（谁/什么/什么值）。'
              '只输出 JSON：{"overview": "..."}。\n\n【记录】\n%s' % (text,))
    try:
        result['overview'] = str(json.loads(llm(prompt) or '{}').get('overview') or '').strip()
    except Exception:
        result['overview'] = ''
    if _tokens(text) > CHRONICLE_TOKENS:
        prompt2 = ('写一段 240-480 字的纪要，只写发生过的事，不推测、不评论，结尾开放。'
                   '只输出 JSON：{"chronicle": "..."}。\n\n【记录】\n%s' % text)
        try:
            result['chronicle'] = str(json.loads(llm(prompt2) or '{}').get('chronicle') or '').strip()
        except Exception:
            result['chronicle'] = ''
    return result


BATCH_INPUT_TOKENS = 3000
BATCH_OUTPUT_TOKENS = 4000
_ENTRY_TOKENS = OVERVIEW_MAX + 20


def _json_array(text):
    """Best effort: the first JSON array of objects in a reply."""
    raw = str(text or '').strip()
    if raw.startswith('```'):
        parts = raw.split('```')
        if len(parts) >= 2:
            raw = parts[1].strip().removeprefix('json').strip()
    candidates = []
    try:
        candidates.append(json.loads(raw))
    except Exception:
        pass
    start = raw.find('[')
    while start != -1:
        depth, in_str, escape = 0, False, False
        for index in range(start, len(raw)):
            char = raw[index]
            if in_str:
                if escape:
                    escape = False
                elif char == '\\':
                    escape = True
                elif char == '"':
                    in_str = False
                continue
            if char == '"':
                in_str = True
            elif char == '[':
                depth += 1
            elif char == ']':
                depth -= 1
                if depth == 0:
                    try:
                        candidates.append(json.loads(raw[start:index + 1]))
                    except Exception:
                        pass
                    break
        start = raw.find('[', start + 1)
    for data in candidates:
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for key in ('events', 'data', 'overviews', 'items'):
                if isinstance(data.get(key), list):
                    return data[key]
    return None


def _call_llm(llm, prompt, max_output_tokens):
    """Hand the output cap over when the callable can take one."""
    try:
        params = inspect.signature(llm).parameters
    except (TypeError, ValueError):
        return llm(prompt)
    for name in ('max_output_tokens', 'max_tokens'):
        if name in params:
            return llm(prompt, **{name: int(max_output_tokens)})
    if any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values()):
        return llm(prompt, max_output_tokens=int(max_output_tokens))
    return llm(prompt)


def _batch_prompt(items):
    blocks = []
    for ev in items:
        blocks.append('【%d-%d】\n%s' % (int(ev.get('start') or 0), int(ev.get('end') or 0),
                                         str(ev.get('text') or '').strip()))
    return ('下面有 %d 个事件，每段以“【起止轮号】”开头。为每个事件写一段不超过 80 字的笔记：'
            '先说这段里关于同一个人、同一件事出现过哪些说法（按先后），'
            '再说明这些说法是后者取代前者，还是几种并存、谁也没让谁失效；'
            '最后一句概括这段在讲什么（谁/什么/什么值）。'
            '必须每个事件一条，条数严格等于 %d；每条不超过 %d 字。'
            '只输出 JSON 数组，元素形如 {"start": 起轮, "end": 止轮, "overview": "..."}，不要解释。\n\n'
            % (len(items), len(items), 80) + '\n\n'.join(blocks))

def _pack_batches(rows, budget_tokens, max_output_tokens):
    """Greedy: every batch fits the input budget and the output cap."""
    cap = max(1, int(max_output_tokens) // _ENTRY_TOKENS)
    batches, current = [], []
    for ev in rows:
        trial = current + [ev]
        if current and (len(trial) > cap or _tokens(_batch_prompt(trial)) > int(budget_tokens)):
            batches.append(current)
            current = [ev]
        else:
            current = trial
    if current:
        batches.append(current)
    return batches


def summarize_events_batch(events, *, llm=None, budget_tokens=BATCH_INPUT_TOKENS,
                           max_output_tokens=BATCH_OUTPUT_TOKENS, flags=None, stats=None):
    """Overviews for many events in few calls, aligned strictly by (start, end).

    A batch whose reply does not line up with the events it was given falls
    back to summarize_event for exactly the events that came back empty.
    """
    record = stats if isinstance(stats, dict) else {}
    record.update({'events': 0, 'batches': 0, 'batch_calls': 0, 'single_calls': 0,
                   'aligned': 0, 'fallback': 0})
    if not enabled(flags):
        return []
    rows = [e for e in (events or []) if isinstance(e, dict)]
    if not rows:
        return []
    rows.sort(key=lambda e: (int(e.get('start') or 0), int(e.get('end') or 0)))
    record['events'] = len(rows)
    overviews = {}
    for batch in _pack_batches(rows, budget_tokens, max_output_tokens):
        record['batches'] += 1
        got = {}
        if llm is not None:
            record['batch_calls'] += 1
            try:
                reply = _call_llm(llm, _batch_prompt(batch), max_output_tokens)
            except Exception:
                reply = None
            items = []
            for item in (_json_array(reply) or []):
                if not isinstance(item, dict):
                    continue
                parsed = _parse_span_item(item)
                if parsed is None:
                    continue
                items.append(parsed)
            for start, end, text in items:
                if not text:
                    continue
                if (start, end) in got:
                    continue
                got[(start, end)] = text
            if items and len(items) != len(batch) and len(record.setdefault('misaligned_samples', [])) < 2:
                record['misaligned_samples'].append({
                    'batch': len(batch),
                    'items': len(items),
                    'raw_head': str(reply or '')[:300],
                    'spans': [(int(ev.get('start') or 0), int(ev.get('end') or 0)) for ev in batch][:8],
                    'got': sorted(got.keys())[:8],
                })
            if items and len(items) == len(batch):
                # second chance: same count, so line them up in order
                spans = [(int(ev.get('start') or 0), int(ev.get('end') or 0)) for ev in batch]
                if all(span not in got for span in spans):
                    for span, (_s, _e, text) in zip(spans, items):
                        if text:
                            got[span] = text
        for ev in batch:
            key = (int(ev.get('start') or 0), int(ev.get('end') or 0))
            if key in got:
                overviews[key] = got[key]
                record['aligned'] += 1
            else:
                record['fallback'] += 1
    out = []
    for ev in rows:
        key = (int(ev.get('start') or 0), int(ev.get('end') or 0))
        if key in overviews:
            out.append({'event_id': ev.get('event_id'), 'start': key[0], 'end': key[1],
                        'overview': overviews[key], 'source': 'batch'})
            continue
        record['single_calls'] += 1
        single = summarize_event(ev, llm=llm, flags=flags)
        out.append({'event_id': ev.get('event_id'), 'start': key[0], 'end': key[1],
                    'overview': str((single or {}).get('overview') or ''),
                    'source': 'single'})
    return out


def _call_rerank(rerank, question, events, rerank_text):
    """Hand the text mode to rerankers that know how to score raw text."""
    try:
        params = inspect.signature(rerank).parameters
    except (TypeError, ValueError):
        return rerank(question, events)
    if 'text' in params:
        return rerank(question, events, text=rerank_text)
    if any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values()):
        return rerank(question, events, text=rerank_text)
    return rerank(question, events)


def _sentence_hits(question, events, entries, qvec, limit):
    """Rank single entries by cosine, then map each hit onto its event."""
    if qvec is None or not events:
        return []
    span = {}
    for ev in events:
        try:
            start, end = int(ev.get('start')), int(ev.get('end'))
        except Exception:
            continue
        for turn in range(start, end + 1):
            span[turn] = ev
    best = {}
    for row in (entries or []):
        if not isinstance(row, dict) or not row.get('vector'):
            continue
        try:
            turn = int(row.get('turn'))
        except Exception:
            continue
        ev = span.get(turn)
        if ev is None:
            continue
        score = _cos(qvec, row['vector'])
        key = id(ev)
        if key not in best or score > best[key][0]:
            best[key] = (score, ev)
    ranked = sorted(best.values(), key=lambda item: item[0], reverse=True)
    return ranked[:max(1, int(limit))]


def _two_stage_rank(question, scored, entries, qvec, rerank, *, coarse_events=30,
                    fine_pool=100, fine_keep=30, stats=None):
    """Coarse events by vector, fine sentences by rerank, then back to events.

    Stage 2 never looks outside the events stage 1 kept, and the rerank is
    always handed at most fine_pool sentences, so its cost cannot grow with
    the size of memory.
    """
    record = stats if isinstance(stats, dict) else {}
    t0 = time.time()
    coarse = scored[:max(1, int(coarse_events))]
    record['coarse_events'] = len(coarse)
    span = {}
    for _score, ev in coarse:
        try:
            start, end = int(ev.get('start')), int(ev.get('end'))
        except Exception:
            continue
        for turn in range(start, end + 1):
            span[turn] = ev
    picked = []
    for row in (entries or []):
        if not isinstance(row, dict) or not row.get('vector'):
            continue
        try:
            turn = int(row.get('turn'))
        except Exception:
            continue
        ev = span.get(turn)
        if ev is None:
            continue
        picked.append((_cos(qvec, row['vector']), turn, row, ev))
    picked.sort(key=lambda item: item[0], reverse=True)
    picked = picked[:max(1, int(fine_pool))]
    record['fine_entries'] = len(picked)
    record['coarse_s'] = round(time.time() - t0, 4)
    _dbg('two_stage qvec=%s events=%d coarse=%d entries=%d fine_entries=%d'
         % (qvec is not None, len(scored or []), len(coarse), len(entries or []), len(picked)))
    if not picked:
        record['fine_kept'] = 0
        record['rerank_s'] = 0.0
        # no sentence mapped onto a coarse event: fall back to the coarse ranking
        fallback = [(s, ev) for s, ev in coarse[:max(1, min(10, len(coarse)))]]
        return fallback, len(fallback)
    t1 = time.time()
    if rerank is not None:
        pseudo = [{'event_id': 'EN%d' % turn, 'start': turn, 'end': turn,
                   'text': rerank_doc(row, ev),
                   'overview': rerank_doc(row, ev)}
                  for _score, turn, row, ev in picked]
        scores = _call_rerank(rerank, question, pseudo, 'sentence')
        if scores and len(scores) == len(pseudo):
            picked = [(float(score), turn, row, ev)
                      for score, (_old, turn, row, ev) in zip(scores, picked)]
            picked.sort(key=lambda item: item[0], reverse=True)
            record['rerank_used'] = True
            record['rerank_calls'] = 1
    record['rerank_s'] = round(time.time() - t1, 4)
    kept = picked[:max(1, int(fine_keep))]
    turns_of = {}
    for _score, turn, _row, ev in kept:
        turns_of.setdefault(id(ev), []).append(turn)
    ranked, seen = [], set()
    for score, _turn, _row, ev in kept:
        if id(ev) in seen:
            continue
        seen.add(id(ev))
        # the caller needs to know which messages matched, to inject them
        ev['hit_turns'] = sorted(set(turns_of.get(id(ev)) or []))
        ranked.append((score, ev))
    record['fine_kept'] = len(ranked)
    return ranked, len(ranked)

def _split_sentences(text):
    raw = str(text or '').strip()
    out, buf = [], ''
    for char in raw:
        buf += char
        if char in '。！？!?':
            if buf.strip():
                out.append(buf.strip())
            buf = ''
    if buf.strip():
        out.append(buf.strip())
    return [item for item in out if item]


def render_event_hits(event, max_hits=3):
    """Injection lines: overview + the matched messages + first/last sentence.

    Keeps the point of the hit without pasting the whole event back in.
    """
    if not isinstance(event, dict):
        return []
    entries = [e for e in (event.get('entries') or []) if isinstance(e, dict)]
    lines = ['【事件｜第%d-%d轮】%s' % (int(event.get('start') or 0), int(event.get('end') or 0),
                                      str(event.get('overview') or '').strip())]
    if not entries:
        return lines
    by_turn = {}
    for entry in entries:
        try:
            turn = int(entry.get('turn'))
        except Exception:
            continue
        by_turn.setdefault(turn, []).append(entry)
    def speaker(entry):
        return '用户' if str(entry.get('role') or '') == 'user' else '助手'
    first = _split_sentences(entries[0].get('text'))
    last = _split_sentences(entries[-1].get('text'))
    if first:
        lines.append('  开头：[%s] %s' % (speaker(entries[0]), first[0]))
    shown = 0
    for turn in [int(t) for t in (event.get('hit_turns') or [])]:
        if shown >= int(max_hits):
            break
        for entry in by_turn.get(turn) or []:
            if shown >= int(max_hits):
                break
            lines.append('  命中：[%s] %s' % (speaker(entry), str(entry.get('text') or '')))
            shown += 1
    if last:
        lines.append('  结尾：[%s] %s' % (speaker(entries[-1]), last[-1]))
    return lines

def event_recall(question, events, *, top_n=None, budget_tokens=8000, selector=None,
                 flags=None, embed=None, pool_size=100, min_budget_fill=0.8,
                 rerank=None, rerank_top=30, stats=None, max_events=None,
                 entry='summary', entries=None, sent_pool=60, rerank_text=None,
                 sent_keep=20, summary_keep=20, coarse_events=30, fine_pool=100,
                 fine_keep=30, rank='cosine', as_of=None, now=None, span=None,
                 centroid=None):
    """Pick whole events within the budget.

    pool_size events are scored first (no fixed 20-event cut), then filled
    greedily until the budget is spent; an event is either taken whole or
    dropped whole. ``top_n`` stays as a legacy alias for ``pool_size``.

    ``entry`` picks the candidate channels: 'summary' (default, events by
    overview), 'sentence' (entries by cosine, reranked on their raw text, then
    mapped onto whole events) or 'union' (both, deduplicated). The sentence
    path falls back to the overview ranking when it finds nothing.
    ``rerank_text`` tells the reranker which text to score: raw text on the
    sentence path, overviews otherwise.
    """
    record = stats if isinstance(stats, dict) else {}
    record.update({'pool': 0, 'selected': 0, 'tokens': 0, 'budget': int(budget_tokens),
                   'fill': 0.0, 'underfilled': False, 'selector_used': False,
                   'rerank_used': False, 'rerank_calls': 0, 'entry': 'summary',
                   'sentence_used': False, 'sentence_hits': 0, 'rerank_text': 'overview',
                   'sent_leg': 0, 'summary_leg': 0, 'coarse_events': 0, 'fine_entries': 0,
                   'fine_kept': 0, 'coarse_s': 0.0, 'rerank_s': 0.0})
    if not enabled(flags):
        return []
    rows = [e for e in (events or []) if isinstance(e, dict)]
    if not rows:
        return []
    rerank = rerank if rerank is not None else _DEFAULT_RERANK
    size = int(pool_size or top_n or 100)
    qvec = None
    if embed is not None:
        try:
            qvec = embed(question)
        except Exception:
            qvec = None
    scored = []
    mode = str(rank or 'cosine').lower()
    for ev in rows:
        score = 0.0
        if qvec and ev.get('vector'):
            score = _cos(qvec, ev['vector'])
        else:
            words = [w for w in str(question).split() if w]
            hay = str(ev.get('overview') or ev.get('text') or '')
            score = sum(1 for w in words if w in hay) / float(len(words) or 1)
        if mode == 'activation' and qvec:
            from . import activation as _act
            score = _act.score(ev, qvec, now=now, as_of=as_of, span=span,
                               centroid=centroid)[0]
        scored.append((score, ev))
    two_stage_done = False
    recent_events = []
    if mode == 'recency' and entries:
        try:
            ordered = sorted(entries, key=lambda r: int(r.get('turn') or 0))
            recent_turns = set(int(r.get('turn') or 0) for r in ordered[-20:])
        except Exception:
            recent_turns = set()
        span_of = {}
        for ev in rows:
            for turn in range(int(ev.get('start') or 0), int(ev.get('end') or 0) + 1):
                span_of[turn] = ev
        seen_recent = set()
        for turn in sorted(recent_turns):
            ev = span_of.get(turn)
            if ev is None or id(ev) in seen_recent:
                continue
            seen_recent.add(id(ev))
            recent_events.append(ev)
        record['recent_events'] = len(recent_events)
    if mode == 'rrf' and qvec:
        from . import activation as _act
        channels = []
        channels.append(['sem', [str(ev.get('event_id') or '') for ev in sorted(
            rows, key=lambda e: _act.cosine(qvec, e.get('vector') or []), reverse=True)]])
        hit_rows = [ev for ev in rows if ev.get('hits_ts')]
        if hit_rows:
            channels.append(['act', [str(ev.get('event_id') or '') for ev in sorted(
                hit_rows, key=lambda e: _act.actr_activation(e.get('hits_ts'),
                                                             now if now is not None else as_of),
                reverse=True)]])
        if as_of is not None:
            channels.append(['time', [str(ev.get('event_id') or '') for ev in sorted(
                rows, key=lambda e: _act.time_proximity(as_of, e.get('end'), span),
                reverse=True)]])
        if centroid:
            channels.append(['spec', [str(ev.get('event_id') or '') for ev in sorted(
                rows, key=lambda e: _act.specificity(e.get('vector') or [], centroid),
                reverse=True)]])
        fused = _act.rrf_scores([ranked for _name, ranked in channels], rows)
        scored = fused
        record['rrf_channels'] = [name for name, _rows in channels]
        record['cos_order'] = [str(ev.get('event_id') or '') for ev in sorted(
            rows, key=lambda e: _act.cosine(qvec, e.get('vector') or []), reverse=True)[:10]]
        record['act_order'] = [str(ev.get('event_id') or '') for _s, ev in scored[:10]]
    scored.sort(key=lambda item: item[0], reverse=True)
    if mode == 'activation' and qvec:
        record['rank'] = 'activation'
        record['cos_order'] = [str(ev.get('event_id') or '') for ev in
                               sorted(rows, key=lambda e: _cos(qvec, e.get('vector') or []),
                                      reverse=True)[:10]]
        record['act_order'] = [str(ev.get('event_id') or '') for _s, ev in scored[:10]]
    entry = str(entry or 'summary').lower()
    if entry not in ('summary', 'sentence', 'union', 'two_stage'):
        entry = 'summary'
    record['entry'] = entry
    rerank_text = str(rerank_text or '').lower()
    if rerank_text not in ('sentence', 'overview'):
        rerank_text = 'sentence' if entry == 'sentence' else 'overview'
    record['rerank_text'] = rerank_text

    sent_hits = []
    if entry in ('sentence', 'union') and entries and qvec is not None:
        sent_hits = _sentence_hits(question, rows, entries, qvec, sent_pool)
        record['sentence_used'] = bool(sent_hits)
        record['sentence_hits'] = len(sent_hits)

    keep = size
    if mode == 'rrf':
        keep = 30
    if False:
        semantic = [ev for _s, ev in sorted(
            ((_cos(qvec, ev.get('vector') or []) if (qvec and ev.get('vector')) else 0.0, ev)
             for ev in rows), key=lambda item: item[0], reverse=True)][:30] if qvec else []
        merged, seen = [], set()
        for ev in recent_events:
            if id(ev) in seen:
                continue
            seen.add(id(ev))
            merged.append(ev)
        for ev in semantic:
            if id(ev) in seen:
                continue
            seen.add(id(ev))
            merged.append(ev)
        record['candidates'] = len(merged)
        ordered_rows = [(1.0 / (1 + index), ev) for index, ev in enumerate(merged)]
        ranked, kept = _two_stage_rank(question, ordered_rows, entries, qvec, rerank,
                                       coarse_events=max(1, len(merged)),
                                       fine_pool=fine_pool, fine_keep=fine_keep,
                                       stats=record)
        if ranked:
            scored = ranked
            keep = max(1, kept)
            two_stage_done = True
            record['recent_kept'] = sum(1 for ev in recent_events
                                        if any(str(x.get('event_id')) == str(ev.get('event_id'))
                                               for _s, x in ranked))
        else:
            scored = [(0.0, ev) for ev in merged]
            keep = min(30, len(merged))
    if entry == 'two_stage' and qvec is not None and entries:
        ranked, kept = _two_stage_rank(question, scored, entries, qvec, rerank,
                                       coarse_events=coarse_events, fine_pool=fine_pool,
                                       fine_keep=fine_keep, stats=record)
        if ranked:
            scored = ranked
            keep = max(1, kept)
            two_stage_done = True
        _dbg('recall two_stage ranked=%d keep=%d fine_kept=%s'
             % (len(ranked), keep, record.get('fine_kept')))
        record['rerank_text'] = 'sentence'
    if not two_stage_done:
        if entry == 'sentence' and sent_hits:
            # raw-entry ranking is the whole candidate pool; the reranker decides the top
            scored = sent_hits
            keep = max(1, int(sent_keep))
            record['sent_leg'] = len(sent_hits)
            record['summary_leg'] = 0
        elif entry == 'union' and sent_hits:
            summary_leg = scored[:max(1, int(summary_keep))]
            merged, seen = [], set()
            for score, ev in sorted(summary_leg + sent_hits[:max(1, int(sent_keep))],
                                    key=lambda item: item[0], reverse=True):
                if id(ev) in seen:
                    continue
                seen.add(id(ev))
                merged.append((score, ev))
            scored = merged
            record['summary_leg'] = len(summary_leg)
            record['sent_leg'] = len(sent_hits)
        # entry='sentence' with no hits, or two_stage with nothing found,
        # falls through to the overview ranking below

    if mode == 'rrf':
        keep = min(30, len(scored))
    if rerank is not None and scored and not two_stage_done:
        head = scored[:int(rerank_top or 30)]
        try:
            head_scores = list(_call_rerank(rerank, question, [ev for _s, ev in head],
                                            rerank_text))
        except Exception:
            head_scores = None
        if head_scores and len(head_scores) == len(head):
            head = [(float(sc), ev) for sc, (_old, ev) in zip(head_scores, head)]
            head.sort(key=lambda item: item[0], reverse=True)
            scored = head + scored[len(head):]
            record['rerank_used'] = True
            record['rerank_calls'] = 1
    cands = [ev for _s, ev in scored[:keep]]
    record['pool'] = len(cands)
    order = cands
    if selector is not None:
        try:
            picked = selector(question, cands, budget_tokens)
        except Exception:
            picked = None
        if picked:
            by_id = {str(ev.get('event_id')): ev for ev in cands}
            chosen = []
            for item in picked:
                if isinstance(item, dict) and item in cands:
                    chosen.append(item)
                elif isinstance(item, str) and item in by_id:
                    chosen.append(by_id[item])
            if chosen:
                order = chosen
                record['selector_used'] = True
    out, used = [], 0
    for ev in order:
        if max_events is not None and len(out) >= int(max_events):
            break
        cost = int(ev.get('tokens') or _tokens(ev.get('text')))
        if used + cost > budget_tokens:
            continue
        used += cost
        out.append(ev)
    record['selected'] = len(out)
    record['max_events'] = int(max_events) if max_events is not None else None
    record['tokens'] = used
    record['fill'] = round(used / float(budget_tokens), 4) if budget_tokens else 0.0
    record['underfilled'] = bool(out) and record['fill'] < float(min_budget_fill)
    return out

def _short_stamp(ts):
    try:
        from datetime import datetime
        return datetime.fromtimestamp(float(ts or 0.0)).strftime('%Y-%m-%d %H:%M')
    except Exception:
        return '----'


def rerank_doc(entry, event=None):
    """Rerank input: time + speaker + sentence + a short note clue (sentence intact)."""
    entry = entry if isinstance(entry, dict) else {}
    role = '用户' if str(entry.get('role') or '') == 'user' else '助手'
    note = str((event or {}).get('overview') or '').strip()[:40]
    return '[%s %s] %s ｜ 事件：%s' % (_short_stamp(entry.get('ts')), role,
                                      str(entry.get('text') or ''), note)


def _parse_span_item(item):
    """Tolerant (start, end, text): accepts start/end, s/e, "a-b", case and Chinese keys."""
    if not isinstance(item, dict):
        return None
    lowered = {str(k).lower(): v for k, v in item.items()}
    text = ''
    for key in ('overview', 'summary', 'note', 'text', '概览', '记录'):
        if lowered.get(key):
            text = str(lowered.get(key)).strip().replace('\n', ' ')
            break
    start = end = None
    for key in ('start', 'begin', 'from', '起轮', '开始'):
        if lowered.get(key) is not None:
            start = lowered.get(key)
            break
    for key in ('end', 'to', '止轮', '结束'):
        if lowered.get(key) is not None:
            end = lowered.get(key)
            break
    if start is None and item.get('span'):
        pair = str(item.get('span')).replace('–', '-').replace('—', '-').split('-')
        if len(pair) == 2:
            start, end = pair[0], pair[1]
    if start is None and item.get('轮号'):
        pair = str(item.get('轮号')).replace('–', '-').split('-')
        if len(pair) == 2:
            start, end = pair[0], pair[1]
        elif pair:
            start = end = pair[0]
    if end is None and isinstance(start, str) and ('-' in start or '–' in start):
        pair = start.replace('–', '-').replace('—', '-').split('-')
        if len(pair) == 2:
            start, end = pair[0], pair[1]
    try:
        start_i = int(str(start).strip())
        end_i = int(str(end if end is not None else start).strip())
    except Exception:
        return None
    if end_i < start_i:
        start_i, end_i = end_i, start_i
    return start_i, end_i, text
