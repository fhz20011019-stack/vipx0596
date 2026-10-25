#!/usr/bin/env python3
"""
Yahoo Fantasy Basketball 全量球员数据抓取（只读公开 API，无需登录）
- 当前赛季排名 / 位置 / 球队 / 持有率 / ADP
- 上赛季（2025）逐项数据：总数 + 场均
输出：CSV + XLSX
"""
import json, re, sys, time, urllib.request, urllib.error, pathlib

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36"
BASE = "https://pub-api-ro.fantasysports.yahoo.com/fantasy/v2/game/nba"
OUT = pathlib.Path("/Users/fanghaoze/Documents/deepseek-harness/default-workspace/yahoo-fantasy")
OUT.mkdir(exist_ok=True)

# Yahoo 官方 stat_id 对照（来自 /game/nba/stat_categories）
STAT_MAP = {
    0: "GP", 1: "GS", 2: "MIN_TOT", 3: "FGA", 4: "FGM", 5: "FG%",
    6: "FTA", 7: "FTM", 8: "FT%", 9: "3PA", 10: "3PM", 11: "3P%",
    12: "PTS", 13: "OREB", 14: "DREB", 15: "REB", 16: "AST", 17: "STL",
    18: "BLK", 19: "TO", 20: "AST/TO", 21: "PF", 22: "FO", 23: "TECH",
    24: "EJ", 25: "FF", 26: "MPG", 27: "DD", 28: "TD",
}
# 保留的列（顺序 = 输出顺序）
KEEP = ["GP","GS","MPG","MIN_TOT","PTS","REB","AST","STL","BLK","TO","PF",
        "FGM","FGA","FG%","FTM","FTA","FT%","3PM","3PA","3P%","OREB","DREB","DD","TD"]
# 需要额外算场均的“累计型”指标
PER_GAME = ["PTS","REB","AST","STL","BLK","TO","PF","FGM","FGA","FTM","FTA","3PM","3PA","OREB","DREB"]


def fetch(url, tries=4):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/xml"})
            with urllib.request.urlopen(req, timeout=40) as r:
                return r.read().decode("utf-8", "replace")
        except Exception as e:
            last = e
            time.sleep(1.2 * (i + 1))
    raise last


def txt(blob, tag):
    m = re.search(rf"<{tag}>([^<]*)</{tag}>", blob)
    return m.group(1).strip() if m else ""


def num(v):
    if v in ("-", "", None):
        return None
    try:
        f = float(v)
        return f
    except ValueError:
        return None


