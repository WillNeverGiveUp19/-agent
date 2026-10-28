# -*- coding: utf-8 -*-
"""
节点：S1-B 归一化
类型：代码节点
位置：S1-A 取榜单(HTTP) → 【本节点】 → S1-C 取标签(HTTP)

作用
    把腾讯成交额榜的原始响应，转成 20 只标准股票对象，并生成下游取标签用的
    完整 filter 表达式。

输入
    body : String    ← S1-A 取榜单.body

输出
    top20      : Array<Object>
    code_in    : String          "300308","300502",...
    filter_str : String          (SECURITY_CODE in ("300308",...))
    cut        : Number          第 20 名成交额（亿）
    n          : Integer

注意
    1. 输入必须绑到 HTTP 节点的 body 字段，不能绑整个节点；
       绑错时 body 会变成 {"body": "..."}，_load() 会自动解开，但仍然建议绑对。
    2. filter_str 是给 S1-C 直接用的完整表达式，不要在 UI 里手工拼接。
"""

import json


def _f(v, default=None):
    try:
        if v is None or v == '':
            return default
        return float(v)
    except Exception:
        return default


def _load(raw):
    """把可能被多层包裹的响应解开，直到拿到真正的 dict"""
    d = raw
    for _ in range(4):
        if isinstance(d, (bytes, bytearray)):
            d = d.decode('utf-8')
        if isinstance(d, str):
            try:
                d = json.loads(d)
            except Exception:
                break
        elif isinstance(d, dict) and 'body' in d and 'data' not in d and 'result' not in d:
            d = d.get('body')
        else:
            break
    return d


async def main(args: Args) -> Output:
    params = args.params
    d = _load(params['body'])

    if not isinstance(d, dict):
        ret: Output = {'top20': [], 'code_in': '', 'filter_str': '',
                       'cut': 0, 'n': 0}
        return ret

    rows = (d.get('data') or {}).get('rank_list') or []

    out = []
    for x in rows:
        nm = x.get('name') or ''
        if 'ST' in nm or '退' in nm:            # 剔除 ST / 退市
            continue
        amt = _f(x.get('turnover'), 0.0) / 1e4   # 万元 -> 亿元
        if amt <= 0:
            continue
        out.append({
            'code':     (x.get('code') or '')[2:],
            'market':   (x.get('code') or '')[:2],
            'name':     nm,
            'price':    _f(x.get('zxj'), 0.0),
            'pct':      _f(x.get('zdf'), 0.0),
            'amount':   round(amt, 2),
            'turnover': _f(x.get('hsl'), 0.0),
            'pe':       _f(x.get('pe_ttm')),
            'pb':       _f(x.get('pn')),
            'mktcap':   _f(x.get('zsz'), 0.0),
            'main_in':  round(_f(x.get('zljlr'), 0.0) / 1e4, 2),
            'amp':      _f(x.get('zf'), 0.0),
            'd5':       _f(x.get('zdf_d5'), 0.0),
            'd20':      _f(x.get('zdf_d20'), 0.0),
        })

    out.sort(key=lambda r: -r['amount'])
    top20 = out[:20]
    for i, r in enumerate(top20):
        r['rank'] = i + 1

    codes = ['"%s"' % r['code'] for r in top20]

    ret: Output = {
        'top20':      top20,
        'code_in':    ','.join(codes),
        'filter_str': '(SECURITY_CODE in (' + ','.join(codes) + '))',
        'cut':        top20[-1]['amount'] if top20 else 0,
        'n':          len(top20),
    }
    return ret
