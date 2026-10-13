#!/usr/bin/env python3
"""
模块 I+ 辅助：离线优先构建 jd_to_read.json（v5.6.6 新增）

用途：从「当前浏览器页面卡片」取 jobId（实时 DOM），关联 surface_cache 取城市/公司等字段，
      仅保留目标四城候选，写出 jd_to_read.json，交给 batch_deliver.py 自动筛投。
职责范围：替代人工逐条初筛 + 实时 DOM 抓城市。修正 v5.6.5 实测暴露的 jid 含 .html 后缀导致与
      surface_cache 失配、全量跨城跳过的问题（去除 .html 后从 surface_cache 取城市）；
      跨城候选不进入 jd_to_read，避免占用浏览器读卡时间。
关联模块：batch_deliver.py(I+) / surface_cache.py(D) / webbridge_client.py / serial_loop.py(I) / profile_loader.py
维护状态：v5.6.6 新增

用法（守护进程在线、浏览器停在目标频道页时）：
    python scripts/build_jd.py            # 全新写出（覆盖旧 jd_to_read.json）
    python scripts/build_jd.py --append   # 追加模式：与现有 jd_to_read.json 按 jobId 合并（多次 next-batch 扩量用）
目标城市由 BOSS_PROFILE 决定（默认 integration: 深圳/广州/上海/杭州）。

★ v5.6.6 新增 --append：单频道 feed 候选有限（K6），单批直接喂加速器难达 150 目标。
  改为「多次 next-batch（每次滚动加载一批）→ 每次 --append 累积」把候选池做大，
  再一次性 batch_deliver 推进，逼近日目标。
"""

import json
import os
import sys
import argparse
import urllib.request
import urllib.error

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SKILL_DIR)
from scripts.profile_loader import TARGET_CITIES

WORK_DIR = os.environ.get("BOSS_WORK_DIR", os.getcwd())
HOST, PORT, SESSION = "127.0.0.1", 10086, "boss-main"

JS = r"""
(function(){
  var links = document.querySelectorAll('a[href*="job_detail"]');
  var seen = {}, out = [];
  for (var i = 0; i < links.length; i++) {
    var href = links[i].getAttribute('href') || '';
    var m = href.match(/job_detail\/([^.?#]+)/);   // 去掉 .html 后缀，匹配 surface_cache jobId
    if (!m) continue;
    var jid = m[1];
    if (seen[jid]) continue;
    seen[jid] = 1;
    var card = links[i].closest('.job-card-box, .job-card-wrap, li');
    var title = '', city = '', company = '', salary = '';
    if (card) {
      var t = card.querySelector('.job-name,.job-title,h3,h4,[class*="title"]');
      if (t) title = t.textContent.trim();
      var c = card.querySelector('.company-location,.job-location,.location');
      if (c) {
        var parts = c.textContent.split(/[·•|]/);
        city = (parts[0] || '').trim();
        if (city.length > 6) city = '';
      }
      var cn = card.querySelector('.company-name,.name,.brand-name');
      if (cn) company = cn.textContent.trim();
      var s = card.querySelector('.job-salary,.salary,[class*="salary"]');
      if (s) salary = s.textContent.trim();
    }
    out.push({jid: jid, title: title, city: city, company: company, salary: salary});
  }
  return JSON.stringify(out);
})()
"""


def daemon_eval(code):
    body = json.dumps({"action": "evaluate", "args": {"code": code}, "session": SESSION}).encode("utf-8")
    req = urllib.request.Request(
        "http://%s:%d/command" % (HOST, PORT), data=body, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read().decode("utf-8")).get("data", {}).get("value", "")
    except Exception:
        return ""


