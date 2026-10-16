#!/usr/bin/env python3
"""
重建 index.html 里的球员池：330 引擎球员 + 403 名 Yahoo 独有球员 = 733 人
- 引擎球员：保留 9 项投影值（v）与逐项统计
- Yahoo 独有球员：用 Yahoo 上赛季场均补齐 9 项，v 留空
- 所有球员统一算混合分（Yahoo 排名 45% + ADP 30% + 引擎价值 25%，缺项重分配权重）
"""
import json, re, unicodedata, pathlib

WS = pathlib.Path("/Users/fanghaoze/Documents/deepseek-harness/default-workspace")
IDX = WS / "index.html"
YAH = WS / "yahoo-fantasy/yahoo_players_raw.json"

eng = json.load(open("/tmp/pool_engine.json", encoding="utf-8"))
yah = json.load(open(YAH, encoding="utf-8"))
try:
    gp3 = json.load(open("/tmp/gp_history.json", encoding="utf-8"))
except Exception:
    gp3 = {}


def three_season_gp(pkey):
    """近三赛季平均出场（只统计有出场的赛季）+ 赛季数"""
    if not pkey or not gp3:
        return None, 0
    vals = []
    for ssn in ("2025", "2024", "2023"):
        v = (gp3.get(ssn) or {}).get(pkey)
        if v:
            vals.append(v)
    if not vals:
        return None, 0
    return round(sum(vals) / len(vals), 1), len(vals)


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

rows = []
used = set()

# ── 1. 引擎球员（有投影价值）
for e in eng:
    y = yidx.get(norm(e["n"]), {})
    used.add(norm(e["n"]))
    rows.append({
        "n": e["n"], "t": y.get("team") or e["t"], "p": y.get("positions") or e["p"],
        "a": e["a"], "g": e["g"], "v": e["v"], "r": e["r"],
        "fg": e["fg"], "ft": e["ft"], "pts": e["pts"], "reb": e["reb"], "ast": e["ast"],
        "tpm": e["tpm"], "stl": e["stl"], "blk": e["blk"], "to": e["to"],
        "yr": y.get("rank_overall"), "yp": y.get("rank_pos"), "adp": y.get("adp"),
        "own": y.get("percent_owned"), "inj": y.get("injury_status") or "",
        "ygp": y.get("L_GP"), "ypts": y.get("L_PTS_pg"), "yreb": y.get("L_REB_pg"),
        "yast": y.get("L_AST_pg"), "ytpm": y.get("L_3PM_pg"), "ystl": y.get("L_STL_pg"),
        "yblk": y.get("L_BLK_pg"), "yto": y.get("L_TO_pg"),
        "yfg": y.get("L_FG%"), "yft": y.get("L_FT%"),
        "k": y.get("player_key") or "",
        "g3": three_season_gp(y.get("player_key"))[0], "g3n": three_season_gp(y.get("player_key"))[1],
        "fga": y.get("L_FGA"), "fgm": y.get("L_FGM"), "fta": y.get("L_FTA"), "ftm": y.get("L_FTM"),
    })

# ── 2. Yahoo 独有球员（没有引擎投影，v 留空，9 项用 Yahoo 上赛季场均）
for y in yah:
    key = norm(y.get("name") or "")
    if not key or key in used:
        continue
    # 没上赛季数据的（新秀/整季缺阵）也收进来，统计列留空
    used.add(key)
    rows.append({
        "n": y.get("name"), "t": y.get("editorial_team_abbr") or y.get("team") or "",
        "p": (y.get("positions") or y.get("display_position") or "").strip().rstrip("/"),
        "a": 0, "g": 0, "v": None, "r": (y.get("risk") or "low"),
        "fg": y.get("L_FG%"), "ft": y.get("L_FT%"),
        "pts": y.get("L_PTS_pg"), "reb": y.get("L_REB_pg"), "ast": y.get("L_AST_pg"),
        "tpm": y.get("L_3PM_pg"), "stl": y.get("L_STL_pg"), "blk": y.get("L_BLK_pg"),
        "to": y.get("L_TO_pg"),
        "yr": y.get("rank_overall"), "yp": y.get("rank_pos"), "adp": y.get("adp"),
        "own": y.get("percent_owned"), "inj": y.get("injury_status") or "",
        "ygp": y.get("L_GP"), "ypts": y.get("L_PTS_pg"), "yreb": y.get("L_REB_pg"),
        "yast": y.get("L_AST_pg"), "ytpm": y.get("L_3PM_pg"), "ystl": y.get("L_STL_pg"),
        "yblk": y.get("L_BLK_pg"), "yto": y.get("L_TO_pg"),
        "yfg": y.get("L_FG%"), "yft": y.get("L_FT%"),
        "k": y.get("player_key") or "",
        "g3": three_season_gp(y.get("player_key"))[0], "g3n": three_season_gp(y.get("player_key"))[1],
        "fga": y.get("L_FGA"), "fgm": y.get("L_FGM"), "fta": y.get("L_FTA"), "ftm": y.get("L_FTM"),
    })

