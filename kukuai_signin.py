#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""库库AI 每日签到（只签到版）。

只做一件事：用你自己的 Cookie，在无头浏览器里点一下「签到」，然后告诉你结果。
不点任务、不发对话、不邀请、不碰任何协议弹窗、不领取奖励以外的任何东西。

用法:
    python kukuai_signin.py --cookies ~/.kukuai/cookies.json
    python kukuai_signin.py --cookies ~/.kukuai/cookies.json --dry-run
    python kukuai_signin.py --cookies cookies.txt --out out/ --headful

Cookie 格式（自动识别三种）:
    1) [{"name":"BDUSS","value":"...","domain":".kukuai.cn"}]
    2) {"BDUSS":"...","STOKEN":"..."}
    3) BDUSS=...; STOKEN=...

stdout 只输出一段 JSON；日志只写文件（<out>/log/）。
"""

from __future__ import annotations

import argparse
import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ---------------------------------------------------------------- 活动参数
HOME_URL = "https://www.kukuai.cn/"
ACTIVITY_START = "2026-10-21"
ACTIVITY_END = "2026-12-04"
NODES = [
    (3, "网盘SVIP天卡"),
    (7, "网盘SVIP卡（以页面公示为准）"),
    (15, "网盘SVIP卡（以页面公示为准）"),
    (30, "网盘SVIP月卡（必达即得）"),
]
CN_TZ = timezone(timedelta(hours=8))

DEFAULT_COOKIE_PATHS = [
    "~/.kukuai/cookies.json",
    "~/.kukuai/cookies.txt",
    "uploads/kukuai_cookies.json",
]

# 站点元素（2026-10 期实测）
SEL_SIGNIN_TITLE = '[data-testid="signin-promo-title"]'
SEL_SIGNIN_CARD = '[data-testid="signin-promo"]'
SEL_ACTIVITY_CLOSE = '[data-testid="activity-dialog-close"]'
SEL_SIGN_BTN = "button.pc-sign-btn"
FRAME_HINT = "kukuPcSignAct"

LOGIN_NEG = ["登录领网盘会员", "登录领取网盘SVIP", "登录后领取连签奖励", "扫码登录"]
SIGNED_HINTS = ["今日已签", "已签到", "明日再来", "明天再来", "已领取"]
RISK_HINTS = ["验证码", "拖动滑块", "滑块验证", "安全验证", "人机验证", "操作过于频繁", "环境异常"]


# ---------------------------------------------------------------- Cookie
def load_cookies(path: Path):
    text = path.read_text(encoding="utf-8").strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        data = None

    raw = []
    if isinstance(data, list):
        raw = data
    elif isinstance(data, dict):
        raw = data["cookies"] if isinstance(data.get("cookies"), list) else \
            [{"name": k, "value": str(v)} for k, v in data.items()]
    else:
        for part in text.split(";"):
            if "=" in part:
                k, v = part.split("=", 1)
                raw.append({"name": k.strip(), "value": v.strip()})

    out = []
    for c in raw:
        if not isinstance(c, dict) or "name" not in c or "value" not in c:
            continue
        item = {"name": str(c["name"]), "value": str(c["value"])}
        dom = str(c.get("domain") or ".kukuai.cn")
        item["domain"] = dom if dom.startswith(".") else "." + dom.lstrip(".")
        item["path"] = c.get("path") or "/"
        if isinstance(c.get("httpOnly"), bool):
            item["httpOnly"] = c["httpOnly"]
        if isinstance(c.get("secure"), bool):
            item["secure"] = c["secure"]
        out.append(item)
    return out


def find_cookie_path(explicit: str) -> Path:
    if explicit:
        p = Path(explicit).expanduser()
        if not p.exists():
            raise FileNotFoundError("Cookie 文件不存在: %s" % p)
        return p
    for cand in DEFAULT_COOKIE_PATHS:
        p = Path(cand).expanduser()
        if p.exists():
            return p
    raise FileNotFoundError("未找到 Cookie 文件，请用 --cookies 指定")


# ---------------------------------------------------------------- 小工具
def today_cn():
    return datetime.now(CN_TZ).date()


def days_left():
    end = datetime.strptime(ACTIVITY_END, "%Y-%m-%d").date()
    return (end - today_cn()).days


def next_node(streak):
    if streak is None:
        return None
    for day, reward in sorted(NODES):
        if streak < day:
            return {"day": day, "need": day - streak, "reward": reward}
    return None


class Session:
    def __init__(self, args, log):
        self.args = args
        self.log = log
        self.page = None
        self.ctx = None
        self.shots = []

    # --- 基础 ---
    def shot(self, tag):
        p = Path(self.args.out).expanduser() / ("kukuai-%s-%s.png" % (tag, datetime.now().strftime("%Y%m%d-%H%M%S")))
        p.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.page.screenshot(path=str(p), full_page=True)
            self.shots.append(str(p))
            self.log("screenshot -> %s" % p)
        except Exception as e:
            self.log("screenshot failed: %s" % e)

    def frame(self):
        for f in self.page.frames:
            if FRAME_HINT in (f.url or ""):
                return f
        return None

    def text(self):
        parts = []
        fr = self.frame()
        if fr:
            try:
                parts.append(fr.inner_text("body") or "")
            except Exception:
                pass
        try:
            parts.append(self.page.inner_text("body") or "")
        except Exception:
            pass
        return re.sub(r"\s+", " ", "\n".join(parts))

    def click(self, sel, timeout=5000, dom_fallback=True):
        try:
            loc = self.page.locator(sel)
            if not loc.count() or not loc.first.is_visible():
                return False
            try:
                loc.first.click(timeout=timeout)
            except Exception as e:
                if not dom_fallback:
                    return False
                self.log("click %s blocked (%s), DOM click" % (sel, str(e)[:60]))
                loc.first.evaluate("e => e.click()")
            return True
        except Exception as e:
            self.log("click %s failed: %s" % (sel, e))
            return False

    def close_dialog(self):
        """关掉活动/会员弹窗，否则点击会被遮罩吃掉。"""
        try:
            loc = self.page.locator(SEL_ACTIVITY_CLOSE)
            if loc.count() and loc.first.is_visible():
                try:
                    loc.first.click(timeout=2000)
                except Exception:
                    loc.first.evaluate("e => e.click()")
                self.page.wait_for_timeout(700)
                self.log("closed activity dialog")
                return True
        except Exception:
            pass
        return False

    # --- 主流程 ---
    def run(self):
        r = {
            "ok": False,
            "stage": "init",
            "status": None,
            "signed": None,
            "streak": None,
            "next_node": None,
            "activity_days_left": days_left(),
            "screenshot": None,
            "error": None,
        }
        out_dir = Path(self.args.out).expanduser()
        out_dir.mkdir(parents=True, exist_ok=True)

        cookies = load_cookies(find_cookie_path(self.args.cookies))
        self.log("cookies: %d" % len(cookies))
        if not cookies:
            r.update(stage="cookies", error="Cookie 为空或格式无法识别")
            return r

        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=not self.args.headful,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
            self.ctx = browser.new_context(viewport={"width": 1440, "height": 1000})
            try:
                self.ctx.add_cookies(cookies)
            except Exception as e:
                self.log("add_cookies issue: %s" % e)
            self.page = self.ctx.new_page()
            self.page.set_default_timeout(30000)
            try:
                self._steps(r)
            finally:
                try:
                    browser.close()
                except Exception:
                    pass
        return r

    def _steps(self, r):
        r["stage"] = "open"
        try:
            self.page.goto(HOME_URL, wait_until="domcontentloaded")
        except Exception as e:
            r.update(stage="open", error="打开页面失败: %s" % e)
            return
        self.page.wait_for_timeout(4500)
        self.close_dialog()
        self.page.wait_for_timeout(800)

        body = self.text()
        if any(k in body for k in RISK_HINTS):
            r.update(stage="risk", error="页面出现验证码/风控提示，已停止，请人工完成")
            self.shot("risk")
            r["screenshot"] = self.shots[-1] if self.shots else None
            return
        if any(k in body for k in LOGIN_NEG):
            r.update(stage="login", error="登录态失效，请重新导出 Cookie")
            self.shot("logged-out")
            r["screenshot"] = self.shots[-1] if self.shots else None
            return

        if self.args.dry_run:
            r.update(ok=True, stage="dry-run", status="probe")
            self.shot("dry-run")
            r["screenshot"] = self.shots[-1] if self.shots else None
            return

        # 打开任务中心（签到按钮在那里）
        r["stage"] = "open-task-center"
        if self.frame() is None:
            self.click(SEL_SIGNIN_TITLE) or self.click(SEL_SIGNIN_CARD)
            self.page.wait_for_timeout(3500)
            self.close_dialog()
            self.page.wait_for_timeout(600)

        streak = self._streak()
        r["streak"] = streak

        # 读按钮文案判断是否已签
        btn_text = ""
        fr = self.frame()
        if fr is not None:
            try:
                loc = fr.locator(SEL_SIGN_BTN)
                if loc.count():
                    btn_text = (loc.first.inner_text() or "").strip()
            except Exception:
                pass
        elif self.page.locator(SEL_SIGN_BTN).count():
            try:
                btn_text = (self.page.locator(SEL_SIGN_BTN).first.inner_text() or "").strip()
            except Exception:
                pass

        flat = self.text()
        if any(k in btn_text for k in SIGNED_HINTS) or (not btn_text and any(k in flat for k in SIGNED_HINTS)):
            r.update(ok=True, stage="done", status="already", signed=True)
            self.shot("already")
            r["screenshot"] = self.shots[-1] if self.shots else None
            return

        # 点签到
        r["stage"] = "signin"
        clicked = False
        if fr is not None:
            try:
                loc = fr.locator(SEL_SIGN_BTN)
                if loc.count() and loc.first.is_visible():
                    try:
                        loc.first.click(timeout=5000)
                    except Exception:
                        loc.first.evaluate("e => e.click()")
                    clicked = True
            except Exception as e:
                self.log("sign btn click failed: %s" % e)
        if not clicked:
            for t in ["立即签到", "今日签到", "点击签到"]:
                try:
                    loc = self.page.get_by_text(t, exact=False)
                    if loc.count() and loc.first.is_visible():
                        try:
                            loc.first.click(timeout=4000)
                        except Exception:
                            loc.first.evaluate("e => e.click()")
                        clicked = True
                        break
                except Exception:
                    continue
        if not clicked:
            r.update(stage="signin", error="没找到签到按钮，页面可能改版")
            self.shot("no-button")
            r["screenshot"] = self.shots[-1] if self.shots else None
            return

        self.page.wait_for_timeout(3500)
        self.close_dialog()
        self.page.wait_for_timeout(800)

        flat = self.text()
        signed = any(k in flat for k in SIGNED_HINTS)
        streak2 = self._streak()
        r["streak"] = streak2 if streak2 is not None else streak
        r["next_node"] = next_node(r["streak"])
        r.update(ok=bool(signed), stage="done", status="signed" if signed else "unconfirmed", signed=signed)
        if not signed:
            r["error"] = "点击后未检测到「今日已签」，请以截图为准"
        self.shot("after")
        r["screenshot"] = self.shots[-1] if self.shots else None

    def _streak(self):
        flat = self.text()
        m = (re.search(r"已连签\s*(\d+)\s*天", flat)
             or re.search(r"已签\s*(\d+)\s*天", flat))
        if m:
            try:
                return int(m.group(1))
            except ValueError:
                return None
        return None


def main(argv=None):
    ap = argparse.ArgumentParser(description="库库AI 每日签到（只签到版）")
    ap.add_argument("--cookies", default="", help="Cookie 文件路径；默认依次找 " + "、".join(DEFAULT_COOKIE_PATHS))
    ap.add_argument("--out", default="outputs", help="截图/日志目录（默认 outputs）")
    ap.add_argument("--log", default="", help="日志目录（默认 <out>/log）")
    ap.add_argument("--dry-run", action="store_true", help="只校验登录态，不点签到")
    ap.add_argument("--headful", action="store_true", help="显示浏览器窗口（排查用）")
    args = ap.parse_args(argv)

    out_dir = Path(args.out).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)
    log_dir = Path(args.log).expanduser() if args.log else out_dir / "log"
    log_dir.mkdir(parents=True, exist_ok=True)
    logfile = log_dir / ("kukuai_signin_%s.log" % datetime.now().strftime("%Y%m%d-%H%M%S"))

    def log(msg):
        try:
            with open(logfile, "a", encoding="utf-8") as f:
                f.write("[%s] %s\n" % (datetime.now(CN_TZ).isoformat(timespec="seconds"), msg))
        except Exception:
            pass

    log("start; out=%s; dry_run=%s" % (out_dir, args.dry_run))
    try:
        r = Session(args, log).run()
    except Exception as e:
        r = {"ok": False, "stage": "fatal", "status": None, "signed": None,
             "error": "%s: %s" % (type(e).__name__, e)}

    r["log"] = str(logfile)
    if r.get("next_node") is None and r.get("streak") is not None:
        r["next_node"] = next_node(r["streak"])
    print(json.dumps(r, ensure_ascii=False, indent=2))
    return 0 if r.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
