#!/usr/bin/env python3
"""把 Yahoo 原始 JSON 整理成全量球员表（CSV + XLSX，多表）"""
import json, pathlib
import pandas as pd

W = pathlib.Path("/Users/fanghaoze/Documents/deepseek-harness/default-workspace/yahoo-fantasy")
raw = json.load(open(W / "yahoo_players_raw.json", encoding="utf-8"))

def g(r, k):
    v = r.get(k)
    return None if v in ("", None) else v

rows = []
for r in raw:
    rows.append({
        "当前排名": g(r, "rank_overall"),
        "位置": (g(r, "positions") or g(r, "display_position") or ""),
        "球员": g(r, "name"),
        "球队": g(r, "team"),
        "伤病状态": g(r, "injury_status") or "",
        "年龄": None,
        "持有率%": g(r, "percent_owned"),
        "持有率变化": g(r, "percent_owned_delta"),
        "ADP": g(r, "adp"),
        "ADP轮次": g(r, "adp_round"),
        "平均身价$": g(r, "avg_cost"),
        "被选中率": g(r, "percent_drafted"),
        "季前ADP": g(r, "preseason_adp"),
        "上季排名": g(r, "rank_2025"),
        "上季_出场": g(r, "L_GP"),
        "上季_首发": g(r, "L_GS"),
        "上季_场均分钟": g(r, "L_MPG"),
        "上季_得分": g(r, "L_PTS_pg"),
        "上季_篮板": g(r, "L_REB_pg"),
        "上季_助攻": g(r, "L_AST_pg"),
        "上季_三分": g(r, "L_3PM_pg"),
        "上季_抢断": g(r, "L_STL_pg"),
        "上季_盖帽": g(r, "L_BLK_pg"),
        "上季_失误": g(r, "L_TO_pg"),
        "上季_犯规": g(r, "L_PF_pg"),
        "上季_FG%": g(r, "L_FG%"),
        "上季_FT%": g(r, "L_FT%"),
        "上季_3P%": g(r, "L_3P%"),
        "上季_投篮命中": g(r, "L_FGM_pg"),
        "上季_投篮出手": g(r, "L_FGA_pg"),
        "上季_罚球命中": g(r, "L_FTM_pg"),
        "上季_罚球出手": g(r, "L_FTA_pg"),
        "上季_三分出手": g(r, "L_3PA_pg"),
        "上季_前场板": g(r, "L_OREB_pg"),
        "上季_后场板": g(r, "L_DREB_pg"),
        "上季_两双": g(r, "L_DD"),
        "上季_三双": g(r, "L_TD"),
        "上季_总得分": g(r, "L_PTS"),
        "上季_总篮板": g(r, "L_REB"),
        "上季_总助攻": g(r, "L_AST"),
        "player_key": g(r, "player_key"),
    })

df = pd.DataFrame(rows)
df = df.sort_values("当前排名", na_position="last").reset_index(drop=True)

# 9 项核心（你联盟的计分项）
nine = df[["当前排名", "球员", "位置", "球队", "上季_出场",
           "上季_FG%", "上季_FT%", "上季_三分", "上季_得分",
           "上季_篮板", "上季_助攻", "上季_抢断", "上季_盖帽", "上季_失误"]].copy()

# 有上季实绩的人，按 9 项产出粗排（便于快速找人）
scored = df[df["上季_出场"].notna()].copy()
scored["产出评分"] = (
    scored["上季_得分"].fillna(0) + scored["上季_篮板"].fillna(0) * 1.2
    + scored["上季_助攻"].fillna(0) * 1.5 + scored["上季_三分"].fillna(0) * 2
    + scored["上季_抢断"].fillna(0) * 2 + scored["上季_盖帽"].fillna(0) * 2
    - scored["上季_失误"].fillna(0) * 1.5
)
scored = scored.sort_values("产出评分", ascending=False)
nine_scored = scored[["产出评分", "球员", "位置", "球队", "上季_出场", "上季_场均分钟",
                      "上季_得分", "上季_篮板", "上季_助攻", "上季_三分",
                      "上季_抢断", "上季_盖帽", "上季_失误", "上季_FG%", "上季_FT%"]]

top200 = df.head(200)
undrafted = df[df["ADP"].isna() & df["持有率%"].notna()].sort_values("持有率%", ascending=False)

# ---------- 写出 ----------
csv_path = W / "yahoo_players_2026_27.csv"
df.to_csv(csv_path, index=False, encoding="utf-8-sig")

xlsx_path = W / "yahoo_players_2026_27.xlsx"
with pd.ExcelWriter(xlsx_path, engine="xlsxwriter") as xw:
    df.to_excel(xw, sheet_name="全量球员", index=False)
    nine.to_excel(xw, sheet_name="9项核心", index=False)
    nine_scored.to_excel(xw, sheet_name="按9项产出排序", index=False)
    top200.to_excel(xw, sheet_name="Top200", index=False)
    undrafted.head(150).to_excel(xw, sheet_name="无ADP高持有", index=False)

    wb = xw.book
    head = wb.add_format({"bold": True, "bg_color": "#1F3864", "font_color": "white",
                          "border": 1, "align": "center", "valign": "vcenter", "text_wrap": True})
    num = wb.add_format({"num_format": "0.00", "border": 1})
    pct = wb.add_format({"num_format": "0.0%", "border": 1})
    txt = wb.add_format({"border": 1})
    for name, frame in [("全量球员", df), ("9项核心", nine), ("按9项产出排序", nine_scored),
                        ("Top200", top200), ("无ADP高持有", undrafted.head(150))]:
        ws = xw.sheets[name]
        ws.freeze_panes(1, 2)
        for i, col in enumerate(frame.columns):
            ws.write(0, i, col, head)
            width = max(9, min(22, int(max([len(str(col)) * 2] + [len(str(v)) for v in frame[col].head(80) if v is not None] or [8])) + 2))
            fmt = pct if "%" in str(col) else (num if "上季" in str(col) or col in ("ADP", "持有率%", "产出评分", "平均身价$") else txt)
            ws.set_column(i, i, width, fmt)
        ws.autofilter(0, 0, len(frame), len(frame.columns) - 1)

print(f"✓ CSV : {csv_path}  ({len(df)} 行)")
print(f"✓ XLSX: {xlsx_path}  (5 个工作表)")
print(f"\n全量 {len(df)} 人 | 有上季数据 {df['上季_出场'].notna().sum()} 人 | 有 ADP {df['ADP'].notna().sum()} 人")
print("\n当前排名 Top 20：")
show = df.head(20)[["当前排名","球员","位置","球队","ADP","持有率%","上季_出场","上季_得分","上季_篮板","上季_助攻","上季_三分","上季_盖帽"]]
print(show.to_string(index=False))
