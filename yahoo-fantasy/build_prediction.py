#!/usr/bin/env python3
"""
2026-27 预测层 v2 —— 在 v1（5 因素）上叠加 9 项改进：

  ① FG%/FT% 贝叶斯回归        （用 FGA/FTA 向联盟均值收缩，修正单季波动）
  ② 薪水 → 出场时间下限        （沉没成本效应：高薪保证出场）
  ③ 同队同位置竞争强度         （同队同位置有产出的人越多，出场越被摊薄）
  ④ 球权传导                  （同队走了大量得分 → 留下的队友受益）
  ⑤ 波动性 / 预测区间          （用近三季标准差给 lo-hi 区间）
  ⑥ FantasyPros 专业预测融合    （265 人；场均 50/50，出场取保守）
  ⑦ 季前赛表现                （无可访问数据源，见报告说明）
  ⑧ 轮换角色（首发/轮换/替补）  （由 FantasyPros 预测 MPG 反推，替代抓不到的深度图）
  ⑨ 常规赛赛程强度             （第 1-19 周各队场次 —— 本联赛只打常规赛，没有季后赛）
  ⑩ 成长预期（年轻球员）        （年龄 ≤23 的上浮，明确标注为高不确定性）

输出 yahoo-fantasy/pred_2026_27.json
"""
import csv, json, re, unicodedata, pathlib, statistics as st, collections

WS = pathlib.Path("/Users/fanghaoze/Documents/deepseek-harness/default-workspace")
RES = WS / "nba-draft-agent/data/research"
ENG = WS / "nba-draft-agent/data/players_2026_27.csv"
YAH = WS / "yahoo-fantasy/yahoo_players_raw.json"
FPJ = WS / "yahoo-fantasy/fantasypros_2026_27.json"
HIST = WS / "yahoo-fantasy/hist_2024_2023.json"
SCH = pathlib.Path("/tmp/nba_data/games_per_week.json")


def norm(s):
    s = unicodedata.normalize("NFKD", str(s or ""))
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"\b(jr|sr|ii|iii|iv|v)\b", "", s.lower())
    return re.sub(r"[^a-z0-9]", "", s)


def strip_paren(s):
    return re.sub(r"\s*[（(][^）)]*[）)]\s*$", "", str(s or "")).strip()


def fnum(v):
    try:
        x = float(v)
        return x if x == x else None
    except Exception:
        return None


CATS = ["pts", "reb", "ast", "tpm", "stl", "blk", "to"]

# ══════════════════════════════════════════════════════════════════════════
yah = json.load(open(YAH, encoding="utf-8"))
fp = json.load(open(FPJ, encoding="utf-8")) if FPJ.exists() else {}
hist = json.load(open(HIST, encoding="utf-8")) if HIST.exists() else {}

# ── 多赛季基准：按出场数加权（解决「上季只打 15 场 → 被收缩成替补」的问题）──
HIST_MAP = {"PTS": "pts", "REB": "reb", "AST": "ast", "3PM": "tpm", "STL": "stl",
            "BLK": "blk", "TO": "to", "FGM": "fgm", "FGA": "fga", "FTM": "ftm", "FTA": "fta"}


def multi_season_base(r):
    """把 上季 + 2024 + 2023 按出场数加权平均（样本越多权重越大）"""
    pk = r.get("pkey")
    last = r.get("last") or {}
    samples = []
    if last.get("gp") and last.get("pts") is not None:
        samples.append((last, last["gp"]))
    h = hist.get(pk) if pk else None
    if h:
        for ssn in ("2024", "2023"):
            d = h.get(ssn)
            if d and (d.get("GP") or 0) >= 15:
                g = d["GP"]
                # ⚠️ 关键：历史数据是「场均」，必须 × 出场数才能和「上季总数」相加
                conv = {"pts": d.get("PTS"), "reb": d.get("REB"), "ast": d.get("AST"),
                        "tpm": d.get("3PM"), "stl": d.get("STL"), "blk": d.get("BLK"),
                        "to": d.get("TO"), "fgm": (d.get("FGM") or 0) * g, "fga": (d.get("FGA") or 0) * g,
                        "ftm": (d.get("FTM") or 0) * g, "fta": (d.get("FTA") or 0) * g}
                samples.append((conv, g))
    if not samples:
        return None
    tot = sum(g for _, g in samples)
    if tot <= 0:
        return None
    out = {}
    for c in list(CATS) + ["fgm", "fga", "ftm", "fta"]:
        vals = [(s.get(c), g) for s, g in samples if s.get(c) is not None]
        if not vals:
            out[c] = None
            continue
        # 命中/出手是「赛季总数」→ 直接求和；场均项 → 除以总出场
        if c in ("fgm", "fga", "ftm", "fta"):
            out[c] = sum(v for v, _ in vals)
        else:
            w = sum(g for _, g in vals)
            out[c] = sum(v * g for v, g in vals) / w
    out["_samples"] = len(samples)
    out["_total_gp"] = tot
    # 命中率由命中/出手重算（更准）
    if out.get("fga"):
        out["fg"] = out["fgm"] / out["fga"] if out.get("fgm") is not None else None
    if out.get("fta"):
        out["ft"] = out["ftm"] / out["fta"] if out.get("ftm") is not None else None
    # 输出场均形式（后续 ① 贝叶斯回归要用到 fgm/fga 的总数概念，所以保留总数）
    return out
