#!/usr/bin/env python3
"""
把 Yahoo 官方排名/ADP 与工作区引擎的 9 项估值合并，注入 index.html
- 330 人池（与截图 OCR 匹配池一致）
- 混合排序：Yahoo 排名 + ADP + 引擎 9 项价值
"""
import json, re, unicodedata, pathlib

WS = pathlib.Path("/Users/fanghaoze/Documents/deepseek-harness/default-workspace")
IDX = WS / "index.html"
YAH = WS / "yahoo-fantasy/yahoo_players_raw.json"

eng = json.load(open("/tmp/pool_engine.json", encoding="utf-8"))
yah = json.load(open(YAH, encoding="utf-8"))


def norm(s):
    s = unicodedata.normalize("NFKD", str(s))
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"\b(jr|sr|ii|iii|iv|v)\b", "", s.lower())
    return re.sub(r"[^a-z0-9]", "", s)


yidx = {}
for r in yah:
    for k in (r.get("name"), r.get("ascii_name")):
        if k:
            yidx.setdefault(norm(k), r)

# ---- 组表 ----
rows = []
for e in eng:
    y = yidx.get(norm(e["n"]), {})
    rows.append({
        "n": e["n"],
        "t": y.get("team") or e["t"],
        "p": y.get("positions") or e["p"],
        "a": e["a"],
        "g": e["g"],
        "v": e["v"],                                  # 引擎 9 项价值
        "r": e["r"],
        "fg": e["fg"], "ft": e["ft"],
        "pts": e["pts"], "reb": e["reb"], "ast": e["ast"],
        "tpm": e["tpm"], "stl": e["stl"], "blk": e["blk"], "to": e["to"],
        "yr": y.get("rank_overall"),                  # Yahoo 当前总排名
        "yp": y.get("rank_pos"),                      # Yahoo 位置排名
        "y25": y.get("rank_2025"),                    # Yahoo 上季排名
        "adp": y.get("adp"),
        "own": y.get("percent_owned"),
        "inj": y.get("injury_status") or "",
        "ygp": y.get("L_GP"),                         # 上季出场（Yahoo 口径）
        "ypts": y.get("L_PTS_pg"),
        "yreb": y.get("L_REB_pg"),
        "yast": y.get("L_AST_pg"),
        "ytpm": y.get("L_3PM_pg"),
        "ystl": y.get("L_STL_pg"),
        "yblk": y.get("L_BLK_pg"),
        "yto": y.get("L_TO_pg"),
        "yfg": y.get("L_FG%"),
        "yft": y.get("L_FT%"),
    })

# ---- 混合分 ----
by_rank = sorted([r for r in rows if r["yr"]], key=lambda x: x["yr"])
for i, r in enumerate(by_rank):
    r["rq"] = i / max(len(by_rank) - 1, 1)            # Yahoo 排名分位
adps = sorted([r["adp"] for r in rows if r["adp"]])
for r in rows:
    a = r.get("adp")
    r["aq"] = (sum(1 for x in adps if x < a) / max(len(adps) - 1, 1)) if a else None

vals = [r["v"] for r in rows if r["v"] is not None]
vmin, vmax = min(vals), max(vals)
for r in rows:
    r["vq"] = ((vmax - r["v"]) / (vmax - vmin)) if r["v"] is not None else None

for r in rows:
    parts = [(r["rq"], 0.45)]
    if r["aq"] is not None:
        parts.append((r["aq"], 0.30))
    if r["vq"] is not None:
        parts.append((r["vq"], 0.25))
    wsum = sum(w for _, w in parts)
    r["mix"] = round(sum(q * w for q, w in parts) / wsum, 4)   # 越小越好
rows.sort(key=lambda r: r["mix"])

# ---- 紧凑数组 ----
COLS = ["n","t","p","a","g","v","r","fg","ft","pts","reb","ast","tpm","stl","blk","to",
        "yr","yp","adp","own","inj","ygp","ypts","yreb","yast","ytpm","ystl","yblk","yto","yfg","yft","mix"]
payload = [[r[c] for c in COLS] for r in rows]
data_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

s = IDX.read_text(encoding="utf-8")

# ---- 1. 替换数据块头部（列定义 + 行数据）----
new_head = (
    '/* Yahoo 官方排名/ADP × 引擎 9 项估值 合并数据\n'
    '   字段：' + ",".join(COLS) + '\n'
    '   mix = 混合分（越小越好）= Yahoo排名45% + ADP30% + 引擎价值25%（缺失项自动重新分配权重）*/\n'
    'const POOL_COLS = ' + json.dumps(COLS) + ';\n'
    'const POOL = ' + data_json + '.map(r => { const o = {}; POOL_COLS.forEach((c, i) => o[c] = r[i]); return o; });\n'
    'const POOL_BY_NAME = {}; POOL.forEach(p => POOL_BY_NAME[p.n.toLowerCase()] = p);\n'
)
start = s.find("const POOL_COLS = [")
end = s.find("const ALL_CATS =")
assert start > 0 and end > start, "找不到数据块"
s = s[:start] + new_head + "\n" + s[end:]

IDX.write_text(s, encoding="utf-8")
print(f"✓ 已注入 {len(rows)} 人合并数据（{len(data_json)/1024:.1f} KB JSON）")
print(f"  有 Yahoo 排名 {sum(1 for r in rows if r['yr'])} 人 | 有 ADP {sum(1 for r in rows if r['adp'])} 人 | 有引擎价值 {sum(1 for r in rows if r['v'] is not None)} 人")
print("\n混合排序 Top 12：")
print(f"  {'球员':<26}{'Yahoo':>6}{'ADP':>7}{'引擎值':>8}{'混合分':>8}")
for r in rows[:12]:
    print(f"  {r['n']:<26}{str(r['yr'] or '-'):>6}{str(r['adp'] or '-'):>7}{str(r['v'] or '-'):>8}{r['mix']:>8.3f}")
