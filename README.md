# 库库AI 每日签到 · 云端模板

点一次 **Use this template**，加一个 Secret，每天自动签到。不装软件、不开电脑、不需要任何 Agent 帮忙。

只做签到：**不做任务、不发对话、不点邀请、不碰协议弹窗**。

## 三步

### 1. 用模板建一个私有仓库

右上 **Use this template → Create a new repository** → 选 **Private**，名字随意。

> 必须 Private：运行截图和结果会留在你的仓库里。

### 2. 加 Secret

`Settings → Secrets and variables → Actions → New repository secret`

- Name：`KUKUAI_COOKIES`
- Secret：你的 Cookie JSON（两个域各一份）

**别手抄**：用 GetCookie 工具抓，点「② 复制已抓取的 Cookie」，粘进 Secret 就行。抓出来是 2 条或 14 条都正常
（2 条 = 登录在 `kuku.baidu.com`，14 条 = 登录在 `www.kukuai.cn`，脚本会自己认）。

手贴的话格式长这样（最少两条）：

```json
[
  {"name":"BDUSS","value":"你的值","domain":".baidu.com","path":"/","httpOnly":true,"secure":true},
  {"name":"STOKEN","value":"你的值","domain":".kuku.baidu.com","path":"/","secure":true}
]
```

Cookie 从哪来：浏览器登录 <https://www.kukuai.cn/>，`F12` → Application → Cookies → `https://www.kukuai.cn`，复制 `BDUSS`、`STOKEN`。`BDUSS` 是 HttpOnly，只能在面板里复制。

Secret 存进去后看不到明文，日志里也不会打印。

### 3. 手动跑一次

**Actions → 库库AI 每日签到 → Run workflow**，跑完看 Summary：会显示「今日已签 / 连签 N 天 / 还差几天」。

之后每天北京时间 09:30 自动跑。

## 输出长什么样

```json
{
  "ok": true,
  "status": "signed",
  "signed": true,
  "streak": 3,
  "next_node": {"day": 7, "need": 4, "reward": "网盘SVIP卡（以页面公示为准）"},
  "activity_days_left": 38
}
```

- `status=signed` 刚签到成功
- `status=already` 今天已经签过
- `status=unconfirmed` 点了但没读到确认标记，看截图人工确认

## 当前活动

| 项 | 内容 |
| --- | --- |
| 活动 | 每日签到得网盘SVIP月卡 · 2026-10-21 ~ 2026-12-04 |
| 每日签到 | 积分 +10、抽奖 +1 |
| 连签档位 | 3 / 7 / 15 / 30 天（30 天必得月卡） |
| 断签 | 清零回第 1 天 |

换期改 `kukuai_signin.py` 顶部三个常量：`ACTIVITY_START`、`ACTIVITY_END`、`NODES`。

## 常见问题

| 现象 | 处理 |
| --- | --- |
| 报登录态失效 | Cookie 过期，重新导出后更新 Secret |
| 报验证码 / 风控 | 云端 IP 被拦。改用境内机器跑同一条命令，或注册自建 runner |
| 60 天后不跑了 | GitHub 会暂停长期无提交仓库的定时任务，手动 Run 一次即恢复 |
| 想推到手机 | 在 workflow 末尾加一步 `ntfy` / Server 酱 / 邮件通知 |

## 本机运行（可选）

```bash
pip install playwright && python -m playwright install chromium
# 本地放好 ~/.kukuai/cookies.json 后
python kukuai_signin.py --cookies ~/.kukuai/cookies.json
```

## 说明

自动化只服务账号本人的签到，不涉及代签、刷量、多账号。平台规则禁止脚本/插件类自动化工具，是否使用请自行判断；遇到验证码会立即停止。
