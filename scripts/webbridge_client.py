#!/usr/bin/env python3
"""
WebBridge HTTP 客户端 — 共享模块（Skill v5.6.6，2026-10-12）

所有 BOSS 脚本通过本模块与 Kimi WebBridge 通信。
提供薪资解密、当前页面岗位提取、弹窗处理及断点续传工具。

核心设计：
  - 从 profile_loader 加载统一 SESSION，复用同一标签页。
  - api() 对通信异常最多尝试 3 次；页面业务错误由调用方判断。
  - extract_jobs() 从当前 DOM 的 Vue 卡片数据提取岗位。
  - ProgressManager 按 jobId 去重，成功记录优先于失败记录。

  - 自动打招呼状态决定 success / blocked / unknown；历史无证据的 unknown
    迁移为 legacy_unknown，不事后推断为 blocked。
  - 一次加载或迁移计算并缓存 duplicate_removed，后续 stats() 只读取该值。

v5.6 改进：normalize() 完成去重、历史 unknown 迁移和状态审计；stats()
输出 success/blocked/fail/unknown/legacy_unknown 及行业口径。

用法：
    from scripts.webbridge_client import evaluate, extract_jobs, ProgressManager
    pm = ProgressManager("stream_progress.json").load()
    counts = pm.stats()
"""

import json
import http.client
import time
import re
import random
import os
import signal
import difflib
import glob
import sys
from datetime import datetime

# ═══════════════════════════════════════════════════════════
# 路径设置 + 用户配置（从 profile_loader 读取，禁止硬编码）
# ═══════════════════════════════════════════════════════════

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SKILL_DIR not in sys.path:
    sys.path.insert(0, SKILL_DIR)

from scripts.profile_loader import SESSION_NAME, USER_NAME

# ═══════════════════════════════════════════════════════════
# 常量
# ═══════════════════════════════════════════════════════════

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 10086

# ★ 全局唯一 SESSION — 从 user_profile.json 读取
#   禁止在各脚本中自定义 SESSION 名
SESSION = SESSION_NAME

DEFAULT_TIMEOUT = 60
MAX_RETRIES = 3
RETRY_DELAY = 3

# ═══════════════════════════════════════════════════════════
# Boss直聘薪资字体解密
# ═══════════════════════════════════════════════════════════

def decrypt_salary(text):
    """解密 Boss直聘薪资字体加密（U+E031~U+E03A → 数字 0~9）"""
    if not text:
        return ""
    result = []
    for ch in text:
        cp = ord(ch)
        if 0xE031 <= cp <= 0xE03A:
            result.append(str(cp - 0xE031))
        else:
            result.append(ch)
    return ''.join(result)


def parse_salary_max(s):
    """解析薪资字符串，返回最高薪资（K为单位）

    例: "12-20K" → 20, "5-7K·14薪" → 7, "4000-6000元/月" → 6
    """
    if not s:
        return 0
    s = re.sub(r'·\d+薪', '', s)
    m = re.search(r'(\d+)-(\d+)K', s)
    if m:
        return int(m.group(2))
    m = re.search(r'(\d+)-(\d+)元/月', s)
    if m:
        return int(m.group(2)) / 1000
    return 0


# ═══════════════════════════════════════════════════════════
# 模块级 API 函数（自带重试）
# ═══════════════════════════════════════════════════════════

def api(action, args=None, session=SESSION, host=DEFAULT_HOST, port=DEFAULT_PORT, timeout=DEFAULT_TIMEOUT):
    """发送 WebBridge API 请求，返回解析后的 dict。自带 MAX_RETRIES 次重试。"""
    if args is None:
        args = {}
    last_error = None
    for attempt in range(MAX_RETRIES):
        try:
            conn = http.client.HTTPConnection(host, port, timeout=timeout)
            body = json.dumps({"action": action, "args": args, "session": session}).encode("utf-8")
            conn.request("POST", "/command", body=body, headers={"Content-Type": "application/json"})
            resp = conn.getresponse()
            data = json.loads(resp.read().decode("utf-8"))
            conn.close()
            return data
        except Exception as e:
            last_error = e
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_DELAY)
    raise last_error


def evaluate(code, session=SESSION):
    """执行 JS 并返回字符串结果"""
    r = api("evaluate", {"code": code}, session=session)
    return r.get("data", {}).get("value", "")


