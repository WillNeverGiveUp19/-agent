# -*- coding: utf-8 -*-
"""
本地回归测试

用途
    不打开扣子也能验证三个节点文件能否正常执行、阈值是否符合预期。
    改完阈值后先跑一遍，避免把错误贴进扣子再回头排查。

运行
    python3 tests/test_nodes.py

原理
    节点文件里的 `Args` / `Output` 是扣子运行时注入的，本地用模拟对象顶替，
    这样可以直接 exec 原文件，不需要为测试改动节点代码。
"""

import asyncio
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
NODES = ROOT / "nodes"


class P:
    """模拟扣子的 args 对象：main(args) 里通过 args.params 取入参"""

    def __init__(self, **kw):
        self.params = kw


def load_node(filename):
    """exec 节点源码，返回其 main 协程函数"""
    src = (NODES / filename).read_text(encoding="utf-8")
    ns = {"Args": object, "Output": dict, "__name__": "node"}
    exec(compile(src, filename, "exec"), ns)
    return ns


def run(node_main, **params):
    return asyncio.run(node_main(P(**params)))


failures = []


def check(label, cond, detail=""):
    if cond:
        print(f"  ✓ {label}")
    else:
        print(f"  ✗ {label}  {detail}")
        failures.append(label)


# ---------------------------------------------------------------- S1-B
print("S1-B 归一化")
b = load_node("node_s1b_normalize.py")

fake_rank = {
    "data": {"rank_list": [
        {"code": "sz300308", "name": "中际旭创", "turnover": "2357261", "zxj": "636.30",
         "zdf": "10.28", "hsl": "3.46", "pe_ttm": "36.64", "pn": "19.49",
         "zsz": "7495.04", "zljlr": "317145.57", "zf": "8.34",
         "zdf_d5": "-1.62", "zdf_d20": "-31.32"},
        {"code": "sh600036", "name": "招商银行", "turnover": "455300", "zxj": "42.13",
         "zdf": "-2.00", "hsl": "0.52", "pe_ttm": "7.00", "pn": "0.93",
         "zsz": "10625.12", "zljlr": "72800.00", "zf": "1.93",
         "zdf_d5": "-0.35", "zdf_d20": "3.21"},
        {"code": "sz000001", "name": "ST测试", "turnover": "1000", "zxj": "1",
         "zdf": "0", "hsl": "1", "pe_ttm": "", "pn": "", "zsz": "1",
         "zljlr": "0", "zf": "1", "zdf_d5": "0", "zdf_d20": "0"},
    ]}
}
out_b = run(b["main"], body=json.dumps(fake_rank, ensure_ascii=False))
check("ST 被剔除", out_b["n"] == 2, f"n={out_b['n']}")
check("成交额万元→亿元", out_b["top20"][0]["amount"] == 235.73, out_b["top20"][0]["amount"])
check("filter_str 带前后括号",
      out_b["filter_str"].startswith("(SECURITY_CODE in (") and out_b["filter_str"].endswith("))"),
      out_b["filter_str"])
check("空 pe 转成 None", out_b["top20"][1]["pe"] == 7.0)

# 双层包裹的 body 也要能解开
out_b2 = run(b["main"], body=json.dumps({"body": json.dumps(fake_rank)}))
check("双层 body 自动解包", out_b2["n"] == 2, f"n={out_b2['n']}")

# ---------------------------------------------------------------- S1-D
print("S1-D 合并去噪")
d = load_node("node_s1d_merge_tags.py")

NOISE = ["标准普尔", "大盘股", "东方财富热股", "深证100R", "基金减仓", "茅指数",
         "创业板综", "行业龙头", "深圳特区", "白酒Ⅱ", "上证180_", "2026中报预增"]
GOOD = ["半导体", "CPO概念", "光通信模块", "存储芯片", "AI眼镜", "人形机器人",
        "PCB", "通信", "白酒", "创新药", "液冷服务器", "第三代半导体"]
for t in NOISE:
    check(f"拦截噪声 {t}", not d["_keep"](t))
for t in GOOD:
    check(f"保留板块 {t}", d["_keep"](t))

fake_tags = {"result": {"data": [
    {"SECURITY_CODE": "300308", "BOARD_NAME": t}
    for t in ["CPO概念", "标准普尔", "大盘股", "5G概念"]
]}}
out_d = run(d["main"], stock_list=out_b["top20"],
            tag_body=json.dumps(fake_tags, ensure_ascii=False))
