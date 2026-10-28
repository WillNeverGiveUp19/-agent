# -*- coding: utf-8 -*-
"""
节点：S3-F 共识打分
类型：代码节点
位置：S2-E3 聚合连击 → 【本节点】 → 结束

作用
    把 S2-E3 的 watchlist（连击板块）打分排序，收敛到 2~4 条真正的强共识，
    避免下一步在十几个板块上平均用力。

输入
    records   : Array<Object>   ← S2-E2 查库.outputList（近 3 日原始快照）
    watchlist : Array<Object>   ← S2-E3.watchlist（已含 streak / distinct / trend）

输出
    scored : Array<Object>   打分后的板块，按 score 降序
    passed : Integer         score >= GATE_WATCH 的数量
    strong : Integer         score >= GATE_STRONG 的数量

五个维度（各 20 分，权重在 WEIGHTS 里可调）
    广度  streak 连续几天 + distinct 几只票接力
    资金  上榜个股主力净流入 / 成交额，且连续为正
    强度  板块平均涨幅 相对 Top20 平均涨幅 的超额
    趋势  成交额份额环比变化 + 上榜只数是否扩大
    健康  换手率、振幅是否在健康区间（过热/无量都扣分）

为什么没有「涨得多」这一维
    涨幅是结果不是原因。真正区分强弱的是：多少票在参与、钱有没有真进来、
    今天的钱比昨天多还是少。

注意
    1. 数据不足 3 天时，广度天然低分，总分到不了 70 —— 这是对的，不是 bug。
    2. 资金口径是「上榜个股净流入之和」，不是「板块主力净流入」，语义要清楚。
"""

# ==================== 可调阈值 ====================
WEIGHTS = {
    'breadth':  20,   # 广度
    'flow':     20,   # 资金
    'strength': 20,   # 强度
    'trend':    20,   # 趋势
    'health':   20,   # 健康
}

GATE_STRONG = 70      # 强共识：进 Step 4 看产业逻辑
GATE_WATCH  = 50      # 观察：留池子，明天再看
MAX_DAYS    = 3       # 回看天数
MAX_PICK    = 3       # 最终推荐几个板块
PICK_JACCARD = 0.5    # 挑选时，与已选板块的股票重合度超过此值就跳过
# =================================================


def _median(xs):
    ys = sorted(x for x in xs if x is not None)
    n = len(ys)
    if n == 0:
        return None
    m = n // 2
    return ys[m] if n % 2 else (ys[m - 1] + ys[m]) / 2.0


def _stock_rows(day_stocks, sector):
    """当日快照里，带该板块标签的个股"""
    return [s for s in day_stocks if sector in (s.get('tags') or [])]


def _score_breadth(w):
    """广度：连续天数 + 接力只数"""
    streak = w.get('streak') or 0
    distinct = w.get('distinct') or 0
    relay = w.get('relay')
    if streak >= 3 and distinct >= 3:
        return 1.0, f'连续{streak}天，{distinct}只票接力'
    if streak >= 3:
        return 0.8, f'连续{streak}天，但只有{distinct}只票'
    if streak == 2 and distinct >= 3:
        return 0.6, f'连续{streak}天，{distinct}只票接力'
    if streak == 2:
        return 0.4, f'连续2天，{distinct}只票'
    if relay:
        return 0.3, f'间歇上榜，{distinct}只票接力'
    return 0.15, '仅单日上榜'


def _score_flow(inflows, amounts):
    """资金：上榜个股净流入占成交额比重，且连续为正"""
    if not amounts or not amounts[-1]:
        return 0.0, '无资金数据'
    ratio = inflows[-1] / amounts[-1] * 100
    pos = 0
    for v in reversed(inflows):
        if v > 0:
            pos += 1
        else:
            break
    if ratio >= 8 and pos >= 2:
        return 1.0, f'净流入占比{ratio:.1f}%，连续{pos}天为正'
    if ratio >= 5 and pos >= 2:
        return 0.8, f'净流入占比{ratio:.1f}%，连续{pos}天为正'
    if ratio >= 3:
        return 0.6, f'净流入占比{ratio:.1f}%'
    if ratio > 0:
        return 0.4, f'净流入占比{ratio:.1f}%，力度偏弱'
    return 0.0, f'净流出{abs(ratio):.1f}%'


def _score_strength(pct_avg, mkt_pct):
    """强度：相对 Top20 平均涨幅的超额"""
    ex = (pct_avg or 0) - mkt_pct
    if ex >= 5:
        return 1.0, f'跑赢大盘{ex:.1f}个百分点'
    if ex >= 3:
        return 0.8, f'跑赢{ex:.1f}个百分点'
    if ex >= 1.5:
        return 0.6, f'小幅跑赢{ex:.1f}个百分点'
    if ex > 0:
        return 0.4, f'微弱领先{ex:.1f}个百分点'
    return 0.15, f'落后大盘{abs(ex):.1f}个百分点'


def _score_trend(share_now, share_prev, n_now, n_prev):
    """趋势：成交额份额环比 + 上榜只数变化"""
    if share_prev is None or share_prev == 0:
        return 0.4, '无前一日数据'
    rel = (share_now - share_prev) / share_prev
    growing = n_now >= (n_prev or 0)
    if rel >= 0.2 and growing:
        return 1.0, f'份额+{rel*100:.0f}%，参与面扩大'
    if rel >= 0.05 and growing:
        return 0.75, f'份额+{rel*100:.0f}%'
    if abs(rel) < 0.05 and growing:
        return 0.6, '份额持平，参与面未缩'
    if rel >= 0.05:
        return 0.5, f'份额+{rel*100:.0f}%，但票数减少'
    if rel <= -0.15:
        return 0.15, f'份额{rel*100:.0f}%，资金在撤'
    return 0.35, '份额小幅回落'