def navigate(url, wait_range=(4, 6), session=SESSION):
    """导航到 URL 并等待 SPA 渲染"""
    r = api("navigate", {"url": url}, session=session)
    time.sleep(random.uniform(*wait_range))
    return r


# ★ v5.6.7 风控拦截检测（2026-10-13 实测）
#   高频读 JD / 投递会触发 BOSS 安全验证，页面被整页跳转到
#   https://www.zhipin.com/web/passport/zp/verify.html?...（标题「安全验证 - BOSS直聘」）。
#   此时 DOM 里一张岗位卡都没有，所有 step_read 都会报 no_link_match /
#   READ_FAILED——极易被误判成"虚拟滚动导致卡片不在 DOM"，进而反复重试、继续硬撞风控，
#   风险极高。必须在读/投之前先判定是否处于拦截页，命中立即停止并交回用户人工处理。
VERIFY_URL_MARKERS = (
    "/web/passport/zp/verify",
    "/web/passport/",
    "security-check",
    "verify.html",
)
VERIFY_TITLE_MARKERS = ("安全验证", "身份验证", "异常访问", "滑动验证")


def is_verification_page(session=SESSION):
    """判断当前是否处于 BOSS 安全验证/风控拦截页。

    返回:
        (bool, url, title): 命中拦截时 bool=True，并带回 URL 与标题供日志与汇报。
    """
    url = evaluate("window.location.href", session=session) or ""
    title = evaluate("document.title", session=session) or ""
    if any(m in url for m in VERIFY_URL_MARKERS):
        return True, url, title
    if any(m in title for m in VERIFY_TITLE_MARKERS):
        return True, url, title
    return False, url, title


def click(selector, session=SESSION):
    """通过 CSS 选择器点击元素"""
    return api("click", {"selector": selector}, session=session).get("data", {}).get("success", False)


def scroll_page(session=SESSION):
    """滚动到页面下方，触发懒加载。

    ★ v5.6.7 修复（2026-10-13）：原实现一次性 window.scrollTo(0, body.scrollHeight)
    跳到底部，BOSS 的懒加载（InfiniteScroll / 监听 scroll 触发加载哨兵）对「瞬时跳底」
    不敏感，导致页面始终只渲染首屏 ~15 张卡片、无法加载更多。改为「增量滚动」——
    每次向下滚动约一屏高度并派发 scroll 事件，使滚动位置逐级穿越加载触发区，
    懒加载才会逐批补充卡片。实测增量滚动 15→30→45 生效。
    """
    evaluate(r"""
    (function(){
      var step = Math.max(700, Math.floor(window.innerHeight * 0.8));
      var y = window.scrollY + step;
      window.scrollTo({top: y, behavior: 'auto'});
      window.dispatchEvent(new Event('scroll'));
      return window.scrollY;
    })()
    """, session=session)


# ═══════════════════════════════════════════════════════════
# Boss直聘 专用工具函数
# ═══════════════════════════════════════════════════════════

# ★ v5.6.7 卡片选择器统一（2026-10-13 根因修复）
#   BOSS 改版后列表卡片的真实容器是 <li class="job-card-box">，旧版硬编码的
#   .job-card-wrap 已失效。后果极严重：recommend_loader._count_cards() 恒返回 0
#   → 滚动后"无新增" → 连续 4 次即判定"穷尽" → 明明往下滚还有源源不断的岗位，
#   skill 却认为信息流枯竭（这正是 10-13 误判"频道耗尽"并越权换频道的根因）。
#   现统一为常量，extract_jobs / _count_cards / keyword_evolver 全部引用它，
#   并同时兼容新旧两种 class。
CARD_SELECTORS = ".job-card-box, .job-card-wrap"