gpw = json.load(open(SCH, encoding="utf-8")) if SCH.exists() else {}

R = collections.OrderedDict()


def rec(key, name=None):
    if key not in R:
        R[key] = {"n": name or key, "factors": [], "conf": "", "src": []}
    if name and (not R[key]["n"] or R[key]["n"] == key):
        R[key]["n"] = name
    return R[key]


# ── 基础：Yahoo 上赛季 ──
for y in yah:
    nm = y.get("name")
    if not nm:
        continue
    r = rec(norm(nm), nm)
    r["last"] = {
        "pts": y.get("L_PTS_pg"), "reb": y.get("L_REB_pg"), "ast": y.get("L_AST_pg"),
        "tpm": y.get("L_3PM_pg"), "stl": y.get("L_STL_pg"), "blk": y.get("L_BLK_pg"),
        "to": y.get("L_TO_pg"), "fg": y.get("L_FG%"), "ft": y.get("L_FT%"),
        "gp": y.get("L_GP"), "mpg": y.get("L_MPG"),
        "fgm": y.get("L_FGM"), "fga": y.get("L_FGA"),
        "ftm": y.get("L_FTM"), "fta": y.get("L_FTA"),
    }
    r["team"] = y.get("editorial_team_abbr") or y.get("team")
    r["pos"] = (y.get("positions") or y.get("display_position") or "").strip().rstrip("/")
    r["pkey"] = y.get("player_key")

# ── 贝叶斯回归的「先验」：按位置分组算，而不是全联盟一个数 ──
# （中锋/大前的 FG% 天然更高，用联盟均值做先验会把顶级内线拉低）
def _pos_group(pos):
    ps = set((pos or "").upper().split("/"))
    if ps & {"C"}:            return "C"
    if ps & {"PF"}:           return "PF"
    if ps & {"SF"}:           return "SF"
    return "G"


_PRIOR = collections.defaultdict(lambda: {"fgm": 0.0, "fga": 0.0, "ftm": 0.0, "fta": 0.0})
for y in yah:
    g = _pos_group(y.get("positions") or y.get("display_position"))
    p = _PRIOR[g]
    p["fgm"] += y.get("L_FGM") or 0; p["fga"] += y.get("L_FGA") or 0
    p["ftm"] += y.get("L_FTM") or 0; p["fta"] += y.get("L_FTA") or 0
PRIOR_FG = {g: (_PRIOR[g]["fgm"] / _PRIOR[g]["fga"] if _PRIOR[g]["fga"] else 0.47) for g in _PRIOR}
PRIOR_FT = {g: (_PRIOR[g]["ftm"] / _PRIOR[g]["fta"] if _PRIOR[g]["fta"] else 0.78) for g in _PRIOR}
LG_FG = sum(PRIOR_FG.values()) / max(1, len(PRIOR_FG))
LG_FT = sum(PRIOR_FT.values()) / max(1, len(PRIOR_FT))
print("  位置先验 FG%:", {k: round(v, 3) for k, v in PRIOR_FG.items()})
print("  位置先验 FT%:", {k: round(v, 3) for k, v in PRIOR_FT.items()})

