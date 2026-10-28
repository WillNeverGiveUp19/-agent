# -*- coding: utf-8 -*-
"""
节点：S2-E3 聚合连击
类型：代码节点
位置：S2-E2 查库 → 【本节点】 → 结束

作用
    读取最近 3 个交易日的原始快照，聚合成板块命中表，再判断「连续几天 + 是否接力」。

输入
    records : Array<Object>   ← S2-E2 查库.outputList
              每条形如 {"trade_date": "2026-10-28", "payload": "[...]"}

输出
    hits       : Array<Object>   当日板块命中（已按 share 排序）
    watchlist  : Array<Object>   连击榜（已归并近义标签）
    trade_date : String
    days_total : Integer         实际参与计算的交易日数
    tot_amt    : Number          当日 Top20 总成交额（亿）

设计要点
    1. 库里只存原始数据，指标在读取时现算 —— 阈值随时可改，历史不会断层。
    2. 先按 trade_date 去重：试运行会重复写入，后写覆盖先写。
    3. 加权命中度 w 不能直接设阈值（每票 10~20 个标签，1/k 只有 0.06），
       必须归一化成有效只数 w_eff = w × 平均标签数 才能用。
    4. 东财同一板块有大量近义标签（半导体/半导体概念/国产芯片…），
       必须按「上榜个股集合重合度」归并，否则一个板块会刷出十几条记录。
"""

import json

# ==================== 可调阈值 ====================
MAX_DAYS      = 3       # 回看天数
MIN_N         = 2       # 板块至少几只票上榜
MIN_SHARE     = 3.0     # 占 Top20 成交额比重（%）
MIN_W_EFF     = 1.5     # 有效只数门槛
DEDUP_JACCARD = 0.85    # 板块归并的重合度阈值（0.7 会误并人工智能/物联网）
STRONG_STREAK = 3       # 强候选：连续几天
WATCH_STREAK  = 2       # 观察：连续几天
# =================================================


def _agg(stocks):
    """把一天的 20 只票聚合成板块命中表"""
    tot = sum(s['amount'] for s in stocks) or 1
    ks = [len(s.get('tags') or []) for s in stocks if s.get('tags')]
    k_avg = (sum(ks) / len(ks)) if ks else 1.0   # 当日平均标签数

    agg = {}
    for s in stocks:
        tags = s.get('tags') or []
        if not tags:
            continue
        wgt = 1.0 / len(tags)              # 一股多标签，权重摊薄
        for t in tags:
            a = agg.setdefault(t, {'w': 0.0, 'n': 0, 'amt': 0.0, 'stocks': [], 'pcts': []})
            a['w'] += wgt
            a['n'] += 1
            a['amt'] += s['amount']
            a['stocks'].append(s['name'])
            a['pcts'].append(s['pct'])

    hits = {}
    for t, a in agg.items():
        share = a['amt'] / tot * 100
        w_eff = a['w'] * k_avg             # 归一化：还原成「有效只数」
        if a['n'] < MIN_N or share < MIN_SHARE or w_eff < MIN_W_EFF:
            continue
        hits[t] = {
            'sector':  t,
            'w':       round(a['w'], 3),
            'w_eff':   round(w_eff, 2),
            'n':       a['n'],
            'amt':     round(a['amt'], 2),
            'share':   round(share, 2),
            'pct_avg': round(sum(a['pcts']) / len(a['pcts']), 2),
            'stocks':  a['stocks'],
        }
    return hits, round(tot, 2)


def _dedup(watch):
    """把上榜个股高度重合的标签合并成一个代表板块"""
    order = {'强候选': 0, '观察': 1, '间歇': 2}
    items = sorted(watch, key=lambda x: (order[x['level']],
                                         -round(x['share'] or 0, 1),
                                         len(x['sector']), x['sector']))
    kept = []
    for w in items:
        s = set(w['stocks'])
        for k in kept:
            ks = set(k['stocks'])
            u = len(s | ks)
            if u and len(s & ks) / u >= DEDUP_JACCARD:
                k.setdefault('alias', []).append(w['sector'])
                k['streak'] = max(k['streak'], w['streak'])
                k['distinct'] = max(k['distinct'], w['distinct'])
                if order[w['level']] < order[k['level']]:
                    k['level'] = w['level']
                break
        else:
            kept.append(dict(w))
    return kept


async def main(args: Args) -> Output:
    params = args.params
    recs = params['records'] or []

    # 1) 按日期去重，保留最新一条（试运行会重复写）
    by_date = {}
    for r in recs:
        d = r.get('trade_date')
        if not d:
            continue
        p = r.get('payload') or '[]'
        by_date[d] = json.loads(p) if isinstance(p, str) else p

    dates = sorted(by_date.keys())[-MAX_DAYS:]
    if not dates:
        ret: Output = {'hits': [], 'watchlist': [], 'trade_date': '',
                       'days_total': 0, 'tot_amt': 0}
        return ret

    hist, tot_amt = [], 0
    for d in dates:
        h, ta = _agg(by_date[d])
        hist.append((d, h))
        tot_amt = ta

    today = dates[-1]
    hits_today = sorted(hist[-1][1].values(), key=lambda x: (-x['share'], -x['w']))
    for i, h in enumerate(hits_today):
        h['rank'] = i + 1

    # 2) 连击判定
    universe = set()
    for _, m in hist:
        universe |= set(m.keys())

    watch = []
    for sec in universe:
        appear = [(d, m[sec]) for d, m in hist if sec in m]

        streak = 0                                  # 从今天往回数的连续天数
        for d, m in reversed(hist):
            if sec in m:
                streak += 1
            else:
                break

        union = set()
        for _, x in appear:
            union |= set(x['stocks'])

        cur = hist[-1][1].get(sec)
        prev = hist[-2][1].get(sec) if len(hist) >= 2 else None
        trend = round(cur['share'] - prev['share'], 2) if (cur and prev) else None

        level = None
        if streak >= STRONG_STREAK:
            level = '强候选'
        elif streak == WATCH_STREAK:
            level = '观察'
        elif len(hist) >= 3 and len(appear) >= 2 and cur:
            level = '间歇'
        if not level:
            continue

        watch.append({
            'sector':   sec,
            'level':    level,
            'streak':   streak,
            'days':     len(appear),
            'distinct': len(union),
            'relay':    len(union) > max((x['n'] for _, x in appear), default=0),
            'share':    cur['share'] if cur else None,
            'trend':    trend,
            'n_today':  cur['n'] if cur else 0,
            'amount':   cur['amt'] if cur else None,
            'stocks':   cur['stocks'] if cur else [],
        })

    order = {'强候选': 0, '观察': 1, '间歇': 2}
    watch = _dedup(watch)                      # 合并近义标签，避免同一板块刷屏
    watch.sort(key=lambda x: (order[x['level']],
                              -round(x['share'] or 0, 1),
                              len(x['sector']), x['sector']))

    ret: Output = {
        'hits':       hits_today,
        'watchlist':  watch,
        'trade_date': today,
        'days_total': len(dates),
        'tot_amt':    tot_amt,
    }
    return ret