_EXTRACT_JOBS_JS = r"""
(function(){
    var CARD_SEL = ".job-card-box, .job-card-wrap";
    var jobs = [];
    var seen = new Set();
    var mode = "vue";

    // ── 路径A：Vue $props.data（字段最全，薪资原文在，后续解密）──
    var cards = document.querySelectorAll(CARD_SEL);
    for (var i = 0; i < cards.length; i++) {
        try {
            var v = cards[i].__vue__;
            var d = v && v.$props && v.$props.data;
            if (!d || !d.encryptJobId) continue;
            var jid = d.encryptJobId;
            if (seen.has(jid)) continue;
            seen.add(jid);
            jobs.push({
                title: d.jobName || "",
                salary: d.salaryDesc || "",
                city: d.cityName || "",
                company: d.brandName || "",
                industry: d.brandIndustry || "",
                scale: d.brandScaleName || "",
                stage: d.brandStageName || "",
                online: !!d.bossOnline,
                welfare: (d.welfareList || []).join("|"),
                degree: d.jobDegree || "",
                experience: d.jobExperience || "",
                jobId: jid,
            });
        } catch(e) {}
    }

    // ── 路径B：DOM 兜底（改版后 li.job-card-box 无 __vue__，路径A 会返回 0）──
    //   ★ 实测证据：10-13 用同样的 DOM 抓取一次收到 330 张卡，证明可行。
    if (jobs.length === 0) {
        mode = "dom";
        var links = document.querySelectorAll('a[href*="job_detail"]');
        function txt(el, sels) {
            for (var s = 0; s < sels.length; s++) {
                var n = el.querySelector(sels[s]);
                if (n && (n.textContent || "").trim()) return (n.textContent || "").trim();
            }
            return "";
        }
        for (var k = 0; k < links.length; k++) {
            var href = links[k].getAttribute("href") || "";
            var m = href.match(/job_detail\/([^.?#]+)/);   // 去 .html 后缀
            if (!m) continue;
            var jid2 = m[1];
            if (seen.has(jid2)) continue;
            seen.add(jid2);
            var card = links[k].closest(CARD_SEL + ", li") || links[k];
            var loc = txt(card, [".company-location", ".job-location", ".location"]);
            var city = "";
            if (loc) {
                var parts = loc.split(/[·•|]/);
                city = (parts[0] || "").trim();
                if (city.length > 6) city = "";      // 异常长文本不是城市名
            }
            var sal = txt(card, [".job-salary", ".salary", "[class*='salary']"]);
            jobs.push({
                title: txt(card, [".job-name", ".job-title", "h3", "h4"]),
                salary: sal,
                city: city,
                company: txt(card, [".company-name", ".name", ".brand-name"]),
                industry: "",
                scale: "",
                stage: "",
                online: false,
                welfare: "",
                degree: "",
                experience: "",
                jobId: jid2,
            });
        }
    }

    return JSON.stringify({total: jobs.length, list: jobs, mode: mode});
})()
"""


def extract_jobs(session=SESSION):
    """从当前页面提取所有岗位卡片（Vue 优先，DOM 兜底）。薪资已解密。

    ★ v5.6.7：路径A 取不到（改版无 __vue__）时自动走 DOM 兜底，并在终端打印
      [提取] mode=dom —— 出现 dom 即说明 Vue 通道失效，属正常降级不是故障。
    """
    raw = evaluate(_EXTRACT_JOBS_JS, session=session)
    try:
        data = json.loads(raw) if raw else {}
        jobs = data.get("list", [])
        print(f"[提取] 卡片 {len(jobs)} 条 (mode={data.get('mode', '?')}, 选择器={CARD_SELECTORS})")
        for j in jobs:
            j['salary'] = decrypt_salary(j.get('salary', ''))
        return jobs
    except (json.JSONDecodeError, TypeError):
        return []


_POPUP_SELECTORS = [
    '.btn-sure',
    '.dialog-container .btn',
    '.greet-pop .btn',
    '.dialog-confirm', '.layer-btn-confirm', '.btn-confirm',
    '.dialog-ok', '.modal-confirm', '.layui-layer-btn0',
]