# ── 引擎投影 ──
with open(ENG, encoding="utf-8-sig", errors="replace") as fh:
    for row in csv.DictReader(fh):
        r = rec(norm(row["player"]), row["player"])
        r["engine"] = {
            "pts": fnum(row["pts"]), "reb": fnum(row["reb"]), "ast": fnum(row["ast"]),
            "tpm": fnum(row["tpm"]), "stl": fnum(row["stl"]), "blk": fnum(row["blk"]),
            "to": fnum(row["to"]), "fg": fnum(row["fg_pct"]), "ft": fnum(row["ft_pct"]),
            "gp": fnum(row["gp_proj"]), "mpg": fnum(row["mpg"]),
        }
        r["age"] = fnum(row.get("age"))
        # ⚠️ 引擎有 28 行是 base_type='none'（引擎拒绝估值，九项全空）。
        #    这类行不能拿来当基准，否则预测会是空的 —— 要回退到上季实际数据。
        if any(r["engine"].get(c) is not None for c in CATS):
            r["src"].append("engine")
            r["conf"] = "high"
            r["eng_ok"] = True
        else:
            r["eng_ok"] = False

# ── 新秀预测 ──
with open(RES / "rookies_2026.csv", encoding="utf-8", errors="replace") as fh:
    for row in csv.DictReader(fh):
        r = rec(norm(row["player"]), row["player"])
        r["rookie"] = {
            "pts": fnum(row["expected_pts"]), "reb": fnum(row["expected_reb"]), "ast": fnum(row["expected_ast"]),
            "tpm": fnum(row["expected_3pm"]), "stl": fnum(row["expected_stl"]), "blk": fnum(row["expected_blk"]),
            "to": fnum(row["expected_to"]), "fg": fnum(row["expected_fg"]), "ft": fnum(row["expected_ft"]),
            "gp": 62.0, "mpg": fnum(row.get("expected_mpg")),
        }
        r["age"] = r.get("age") or fnum(row.get("age"))
        r["factors"].append("新秀")
        r["src"].append("rookie")
        r["conf"] = "low"
        if row.get("role(先发/第六人/替补)"):
            r["rookie_role"] = row["role(先发/第六人/替补)"]
        r["rookie_note"] = (row.get("notes") or "")[:130]

# ── 薪水（②）──
with open(RES / "ages_contracts_2026_27.csv", encoding="utf-8", errors="replace") as fh:
    for row in csv.DictReader(fh):
        r = rec(norm(row["player"]), row["player"])
        if r.get("age") is None:
            r["age"] = fnum(row.get("age"))
        s = fnum(row.get("annual_salary_millions"))
        if s:
            r["salary"] = s

# ── 角色变化 / 交易（④）──
with open(RES / "role_changes_2026.csv", encoding="utf-8", errors="replace") as fh:
    for row in csv.DictReader(fh):
        r = rec(norm(row["player"]), row["player"])
        d = (row.get("direction") or "").strip()
        imp = (row.get("role_impact") or "").strip()
        r["role_dir"] = d
        r["role_note"] = imp[:150]
        r["team_2026_27"] = row.get("team_2026_27") or r.get("team")
        if d == "up":
            r["factors"].append("角色↑")
        elif d == "down":
            r["factors"].append("角色↓")
        elif d == "new_team":
            r["factors"].append("换队")
        if row.get("change_type") == "trade":
            r["factors"].append("交易")
        if re.search(r"(coach|system|Spoelstra|Jenkins|pace|usage|rotation|minutes)", imp, re.I):
            m = re.search(r"([A-Z][a-zA-Z]+(?:'s)? (?:system|offense|rotation|pace)[^.]*)", imp)
            r["coach"] = (m.group(1)[:90] if m else imp[:90])

# ── 伤病分类（⑤）──
UNVER_RE = re.compile(r"待核实|NEEDS VERIFICATION|no explicit|not verified|unconfirmed", re.I)
NOT_INJ_RE = re.compile(r"not listed|on 'more|radar' list|coach praised|deep rotation|no injury", re.I)
HEALTHY_RE = re.compile(r"100% healthy|no restrictions|full go|full clearance|fully cleared|"
                        r"cleared for|no limitations|returned in (jan|feb|mar|apr|may|dec)|"
                        r"making good progress|ready to pick up|ramping up|5-on-5 full-contact", re.I)
PRESEASON_RE = re.compile(r"miss the (entire )?preseason|out for [^.]{0,20}preseason|"
                          r"held out of [^.]{0,20}preseason|preseason (availability|game|opener)|"
                          r"missed start of training camp", re.I)
