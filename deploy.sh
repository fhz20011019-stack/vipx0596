#!/usr/bin/env bash
# 一键部署：完整版 → 随机名仓库；试用版 → 公开仓库
set -e
cd "$(dirname "$0")"
: "${GH_TOKEN:?请先 export GH_TOKEN=你的GitHub令牌}"
FULL_REPO=$(cat .full-repo-name)
PAGES_USER=fhz20011019-stack

echo "⓪ 刷新版本号…"
# 每次部署自动把 BUILD 换成当前时间戳，让老页面能检测到自己过期了
STAMP="v$(date +%y%m%d.%H%M)"
python3 - "$STAMP" <<'PYEOF'
import re, sys, pathlib
stamp = sys.argv[1]
for f in ("index.html",):
    p = pathlib.Path(f); s = p.read_text(encoding="utf-8")
    s2 = re.sub(r'const BUILD = "v[^"]*"', 'const BUILD = "%s"' % stamp, s, count=1)
    if s2 != s:
        p.write_text(s2, encoding="utf-8")
        print("   BUILD =", stamp)
PYEOF

echo "⓪b 部署前语法检查…"
python3 - <<'PYEOF'
import pathlib, re, subprocess, sys
s = pathlib.Path('index.html').read_text(encoding='utf-8')
js = re.findall(r'<script>(.*?)</script>', s, re.S)
pathlib.Path('/tmp/_dcheck.js').write_text(js[-1], encoding='utf-8')
r = subprocess.run(['node','--check','/tmp/_dcheck.js'], capture_output=True, text=True)
if r.returncode != 0:
    print("   ❌ 语法错误，已阻止部署：\n" + r.stderr[:500]); sys.exit(1)
print("   ✓ 语法通过")
PYEOF

echo "① 构建试用版…"
python3 make_trial.py 300 >/dev/null

echo "② 推送完整版 → $FULL_REPO"
S=.stage-full; rm -rf "$S"; mkdir -p "$S/yahoo-fantasy" "$S/yahoo-proxy/deploy"
cp index.html make_trial.py deploy.sh README.md 分享试用版-说明.md "$S/"
cp yahoo-fantasy/*.json yahoo-fantasy/*.py yahoo-fantasy/*.csv yahoo-fantasy/*.xlsx yahoo-fantasy/README.md "$S/yahoo-fantasy/" 2>/dev/null || true
for f in worker.js wrangler.toml package.json README.md; do cp yahoo-proxy/$f "$S/yahoo-proxy/"; done
cp yahoo-proxy/deploy/worker-paste.js "$S/yahoo-proxy/deploy/"
( cd "$S"; git init -q -b main; git config user.name "$PAGES_USER"; git config user.email "$PAGES_USER@users.noreply.github.com"
  git add -A; git commit -q -m "deploy $(date +%m-%d\ %H:%M)"
  git remote add origin "https://${PAGES_USER}:${GH_TOKEN}@github.com/${PAGES_USER}/${FULL_REPO}.git"
  git push -q -u origin main --force )
rm -rf "$S"

echo "③ 推送试用版 → hoops-ai"
S=.stage-trial; rm -rf "$S"; mkdir -p "$S"
cp trial.html "$S/index.html"
cat > "$S/README.md" <<'EOF'
# HOOPS AI 选秀助手 · 5 分钟试用版

👉 https://fhz20011019-stack.github.io/hoops-ai/

## 试用说明
- ⏱ 5 分钟自动锁定
- 🔒 只读：不能改设置 / 不能连 Yahoo 同步 / 不能导出
- 🔐 **球员预测排名与预测数据打码**，付费后解锁
- 💾 不留痕迹
EOF
( cd "$S"; git init -q -b main; git config user.name "$PAGES_USER"; git config user.email "$PAGES_USER@users.noreply.github.com"
  git checkout -q --orphan main; git add -A; git commit -q -m "trial $(date +%m-%d\ %H:%M)"
  git remote add origin "https://${PAGES_USER}:${GH_TOKEN}@github.com/${PAGES_USER}/hoops-ai.git"
  git push -q -u origin main --force )
rm -rf "$S"

echo "④ 等待 Pages 构建…"
for repo in hoops-ai "$FULL_REPO"; do
  for i in $(seq 1 40); do
    st=$(curl -s -H "Authorization: Bearer $GH_TOKEN" "https://api.github.com/repos/${PAGES_USER}/${repo}/pages/builds/latest" | python3 -c "import sys,json;print(json.load(sys.stdin).get('status'))" 2>/dev/null)
    [ "$st" = "built" ] && { echo "   $repo ✓"; break; }; sleep 8
  done
done
echo
echo "试用版 : https://${PAGES_USER}.github.io/hoops-ai/"
echo "完整版 : https://${PAGES_USER}.github.io/${FULL_REPO}/"
