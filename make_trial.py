#!/usr/bin/env python3
"""
从 index.html 生成试用版 trial.html

改动：
  ① const TRIAL = false  →  true
  ② 顶栏加「试用版」标题
  ③ 试用时长可调（默认 300 秒）
"""
import pathlib, re, sys

WS = pathlib.Path(__file__).resolve().parent
SECONDS = int(sys.argv[1]) if len(sys.argv) > 1 else 300
src = (WS / "index.html").read_text(encoding="utf-8")

assert src.count("const TRIAL = false;") == 1, "找不到 TRIAL 开关"
out = src.replace("const TRIAL = false;", "const TRIAL = true;", 1)
assert out.count("const TRIAL_SECONDS = 300;") == 1, "找不到试用时长"
out = out.replace("const TRIAL_SECONDS = 300;", f"const TRIAL_SECONDS = {SECONDS};", 1)

# 填入日志上报地址
WORKER = "https://hoops-ai-yahoo-proxy.fhz20011019.workers.dev"
assert out.count('const TRIAL_LOG_URL = "";') == 1
out = out.replace('const TRIAL_LOG_URL = "";', f'const TRIAL_LOG_URL = "{WORKER}";', 1)

# 标题区分
out = re.sub(r"<title>(.*?)</title>", r"<title>\1 · 试用版</title>", out, count=1)

path = WS / "trial.html"
path.write_text(out, encoding="utf-8")
print(f"✓ 生成 trial.html  ({len(out)/1024:.0f} KB, 试用 {SECONDS} 秒)")
print(f"   TRIAL = true : {out.count('const TRIAL = true;')}")