HIST_RE = re.compile(r"\bage[- ]?\d|durability|missed \d+ games|injury history|has topped 70|"
                     r"missed two-thirds|missed 19 months|108 games|recurring issue|"
                     r"age and games|rest days are the risk|preservation", re.I)
OUT_SEASON_RE = re.compile(r"miss the entire (20\d\d|20\d\d-\d\d|season)|season-ending|"
                           r"out for the (entire )?season|miss(es)? the whole season", re.I)
SEVERE_RE = re.compile(r"entire (20\d\d|season)|out indefinitely|extended absence|"
                       r"~?\d+ months|torn acl|ruptured|torn achilles", re.I)
MODERATE_RE = re.compile(r"will not be ready for (the )?start|not be ready for the start|"
                         r"ret (jan|feb|dec|mar)|return (jan|feb|dec|mar)|rehabilitat|"
                         r"miss(es)? the (entire )?start|19 months|out until|not yet cleared|"
                         r"will miss the .{0,12}start", re.I)
MINOR_RE = re.compile(r"tweaked|preseason|re-evaluated|held out|strain|soreness|hamstring|"
                      r"ankle|foot|back|calf|knee|illness|undisclosed|good progress", re.I)


def classify_injury(detail):
    d = detail or ""
    if UNVER_RE.search(d):          return None
    if NOT_INJ_RE.search(d):        return None
    if HEALTHY_RE.search(d):        return "healthy"
    if HIST_RE.search(d):           return "history"
    if PRESEASON_RE.search(d):      return "minor"
    if OUT_SEASON_RE.search(d):     return "out_season"
    if SEVERE_RE.search(d):         return "severe"
    if MODERATE_RE.search(d):       return "moderate"
    if MINOR_RE.search(d):          return "minor"
    return "moderate"


INJ_GP = {"out_season": 0.06, "severe": 0.45, "moderate": 0.72, "minor": 0.93}

with open(RES / "risk_flags.csv", encoding="utf-8", errors="replace") as fh:
    for row in csv.DictReader(fh):
        nm = strip_paren(row["player_or_team"])
        nm = re.sub(r"\s*\(.*?\)\s*", "", nm).strip().split("/")[0].strip()
        r = rec(norm(nm), nm)
        t, det = row.get("type"), (row.get("detail") or "").strip()
        if t == "injury":
            kind = classify_injury(det)
            if kind == "healthy":
                r["factors"].append("已康复"); r["hist_note"] = det[:120]
            elif kind == "history":
                r["factors"].append("耐久性"); r["hist_note"] = det[:120]
            elif kind:
                r["factors"].append("伤病"); r["inj_kind"] = kind; r["inj_note"] = det[:120]
        elif t == "contract":
            r["factors"].append("合同年"); r["contract_note"] = det[:120]
        elif t == "tanking":
            r["factors"].append("摆烂队")
        elif t == "trade_rumor":
            r["factors"].append("交易流言")
        elif t == "sleeper":
            r["factors"].append("潜力股")
        elif t == "fade":
            r["factors"].append("看衰")

# ── 近三季出场（⑤ 波动性）──
try:
    gp3 = json.load(open("/tmp/gp_history.json", encoding="utf-8"))
except Exception:
    gp3 = {}
for k, r in R.items():
    pk = r.get("pkey")
    if not pk:
        continue
    vals = [v for v in ((gp3.get(s) or {}).get(pk) for s in ("2025", "2024", "2023")) if v]
    if vals:
        r["gp3_avg"] = round(sum(vals) / len(vals), 1)
        r["gp3_sd"] = round(st.pstdev(vals), 1) if len(vals) > 1 else 0.0

# ── ③ 同队同位置竞争：按「在队内该位置的产出排名」判断，而不是单纯数人数 ──
# （人数多但你是队里最好的，不该罚；只有排到第 3 名开外才真的被挤）
byteam = collections.defaultdict(list)
for k, r in R.items():
    t, last = r.get("team"), r.get("last") or {}
    if t and (last.get("pts") or 0) > 4:
        byteam[t].append(r)