def handle_popup(session=SESSION):
    """检测并处理弹窗（特别是第120份时的"好"弹窗）"""
    time.sleep(1.5)

    result = evaluate("""
    (function(){
        var prioritySelectors = %s;
        for (var j = 0; j < prioritySelectors.length; j++) {
            var btn = document.querySelector(prioritySelectors[j]);
            if (btn) {
                var rect = btn.getBoundingClientRect();
                var style = window.getComputedStyle(btn);
                if (rect.width > 0 && rect.height > 0 && style.display !== 'none') {
                    btn.click();
                    return 'clicked: ' + prioritySelectors[j];
                }
            }
        }
        var btns = document.querySelectorAll('button, a');
        for (var i = 0; i < btns.length; i++) {
            var el = btns[i];
            var text = (el.textContent || '').trim();
            if (text === '好' || text === '确定' || text === '我知道了' || text === '继续沟通') {
                var rect = el.getBoundingClientRect();
                if (rect.width > 0 && rect.height > 0) {
                    el.click();
                    return 'clicked: ' + text + ' (' + el.tagName + '.' + el.className + ')';
                }
            }
        }
        return 'no_popup';
    })()
    """ % json.dumps(_POPUP_SELECTORS), session=session)

    if result and result != 'no_popup':
        time.sleep(1)
        still_visible = evaluate("""
        (function(){
            var dialog = document.querySelector('.dialog-wrap.greet-pop, .dialog-container');
            if (!dialog) return false;
            var rect = dialog.getBoundingClientRect();
            var style = window.getComputedStyle(dialog);
            return (rect.width > 0 && rect.height > 0 && style.display !== 'none');
        })()
        """, session=session)
        if still_visible == 'true':
            evaluate("""
            (function(){
                var btn = document.querySelector('.btn-sure');
                if (btn) {
                    var rect = btn.getBoundingClientRect();
                    var x = rect.left + rect.width / 2;
                    var y = rect.top + rect.height / 2;
                    ['mousedown', 'mouseup', 'click'].forEach(function(type) {
                        var evt = new MouseEvent(type, {
                            bubbles: true, cancelable: true, view: window,
                            clientX: x, clientY: y
                        });
                        btn.dispatchEvent(evt);
                    });
                    return 'mouse_event_clicked';
                }
                return 'no_btn_sure';
            })()
            """, session=session)
            time.sleep(1)
            return result + ' + retry_mouse'

    return result


# ═══════════════════════════════════════════════════════════
# 进度管理（断点续传）
# ═══════════════════════════════════════════════════════════