def main():
    ap = argparse.ArgumentParser(description="离线优先构建 jd_to_read.json（v5.6.6）")
    ap.add_argument("--append", action="store_true", help="追加模式：与现有 jd_to_read.json 按 jobId 合并，不覆盖")
    a = ap.parse_args()

    cards_raw = daemon_eval(JS)
    try:
        cards = json.loads(cards_raw)
    except Exception:
        print("ERROR: 当前页面卡片抓取失败（守护进程是否在线？）:", cards_raw[:120])
        sys.exit(1)

    # ★ v5.6.7：surface_cache.json 可能尚未生成（刷新后直接构建候选），缺失时降级为空
    #   而不是崩溃——城市等字段改由实时 DOM 提供（见下方 city 兜底逻辑）。
    sc_path = os.path.join(WORK_DIR, "surface_cache.json")
    sc = []
    if os.path.exists(sc_path):
        try:
            sc = json.load(open(sc_path, encoding="utf-8"))
        except (json.JSONDecodeError, IOError):
            sc = []
    sc_by = {c.get("jobId"): c for c in sc if c.get("jobId")}

    delivered = set()
    sp = os.path.join(WORK_DIR, "stream_progress.json")
    if os.path.exists(sp):
        try:
            s = json.load(open(sp, encoding="utf-8"))
            for key in ("delivered", "failed"):
                for rec in (s.get(key) or []):
                    if rec.get("jobId"):
                        delivered.add(rec["jobId"])
        except Exception:
            pass

    # 追加模式：载入已有 jd_to_read.json，按 jobId 去重合并
    existing = {}
    jd_path = os.path.join(WORK_DIR, "jd_to_read.json")
    if a.append and os.path.exists(jd_path):
        try:
            for rec in json.load(open(jd_path, encoding="utf-8")):
                if rec.get("jobId"):
                    existing[rec["jobId"]] = rec
        except Exception:
            pass

    kept, skipped_city, skipped_delivered, skipped_dup = [], 0, 0, 0
    for c in cards:
        jid = c["jid"]
        if jid in existing:
            skipped_dup += 1
            continue
        meta = sc_by.get(jid, {})
        # ★ v5.6.7：城市来源优先级 = surface_cache → 实时 DOM。
        #   刷新补量拿到的新岗位常常还没进 surface_cache，旧版会因为取不到 city
        #   而把所有新货当成"跨城"跳过（刷新白刷）。现从 DOM 兜底；仍取不到则
        #   标记为未知并保留，交由后续 read/decide 判断，绝不静默丢弃。
        city = meta.get("city") or c.get("city") or ""
        if jid in delivered:
            skipped_delivered += 1
            continue
        if city and city not in TARGET_CITIES:
            skipped_city += 1
            print(f"  跨城跳过({city}): {c.get('title','')[:22]}")
            continue
        # ★ 字段优先级：surface_cache（Vue 通道，薪资已解密）> 实时 DOM。
        #   BOSS 对薪资做了字体反爬，DOM 原文是乱码字形（实测输出 "-元/天"），
        #   直接用 DOM 会把乱码写进候选池；Vue 的 salaryDesc 经 decrypt_salary 才可读。
        kept.append({
            "page_order": len(kept),
            "jobId": jid,
            "title": meta.get("title") or c.get("title") or "",
            "company": meta.get("company") or c.get("company") or "",
            "city": city or "未知",
            "salary": meta.get("salary") or c.get("salary") or "",
            "industry": meta.get("industry", ""),
        })

    # 合并已有 + 本轮新候选，重新排 page_order
    merged = list(existing.values()) + kept
    for idx, rec in enumerate(merged, 1):
        rec["page_order"] = idx

    json.dump(
        merged,
        open(jd_path, "w", encoding="utf-8"),
        ensure_ascii=False,
        indent=2,
    )
    mode = "追加" if a.append else "全新"
    print(f"\njd_to_read.json 已{mode}写出: 累计 {len(merged)} 条（目标四城）；"
          f"本轮新 {len(kept)}，跨城跳过 {skipped_city}，已投跳过 {skipped_delivered}，去重 {skipped_dup}")
    for k in kept:
        print(f"  - {k['title'][:26]:<28} {k['city']} | {k['company'][:16]}")


if __name__ == "__main__":
    main()