for t, lst in byteam.items():
    for r in lst:
        pos_set = set((r.get("pos") or "").split("/"))
        rivals = [x for x in lst if x is not r and pos_set & set((x.get("pos") or "").split("/"))]
        # 按上季得分排序，看自己排第几
        group = sorted([r] + rivals, key=lambda x: -((x.get("last") or {}).get("pts") or 0))
        rank = group.index(r) + 1
        r["pos_rank"] = rank
        r["pos_rivals"] = len(rivals)

# ── ④ 球队流失的得分总量 ──
team_departed = collections.Counter()
for k, r in R.items():
    if r.get("team_2026_27") and r.get("team") and r["team_2026_27"] != r["team"]:
        team_departed[r["team"]] += (r.get("last") or {}).get("pts") or 0

# ══════════════════════════════════════════════════════════════════════════
def rnd(v, nd=1):
    return round(v, nd) if isinstance(v, (int, float)) else None


def as_pct(v):
    """统一成百分数：0.569 → 56.9；56.9 → 56.9（缺数据则 None）"""
    if not isinstance(v, (int, float)):
        return None
    return round(v * 100, 1) if v < 1.5 else round(v, 1)


def age_factor(age):
    if age is None: return 1.0
    if age <= 21: return 1.06
    if age <= 23: return 1.04
    if age <= 25: return 1.02
    if age <= 28: return 1.00
    if age <= 30: return 0.98
    if age <= 32: return 0.96
    if age <= 34: return 0.93
    if age <= 36: return 0.90
    return 0.86


ROLE_F = {"up": 1.10, "down": 0.90, "new_team": 0.97}
out = {}

