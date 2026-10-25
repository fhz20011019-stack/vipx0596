# 🏀 HOOPS AI · NBA 智能分析台

单文件静态页面（`index.html`），NBA 深色主题，四大分析入口 + Dify Agent 聊天窗口，回答以 Markdown 卡片渲染。

## 功能

| 模块 | 说明 |
| --- | --- |
| 选秀榜 | 榜单 Top 10 表格 + 体测亮点 + 球队需求匹配 |
| 伤病名单 | 伤停表格（状态 / 预计复出）+ 轮换影响 + 替代方案 |
| 球员对比 | 填两名球员 → 逐项对比表格 + 分场景结论（含梦幻 9 项） |
| 交易分析 | 填两支球队（可选筹码）→ 薪资匹配 + 筹码估值 + 备选方案 |
| 聊天窗口 | Dify Agent 流式输出（SSE）、Markdown 表格/代码块/引用卡片、复制、重试、停止、图片上传 |

## 快速开始

1. 用本地服务器打开页面（不要用 `file://`，避免 CORS 问题）：

   ```bash
   cd <本目录>
   python3 -m http.server 8788
   # 浏览器打开 http://127.0.0.1:8788/index.html
   ```

2. 点右上角 ⚙️ 填入 Dify 配置：

   - **API Base URL**：`https://api.dify.ai/v1`（自部署改成自己的域名，末尾保留 `/v1`）
   - **API Key**：Dify 应用 → 访问 API → API 密钥（`app-` 开头）
   - 可选：**中转地址**（解决 CORS）、**全局 inputs**（应用自定义变量）、**角色设定**

3. 点「保存并连接」，状态灯变绿即成功；或点右上角 🎬 演示 查看 Markdown 卡片渲染效果。

## 内置 Key（自动带上配置）

打开 `index.html`，找到 `<script>` 顶部的 `DEFAULT_CONFIG`：

```js
const DEFAULT_CONFIG = {
  apiBase: "https://api.dify.ai/v1",
  apiKey:  "",                 // ← 填 app-xxxx，页面会自动加载并连接
  proxy:   "",
  inputs:  {},
  system:  "你是 HOOPS AI……"
};
```

> 页面优先使用浏览器 localStorage 里的配置；清空配置（设置 → 恢复占位默认）后会回落到这里的默认值。

## CORS 说明

纯静态页面从浏览器直连 Dify，若报 `Failed to fetch` / CORS：

1. 自部署 Dify：在 `.env` 里把本站域名加入 `API_CORS_ALLOWED_ORIGINS`（形如 `https://你的用户名.github.io`），重启 API 服务；
2. 或用 Cloudflare Worker 之类的服务端做一层转发，然后在设置里填「中转地址」，请求会变成 `中转地址 + 完整 Dify 地址`。

## 安全提醒

这是纯静态页面，写进文件的 API Key 对任何拿到链接的人都是可见的。正式对外发布建议：

- 使用面向终端用户的 Dify 应用 + 域名白名单；
- 或把 Key 放在服务端中转（Worker / 函数计算）里，页面只填中转地址。

## 发布到 GitHub Pages

已发布：**https://fhz20011019-stack.github.io/hoops-ai/**

更新页面的方式（改完 `index.html` 后）：

```bash
git clone https://github.com/fhz20011019-stack/hoops-ai.git
cd hoops-ai
# 用新版 index.html 覆盖后
git add -A && git commit -m "update page" && git push
# Pages 会自动重新构建，1 分钟左右生效
```

首次从零发布：仓库 Settings → Pages → Source 选 `Deploy from a branch` → `main` / `(root)` → Save。