class ProgressManager:
    """投递进度管理器 — 支持断点续传、自动打招呼分类和去重统计。

    用法:
        pm = ProgressManager()
        pm.load()
        if pm.is_done(job_id):
            continue
        pm.add_delivered(job_id, job, run_id=run_id, evidence=evidence)
        pm.save()
    """

    SUCCESS_RANK = {
        "success": 5,
        "blocked": 4,
        "fail": 3,
        "unknown": 2,
        "legacy_unknown": 1,
    }
    TERMINAL_FAIL = ("fatal_limit", "login_expired", "skip")

    def __init__(self, filepath="stream_progress.json"):
        self.filepath = filepath
        self.data = {"delivered": [], "failed": []}
        self._normalized = False

    def load(self):
        if os.path.exists(self.filepath):
            with open(self.filepath, "r", encoding="utf-8") as f:
                self.data = json.load(f)
        self.normalize()
        return self

    def _now(self):
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def _copy_item(self, item):
        if isinstance(item, dict):
            return json.loads(json.dumps(item, ensure_ascii=False))
        return {}

    def _evidence_of(self, item):
        if not isinstance(item, dict):
            return {}
        evidence = item.get("evidence")
        if isinstance(evidence, dict):
            return evidence
        return {}

    def _has_greeting_evidence(self, item):
        evidence = self._evidence_of(item)
        keys = (
            "auto_greeting_state",
            "greeting_triggered",
            "greeting_sent",
            "chat_relation",
            "message_visible",
            "delivery_page",
            "company_match",
            "missing_evidence",
        )
        if any(k in evidence for k in keys):
            return True
        if any(k in item for k in keys):
            return True
        reason = str(item.get("reason") or "")
        return "auto_greeting_state" in reason or "自动打招呼" in reason

    def classify_status(self, item):
        """将记录归入 success/blocked/fail/unknown/legacy_unknown。"""
        if not isinstance(item, dict):
            return "fail"
        explicit = item.get("result") or item.get("status") or ""
        reason = str(item.get("reason") or "")
        if explicit in self.TERMINAL_FAIL:
            return "fail"
        if explicit in self.SUCCESS_RANK:
            status = explicit
        else:
            status = None
            for candidate in ("blocked", "unknown", "legacy_unknown", "fail", "success"):
                if reason.startswith(candidate + ":"):
                    status = candidate
                    break
            if status is None:
                status = "fail"
        if status == "unknown" and not self._has_greeting_evidence(item):
            return "legacy_unknown"
        return status

    def _prefer_item(self, old, new):
        old = old or {}
        new = new or {}
        old_status = self.classify_status(old)
        new_status = self.classify_status(new)
        if self.SUCCESS_RANK.get(new_status, 0) > self.SUCCESS_RANK.get(old_status, 0):
            chosen = self._copy_item(new)
        elif self.SUCCESS_RANK.get(new_status, 0) < self.SUCCESS_RANK.get(old_status, 0):
            chosen = self._copy_item(old)
        else:
            chosen = self._copy_item(new)
        previous = old.get("result") or old.get("status")
        current = chosen.get("result") or chosen.get("status") or new_status
        if previous and previous != current:
            chosen["previous_status"] = previous
        chosen.setdefault("updated_at", self._now())
        if old.get("evidence") and not chosen.get("evidence"):
            chosen["evidence"] = self._copy_item(old.get("evidence"))
        return chosen

    def _finalize_item(self, item):
        item = self._copy_item(item)
        status = self.classify_status(item)
        item["result"] = status
        item["status"] = status
        item.setdefault("updated_at", self._now())
        if status in ("blocked", "fail", "unknown", "legacy_unknown") and not item.get("reason"):
            item["reason"] = status
        return item

    def normalize(self, persist_duplicates=True):
        """按 jobId 去重；成功优先；历史无证据 unknown 迁为 legacy_unknown。"""
        raw_delivered = list(self.data.get("delivered", []) or [])
        raw_failed = list(self.data.get("failed", []) or [])
        merged = {}
        for item in raw_delivered + raw_failed:
            jid = (item or {}).get("jobId")
            if not jid:
                continue
            if jid in merged:
                merged[jid] = self._prefer_item(merged[jid], item)
            else:
                merged[jid] = self._copy_item(item)

        delivered = []
        failed = []
        for item in merged.values():
            item = self._finalize_item(item)
            if item["result"] == "success":
                delivered.append(item)
            else:
                failed.append(item)

        computed = max(0, len(raw_delivered) + len(raw_failed) - len(delivered) - len(failed))
        cached = self.data.get("duplicate_removed")
        if persist_duplicates and isinstance(cached, int) and cached >= computed:
            duplicate_removed = cached
        else:
            duplicate_removed = computed

        self.data["delivered"] = delivered
        self.data["failed"] = failed
        self.data["duplicate_removed"] = duplicate_removed
        self.data["_duplicate_removed"] = duplicate_removed
        self._normalized = True
        return self.data

    def stats(self):
        """返回唯一岗位的最终状态统计；报表和终端必须复用此口径。"""
        if not self._normalized:
            self.normalize()
        delivered = self.data.get("delivered", []) or []
        failed = self.data.get("failed", []) or []
        failed_statuses = [self.classify_status(j) for j in failed]
        groups = {j.get("industry") for j in delivered if j.get("industry")}
        return {
            "unique_total": len(delivered) + len(failed),
            "delivered": len(delivered),
            "success_total": len(delivered),
            "failed": len(failed),
            "fail_total": failed_statuses.count("fail"),
            "unknown_total": failed_statuses.count("unknown"),
            "blocked_total": failed_statuses.count("blocked"),
            "legacy_unknown_total": failed_statuses.count("legacy_unknown"),
            "unknown": failed_statuses.count("unknown"),
            "blocked": failed_statuses.count("blocked"),
            "duplicate_removed": self.data.get("duplicate_removed", self.data.get("_duplicate_removed", 0)),
            "industry_count": len(groups),
            "empty_industry_count": sum(1 for j in delivered if not j.get("industry")),
        }

    def save(self):
        if not self._normalized:
            self.normalize()
        with open(self.filepath, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)

    @property
    def delivered_ids(self):
        return set(j["jobId"] for j in self.data.get("delivered", []) if j.get("jobId"))

    @property
    def failed_ids(self):
        return set(j["jobId"] for j in self.data.get("failed", []) if j.get("jobId"))

    @property
    def all_done_ids(self):
        return self.delivered_ids | self.failed_ids

    def is_done(self, job_id):
        return job_id in self.all_done_ids

    def _remove_job(self, key, job_id):
        self.data[key] = [x for x in self.data.get(key, []) if x.get("jobId") != job_id]

    def _bump_duplicate(self):
        current = self.data.get("duplicate_removed", self.data.get("_duplicate_removed", 0)) or 0
        self.data["duplicate_removed"] = current + 1
        self.data["_duplicate_removed"] = self.data["duplicate_removed"]

    def _base_record(self, job_id, job, status, run_id=None, evidence=None, reason=None):
        job = job or {}
        record = {
            "jobId": job_id,
            "title": job.get("title", ""),
            "company": job.get("company", ""),
            "salary": job.get("salary", ""),
            "industry": job.get("industry", ""),
            "result": status,
            "status": status,
            "updated_at": self._now(),
        }
        if run_id:
            record["run_id"] = run_id
        if evidence:
            record["evidence"] = self._copy_item(evidence)
        if reason:
            record["reason"] = reason
        return record

    def add_delivered(self, job_id, job, run_id=None, evidence=None):
        existing = None
        for key in ("delivered", "failed"):
            for item in self.data.get(key, []) or []:
                if item.get("jobId") == job_id:
                    existing = item
                    break
        record = self._base_record(job_id, job, "success", run_id=run_id, evidence=evidence)
        if existing:
            self._bump_duplicate()
            previous = existing.get("result") or existing.get("status")
            if previous and previous != "success":
                record["previous_status"] = previous
            if existing.get("evidence") and not record.get("evidence"):
                record["evidence"] = self._copy_item(existing.get("evidence"))
        self._remove_job("failed", job_id)
        self._remove_job("delivered", job_id)
        self.data.setdefault("delivered", []).append(record)
        self._normalized = False

    def add_failed(self, job_id, job, reason, run_id=None, evidence=None, status=None):
        if job_id in self.delivered_ids:
            return
        if status is None:
            status = reason.split(":", 1)[0] if ":" in str(reason) else "fail"
        if status in self.TERMINAL_FAIL:
            status = "fail"
        if status not in self.SUCCESS_RANK:
            status = "fail"
        record = self._base_record(job_id, job, status, run_id=run_id, evidence=evidence, reason=reason)
        existing = None
        for item in self.data.get("failed", []) or []:
            if item.get("jobId") == job_id:
                existing = item
                break
        if existing:
            self._bump_duplicate()
            previous = existing.get("result") or existing.get("status")
            if previous and previous != status:
                record["previous_status"] = previous
            if existing.get("evidence") and not record.get("evidence"):
                record["evidence"] = self._copy_item(existing.get("evidence"))
        self._remove_job("failed", job_id)
        self.data.setdefault("failed", []).append(record)
        self._normalized = False

    @property
    def delivered_count(self):
        return len(self.data.get("delivered", []))

    @property
    def failed_count(self):
        return len(self.data.get("failed", []))