for k, r in R.items():
    last = r.get("last") or {}
    eng = r.get("engine")
    rook = r.get("rookie")

    msb = None
    # 上季样本太小、或引擎拒绝估值但有历史 → 用多赛季加权基准
    if not rook and ((last.get("gp") or 0) < 30 or (not r.get("eng_ok") and not last.get("gp"))):
        msb = multi_season_base(r)

    if rook:
        base = dict(rook); base_src = "rookie"
    elif msb and msb.get("_samples", 0) >= 2:
        # 有跨赛季数据：用加权基准覆盖引擎的收缩投影
        base = {c: msb.get(c) for c in CATS}
        base["fg"], base["ft"] = msb.get("fg"), msb.get("ft")
        base["gp"], base["mpg"] = None, (eng or {}).get("mpg") or last.get("mpg")
        base_src = "multi-season"
        r["factors"].append("多季基准")
        r["msb_gp"] = msb.get("_total_gp")
    elif eng and r.get("eng_ok"):
        base = dict(eng); base_src = "engine"
    elif last.get("pts") is not None:
        kk = age_factor(r.get("age")) * ROLE_F.get(r.get("role_dir"), 1.0)
        base = {c: (last.get(c) or 0) * kk for c in CATS}
        base["fg"], base["ft"] = last.get("fg"), last.get("ft")
        base["gp"], base["mpg"] = last.get("gp"), last.get("mpg")
        base_src = "derived"
    else:
        continue

    # ══ ⑥ FantasyPros 融合 ══
    f = fp.get(k)
    if f:
        for c in CATS:
            a, b = base.get(c), f.get(c)
            if a is not None and b is not None:
                base[c] = (a + b) / 2
            elif b is not None:
                base[c] = b
        # 命中率：统一成百分数再平均
        for key in ("fg", "ft"):
            a, b = base.get(key), f.get(key)
            if a is not None and b is not None:
                a2 = a * 100 if a < 1.5 else a
                base[key] = (a2 + b) / 2
            elif b is not None:
                base[key] = b
        if f.get("mpg"):
            base["mpg"] = f["mpg"]
        r["src"].append("fantasypros")
        if r.get("conf") != "high":
            r["conf"] = "medium"
        if f.get("pts") and r.get("eng_ok") and (eng or {}).get("pts") and abs(f["pts"] - eng["pts"]) / max(eng["pts"], 1) > 0.15:
            r["factors"].append("源分歧")

    mpg = base.get("mpg")

    # ══ ① FG%/FT% 贝叶斯回归 ══
    if not rook:
        # 用「多赛季累计」的命中/出手数（如果有），而不是只盯上季的小样本
        if msb and msb.get("fga"):
            fgm, fga = msb.get("fgm"), msb.get("fga")
            ftm, fta = msb.get("ftm"), msb.get("fta")
        else:
            fgm, fga = last.get("fgm"), last.get("fga")
            ftm, fta = last.get("ftm"), last.get("fta")
        g = _pos_group(r.get("pos"))
        if fga and fgm is not None:
            base["fg"] = round((fgm + 90.0 * PRIOR_FG.get(g, LG_FG)) / (fga + 90.0) * 100, 1)
        if fta and ftm is not None:
            base["ft"] = round((ftm + 70.0 * PRIOR_FT.get(g, LG_FT)) / (fta + 70.0) * 100, 1)
        r["sample_fga"] = int(fga) if fga else 0
    else:
        # 新秀：CSV 缺 FG%/FT% 时用「同位置先验」兜底（而不是留 0）
        g = _pos_group(r.get("pos"))
        rfg, rft = rook.get("fg"), rook.get("ft")
        base["fg"] = rfg * 100 if rfg else PRIOR_FG.get(g, LG_FG) * 100
        base["ft"] = rft * 100 if rft else PRIOR_FT.get(g, LG_FT) * 100

    # ══ ⑥b 出场融合（保守）══
    gp_mine = r.get("gp3_avg") or base.get("gp")
    if eng and r.get("eng_ok") and eng.get("gp"):
        gp_mine = (gp_mine + eng["gp"]) / 2 if gp_mine else eng["gp"]
    gp_fp = f.get("gp") if f else None
    if gp_fp and gp_mine:
        gp = min(gp_fp, gp_mine) if r.get("inj_kind") in INJ_GP else (gp_fp + gp_mine) / 2
    else:
        gp = gp_mine or gp_fp
    if gp and r.get("inj_kind") in INJ_GP:
        gp *= INJ_GP[r["inj_kind"]]

    # ══ ② 薪水 → 出场时间下限 ══
    sal = r.get("salary")
    if sal and mpg:
        floor = 28 if sal >= 25 else (24 if sal >= 15 else (20 if sal >= 8 else 0))
        if floor and mpg < floor:
            r["factors"].append("薪水保出场")
            mpg = floor

    # ══ ③ 位置拥挤：只在「没有外部 MPG 数据」时做 ══
    # 原因：FantasyPros / 引擎的预测 MPG 已经反映了深度图竞争，
    #       再有 MPG 的情况下扣产量就是重复惩罚（曾导致 Giannis 从 28.6 掉到 23.6）
    has_ext_mpg = bool((f or {}).get("mpg")) or bool((eng or {}).get("mpg"))
    prank = r.get("pos_rank", 1)
    if prank >= 3 and base.get("pts") and not has_ext_mpg:
        cut = 1 - min(0.10, (prank - 2) * 0.03)
        for c in CATS:
            if base.get(c) is not None:
                base[c] *= cut
        if mpg:
            mpg *= cut
        r["factors"].append("位置拥挤")

    # ══ ④ 球权释放 ══
    t0 = r.get("team")
    if r.get("role_dir") != "up" and t0 and team_departed.get(t0, 0) >= 35:
        boost = 1 + min(0.07, team_departed[t0] / 1200.0)
        for c in ("pts", "ast", "tpm"):
            if base.get(c) is not None:
                base[c] *= boost
        r["factors"].append("球权释放")

    # ══ ⑩ 成长预期（年轻球员）══
    # 为什么加：市场（Yahoo/ADP）对 22-23 岁的球员普遍给成长溢价，
    #   而纯产出模型只反映"已经打出来的水平"，导致系统性低估
    #   （Maluach / Kuminga / Day'Ron Sharpe 这类差 100-200 位）
    # 代价：这是【赌注】不是事实 → 打「成长预期」标签 + 可信度降为 low
    age = r.get("age")
    if age is not None and age <= 23 and base.get("pts"):
        g = min(1.12, 1 + (24 - age) * 0.025)          # 20岁×1.10 21岁×1.075 22岁×1.05 23岁×1.025
        why = []
        if r.get("role_dir") == "up":
            g = min(1.15, g * 1.03); why.append("角色↑")
        if "摆烂队" in r["factors"]:
            g = min(1.15, g * 1.03); why.append("重建队球权")
        if g > 1.001:
            for c in CATS:
                if base.get(c) is not None:
                    base[c] *= g
            r["factors"].append("成长预期")
            r["growth"] = round((g - 1) * 100, 1)
            r["growth_why"] = "+".join(why)
            # 成长加成只是一个【组件】有不确定性，不改变基础投影的可信度
            # 所以 high → medium（降一档），本来就 medium/low 的保持不变
            if r.get("conf") == "high":
                r["conf"] = "medium"

    # ══ ⑤ 区间 ══
    sd = r.get("gp3_sd", 0) or 0
    gpv = gp or 60
    gp_lo = max(0, round(gpv - sd * 1.2, 1))
    gp_hi = min(82, round(gpv + sd * 0.6, 1))

    # ══ ⑧ 轮换角色 ══
    role = ""
    if mpg:
        role = "首发" if mpg >= 28 else ("主力轮换" if mpg >= 22 else ("替补" if mpg >= 14 else "边缘"))
    elif r.get("rookie_role"):
        role = r["rookie_role"]

    # ══ ⑨ 常规赛窗口场次（第 1-19 周；本联赛只打常规赛）══
    ab = (r.get("team_2026_27") or t0 or "").upper()
    po = None
    for key in (ab, ab.replace("SA", "SAS"), ab.replace("NO", "NOP"), ab.replace("UTAH", "UTA"),
                ab.replace("GS", "GSW"), ab.replace("NY", "NYK"), ab.replace("PHO", "PHX")):
        if key and key in gpw:
            c = gpw[key]
            po = sum(int(c.get(str(w), 0)) for w in range(1, 20))   # 第 1-19 周
            break
    # 全联盟 57-60 场，差异很小，所以只作为参考信息展示，不做成因素标签

    # 九项全空的球员（完全没数据的新秀）不显示出场数，避免「有场次没数据」的误导
    has_stats = any(base.get(c) is not None for c in CATS)
    if not has_stats:
        gp = None

    note = (r.get("inj_note") or r.get("contract_note") or r.get("hist_note") or
            r.get("role_note") or r.get("rookie_note") or "")[:150]
    out[k] = {
        "n": r["n"],
        "p": [rnd(base.get(c)) for c in CATS] + [as_pct(base.get("fg")), as_pct(base.get("ft"))],
        "gp": rnd(gp), "gl": gp_lo, "gh": gp_hi,
        "mpg": rnd(mpg), "role": role, "rs": po,      # rs = 常规赛窗口场次
        "c": r.get("conf", ""),
        "s": base_src + ("+fp" if f else ""),
        "f": [],
        "note": note,
        "coach": (r.get("coach") or "")[:90],
        "_factors": r["factors"],
    }

