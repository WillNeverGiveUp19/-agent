# -*- coding: utf-8 -*-
"""
节点：S1-D 合并去噪
类型：代码节点
位置：S1-C 取标签(HTTP) → 【本节点】 → S2-E1 写库

作用
    把东财 F10 题材标签合并进股票对象，并按「固定黑名单 + 正则规则」剔除噪声。

输入
    stock_list : Array<Object>   ← S1-B.top20
    tag_body   : String          ← S1-C.body

输出
    stock_tags  : Array<Object>  带 tags / n_tag / n_raw
    n_tag_total : Integer        去噪前的原始标签总数（用于校验，应约 600~750）
    raw_payload : String         当日快照 JSON，直接存入数据库
    trade_date  : String         YYYY-MM-DD

为什么要有黑名单
    东财给每只票 25~40 个标签，其中大量是伪板块。不去噪的话，「融资融券」
    「标准普尔」「大盘股」这类每天出现，会让「连续两三天集中出现」彻底失效。

为什么用正则而不是纯枚举
    指数成分类标签（深证100R / 深成500 / 中证500 …）会不断新增，
    纯枚举永远漏。按词根 + 锚定匹配可以一次性覆盖。
"""

import json
import re
import datetime

# ==================== 可调规则 ====================
# 固定黑名单：语义明确的噪声标签
DROP = {
    # 资金 / 持仓
    "融资融券", "沪股通", "深股通", "AH股", "转债标的", "证金持股", "大基金持股",
    # 打包组合 / 身份标签
    "茅指数", "宁组合", "核心资产", "中特估", "行业龙头", "权重股", "独角兽", "超级品牌",
    "周期股", "趋势股", "专精特新", "新型工业化", "味蕾经济", "壳资源", "ST股",
    # 交易属性
    "高市净率", "高成长股", "高股息率", "破增发价股", "破净股", "百元股", "低价股",
    "高价股", "次新股", "高送转", "昨日涨停", "昨日连板", "昨日触板", "昨日高振幅",
    "股权分散", "东方财富热股",
    # 地域
    "一带一路", "京津冀", "粤港澳", "东北振兴", "自贸区",
    # 业绩预告
    "预盈预增", "预亏预减",
    # 杂项
    "贬值受益", "创投", "参股银行", "参股券商", "参股保险", "股权激励", "乡村振兴",
}

# 正则黑名单：按模式拦截的噪声
PATS = [
    re.compile(r"(标准普尔|标普|MSCI|富时|罗素|道琼斯|深证|上证|中证|沪深|国证|深成|创业板综|创业成份|科创50|北证50)"),
    re.compile(r"(重仓|增仓|减仓|新进|持股|调研|金股)"),
    re.compile(r"^(大盘|中盘|小盘|微盘)"),
    re.compile(r"(风格|板块|特区|三角|大开发|经济带)$"),
    re.compile(r"[ⅠⅡⅢⅣ]$"),
    re.compile(r"^昨日"),
    re.compile(r"^\d{4}.*(预增|预减|预盈|预亏|中报|年报|季报)"),
]
# =================================================


def _load(raw):
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


def _keep(t):
    if t in DROP:
        return False
    if t.endswith("_"):
        return False
    return not any(p.search(t) for p in PATS)


async def main(args: Args) -> Output:
    params = args.params
    stocks = params['stock_list']
    d = _load(params['tag_body'])
    rows = ((d or {}).get('result') or {}).get('data') or []

    by = {}
    for r in rows:
        by.setdefault(r.get('SECURITY_CODE'), []).append(r.get('BOARD_NAME'))

    stock_tags = []
    for s in stocks:
        raw_tags = by.get(s['code'], [])
        tags = [t for t in raw_tags if t and _keep(t)]
        s2 = dict(s)
        s2['tags'] = tags
        s2['n_tag'] = len(tags)
        s2['n_raw'] = len(raw_tags)
        stock_tags.append(s2)

    ret: Output = {
        'stock_tags':  stock_tags,
        'n_tag_total': sum(x['n_raw'] for x in stock_tags),
        'raw_payload': json.dumps(stock_tags, ensure_ascii=False),
        'trade_date':  datetime.date.today().isoformat(),
    }
    return ret