def parse_players(xml):
    out = []
    for blk in re.findall(r"<player>(.*?)</player>", xml, re.S):
        name = txt(blk, "full")
        if not name:
            continue
        rec = {
            "player_key": txt(blk, "player_key"),
            "player_id": txt(blk, "player_id"),
            "name": name,
            "ascii_name": (txt(blk, "ascii_first") + " " + txt(blk, "ascii_last")).strip(),
            "team": txt(blk, "editorial_team_abbr"),
            "team_full": txt(blk, "editorial_team_full_name"),
            "positions": "/".join(re.findall(r"<position>([^<]*)</position>",
                          (re.search(r"<eligible_positions>(.*?)</eligible_positions>", blk, re.S).group(1)
                           if re.search(r"<eligible_positions>(.*?)</eligible_positions>", blk, re.S) else ""))),
            "display_position": txt(blk, "display_position"),
            "uniform_number": txt(blk, "uniform_number"),
            "injury_status": txt(blk, "status") if "<status>" in blk else "",
            "is_undroppable": txt(blk, "is_undroppable"),
        }
        # 持有率
        po = re.search(r"<percent_owned>(.*?)</percent_owned>", blk, re.S)
        rec["percent_owned"] = num(txt(po.group(1), "value")) if po else None
        rec["percent_owned_delta"] = num(txt(po.group(1), "delta")) if po else None
        # 排名
        rk = {}
        for rt, rv, rs in re.findall(r"<rank_type>([^<]*)</rank_type>\s*<rank_value>([^<]*)</rank_value>(?:\s*<rank_season>([^<]*)</rank_season>)?", blk):
            rk[f"rank_{rt}" + (f"_{rs}" if rs else "")] = num(rv)
        rec["rank_overall"] = rk.get("rank_OR")
        rec["rank_pos"] = rk.get("rank_P")
        rec["rank_2026"] = rk.get("rank_S_2026")
        rec["rank_2025"] = rk.get("rank_S_2025")
        rec["rank_2024"] = rk.get("rank_S_2024")
        # 选秀分析
        da = re.search(r"<draft_analysis>(.*?)</draft_analysis>", blk, re.S)
        if da:
            rec["adp"] = num(txt(da.group(1), "average_pick"))
            rec["adp_round"] = num(txt(da.group(1), "average_round"))
            rec["avg_cost"] = num(txt(da.group(1), "average_cost"))
            rec["percent_drafted"] = num(txt(da.group(1), "percent_drafted"))
            rec["preseason_adp"] = num(txt(da.group(1), "preseason_average_pick"))
        # 上赛季逐项
        st = re.search(r"<player_stats>(.*?)</player_stats>", blk, re.S)
        if st:
            stat_blob = st.group(1)
            rec["stats_season"] = txt(stat_blob, "season")
            pairs = re.findall(r"<stat_id>(\d+)</stat_id>\s*<value>([^<]*)</value>", stat_blob)
            got = {}
            for sid, val in pairs:
                col = STAT_MAP.get(int(sid))
                if col and col not in got:
                    got[col] = num(val)
            gp = got.get("GP")
            mpg = got.get("MPG")
            if not mpg and got.get("MIN_TOT") and gp:
                mpg = round(got["MIN_TOT"] / gp, 1)   # API 常不回传 26，自己算
            got["MPG"] = mpg
            for col in KEEP:
                v = got.get(col)
                rec[f"L_{col}"] = v
                if col in PER_GAME and v is not None and gp:
                    rec[f"L_{col}_pg"] = round(v / gp, 2)
        out.append(rec)
    return out


def main():
    all_rows, start, empty = [], 0, 0
    while True:
        url = f"{BASE}/players;count=25;start={start};sort=AR;out=percent_owned,ranks,draft_analysis/stats;type=season;season=2025"
        try:
            xml = fetch(url)
        except Exception as e:
            print(f"  [{start}] 请求失败: {e}", flush=True)
            empty += 1
            if empty > 4:
                break
            start += 25
            continue
        # 错误响应
        if "<error" in xml or "does not exist" in xml:
            print(f"  [{start}] API 报错，停止", flush=True)
            break
        rows = parse_players(xml)
        if not rows:
            print(f"  [{start}] 空页，停止", flush=True)
            break
        all_rows.extend(rows)
        print(f"  [{start:>4}-{start+len(rows)-1:>4}] 累计 {len(all_rows)} 人 | 末尾: {rows[-1]['name']}", flush=True)
        start += 25
        if start > 1200:
            break
        time.sleep(0.25)

    # 去重
    seen, uniq = set(), []
    for r in all_rows:
        k = r["player_id"] or r["name"]
        if k in seen:
            continue
        seen.add(k)
        uniq.append(r)

    json_path = OUT / "yahoo_players_raw.json"
    json_path.write_text(json.dumps(uniq, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n抓取完成：{len(uniq)} 名球员（去重后）→ {json_path}")

    # 摘要
    with_stats = [r for r in uniq if r.get("L_GP")]
    print(f"其中上赛季有出场记录：{len(with_stats)} 人")
    top = sorted([r for r in uniq if r.get("rank_overall")], key=lambda x: x["rank_overall"])[:15]
    print("\n当前排名 Top 15：")
    for r in top:
        print(f"  {int(r['rank_overall']):>3}. {r['name']:<26}{r.get('display_position',''):<8}{r.get('team',''):<5}"
              f"ADP={r.get('adp') or '-':<5} 持有={r.get('percent_owned') or '-':<5}"
              f" 上季 {r.get('L_GP') or '-'}场 {r.get('L_PTS_pg') or '-'}分 {r.get('L_REB_pg') or '-'}板 {r.get('L_AST_pg') or '-'}助")


if __name__ == "__main__":
    main()
