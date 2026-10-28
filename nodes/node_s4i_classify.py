# -*- coding: utf-8 -*-
"""
节点：S4-I 逻辑分级
类型：代码节点
位置：循环体（搜索 + 大模型）→ 【本节点】 → 结束

作用
    把大模型对每个板块产出的产业逻辑 JSON，合并成列表，并按驱动性质分级
    A / B / C，给出仓位建议。

输入
    results : Array<Object>   循环节点的输出，每条形如
              {"sector": "通信", "driver": "订单", "catalyst": [...],
               "chain": {...}, "shovel": [...], "prosperity": "上行",
               "duration": "强", "risk": [...], "confidence": 70,
               "one_liner": "..."}

输出
    logic      : Array<Object>   分级后的列表，A 在前
    count_a    : Integer
    count_b    : Integer
    count_c    : Integer
    summary    : String          一句话概括，可直接拼进日报

分级规则
    A 类（正常仓位）：政策 / 订单 / 涨价 / 技术 驱动，且景气度上行
    B 类（半仓）    ：事件驱动，或景气度平稳，或持续性偏弱
    C 类（只观察）  ：纯资金驱动，或景气度下行

为什么分级
    决定仓位的第一步不是「这个板块好不好」，而是「这波钱是产业逻辑带来的
    还是纯情绪带来的」。前者可以给时间，后者只能给分钟。
"""

# ==================== 可调规则 ====================
CLASS_A_DRIVERS = {'政策', '订单', '涨价', '技术'}
CLASS_B_DRIVERS = {'事件'}
POSITION = {
    'A': '正常仓位',
    'B': '半仓',
    'C': '只观察，不参与',
}
MIN_CONFIDENCE = 40      # 低于此置信度，A 类降为 B 类
# =================================================


def _norm(x):
    """大模型有时会把 JSON 包在循环输出的一层里"""
    if isinstance(x, dict) and 'item' in x and isinstance(x['item'], dict):
        return x['item']
    return x


def _grade(item):
    driver = (item.get('driver') or '').strip()
    prosperity = (item.get('prosperity') or '').strip()
    duration = (item.get('duration') or '').strip()
    conf = item.get('confidence')
    conf = conf if isinstance(conf, (int, float)) else 50

    if driver == '纯资金':
        return 'C', '纯资金驱动，没有产业逻辑支撑'
    if prosperity == '下行':
        return 'C', '景气度下行'
    if driver in CLASS_A_DRIVERS and prosperity == '上行':
        if conf < MIN_CONFIDENCE:
            return 'B', f'{driver}驱动但置信度仅{conf:.0f}'
        return 'A', f'{driver}驱动，景气度上行'
    if driver in CLASS_B_DRIVERS:
        return 'B', '事件驱动，缺乏持续性'
    if duration == '弱':
        return 'C', '持续性弱'
    return 'B', f'{driver or "未识别"}驱动，景气度{prosperity or "未知"}'


async def main(args: Args) -> Output:
    params = args.params
    raw = params.get('results') or []

    logic = []
    for r in raw:
        it = _norm(r)
        if not isinstance(it, dict):
            continue
        sector = it.get('sector') or ''
        if not sector:
            continue

        cls, why = _grade(it)

        chain = it.get('chain') or {}
        logic.append({
            'sector':     sector,
            'class':      cls,
            'position':   POSITION[cls],
            'grade_why':  why,
            'driver':     it.get('driver') or '未识别',
            'catalyst':   it.get('catalyst') or [],
            'prosperity': it.get('prosperity') or '未知',
            'duration':   it.get('duration') or '未知',
            'chain': {
                'upstream':   chain.get('upstream') or [],
                'midstream':  chain.get('midstream') or [],
                'downstream': chain.get('downstream') or [],
            },
            'shovel':     it.get('shovel') or [],
            'risk':       it.get('risk') or [],
            'confidence': it.get('confidence') if isinstance(it.get('confidence'), (int, float)) else 50,
            'one_liner':  it.get('one_liner') or '',
        })

    order = {'A': 0, 'B': 1, 'C': 2}
    logic.sort(key=lambda x: (order[x['class']], -x['confidence']))

    count = {k: sum(1 for x in logic if x['class'] == k) for k in 'ABC'}

    if not logic:
        summary = '本次无板块通过逻辑验证'
    else:
        a = [x['sector'] for x in logic if x['class'] == 'A']
        b = [x['sector'] for x in logic if x['class'] == 'B']
        parts = []
        if a:
            parts.append('A类（可给时间）：' + '、'.join(a))
        if b:
            parts.append('B类（半仓）：' + '、'.join(b))
        if not parts:
            parts.append('全部为纯资金炒作，不参与')
        summary = '；'.join(parts)

    ret: Output = {
        'logic':   logic,
        'count_a': count['A'],
        'count_b': count['B'],
        'count_c': count['C'],
        'summary': summary,
    }
    return ret
