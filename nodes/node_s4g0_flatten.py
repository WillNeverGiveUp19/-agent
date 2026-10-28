# -*- coding: utf-8 -*-
"""
节点：S4-G0 拆字段
类型：代码节点
位置：循环体第一个节点（在 S4-G 搜索之前）

作用
    扣子的变量选择器对 Object 类型常常不给展开，导致无法直接引用
    `item.sector` 这类字段。本节点把 picks 的每一条拆成若干扁平变量，
    下游节点用简单类型引用即可。

输入
    item : Object   ← 循环节点的循环变量（当前板块）

输出
    sector   : String   板块名
    stocks   : String   上榜个股，顿号分隔（给提示词用）
    query    : String   拼好的搜索词
    pct_avg  : Number   板块今日涨幅
    excess   : Number   相对大盘超额
    streak   : Integer  连续上榜天数
    distinct : Integer  3 日内不同个股数
    score    : Number   共识分
"""

# ==================== 可调 ====================
QUERY_SUFFIX = "公告 扩产 中标 涨价 研报"   # 搜索词后缀
# ==============================================


async def main(args: Args) -> Output:
    params = args.params
    it = params.get('item') or {}

    # 兼容被包一层的情况：{"item": {...}}
    if isinstance(it, dict) and isinstance(it.get('item'), dict):
        it = it['item']

    sector = str(it.get('sector') or '').strip()

    stocks = it.get('stocks') or []
    if isinstance(stocks, (list, tuple)):
        stocks = '、'.join(str(s) for s in stocks if s)
    else:
        stocks = str(stocks)

    def num(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return 0

    def integer(v):
        try:
            return int(v)
        except (TypeError, ValueError):
            return 0

    ret: Output = {
        'sector':   sector,
        'stocks':   stocks,
        'query':    (sector + ' ' + QUERY_SUFFIX).strip(),
        'pct_avg':  num(it.get('pct_avg')),
        'excess':   num(it.get('excess')),
        'streak':   integer(it.get('streak')),
        'distinct': integer(it.get('distinct')),
        'score':    num(it.get('score')),
    }
    return ret