# ═══════════════════════════════════════════════════════════
# 健康检查与 Daemon 管理
# ═══════════════════════════════════════════════════════════

def health_check(host=DEFAULT_HOST, port=DEFAULT_PORT):
    """快速检查 WebBridge daemon 是否可达（探测真实的 /command 端点）。

    ★ 旧实现向 GET / 探活，仅认 200/404；但当前 daemon 版本对 / 返回 502，
      而真正的控制端点 POST /command 正常（list_tabs 返回 ok:true），导致误报'不可达'。
      改为直接探测 /command，准确反映 daemon 可用性，且不破坏旧 daemon（/ 返回 200）场景。
    """
    try:
        conn = http.client.HTTPConnection(host, port, timeout=5)
        body = json.dumps({"action": "list_tabs", "args": {}, "session": SESSION}).encode("utf-8")
        conn.request("POST", "/command", body=body, headers={"Content-Type": "application/json"})
        data = json.loads(conn.getresponse().read().decode("utf-8"))
        conn.close()
        return bool(data.get("ok"))
    except Exception:
        return False


def ensure_active_tab(session=SESSION, timeout_wait=10):
    """确保 session 有活跃标签页

    WebBridge active 标志不可靠（navigate 后仍为 False），
    改为：有标签页就尝试 evaluate，失败才 navigate。
    """
    try:
        if not health_check():
            return False

        # 有标签页时直接尝试 evaluate
        r = api("list_tabs", {}, session=session, timeout=5)
        if r.get("ok"):
            tabs_data = r.get("data", {})
            tabs = tabs_data.get("tabs", []) if isinstance(tabs_data, dict) else tabs_data
            if tabs:
                if str(evaluate("1+1", session=session)) == "2":
                    return True

        # 无标签页或不可交互，导航创建
        nav_r = navigate("https://www.zhipin.com", wait_range=(timeout_wait, timeout_wait + 2), session=session)
        if not nav_r.get("ok"):
            return False
        return str(evaluate("1+1", session=session)) == "2"
    except Exception:
        return False


