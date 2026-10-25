# HOOPS AI · Yahoo Fantasy OAuth 代理（Cloudflare Worker）

静态页面做不了 OAuth（没有回调地址、不能存 client secret），所以用一个免费 Worker 中转。
**你只登录一次 Yahoo，之后页面就能随时读你的联盟、阵容、对手。**

```
你的浏览器 → GitHub Pages 页面 → 本 Worker（存 OAuth token）→ Yahoo Fantasy API
```

---

## 部署前：先在 Yahoo 注册应用（约 5 分钟）

1. 打开 **https://developer.yahoo.com/apps/create/**
2. 填：
   | 字段 | 填什么 |
   |---|---|
   | Application Name | `HOOPS AI` |
   | Application Type | **Confidential Client**（必须有 client secret） |
   | Redirect URI(s) | 先随便填 `https://example.com/callback`，**部署完 Worker 后回来改成你的 Worker 地址 + `/callback`** |
   | API Permissions | 勾 **Fantasy Sports → Read**（scope 是 `fspt-r`） |
3. 创建后记下 **Client ID** 和 **Client Secret**

> ⚠️ Yahoo 的 Fantasy Sports API 对个人使用免费，但**首次使用需要在应用页面勾选相应权限**；
> 若审核被拒，用 `fspt-r`（只读）通常是最容易通过的。

---

## 第 1 步：安装并登录 Cloudflare

```bash
cd yahoo-proxy
npm install
npx wrangler login          # 浏览器里点一下授权（免费账号即可）
```

## 第 2 步：创建 KV（存 token）

```bash
npx wrangler kv namespace create HOOPS_KV
```

把输出里的 `id = "xxxxx"` 填进 `wrangler.toml` 的 `[[kv_namespaces]]`。

## 第 3 步：填两个地址

编辑 `wrangler.toml`：

```toml
[vars]
ALLOWED_ORIGIN = "https://fhz20011019-stack.github.io"
PUBLIC_BASE_URL = "https://hoops-ai-yahoo-proxy.你的子域.workers.dev"
```

> `PUBLIC_BASE_URL` 现在是占位符 —— 第 4 步部署后 Cloudflare 会打印真实地址，回来改这里再部署一次。

## 第 4 步：部署

```bash
npx wrangler deploy
```

会打印形如 `https://hoops-ai-yahoo-proxy.abc123.workers.dev` 的地址：
1. 把它填回 `wrangler.toml` 的 `PUBLIC_BASE_URL`
2. **同时填到 Yahoo 应用的 Redirect URI**：`https://hoops-ai-yahoo-proxy.abc123.workers.dev/callback`
3. 再跑一次 `npx wrangler deploy`

## 第 5 步：设置 Secrets

```bash
npx wrangler secret put YAHOO_CLIENT_ID
npx wrangler secret put YAHOO_CLIENT_SECRET
```

（粘贴第 0 步拿到的值；不会写进文件，安全）

## 第 6 步：授权并验证

1. 浏览器打开 `https://你的worker地址/` → 应返回 `{"ok":true,...}`
2. 打开 `https://你的worker地址/login` → 登录 Yahoo → 看到「✅ 授权成功」
3. 打开 `https://你的worker地址/debug` → 应返回你的联盟 XML

## 第 7 步：接到页面

打开 https://fhz20011019-stack.github.io/hoops-ai/ → ⚙️ → 填 **Yahoo 同步代理地址** = 你的 Worker 地址 → 保存
→ 点选秀榜卡片上的 **🔗 同步 Yahoo** → 自动读联盟 + 阵容 + 九项强度

---

## 接口一览

| 路由 | 作用 |
|---|---|
| `GET /` | 健康检查 |
| `GET /login` | 跳转 Yahoo 授权 |
| `GET /callback` | OAuth 回调（存 token） |
| `GET /status` | `{authorized, expiresAt}` |
| `GET /api?path=<yahoo路径>` | 代理 Yahoo API（自动带 token、过期自动刷新） |
| `GET /debug` | 列出当前 token 能看到的联盟（排查用） |
| `POST /logout` | 清除 token |

## 常见问题

| 现象 | 原因 / 解决 |
|---|---|
| `/callback` 报 `redirect_uri_mismatch` | Yahoo 应用里登记的 Redirect URI 和 `PUBLIC_BASE_URL + /callback` 不一致（注意 https、有无结尾斜杠） |
| `/api` 返回 `not_authorized` | 还没走 `/login`，或 token 被清（重新登录一次） |
| 页面同步报 `Failed to fetch` | Worker 地址填错，或 `ALLOWED_ORIGIN` 不是 `https://fhz20011019-stack.github.io` |
| Yahoo 报 `scope` 错误 | 应用里没勾 Fantasy Sports 权限 |
| token 几周后失效 | 会自动刷新；若 refresh_token 也过期，重新走一次 `/login` |
