/**
 * HOOPS AI · Yahoo Fantasy OAuth 代理（Cloudflare Worker）— 可直接粘贴版
 * 部署方式见本文件末尾注释。
 *
 * 需要在 Worker 的 Settings → Variables 里配置：
 *   HOOPS_KV            （KV Namespace 绑定，变量名必须叫这个）
 *   YAHOO_CLIENT_ID     （Secret）
 *   YAHOO_CLIENT_SECRET （Secret）
 *   PUBLIC_BASE_URL     （普通变量，填本 Worker 的公开地址）
 *   ALLOWED_ORIGIN      （普通变量，默认已是你的页面地址）
 *   YAHOO_COOKIE        （可选；路线 B：Yahoo 登录 Cookie，用于抓取你的联盟/阵容网页）
 */

const Y_AUTH = "https://api.login.yahoo.com/oauth2/request_auth";
const Y_TOKEN = "https://api.login.yahoo.com/oauth2/get_token";
const Y_API = "https://fantasysports.yahooapis.com/fantasy/v2";
const SCOPE = "fspt-r";

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const origin = env.ALLOWED_ORIGIN || "https://fhz20011019-stack.github.io";   // 你的页面地址
    const self = env.PUBLIC_BASE_URL || "https://hoops-ai-yahoo-proxy.fhz20011019.workers.dev";   // 已内置你的 Worker 地址

    const cors = {
      "Access-Control-Allow-Origin": origin === "*" ? "*" : origin,
      "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
      "Access-Control-Allow-Headers": "Content-Type, X-Yahoo-Cookie",
      "Vary": "Origin",
    };
    if (request.method === "OPTIONS") return new Response(null, { status: 204, headers: cors });

    const fmtSec = n => { n = Math.max(0, Math.round(n || 0));
    return Math.floor(n / 60) + ":" + String(n % 60).padStart(2, "0"); };
  const esc = s => String(s == null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  const json = (obj, status = 200) =>
      new Response(JSON.stringify(obj, null, 2), { status, headers: { ...cors, "Content-Type": "application/json; charset=utf-8" } });

    try {
      switch (url.pathname) {
        case "/":
          return json({ ok: true, service: "hoops-ai-yahoo-proxy", time: new Date().toISOString(),
                        endpoints: ["/login", "/callback", "/status", "/api?path=...", "/debug", "/logout", "/log", "/trial", "/trial-admin"] });

        case "/login": {
          const state = crypto.randomUUID();
          await env.HOOPS_KV.put("state:" + state, "1", { expirationTtl: 600 });
          const u = new URL(Y_AUTH);
          u.searchParams.set("client_id", env.YAHOO_CLIENT_ID);
          u.searchParams.set("redirect_uri", self + "/callback");
          u.searchParams.set("response_type", "code");
          u.searchParams.set("scope", SCOPE);
          u.searchParams.set("state", state);
          u.searchParams.set("language", "en-us");
          return Response.redirect(u.toString(), 302);
        }

        case "/callback": {
          const code = url.searchParams.get("code");
          const state = url.searchParams.get("state");
          const err = url.searchParams.get("error");
          if (err) return html("授权失败：" + err + "（" + (url.searchParams.get("error_description") || "") + "）");
          if (!code) return html("没有拿到 code，请重新走 /login");
          const ok = state ? await env.HOOPS_KV.get("state:" + state) : null;
          if (!ok) return html("state 校验失败（可能超时或重放），请重新走 /login");
          await env.HOOPS_KV.delete("state:" + state);

          const res = await fetch(Y_TOKEN, {
            method: "POST",
            headers: {
              "Content-Type": "application/x-www-form-urlencoded",
              "Authorization": "Basic " + btoa(env.YAHOO_CLIENT_ID + ":" + env.YAHOO_CLIENT_SECRET),
            },
            body: new URLSearchParams({
              grant_type: "authorization_code",
              code,
              redirect_uri: self + "/callback",
            }),
          });
          const data = await res.json().catch(() => ({}));
          if (!res.ok || !data.access_token) {
            return html("换 token 失败：" + JSON.stringify(data).slice(0, 500));
          }
          await saveToken(env, data);
          return html("✅ 授权成功！可以关掉这个页面，回到 HOOPS AI 控制台点「同步我的联盟」。");
        }

        case "/status": {
          const t = await getToken(env);
          return json({ authorized: !!t, expiresAt: t ? new Date(t.expires_at).toISOString() : null,
                        hasRefresh: !!(t && t.refresh_token) });
        }

        case "/logout": {
          await env.HOOPS_KV.delete("yahoo:token");
          return json({ ok: true, authorized: false });
        }

        case "/debug": {
          const t = await getToken(env);
          if (!t) return json({ authorized: false, hint: "先访问 /login" }, 401);
          const r = await yahooGet(env, "users;use_login=1/games;game_keys=nba/leagues");
          return new Response(r.body, { status: r.status, headers: { ...cors, "Content-Type": "application/xml; charset=utf-8" } });
        }

        case "/yahoo-status": {
          const ck = request.headers.get("X-Yahoo-Cookie") || env.YAHOO_COOKIE;
          if (!ck) return json({ cookieSet: false, hint: "在 Worker 变量里加 YAHOO_COOKIE（Yahoo 登录后的 Cookie 字符串）" });
          const r = await fetch("https://basketball.fantasysports.yahoo.com/nba", { headers: WEB_HEADERS(ck) });
          return json({ cookieSet: true, count: ck.length, probeStatus: r.status,
                        usable: r.status === 200 && !/login\.yahoo\.com/.test(r.url || "") });
        }

        /* 路线 B：用你的 Yahoo 登录 Cookie 抓网页，返回 HTML（页面端再解析）
           只允许访问 basketball.fantasysports.yahoo.com，防止被当成开放代理 */
        case "/yahoo": {
          const target = url.searchParams.get("url");
          if (!target) return json({ error: "缺少 url 参数" }, 400);
          /* 允许两类地址：
             ① 网页（basketball.fantasysports.yahoo.com）—— 抓选秀室/设置页
             ② 免 OAuth 的公开 Fantasy API（pub-api-ro...）—— 结构化数据，选秀实时同步用这个
             白名单写死，避免被当成开放代理 */
          const OK_TARGETS = [
            /^https:\/\/basketball\.fantasysports\.yahoo\.com\//i,
            /^https:\/\/pub-api-ro\.fantasysports\.yahoo\.com\/fantasy\/v2\//i,
          ];
          if (!OK_TARGETS.some(re => re.test(target))) {
            return json({ error: "bad_url",
              hint: "只允许 basketball.fantasysports.yahoo.com/ 或 pub-api-ro.fantasysports.yahoo.com/fantasy/v2/ 开头的地址" }, 400);
          }
          // Cookie 优先用页面传来的请求头（存在用户本机），否则用 Worker 里的 YAHOO_COOKIE
          const ck = request.headers.get("X-Yahoo-Cookie") || env.YAHOO_COOKIE;
          if (!ck) return json({ error: "no_cookie",
            hint: "还没设置 Cookie。两种方式任选：① 直接在页面 ⚙️ 设置里填「Yahoo 登录 Cookie」；② 到 Worker → Settings → Variables 添加 YAHOO_COOKIE" }, 400);
          const r = await fetch(target, { headers: WEB_HEADERS(ck), redirect: "manual" });
          if (r.status >= 300 && r.status < 400) {
            const loc = r.headers.get("location") || "";
            return json({ error: "cookie_expired", status: r.status, location: loc.slice(0, 160),
              hint: "Cookie 失效了（跳转到登录页）。重新从浏览器复制新的 Cookie 覆盖 YAHOO_COOKIE 即可。" }, 401);
          }
          if (!r.ok) return json({ error: "fetch_failed", status: r.status }, 502);
          const body = await r.text();
          const ct = r.headers.get("content-type") || "text/html; charset=utf-8";
          return new Response(body, { headers: { ...cors, "Content-Type": ct } });
        }


        /* ══════════ 试用版选人记录 ══════════ */

        /* ══════════ 一次性试用链接 ══════════ */
        case "/trial": {
          // 页面端调用：用 token 换取剩余试用秒数
          // 关键：开始时间是服务端记的，所以刷新 / 关掉重开都不能重置
          let token = url.searchParams.get("t") || "";
          if (request.method === "POST") {
            const b = await request.json().catch(() => null);
            if (b && b.token) token = b.token;
          }
          if (!token) return json({ ok: false, err: "no_token", msg: "没有带试用链接参数" }, 400);
          token = String(token).slice(0, 64).replace(/[^A-Za-z0-9_-]/g, "");
          const key = "tok:" + token;
          const raw = await env.HOOPS_KV.get(key);
          if (!raw) return json({ ok: false, err: "invalid", msg: "链接无效（可能已被删除，或者不是完整的链接）" }, 404);
          const rec = JSON.parse(raw);
          const now = Date.now();
          if (rec.revoked) return json({ ok: false, err: "revoked", msg: "这个链接已被停用" }, 403);
          if (!rec.startedAt) { rec.startedAt = now; rec.uses = 1; }
          else { rec.uses = (rec.uses || 1) + 1; }
          const total = rec.seconds || 300;
          const elapsed = Math.floor((now - rec.startedAt) / 1000);
          const left = Math.max(0, total - elapsed);
          rec.lastSeen = now; rec.left = left; rec.total = total;
          if (left <= 0) { rec.dead = true; rec.deadAt = rec.deadAt || now; }
          await env.HOOPS_KV.put(key, JSON.stringify(rec), { expirationTtl: 60 * 60 * 24 * 180 });
          if (left <= 0) {
            return json({ ok: false, err: "expired", left: 0, total: total,
                          msg: "这个链接的试用时间已经用完了（共 " + Math.round(total / 60) + " 分钟）" });
          }
          return json({ ok: true, left: left, total: total, uses: rec.uses, token: token });
        }

        case "/trial-admin": {
          // 只有知道 LOG_KEY 的人能进
          const need = env.LOG_KEY;
          const got = url.searchParams.get("key") || "";
          const head = '<!doctype html><html><head><meta charset="utf-8"><title>试用链接管理</title><style>' +
            'body{background:#07090f;color:#e9edf6;font-family:-apple-system,"PingFang SC",sans-serif;padding:26px;max-width:1100px;margin:0 auto}' +
            'h1{font-size:20px;margin:0 0 4px}.sub{color:#7f93ab;font-size:12.5px;margin-bottom:20px}' +
            '.bar{background:rgba(255,255,255,.035);border:1px solid rgba(255,255,255,.1);border-radius:12px;padding:16px 18px;margin-bottom:20px;display:flex;gap:12px;align-items:center;flex-wrap:wrap}' +
            'input{background:rgba(0,0,0,.4);border:1px solid rgba(255,255,255,.18);color:#e9edf6;padding:9px 12px;border-radius:9px;font-size:14px;width:80px}' +
            'a.btn,button{background:linear-gradient(135deg,#ff6b1a,#ff9a4d);border:none;color:#fff;padding:10px 20px;border-radius:10px;font-size:14px;font-weight:700;cursor:pointer;text-decoration:none;display:inline-block}' +
            'table{border-collapse:collapse;width:100%;font-size:13px}' +
            'th,td{padding:10px 12px;border-bottom:1px solid rgba(255,255,255,.09);text-align:left;vertical-align:top}' +
            'th{color:#9fb2cc;font-size:11.5px;font-weight:700;letter-spacing:.4px}' +
            'tr:hover td{background:rgba(61,139,255,.06)}' +
            'code{background:rgba(255,255,255,.07);padding:3px 8px;border-radius:6px;font-size:11.5px;word-break:break-all;color:#bfe0ff}' +
            '.ok{color:#7CFFB2}.warn{color:#ffd9a0}.dead{color:#7f93ab}.err{color:#ff8a8a}' +
            '.cp{background:rgba(61,139,255,.18);border:1px solid rgba(61,139,255,.5);color:#bfe0ff;padding:5px 11px;border-radius:7px;font-size:11.5px;cursor:pointer;font-weight:700}' +
            '</style></head><body>';
          if (!need) return new Response(head + '<h1>还没设置 LOG_KEY</h1><div class="sub">请在 Worker 变量里加一个 LOG_KEY</div></body></html>',
            { headers: { "Content-Type": "text/html; charset=utf-8" } });
          if (got !== need) return new Response(head + '<h1>密钥不对</h1></body></html>',
            { status: 403, headers: { "Content-Type": "text/html; charset=utf-8" } });

          const base = (env.PUBLIC_SITE || "https://fhz20011019-stack.github.io/hoops-ai") + "/";

          // 生成新链接
          const made = [];
          const nNew = Math.max(0, Math.min(30, parseInt(url.searchParams.get("new") || "0", 10) || 0));
          const secs = Math.max(30, Math.min(86400, parseInt(url.searchParams.get("sec") || "300", 10) || 300));
          const who = (url.searchParams.get("who") || "").slice(0, 30);
          const fresh = [];
          for (let i = 0; i < nNew; i++) {
            const tk = Array.from(crypto.getRandomValues(new Uint8Array(12)))
              .map(b => "abcdefghijkmnpqrstuvwxyz23456789"[b % 32]).join("");
            const rec = { token: tk, created: Date.now(), seconds: secs, for: who, uses: 0 };
            await env.HOOPS_KV.put("tok:" + tk, JSON.stringify(rec),
              { expirationTtl: 60 * 60 * 24 * 180 });
            made.push(base + "?t=" + tk);
            fresh.push(rec);          // KV list 有最终一致性，刚写的可能列不出来 → 手动带上
          }

          // 停用
          const rv = url.searchParams.get("revoke");
          if (rv) {
            const raw = await env.HOOPS_KV.get("tok:" + rv);
            if (raw) {
              const r = JSON.parse(raw); r.revoked = true;
              await env.HOOPS_KV.put("tok:" + rv, JSON.stringify(r), { expirationTtl: 60 * 60 * 24 * 180 });
            }
          }

          // 列出所有
          const page = await env.HOOPS_KV.list({ prefix: "tok:", limit: 1000 });
          const toks = [];
          for (const k of page.keys) {
            const v = await env.HOOPS_KV.get(k.name);
            if (v) { try { toks.push(JSON.parse(v)); } catch (e) {} }
          }
          const seen = new Set(fresh.map(f => f.token));
          const merged = fresh.concat(toks.filter(t => !seen.has(t.token)));
          toks.length = 0; merged.forEach(t => toks.push(t));
          toks.sort((a, b) => (b.created || 0) - (a.created || 0));
          const rows = toks.map(t => {
            const st = t.revoked ? ['<span class="dead">已停用</span>', "—"]
              : t.dead ? ['<span class="err">已用完</span>', "0:00"]
              : t.startedAt ? ['<span class="warn">使用中</span>', fmtSec(t.left)]
              : ['<span class="ok">未使用</span>', fmtSec(t.seconds || 300)];
            return `<tr>
              <td><code>${esc(base + "?t=" + t.token)}</code></td>
              <td>${st[0]}</td><td>${st[1]}</td><td>${t.uses || 0}</td>
              <td>${esc(t.for || "")}</td>
              <td>${t.startedAt ? new Date(t.startedAt).toLocaleString("zh-CN") : "—"}</td>
              <td><button class="cp" data-url="${esc(base + "?t=" + t.token)}">复制</button>
                  <a class="cp" style="text-decoration:none" href="?key=${encodeURIComponent(got)}&revoke=${encodeURIComponent(t.token)}">停用</a></td>
            </tr>`;
          }).join("");

          const madeHtml = made.length
            ? '<div class="bar" style="display:block"><div style="font-weight:700;margin-bottom:10px">刚生成的 ' + made.length + ' 个链接：</div>' +
              made.map(u => '<div style="margin:6px 0"><code>' + esc(u) + '</code> <button class="cp" data-url="' + esc(u) + '">复制</button></div>').join("") +
              '</div>'
            : "";

          return new Response(head +
            '<h1>🔗 一次性试用链接</h1>' +
            '<div class="sub">每个链接共 ' + Math.round(secs / 60) + ' 分钟试用时间，<b>刷新 / 关掉重开都不重置</b>，用完即废。</div>' +
            (made.length ? '<div class="bar" style="border-color:rgba(255,170,60,.4);background:rgba(255,170,60,.08);color:#ffd9a0">' +
              '⚠️ 刚生成的链接，Cloudflare 的存储要 <b>最多 60 秒</b>才全球同步完。建议<b>生成后等 1 分钟再发出去</b>，否则对方可能看到「链接无效」。</div>' : "") +
            '<div class="bar">' +
              '<form method="get" style="display:flex;gap:10px;align-items:center;flex-wrap:wrap">' +
              '<input type="hidden" name="key" value="' + esc(got) + '">' +
              '生成 <input type="number" name="new" value="1" min="1" max="30"> 个链接，' +
              '每个 <input type="number" name="sec" value="300" min="30" step="30"> 秒' +
              '，备注 <input type="text" name="who" placeholder="给谁用" style="width:130px">' +
              '<button type="submit">生成</button></form>' +
            '</div>' +
            madeHtml +
            '<table><thead><tr><th>链接</th><th>状态</th><th>剩余</th><th>打开次数</th><th>备注</th><th>首次使用</th><th>操作</th></tr></thead>' +
            '<tbody>' + (rows || '<tr><td colspan="7" style="padding:40px;text-align:center;color:#7f93ab">还没有生成过链接</td></tr>') + '</tbody></table>' +
            '<script>document.querySelectorAll(".cp[data-url]").forEach(function(b){b.onclick=function(){' +
            'navigator.clipboard.writeText(b.dataset.url);b.textContent="已复制✓";setTimeout(function(){b.textContent="复制"},1200);};});</script>' +
            '</body></html>', { headers: { "Content-Type": "text/html; charset=utf-8" } });
        }

        case "/log": {
          // 写入（页面端调用，无需密钥）
          if (request.method === "POST") {
            const body = await request.json().catch(() => null);
            if (!body || !body.sid) return json({ ok: false, err: "缺少 sid" }, 400);
            const sid = String(body.sid).slice(0, 48).replace(/[^A-Za-z0-9_-]/g, "");
            const t = Date.now();
            const which = String(body.type || "event").slice(0, 24);
            // 事件本身
            await env.HOOPS_KV.put(`log:${sid}:${String(t).padStart(14, "0")}:${which}`,
              JSON.stringify(body), { expirationTtl: 60 * 60 * 24 * 120 });
            // 会话摘要（方便你一眼看列表）
            const sk = `sess:${sid}`;
            let sum = {};
            try { sum = JSON.parse((await env.HOOPS_KV.get(sk)) || "{}"); } catch (e) { sum = {}; }
            sum.sid = sid;
            sum.user = body.user || sum.user || "(未填)";
            sum.slot = body.slot != null ? body.slot : sum.slot;
            sum.team = body.team || sum.team || "";
            sum.punts = (body.punts && body.punts.length) ? body.punts : (sum.punts || []);
            sum.first = sum.first || body.t || new Date(t).toISOString();
            sum.last = body.t || new Date(t).toISOString();
            sum.events = (sum.events || 0) + 1;
            if (which === "pick") {
              sum.picks = sum.picks || [];
              sum.picks.push({ pick: body.d && body.d.pick, player: body.d && body.d.player });
            }
            if (which === "undo") { sum.undos = (sum.undos || 0) + 1; }
            if (which === "session_end" || which === "session_close") {
              sum.ended = which;
              sum.finalRoster = (body.d && body.d.roster) || sum.finalRoster || [];
            }
            await env.HOOPS_KV.put(sk, JSON.stringify(sum), { expirationTtl: 60 * 60 * 24 * 120 });
            return json({ ok: true });
          }

          // 读取（只有知道密钥的人能看）
          const need = env.LOG_KEY;
          const got = url.searchParams.get("key") || "";
          if (!need) return json({ ok: false, err: "服务端还没设置 LOG_KEY。请在 Worker → Settings → Variables 里加一个 LOG_KEY（类型选 Secret）" }, 500);
          if (got !== need) return json({ ok: false, err: "密钥不对" }, 403);

          const sid = url.searchParams.get("sid");
          if (sid) {
            // 单个会话的完整事件流
            const page = await env.HOOPS_KV.list({ prefix: `log:${sid}:`, limit: 1000 });
            const names = page.keys.map(k => k.name).sort();
            const evts = [];
            for (const n of names) {
              const v = await env.HOOPS_KV.get(n);
              if (v) { try { evts.push(JSON.parse(v)); } catch (e) {} }
            }
            const sum = await env.HOOPS_KV.get(`sess:${sid}`);
            return json({ ok: true, summary: sum ? JSON.parse(sum) : null, events: evts });
          }

          // 列出所有会话
          const page = await env.HOOPS_KV.list({ prefix: "sess:", limit: 1000 });
          const out = [];
          for (const k of page.keys) {
            const v = await env.HOOPS_KV.get(k.name);
            if (v) { try { out.push(JSON.parse(v)); } catch (e) {} }
          }
          out.sort((a, b) => String(b.last || "").localeCompare(String(a.last || "")));
          if (url.searchParams.get("view") === "1") {
            const rows = out.map(s => `<tr>
              <td>${esc(s.user)}</td><td>${esc(s.team)}</td><td>${s.slot || "—"}</td>
              <td>${(s.punts || []).join(" ") || "无"}</td>
              <td>${s.events || 0}</td>
              <td>${(s.picks || []).length}</td>
              <td>${esc(s.ended || "进行中")}</td>
              <td>${esc(s.first || "")}<br><span style="color:#7f93ab">→ ${esc(s.last || "")}</span></td>
              <td><a href="?key=${encodeURIComponent(got)}&sid=${encodeURIComponent(s.sid)}&view=1">看详情</a></td>
            </tr>`).join("");
            return new Response(`<!doctype html><html><head><meta charset="utf-8">
              <title>试用记录</title><style>
              body{background:#07090f;color:#e9edf6;font-family:-apple-system,"PingFang SC",sans-serif;padding:26px}
              h1{font-size:19px;margin:0 0 4px}.sub{color:#7f93ab;font-size:12.5px;margin-bottom:18px}
              table{border-collapse:collapse;width:100%;font-size:13px}
              th,td{padding:9px 11px;border-bottom:1px solid rgba(255,255,255,.09);text-align:left;vertical-align:top}
              th{color:#9fb2cc;font-size:11.5px;font-weight:700;text-transform:uppercase;letter-spacing:.4px}
              tr:hover td{background:rgba(61,139,255,.07)}
              a{color:#ff9a4d;text-decoration:none}a:hover{text-decoration:underline}
              .empty{color:#7f93ab;padding:50px;text-align:center}
              </style></head><body>
              <h1>📋 试用记录</h1>
              <div class="sub">共 ${out.length} 次试用 · 数据保留 120 天</div>
              ${out.length ? `<table><thead><tr><th>用户名</th><th>球队</th><th>顺位</th><th>放弃项</th>
              <th>事件</th><th>选人</th><th>结束方式</th><th>时间</th><th></th></tr></thead><tbody>${rows}</tbody></table>`
              : '<div class="empty">还没有人试用过</div>'}
              </body></html>`, { headers: { "Content-Type": "text/html; charset=utf-8" } });
          }
          return json({ ok: true, count: out.length, sessions: out });
        }

        case "/log-detail": {
          const need = env.LOG_KEY;
          if ((url.searchParams.get("key") || "") !== need) return json({ ok: false }, 403);
          const sid = url.searchParams.get("sid") || "";
          const page = await env.HOOPS_KV.list({ prefix: `log:${sid}:`, limit: 1000 });
          const evts = [];
          for (const n of page.keys.map(k => k.name).sort()) {
            const v = await env.HOOPS_KV.get(n);
            if (v) { try { evts.push(JSON.parse(v)); } catch (e) {} }
          }
          const sum = JSON.parse((await env.HOOPS_KV.get(`sess:${sid}`)) || "{}");
          const rows = evts.map(e => {
            const d = e.d || {};
            let extra = "";
            if (e.type === "pick") extra = `第 ${d.pick} 签 · Yahoo#${d.yahooRank} · ADP ${d.adp} · 上季 ${(d.lastSeason || [])[0]}分/${(d.lastSeason || [])[1]}板`;
            else if (e.type === "strategy") extra = "放弃：" + ((d.punts || []).join(" ") || "无");
            else if (e.type === "session_start") extra = `开始试用 · ${e.team} · 第 ${e.slot} 顺位`;
            else if (e.type === "session_end") extra = `阵容：${(d.roster || []).join("、")}`;
            else if (e.type === "session_close") extra = `阵容：${(d.roster || []).join("、")}`;
            else if (e.type === "undo") extra = "撤销了 " + d.player;
            else if (e.type === "sim_finish") extra = `模拟完成，最终阵容 ${(d.roster || []).length} 人`;
            return `<tr><td>${esc(e.t || "")}</td><td>${esc(e.type || "")}</td><td>${esc(d.player || "")}</td><td>${esc(extra)}</td></tr>`;
          }).join("");
          return new Response(`<!doctype html><html><head><meta charset="utf-8"><title>${esc(sum.user || sid)}</title><style>
            body{background:#07090f;color:#e9edf6;font-family:-apple-system,"PingFang SC",sans-serif;padding:26px}
            h1{font-size:19px;margin:0 0 4px}.sub{color:#7f93ab;font-size:12.5px;margin-bottom:18px}
            .card{background:rgba(255,255,255,.03);border:1px solid rgba(255,255,255,.1);border-radius:12px;padding:16px 18px;margin-bottom:18px;font-size:13px;line-height:1.9}
            table{border-collapse:collapse;width:100%;font-size:12.5px}
            th,td{padding:8px 10px;border-bottom:1px solid rgba(255,255,255,.09);text-align:left;vertical-align:top}
            th{color:#9fb2cc;font-size:11px}
            a{color:#ff9a4d;text-decoration:none}
            </style></head><body>
            <h1>${esc(sum.user || "(未填用户名)")}</h1>
            <div class="sub"><a href="?key=${encodeURIComponent(need)}&view=1">← 返回列表</a></div>
            <div class="card">
              <b>球队</b>：${esc(sum.team || "—")} · <b>顺位</b>：${sum.slot || "—"}<br>
              <b>策略（放弃）</b>：${(sum.punts || []).join(" ") || "无"}<br>
              <b>开始</b>：${esc(sum.first || "—")}<br>
              <b>最后活动</b>：${esc(sum.last || "—")} · 共 ${sum.events || 0} 个事件<br>
              <b>选了</b>：${(sum.picks || []).map(p => `第${p.pick}签 ${esc(p.player)}`).join("、") || "还没选"}<br>
              <b>撤销次数</b>：${sum.undos || 0}<br>
              <b>最终阵容</b>：${(sum.finalRoster || []).join("、") || "—"}
            </div>
            <table><thead><tr><th>时间</th><th>动作</th><th>球员</th><th>详情</th></tr></thead><tbody>${rows}</tbody></table>
            </body></html>`, { headers: { "Content-Type": "text/html; charset=utf-8" } });
        }

        case "/api": {
          const path = url.searchParams.get("path");
          if (!path) return json({ error: "缺少 path 参数" }, 400);
          if (!/^[a-z0-9;,_:=.\/%-]+$/i.test(path) || path.startsWith("http")) return json({ error: "path 不合法" }, 400);
          const t = await getToken(env);
          if (!t) return json({ error: "not_authorized", hint: "浏览器打开 " + self + "/login 先授权" }, 401);
          const r = await yahooGet(env, path.replace(/^\/+/, ""));
          return new Response(r.body, { status: r.status, headers: { ...cors, "Content-Type": "application/xml; charset=utf-8" } });
        }

        default:
          return json({ error: "not_found", path: url.pathname }, 404);
      }
    } catch (e) {
      return json({ error: "worker_exception", message: String(e && e.message || e) }, 500);
    }
  },
};