def clean_pid_files():
    """清理 WebBridge PID 残留文件"""
    pid_patterns = [
        os.path.expanduser("~/.kimi-webbridge/daemon.pid"),
        os.path.expanduser("~/.kimi-webbridge*.pid"),
        # (removed: trae-cn pattern, not applicable in Marvis)
    ]
    cleaned = []
    for pattern in pid_patterns:
        for f in glob.glob(pattern):
            if os.path.exists(f):
                try:
                    os.remove(f)
                    cleaned.append(f)
                except Exception:
                    pass
    return cleaned


# ═══════════════════════════════════════════════════════════
# 信号安全中断
# ═══════════════════════════════════════════════════════════

class SafeInterrupt(BaseException):
    pass


def _signal_handler(signum, frame):
    raise SafeInterrupt(f"Received signal {signum}")


def register_signal_guard():
    signal.signal(signal.SIGTERM, _signal_handler)


# ═══════════════════════════════════════════════════════════
# WebBridge 类
# ═══════════════════════════════════════════════════════════

class WebBridge:
    """Kimi WebBridge 通信封装

    用法:
        wb = WebBridge()
        wb.navigate(url)
        jobs = wb.extract_jobs()
    """

    def __init__(self, host=DEFAULT_HOST, port=DEFAULT_PORT, session=SESSION, timeout=DEFAULT_TIMEOUT):
        self.host = host
        self.port = port
        self.session = session
        self.timeout = timeout

    def api(self, action, args=None, timeout=None):
        return api(action, args, self.session, self.host, self.port, timeout or self.timeout)

    def evaluate(self, code):
        return evaluate(code, self.session)

    def navigate(self, url, wait_range=(4, 6)):
        return navigate(url, wait_range, self.session)

    def click(self, selector):
        return click(selector, self.session)

    def scroll_page(self):
        return scroll_page(self.session)

    def snapshot(self):
        return self.api("snapshot", {})

    def screenshot(self, path):
        return self.api("screenshot", {"path": path})

    def list_tabs(self):
        r = self.api("list_tabs", {})
        data = r.get("data", r)
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return data.get("tabs", data.get("data", []))
        return []

    def close_tab(self, tab_id):
        return self.api("close_tab", {"tabId": tab_id})

    def extract_jobs(self):
        return extract_jobs(self.session)

    def handle_popup(self):
        return handle_popup(self.session)

    def ensure_active_tab(self, timeout_wait=10):
        return ensure_active_tab(self.session, timeout_wait)

    def verify_login(self, username=None):
        if username is None:
            username = USER_NAME
        body = self.evaluate("document.body.innerText") or "" 
        if username in body:
            return True
        time.sleep(5)
        body = self.evaluate("document.body.innerText") or ""
        return username in body

    def body_with_retry(self):
        body = self.evaluate("document.body.innerText") or ""
        if len(body) < 200:
            time.sleep(5)
            body = self.evaluate("document.body.innerText") or ""
        return body

    def find_chat_button_ref(self):
        snap = self.snapshot()
        tree_str = json.dumps(snap, ensure_ascii=False)
        for p in [
            r"'name':\s*'立即沟通'.*?'ref':\s*'(@e\d+)'",
            r"'ref':\s*'(@e\d+)'.*?'name':\s*'立即沟通'",
            r'"name":\s*"立即沟通".*?"ref":\s*"(@e\d+)"',
            r'"ref":\s*"(@e\d+)".*?"name":\s*"立即沟通"',
        ]:
            m = re.search(p, tree_str)
            if m:
                return m.group(1)
        return None


# ═══════════════════════════════════════════════════════════
# 版本信息
# ═══════════════════════════════════════════════════════════

__version__ = "3.0.0"
__updated__ = "2026-07-26"
__changes__ = """
v3.0.0 (2026-07-26):
  - 全局唯一 SESSION="boss-main"，禁止各脚本自定义 session 名
  - 新增 extract_jobs(): Vue $props.data 统一提取
  - 新增 handle_popup(): 弹窗处理（含第120份投递"好"弹窗）
  - 新增 scroll_page(): 滚动加载
  - 新增 parse_salary_max(): 薪资解析
  - 新增 ProgressManager: 断点续传进度管理类
  - 新增 clean_pid_files(): PID 残留清理
  - api() 自带 3 次重试
  - 所有函数默认使用全局 SESSION
"""