check("标签已合并到票上", out_d["stock_tags"][0]["tags"] == ["CPO概念", "5G概念"],
      out_d["stock_tags"][0]["tags"])
check("n_raw 记录去噪前数量", out_d["stock_tags"][0]["n_raw"] == 4)
check("raw_payload 可反序列化",
      len(json.loads(out_d["raw_payload"])) == 2)

# ---------------------------------------------------------------- S2-E3
print("S2-E3 聚合连击")
e = load_node("node_s2e3_aggregate.py")

records = json.loads((ROOT / "tests" / "sample_records.json").read_text(encoding="utf-8"))
out_e = run(e["main"], records=records)

check("重复日期已去重", out_e["days_total"] == 3, f"days_total={out_e['days_total']}")
check("hits 非空", len(out_e["hits"]) > 0, len(out_e["hits"]))
check("watchlist 非空（3 天应有连击）", len(out_e["watchlist"]) > 0, len(out_e["watchlist"]))
check("总成交额量级正常", 500 < out_e["tot_amt"] < 5000, out_e["tot_amt"])

forbidden = {"标准普尔", "大盘股", "东方财富热股", "深证100R", "茅指数"}
leaked = [h["sector"] for h in out_e["hits"] if h["sector"] in forbidden]
check("hits 中无噪声标签", not leaked, leaked)

top = out_e["watchlist"][0]
check("watchlist 首条是强候选", top["level"] == "强候选", top["level"])
check("streak 正确", top["streak"] == 3, top["streak"])
alias_count = sum(len(w.get("alias", [])) for w in out_e["watchlist"])
check("近义标签被归并（alias 非空）", alias_count > 0, alias_count)
print(f"  · 归并掉的近义标签数：{alias_count}")

empty = run(e["main"], records=[])
check("空记录不报错", empty["days_total"] == 0 and empty["hits"] == [])

# ---------------------------------------------------------------- S3-F
print("S3-F 共识打分")
f = load_node("node_s3f_score.py")

out_f = run(f["main"], records=records, watchlist=out_e["watchlist"])

check("scored 非空", len(out_f["scored"]) > 0, len(out_f["scored"]))
check("按分数降序",
      all(out_f["scored"][i]["score"] >= out_f["scored"][i + 1]["score"]
          for i in range(len(out_f["scored"]) - 1)))
check("picks 不超过 MAX_PICK", len(out_f["picks"]) <= 3, len(out_f["picks"]))
check("picks 分数均达标",
      all(x["score"] >= 50 for x in out_f["picks"]))

# 每条记录的五个维度之和应等于总分
bad_sum = [x["sector"] for x in out_f["scored"]
           if abs(sum(x["dims"].values()) - x["score"]) > 0.2]
check("维度之和等于总分", not bad_sum, bad_sum[:3])

# picks 之间不能是同一批票
overlap = []
for i in range(len(out_f["picks"])):
    for j in range(i + 1, len(out_f["picks"])):
        a = set(out_f["picks"][i]["stocks"])
        b = set(out_f["picks"][j]["stocks"])
        u = len(a | b)
        if u and len(a & b) / u >= 0.5:
            overlap.append((out_f["picks"][i]["sector"], out_f["picks"][j]["sector"]))
check("picks 之间股票不重合", not overlap, overlap)

check("每条都有 5 个维度",
      all(len(x["dims"]) == 5 for x in out_f["scored"]))
check("每条都有 5 条理由",
      all(len(x["reasons"]) == 5 for x in out_f["scored"]))
check("重复板块被标记 dup_of",
      any("dup_of" in x for x in out_f["scored"]),
      "没有任何板块被判重复，检查 PICK_JACCARD")

empty_f = run(f["main"], records=[], watchlist=[])
check("空输入不报错", empty_f["scored"] == [] and empty_f["picks"] == [])

print(f"  · 当前样本：{out_f['strong']} 个强共识 / {out_f['passed']} 个达标 / "
      f"最终推荐 {[p['sector'] for p in out_f['picks']]}")

# ---------------------------------------------------------------- 汇总
print()
if failures:
    print(f"失败 {len(failures)} 项：{failures}")
    sys.exit(1)
print("全部通过")