/* ---------------- Yahoo 网页请求头（路线 B 用） ---------------- */
const UA_WEB = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36";
const WEB_HEADERS = (cookie) => ({
  "Cookie": cookie,
  "User-Agent": UA_WEB,
  "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
  "Accept-Language": "en-US,en;q=0.9",
  "Referer": "https://basketball.fantasysports.yahoo.com/",
});

/* ---------------- token 存取 ---------------- */
async function saveToken(env, data) {
  const rec = {
    access_token: data.access_token,
    refresh_token: data.refresh_token || null,
    expires_at: Date.now() + (Number(data.expires_in || 3600) - 60) * 1000,
    token_type: data.token_type || "bearer",
    guid: data.xoauth_yahoo_guid || null,
  };
  await env.HOOPS_KV.put("yahoo:token", JSON.stringify(rec));
  return rec;
}

async function getToken(env) {
  const raw = await env.HOOPS_KV.get("yahoo:token");
  if (!raw) return null;
  let t; try { t = JSON.parse(raw); } catch (e) { return null; }
  if (t.expires_at && Date.now() < t.expires_at) return t;
  if (!t.refresh_token) return t;                       // 没法刷新，交给上层报错
  const res = await fetch(Y_TOKEN, {
    method: "POST",
    headers: {
      "Content-Type": "application/x-www-form-urlencoded",
      "Authorization": "Basic " + btoa(env.YAHOO_CLIENT_ID + ":" + env.YAHOO_CLIENT_SECRET),
    },
    body: new URLSearchParams({ grant_type: "refresh_token", refresh_token: t.refresh_token }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok || !data.access_token) return t;
  return await saveToken(env, { ...data, refresh_token: data.refresh_token || t.refresh_token });
}

async function yahooGet(env, path) {
  const t = await getToken(env);
  const apiUrl = Y_API + "/" + path + (path.includes("?") ? "&" : "?") + "format=json";
  const res = await fetch(apiUrl, { headers: { Authorization: "Bearer " + t.access_token, Accept: "application/json" } });
  const body = await res.text();
  return { status: res.status, body };
}

function html(msg) {
  return new Response(
    `<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8"><title>HOOPS AI · Yahoo 授权</title>
     <style>body{background:#07090f;color:#e9edf6;font-family:-apple-system,"PingFang SC",sans-serif;
     display:flex;align-items:center;justify-content:center;height:100vh;margin:0}
     .box{max-width:520px;padding:28px 30px;border-radius:16px;background:#151b2c;border:1px solid rgba(255,255,255,.12);
     box-shadow:0 18px 44px rgba(0,0,0,.5);font-size:15px;line-height:1.7}
     b{color:#ff9a4d}</style></head><body><div class="box">${msg}</div></body></html>`,
    { headers: { "Content-Type": "text/html; charset=utf-8" } }
  );
}


/* ============================================================================
   部署说明（Cloudflare 网页版，无需命令行）
   ---------------------------------------------------------------------------
   1. 打开 https://dash.cloudflare.com → 左侧 Workers & Pages → Create
   2. 选 Worker → 起名 hoops-ai-yahoo-proxy → Deploy
   3. 点 Edit code，把本文件全部内容覆盖进去 → Deploy
   4. 回到该 Worker → Settings：
      · Variables and Secrets 添加（PUBLIC_BASE_URL 可不填，代码里已内置）：
          YAHOO_CLIENT_ID      = 你的 Client ID   （类型选 Secret）
          YAHOO_CLIENT_SECRET  = 你的 Client Secret（类型选 Secret）
          PUBLIC_BASE_URL      = https://hoops-ai-yahoo-proxy.fhz20011019.workers.dev
          ALLOWED_ORIGIN       = https://fhz20011019-stack.github.io
          YAHOO_COOKIE         = （可选，Yahoo 登录 Cookie；不填就用不了 /yahoo 抓取）
          LOG_KEY              = （Secret）试用记录查看密钥，填：lk_AyaDxOX-eZnr8UGM9Cmwv3XL
      · Bindings 添加 KV Namespace：变量名 HOOPS_KV，选新建的命名空间
   5. 回 Yahoo 应用设置，把 Redirect URI 改成：
          https://hoops-ai-yahoo-proxy.fhz20011019.workers.dev/callback
   6. 浏览器打开  .../login  授权；看到「✅ 授权成功」即完成
   ============================================================================ */

// ===== END-OF-HOOPS-WORKER（粘贴到这一行为止，看到它就说明代码完整）=====