FACTOR_ORDER = ["新秀", "伤病", "已康复", "合同年", "换队", "交易", "角色↑", "角色↓", "耐久性",
                "源分歧", "薪水保出场", "位置拥挤", "球权释放", "摆烂队", "交易流言",
                "潜力股", "看衰"]
for k, v in out.items():
    uniq = list(dict.fromkeys(v.pop("_factors")))
    uniq.sort(key=lambda x: FACTOR_ORDER.index(x) if x in FACTOR_ORDER else 99)
    v["f"] = uniq[:5]

json.dump(out, open(WS / "yahoo-fantasy/pred_2026_27.json", "w"), ensure_ascii=False, separators=(",", ":"))

srcs = collections.Counter(v["s"] for v in out.values())
facs = collections.Counter(f for v in out.values() for f in v["f"])
print(f"✓ 预测层 v2：{len(out)} 人")
print(f"  来源: {dict(srcs)}")
print(f"  因素: {dict(facs)}")
print(f"  联盟均值 FG%={LG_FG:.3f} FT%={LG_FT:.3f}")
print(f"  文件: {(WS/'yahoo-fantasy/pred_2026_27.json').stat().st_size/1024:.0f} KB")
print("\n样例：")
for nm in ["Nikola Jokic", "Giannis Antetokounmpo", "Jayson Tatum", "Victor Wembanyama",
           "Tyler Herro", "AJ Dybantsa", "Stephen Curry", "Zion Williamson", "Rudy Gobert"]:
    v = out.get(norm(nm))
    if v:
        print(f"  {nm:<24} {v['p'][0]}/{v['p'][1]}/{v['p'][2]}  {v['gp']}场({v['gl']}-{v['gh']})  "
              f"{v['mpg']}min {v['role']:<5} 常规赛{str(v['rs']):<3}场 FG{v['p'][7]} FT{v['p'][8]}  {'/'.join(v['f'])[:40]}")