# ── 3. 混合分（越小越优先）
by_rank = sorted([r for r in rows if r["yr"]], key=lambda x: x["yr"])
for i, r in enumerate(by_rank):
    r["rq"] = i / max(len(by_rank) - 1, 1)
adps = sorted([r["adp"] for r in rows if r["adp"]])
for r in rows:
    a = r.get("adp")
    r["aq"] = (sum(1 for x in adps if x < a) / max(len(adps) - 1, 1)) if a else None
vals = [r["v"] for r in rows if r["v"] is not None]
vmin, vmax = min(vals), max(vals)
for r in rows:
    r["vq"] = ((vmax - r["v"]) / (vmax - vmin)) if r["v"] is not None else None
for r in rows:
    parts = []
    if r.get("rq") is not None: parts.append((r["rq"], 0.45))
    if r.get("aq") is not None: parts.append((r["aq"], 0.30))
    if r.get("vq") is not None: parts.append((r["vq"], 0.25))
    r["mix"] = round(sum(q * w for q, w in parts) / sum(w for _, w in parts), 4) if parts else 1.5
rows.sort(key=lambda r: r["mix"])

COLS = ["n","t","p","a","g","v","r","fg","ft","pts","reb","ast","tpm","stl","blk","to",
        "yr","yp","adp","own","inj","ygp","ypts","yreb","yast","ytpm","ystl","yblk","yto","yfg","yft","mix","k",
        "g3","g3n","fga","fgm","fta","ftm"]
payload = [[r[c] for c in COLS] for r in rows]
data_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

s = IDX.read_text(encoding="utf-8")
start = s.find("const POOL_COLS = [")
end = s.find("const ALL_CATS =")
assert start > 0 and end > start, "找不到数据块"

new_head = (
    '/* Yahoo 官方排名/ADP × 引擎 9 项估值 合并数据（' + str(len(rows)) + ' 人）\n'
    '   字段：' + ",".join(COLS) + '\n'
    '   mix = 混合分（越小越好）= Yahoo排名45% + ADP30% + 引擎价值25%（缺失项自动重分配权重）*/\n'
    'const POOL_COLS = ' + json.dumps(COLS) + ';\n'
    'const POOL = ' + data_json + '.map(r => { const o = {}; POOL_COLS.forEach((c, i) => o[c] = r[i]); return o; });\n'
    'const POOL_BY_NAME = {};\n'
    'const nameKey = s => String(s || "").normalize("NFKD").replace(/[\\u0300-\\u036f]/g, "")\n'
    '  .toLowerCase().replace(/\\b(jr|sr|ii|iii|iv|v)\\b/g, "").replace(/[^a-z0-9]/g, "");\n'
    'POOL.forEach(p => { POOL_BY_NAME[nameKey(p.n)] = p; if (p.n) POOL_BY_NAME[p.n.toLowerCase()] = p; });\n'
    'const lookupPlayer = name => POOL_BY_NAME[nameKey(name)] || POOL_BY_NAME[String(name || "").toLowerCase()] || null;\n'
    '/* player_key → 球员（选秀实时同步用：Yahoo 只给 key，不给名字） */\n'
    'const POOL_BY_KEY = {};\n'
    'POOL.forEach(p => { if (p.k) POOL_BY_KEY[p.k] = p; });\n'
)
s = s[:start] + new_head + "\n" + s[end:]
IDX.write_text(s, encoding="utf-8")

print(f"✓ 球员池重建完成：{len(rows)} 人（引擎 {len(eng)} + Yahoo 独有 {len(rows)-len(eng)}）")
print(f"  JSON {len(data_json)/1024:.0f} KB")
print(f"  有 Yahoo 排名 {sum(1 for r in rows if r['yr'])} | 有 ADP {sum(1 for r in rows if r['adp'])} | 有引擎价值 {sum(1 for r in rows if r['v'] is not None)}")
print("\nTop 12 混合排序：")
for r in rows[:12]:
    print(f"  {r['n']:<26} Yahoo#{str(r['yr'] or '-'):>4} ADP={str(r['adp'] or '-'):>6} 引擎值={str(r['v'] or '-'):>6} mix={r['mix']}")