def _score_health(to_med, amp_med):
    """健康：换手率与振幅是否在可参与区间"""
    if to_med is None:
        return 0.5, '无换手数据'
    amp = amp_med or 0
    if to_med > 25:
        return 0.3, f'换手中位{to_med:.1f}%，筹码过热'
    if to_med < 3:
        return 0.5, f'换手中位{to_med:.1f}%，参与度不足'
    if amp >= 12:
        return 0.4, f'振幅中位{amp:.1f}%，分歧过大'
    if amp < 8:
        return 1.0, f'换手{to_med:.1f}%、振幅{amp:.1f}%，量价健康'
    return 0.7, f'换手{to_med:.1f}%、振幅{amp:.1f}%'


async def main(args: Args) -> Output:
    import json

    params = args.params
    recs = params['records'] or []
    watchlist = params['watchlist'] or []

    # 1) 按日期去重并排序
    by_date = {}
    for r in recs:
        d = r.get('trade_date')
        if not d:
            continue
        p = r.get('payload') or '[]'
        by_date[d] = json.loads(p) if isinstance(p, str) else p
    dates = sorted(by_date.keys())[-MAX_DAYS:]

    if not dates or not watchlist:
        ret: Output = {'scored': [], 'picks': [], 'passed': 0, 'strong': 0}
        return ret

    today = dates[-1]
    prev_day = dates[-2] if len(dates) >= 2 else None
    today_stocks = by_date[today]
    prev_stocks = by_date[prev_day] if prev_day else []

    # 2) 基准：Top20 平均涨幅
    mkt_pct = sum(s['pct'] for s in today_stocks) / len(today_stocks) if today_stocks else 0

    scored = []
    for w in watchlist:
        sec = w['sector']

        # 逐日资金与成交额
        inflows, amounts = [], []
        for d in dates:
            rows = _stock_rows(by_date[d], sec)
            amounts.append(sum(r['amount'] for r in rows))
            inflows.append(sum((r.get('main_in') or 0) for r in rows))

        rows_today = _stock_rows(today_stocks, sec)
        rows_prev = _stock_rows(prev_stocks, sec) if prev_day else []

        pct_avg = (sum(r['pct'] for r in rows_today) / len(rows_today)) if rows_today else 0
        to_med = _median([r.get('turnover') for r in rows_today])
        amp_med = _median([r.get('amp') for r in rows_today])

        tot_today = sum(s['amount'] for s in today_stocks) or 1
        tot_prev = sum(s['amount'] for s in prev_stocks) or 1
        share_now = (sum(r['amount'] for r in rows_today) / tot_today * 100) if rows_today else 0
        share_prev = (sum(r['amount'] for r in rows_prev) / tot_prev * 100) if rows_prev else None

        r1, why1 = _score_breadth(w)
        r2, why2 = _score_flow(inflows, amounts)
        r3, why3 = _score_strength(pct_avg, mkt_pct)
        r4, why4 = _score_trend(share_now, share_prev, len(rows_today), len(rows_prev))
        r5, why5 = _score_health(to_med, amp_med)

        ratios = {'breadth': r1, 'flow': r2, 'strength': r3, 'trend': r4, 'health': r5}
        whys = {'breadth': why1, 'flow': why2, 'strength': why3, 'trend': why4, 'health': why5}

        total = sum(WEIGHTS[k] * ratios[k] for k in WEIGHTS)

        if total >= GATE_STRONG:
            grade = '强共识'
        elif total >= GATE_WATCH:
            grade = '观察'
        else:
            grade = '放弃'

        scored.append({
            'sector': sec,
            'score': round(total, 1),
            'grade': grade,
            'dims': {k: round(WEIGHTS[k] * ratios[k], 1) for k in WEIGHTS},
            'reasons': [whys[k] for k in ('breadth', 'flow', 'strength', 'trend', 'health')],
            'streak': w.get('streak'),
            'days': w.get('days'),
            'distinct': w.get('distinct'),
            'relay': w.get('relay'),
            'share': round(share_now, 2),
            'share_trend': w.get('trend'),
            'n_today': len(rows_today),
            'inflow': round(inflows[-1], 2),
            'inflow_ratio': round(inflows[-1] / amounts[-1] * 100, 2) if amounts[-1] else 0,
            'pct_avg': round(pct_avg, 2),
            'excess': round(pct_avg - mkt_pct, 2),
            'stocks': w.get('stocks') or [r['name'] for r in rows_today],
        })

    scored.sort(key=lambda x: (-x['score'], x['sector']))

    # 3) 挑选：分数达标 + 与已选板块股票重合度低
    picks, picked_sets = [], []
    for x in scored:
        if x['score'] < GATE_WATCH:
            break
        cur = set(x['stocks'])
        dup = None
        for i, ps in enumerate(picked_sets):
            u = len(cur | ps)
            if u and len(cur & ps) / u >= PICK_JACCARD:
                dup = picks[i]['sector']
                break
        if dup:
            x['dup_of'] = dup
            continue
        if len(picks) < MAX_PICK:
            picks.append(x)
            picked_sets.append(cur)

    passed = sum(1 for x in scored if x['score'] >= GATE_WATCH)
    strong = sum(1 for x in scored if x['score'] >= GATE_STRONG)

    ret: Output = {'scored': scored, 'picks': picks,
                   'passed': passed, 'strong': strong}
    return ret
