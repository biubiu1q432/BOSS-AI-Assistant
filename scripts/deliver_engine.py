#!/usr/bin/env python3
"""
模块 F：页面内投递执行引擎（Skill v5.6.6，2026-10-12）

职责：定位当前岗位卡片、点击沟通、检查致命提示、处理弹窗并返回结果。
接口：deliver_inplace(job_id, job_info) 返回 (status, detail, evidence)。

v5.6 改进：点进沟通界面即视为投递成功。自动打招呼关闭仍记 blocked；
不要求公司名匹配或首条消息文本。legacy_unknown 仅用于历史迁移。

v5.6.1 修复①：状态判定失效（最高优先级）。根因是「留在此页」弹窗被点掉后
_chat_evidence 已读不到该按钮，导致 stay_btn=false、classify 误判 unknown。
现改为：把过程标志 stayed_on_page 并入证据 stay_btn；新增 _wait_delivery_outcome
轮询等待聊天页跳转 / 弹窗延迟出现；_chat_evidence 新增会话列表核验
chat_list_match（目标公司 + 送达/您好证据），作为权威成功信号。

用法：
    from scripts.deliver_engine import deliver_inplace, check_delivery_target
"""

import json
import time
import random
import sys
import os

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SKILL_DIR)

from scripts.profile_loader import WORK_DIR, DAILY_TARGET, CITY_CODE

from scripts.webbridge_client import (
    SESSION, evaluate, click, navigate, handle_popup,
    ensure_active_tab, health_check,
    ProgressManager, register_signal_guard, SafeInterrupt,
)
from scripts.jd_reader import click_card_inplace

# ═══════════════════════════════════════════════════════════
# ★ v5.0 投递目标常量 — 从 user_profile.json 读取 (profile_loader 导入)
# ═══════════════════════════════════════════════════════════


# ═══════════════════════════════════════════════════════════
# 页面反馈检测常量 (从 v2 迁移)
# ═══════════════════════════════════════════════════════════

FATAL_PATTERNS = [
    "今日沟通次数已达上限",
    "今日沟通已达上限",
    "今日已达上限",
    "沟通次数已达上限",
    "今日投递已达上限",
    "每天最多沟通",
    "今日沟通额度已用完",
    "达到沟通上限",
    "沟通上限",
    "您今天已与",
    "休息一下，明天再来",
    "已达今日沟通上限",
]

LOGIN_PATTERNS = [
    "请先登录",
    "登录已过期",
    "扫码登录",
    "BOSS直聘登录",
    "安全验证",
]

SKIP_PATTERNS = [
    "已经沟通过",
    "已沟通过该职位",
    "职位已关闭",
    "职位不存在",
    "职位已下线",
    "该职位已失效",
]

MAX_CONSECUTIVE_UNKNOWN = 3


# ═══════════════════════════════════════════════════════════
# ★ v5.0 投递目标检查 — 流程图"总投递数量是否满足要求"节点
# ═══════════════════════════════════════════════════════════

def check_delivery_target(progress_file=None):
    """★ 流程图节点: 总投递数量是否满足要求

    读取投递进度文件，判断成功投递总数是否达到 DAILY_TARGET。

    参数:
        progress_file: 进度文件路径（默认使用工作目录下的 stream_progress.json）

    返回:
        dict: {
            "target_met": bool,       # 是否达标
            "delivered_count": int,   # 已投递成功数
            "target": int,            # 目标数
            "remaining": int,         # 还差多少
        }
    """
    if progress_file is None:
        progress_file = os.path.join(WORK_DIR, "stream_progress.json")

    pm = ProgressManager(progress_file)
    pm.load()

    delivered_count = getattr(pm, 'delivered_count', 0) or len(getattr(pm, 'delivered', []))
    target_met = delivered_count >= DAILY_TARGET
    remaining = max(0, DAILY_TARGET - delivered_count)

    result = {
        "target_met": target_met,
        "delivered_count": delivered_count,
        "target": DAILY_TARGET,
        "remaining": remaining,
    }

    print(f"[目标] 已投递 {delivered_count}/{DAILY_TARGET}" + 
          (f" ★ 已达标！" if target_met else f" (还差 {remaining})"))

    return result


# ═══════════════════════════════════════════════════════════
# 弹窗处理
# ═══════════════════════════════════════════════════════════

def handle_greet_popup():
    """处理打招呼弹窗，点击"发送"按钮完成投递

    BOSS直聘点击"立即沟通"后原地弹出打招呼确认框，
    需要点击"发送"按钮发送招呼语。

    返回:
        'sent:xxx' | 'no_popup'
    """
    popup_result = evaluate("""
    (function(){
        var dialogSelectors = '.dialog-wrap, .greet-pop, .dialog-container, .layer-dialog, .modal, .ant-modal-wrap, .layer-ext';
        var dialogs = document.querySelectorAll(dialogSelectors);
        for (var i = 0; i < dialogs.length; i++) {
            var d = dialogs[i];
            var rect = d.getBoundingClientRect();
            var style = window.getComputedStyle(d);
            if (rect.width > 0 && rect.height > 0 && style.display !== 'none') {
                var btns = d.querySelectorAll('a, button, .btn, .dialog-btn, span.btn');
                for (var j = 0; j < btns.length; j++) {
                    var text = btns[j].textContent.trim();
                    if (text === '发送' || text === '发送招呼' || text === '发送消息') {
                        btns[j].click();
                        return 'sent:' + text;
                    }
                }
            }
        }

        var allBtns = document.querySelectorAll('a, button, .btn, .dialog-btn, .btn-sure, .layer-btn-confirm');
        for (var k = 0; k < allBtns.length; k++) {
            var el = allBtns[k];
            var text = el.textContent.trim();
            if (text === '发送' || text === '发送招呼' || text === '发送消息') {
                var rect = el.getBoundingClientRect();
                var style = window.getComputedStyle(el);
                if (rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden') {
                    el.click();
                    return 'sent:fallback_' + text;
                }
            }
        }

        return 'no_popup';
    })()
    """)
    return popup_result if popup_result else 'no_popup'


def click_stay_on_page():
    """点击"留在此页"按钮

    投递成功后 BOSS 原地弹出确认弹窗，含"留在此页"和"继续沟通"两个按钮。
    必须点"留在此页"（留在当前页面），绝不点"继续沟通"（会跳转聊天页）。

    返回:
        'clicked:留在此页' | 'not_found'
    """
    result = evaluate("""
    (function(){
        var btns = document.querySelectorAll('button, a');
        for (var i = 0; i < btns.length; i++) {
            var el = btns[i];
            var text = (el.textContent || '').trim();
            if (text === '留在此页') {
                var rect = el.getBoundingClientRect();
                var style = window.getComputedStyle(el);
                if (rect.width > 0 && rect.height > 0 && style.display !== 'none') {
                    el.click();
                    return 'clicked:留在此页';
                }
            }
        }
        return 'not_found';
    })()
    """)
    return result or 'not_found'


# ═══════════════════════════════════════════════════════════
# 状态检测辅助函数
# ═══════════════════════════════════════════════════════════

def _check_fatal_patterns():
    """检测页面是否有致命错误/登录过期/跳过模式

    返回:
        (status, detail): 匹配到模式时返回对应 status，无匹配返回 (None, '')
    """
    page_text = evaluate("""
    (function(){
        var texts = [];
        texts.push(document.body.innerText || '');
        var dialogs = document.querySelectorAll(
            '.dialog-wrap, .dialog-container, .greet-pop, .layer-dialog, ' +
            '.modal, .toast, .message, .ant-message, .ant-modal, ' +
            '.dialog-body, .dialog-content, .pop-content, .tips-content'
        );
        for (var i = 0; i < dialogs.length; i++) {
            var d = dialogs[i];
            var rect = d.getBoundingClientRect();
            var style = window.getComputedStyle(d);
            if (rect.width > 0 && rect.height > 0 && style.display !== 'none') {
                texts.push(d.innerText || '');
            }
        }
        return texts.join('\\n').substring(0, 3000);
    })()
    """) or ""

    current_url = evaluate("window.location.href") or ""
    if "login" in current_url or "passport" in current_url:
        return 'login_expired', f"页面跳转登录: {current_url[:80]}"

    for pattern in FATAL_PATTERNS:
        if pattern in page_text:
            return 'fatal_limit', f"触发每日上限: {pattern}"

    for pattern in LOGIN_PATTERNS:
        if pattern in page_text:
            return 'login_expired', f"登录过期: {pattern}"

    for pattern in SKIP_PATTERNS:
        if pattern in page_text:
            return 'skip', f"跳过: {pattern}"

    return None, ''


def _chat_evidence(job_info=None):
    """读取投递后的可观察证据。

    成功判定：已经进入沟通界面（聊天页 URL 或可见聊天容器）。
    自动打招呼关闭仍记 blocked；公司名和首条消息不是成功前提。
    """
    job_info = job_info or {}
    company = job_info.get("company", "") or ""
    title = job_info.get("title", "") or ""
    boss = job_info.get("boss_name", "") or job_info.get("recruiter", "") or ""
    payload = json.dumps({
        "company": company,
        "title": title,
        "boss": boss,
    }, ensure_ascii=False)
    script = r'''
    (function(){
      var target = %s;
      var company = target.company || '';
      var title = target.title || '';
      var boss = target.boss || '';
      var url = window.location.href || '';
      var chatSelectors = [
        '.chat-conversation', '.conversation', '.chat-content', '.message-list',
        '.chat-message-list', '.im-chat', '.chat-dialog', '.job-chat-box',
        '.geek-chat', '.chat-box', '.conversation-bd', '.chat-container',
        '.im-container', '.chat-wrapper', '.chat-user', '.chat-header',
        '.conversation-list', '.chat-message', '#chat-list',
        '.chat-list', '.im-conversation', '.conversation-item', '.chat-item',
        '.im-chat-header', '.header-info'
      ];
      var greetingSelectors = [
        '.greet-pop', '.dialog-wrap', '.dialog-container', '.layer-dialog',
        '.auto-greet', '.greet-setting', '.chat-op'
      ];
      function visible(el){
        if (!el) return false;
        var rect = el.getBoundingClientRect();
        var style = window.getComputedStyle(el);
        return rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden';
      }
      function collect(selectors){
        var nodes = [];
        for (var i = 0; i < selectors.length; i++) {
          var found = document.querySelectorAll(selectors[i]);
          for (var j = 0; j < found.length; j++) {
            if (visible(found[j])) nodes.push(found[j]);
          }
        }
        return nodes;
      }
      var chatNodes = collect(chatSelectors);
      var greetingNodes = collect(greetingSelectors);
      var chatText = chatNodes.map(function(n){ return n.innerText || ''; }).join('\n');
      var greetingText = greetingNodes.map(function(n){ return n.innerText || ''; }).join('\n');
      var scoped = (chatText + '\n' + greetingText).trim();
      function includesAny(text, parts){
        for (var i = 0; i < parts.length; i++) {
          if (parts[i] && text.indexOf(parts[i]) >= 0) return true;
        }
        return false;
      }
      var disabled = includesAny(greetingText + chatText, ['请开启自动打招呼', '自动打招呼未开启', '未开启自动打招呼', '关闭自动打招呼']);
      var enabled = includesAny(greetingText + chatText, ['自动打招呼已开启', '已开启自动打招呼']);
      var btn = document.querySelector('.op-btn-chat, .btn-startchat, .job-chat-btn');
      var btnText = btn ? (btn.textContent || '').replace(/\s+/g, ' ').trim() : '';
      var stayBtn = false;
      var allBtns = document.querySelectorAll('button, a, span');
      for (var i = 0; i < allBtns.length; i++) {
        var t = (allBtns[i].textContent || '').replace(/\s+/g, ' ').trim();
        if (t === '留在此页' && visible(allBtns[i])) stayBtn = true;
      }
      var relation = includesAny(chatText, ['您正在与Boss沟通', '您正在与Boss', '您正在与']);
      var companyMatch = !!(company && chatText.indexOf(company) >= 0);
      var messageVisible = includesAny(chatText, ['送达', '发送成功', '您好']);
      var greetingTriggered = includesAny(greetingText, ['发送招呼', '已发送招呼', '招呼已发送']) || includesAny(chatText, ['自动打招呼已发送']);
      var chatUrl = url.indexOf('/web/geek/chat') >= 0;
      var continued = btnText.indexOf('继续沟通') >= 0;
      var chatUi = chatUrl || chatNodes.length > 0 || relation || stayBtn || continued;
      // ★ 修复①：会话列表/头部核验 — 在左侧会话列表与当前会话头部找目标公司 + 送达证据
      var convListSelectors = ['.conversation-list', '.chat-list', '.im-conversation', '.conversation-item', '.chat-item', '#chat-list'];
      var convText = '';
      for (var ci = 0; ci < convListSelectors.length; ci++) {
        var cln = document.querySelectorAll(convListSelectors[ci]);
        for (var cj = 0; cj < cln.length; cj++) {
          if (visible(cln[cj])) convText += '\n' + (cln[cj].innerText || '');
        }
      }
      var headerSelectors = ['.chat-header', '.conversation-header', '.geek-chat .header', '.im-chat-header', '.header-info', '.chat-op'];
      var headerText = '';
      for (var hi = 0; hi < headerSelectors.length; hi++) {
        var hn = document.querySelectorAll(headerSelectors[hi]);
        for (var hj = 0; hj < hn.length; hj++) {
          if (visible(hn[hj])) headerText += '\n' + (hn[hj].innerText || '');
        }
      }
      var targetInContext = !!(company && (convText.indexOf(company) >= 0 || headerText.indexOf(company) >= 0 || chatText.indexOf(company) >= 0));
      var sentEvidence = includesAny(convText + '\n' + headerText + '\n' + chatText, ['送达', '您好', '已发送', '自动打招呼已发送', '打招呼']);
      var chat_list_match = targetInContext && sentEvidence;
      return JSON.stringify({
        auto_greeting_state: disabled ? 'disabled' : (enabled || greetingTriggered || messageVisible ? 'enabled' : 'unknown'),
        greeting_triggered: greetingTriggered,
        greeting_sent: !!(messageVisible && (relation || companyMatch)),
        chat_relation: relation || continued || chatUrl,
        message_visible: messageVisible,
        delivery_page: chatUi,
        chat_ui: chatUi,
        company_match: companyMatch,
        btn_text: btnText,
        stay_btn: stayBtn,
        chat_list_match: chat_list_match,
        chat_list_text: (convText + '\n' + headerText).slice(0, 200),
        scoped_text: scoped.slice(0, 300)
      });
    })()
    ''' % payload
    raw = evaluate(script) or '{}'
    try:
        data = json.loads(raw)
    except Exception:
        data = {
            'auto_greeting_state': 'unknown',
            'greeting_triggered': False,
            'greeting_sent': False,
            'chat_relation': False,
            'message_visible': False,
            'delivery_page': False,
            'company_match': False,
        }
    missing = []
    if not (data.get('delivery_page') or data.get('chat_ui') or data.get('chat_relation')):
        missing.append('delivery_page')
    data['missing_evidence'] = missing
    data['greeting_sent'] = bool(data.get('greeting_sent'))
    data['chat_ui'] = bool(data.get('chat_ui') or data.get('delivery_page') or data.get('chat_relation'))
    return data


def classify_delivery(evidence, popup_sent=False, stayed_on_page=False):
    """点进沟通界面即成功；自动打招呼关闭记 blocked。"""
    evidence = dict(evidence or {})
    evidence['popup_sent'] = bool(popup_sent)
    evidence['stayed_on_page'] = bool(stayed_on_page)
    state = evidence.get('auto_greeting_state') or 'unknown'
    if state == 'disabled':
        return 'blocked', '自动打招呼未开启，无法完成有效沟通', evidence
    chat_ok = bool(
        evidence.get('delivery_page')
        or evidence.get('chat_ui')
        or evidence.get('chat_relation')
        or evidence.get('stay_btn')
        or evidence.get('chat_list_match')
        or ('继续沟通' in str(evidence.get('btn_text') or ''))
    )
    if chat_ok:
        return 'success', '已进入沟通界面', evidence
    missing = evidence.get('missing_evidence') or []
    return 'unknown', '投递结果证据不足: missing=' + (','.join(missing) or 'none'), evidence
def _get_chat_button_text():
    """获取当前沟通按钮的文字"""
    return evaluate("""
    (function(){
        var btn = document.querySelector('.op-btn-chat, .btn-startchat, .job-chat-btn');
        return btn ? btn.textContent.trim() : '';
    })()
    """) or ""


def _wait_delivery_outcome(job_info, timeout=10):
    """★ 修复①：点击「立即沟通」后轮询等待投递结果落地。

    兼容 BOSS 两种成功路径：
      - 路径A：自动打招呼后 SPA 跳转到 /web/geek/chat 聊天页（chatUrl 命中）
      - 路径B：原地弹出「留在此页」确认弹窗（说明招呼已发送，留在岗位页）

    轮询期间：
      1. 命中聊天页 URL -> 返回 reached_chat=True
      2. 出现「留在此页」-> 点击并停留 -> 返回 stayed_on_page=True
      3. 出现打招呼弹窗（发送/发送招呼）-> 点击发送后继续轮询
      4. 检测到每日上限等致命提示 -> 立即中断（交由上层判 fatal）

    超时未落地返回 (False, False, False)，交由 classify 判 unknown。
    """
    deadline = time.time() + timeout
    reached_chat = False
    stayed_on_page = False
    popup_sent = False
    while time.time() < deadline:
        # 致命上限优先中断
        fs, _ = _check_fatal_patterns()
        if fs:
            break
        url = evaluate("window.location.href") or ""
        if url and url.find('/web/geek/chat') >= 0:
            reached_chat = True
            break
        # 处理可能的打招呼弹窗（发送）
        popup = handle_greet_popup()
        if popup != 'no_popup':
            popup_sent = True
            time.sleep(1.2)
            continue
        # 检测「留在此页」确认弹窗
        stay = click_stay_on_page()
        if stay == 'clicked:留在此页':
            stayed_on_page = True
            time.sleep(1)
            break
        time.sleep(0.8)
    return reached_chat, stayed_on_page, popup_sent


# ═══════════════════════════════════════════════════════════
# 核心投递逻辑
# ═══════════════════════════════════════════════════════════

def deliver_inplace(job_id, job_info=None, skip_card_click=False):
    """当前页面内原地投递单个岗位

    流程:
      1. 点击卡片（右侧面板就地切 JD）【skip_card_click=True 时跳过，用于已直达详情页】
      2. scrollIntoView + 点击「立即沟通」(.op-btn-chat)
      3. 等2s -> 立即检测致命错误
      4. 采集打招呼状态 + 处理打招呼弹窗（点击"发送"）
      5. 点击「留在此页」（post-greet 确认弹窗，出现即说明招呼已发送）
      5b. 若未命中「留在此页」，轮询等待聊天页跳转 / 弹窗延迟出现
      6. 检测最终状态 + 采集证据（含会话列表核验）
      7. 根据累计证据返回 status；跳转聊天页时返回岗位列表延续循环

    参数:
        job_id: 加密岗位 ID
        job_info: 可选的岗位信息 dict
        skip_card_click: True 时跳过卡片点击，直接对「已打开的岗位详情页」投递
            （用于按 jobId 直达 job_detail/{id}.html 的补投/重试场景，避免重复定位卡片）

    返回:
        (status, detail, evidence)
        status: 'success' | 'blocked' | 'fatal_limit' | 'login_expired' | 'skip' | 'fail' | 'unknown'
    """
    title = (job_info or {}).get('title', '')[:25] if job_info else job_id

    # 1. 点击卡片（v5.6.6 等待调优：verify max_wait 5→2.5）
    #    ★ v5.6.7 补：skip_card_click=True 时跳过卡片定位，直接对已打开详情页投递
    if skip_card_click:
        time.sleep(0.8)
    else:
        click_result = click_card_inplace(job_id, verify=True, max_wait=2.5)
        if not click_result["ok"]:
            return 'fail', f"卡片定位失败: {click_result['detail']}", {'missing_evidence': ['card']}

        time.sleep(0.6)

    # 2. scrollIntoView + 点击
    scroll_result = evaluate("""
    (function(){
        var btn = document.querySelector('.op-btn-chat');
        if (!btn) btn = document.querySelector('.btn-startchat, .job-chat-btn');
        if (!btn) return 'not_found';
        var text = btn.textContent.trim();
        if (text.indexOf('继续沟通') >= 0) return 'already:' + text;
        btn.scrollIntoView({block: 'center'});
        return 'scrolled:' + text;
    })()
    """)

    if scroll_result.startswith('already:'):
        return 'skip', f'已沟通过: {scroll_result}', {'missing_evidence': ['already_chatted']}

    if scroll_result == 'not_found':
        body_text = evaluate("document.body.innerText") or ""
        if any(p in body_text for p in ['职位已关闭', '职位不存在', '已下线']):
            return 'skip', '职位已关闭/下线', {'missing_evidence': ['job_closed']}
        return 'fail', '沟通按钮未找到', {'missing_evidence': ['chat_button']}

    time.sleep(0.5)

    btn_state = evaluate(r"""
    (function(){
        var btn = document.querySelector('.job-detail-container .op-btn-chat, .job-detail-box .op-btn-chat, .op-btn-chat, .btn-startchat, .job-chat-btn');
        if (!btn) return 'not_found';
        var text = (btn.textContent || '').replace(/\s+/g,' ').trim();
        var cls = (btn.className || '').toString();
        if (text.indexOf('继续沟通') >= 0) return 'already:' + text;
        if (cls.indexOf('is-disabled') >= 0 || btn.getAttribute('disabled') !== null) return 'disabled:' + text;
        btn.scrollIntoView({block:'center'});
        return 'ready:' + text;
    })()
    """)
    if btn_state and str(btn_state).startswith('already:'):
        return 'skip', f'已沟通过: {btn_state}', {'missing_evidence': ['already_chatted']}
    if btn_state and str(btn_state).startswith('disabled:'):
        return 'skip', f'沟通按钮不可点: {btn_state}', {'missing_evidence': ['chat_button_disabled']}
    if btn_state == 'not_found' or not btn_state:
        return 'fail', '点击时按钮消失', {'missing_evidence': ['chat_button']}

    clicked = False
    for selector in ('.job-detail-container .op-btn-chat', '.job-detail-box .op-btn-chat', '.op-btn-chat', '.btn-startchat', '.job-chat-btn'):
        try:
            if click(selector):
                clicked = True
                click_result = 'clicked:' + selector
                break
        except Exception:
            continue
    if not clicked:
        click_result = evaluate("""
        (function(){
            var btn = document.querySelector('.op-btn-chat, .btn-startchat, .job-chat-btn');
            if (!btn) return 'not_found';
            if (typeof btn.click === 'function') btn.click();
            return 'clicked:fallback';
        })()
        """)

    if (not clicked) and (click_result == 'not_found' or not click_result):
        return 'fail', '点击时按钮消失', {'missing_evidence': ['chat_button']}

    # 3. 等待弹窗出现后，先采集自动打招呼状态，再处理弹窗。（v5.6.6 等待调优：2s→1.0s）
    time.sleep(1.0)
    fatal_status, fatal_detail = _check_fatal_patterns()
    if fatal_status:
        return fatal_status, fatal_detail, {'missing_evidence': ['fatal']}

    greeting_before = _chat_evidence(job_info)

    # 4. 处理打招呼弹窗（过程证据，不能单独证明成功）
    popup = handle_greet_popup()
    sent_greeting = (popup != 'no_popup')
    if sent_greeting:
        time.sleep(1.0)

    # 5. 点击「留在此页」（post-greet 确认弹窗，出现即说明招呼已发送）
    stay_result = click_stay_on_page()
    stayed_on_page = (stay_result == 'clicked:留在此页')
    if stayed_on_page:
        time.sleep(1.2)  # ★ 等待按钮状态从「立即沟通」变为「继续沟通」（v5.6.6 等待调优：2s→1.2s）
    elif not sent_greeting:
        handle_popup()
        time.sleep(1)

    reached_chat = False
    # 5b. ★ 修复①：兼容弹窗延迟出现 / 跳转到聊天页两种情况
    if not stayed_on_page:
        reached_chat, stayed_on_page, popup_sent = _wait_delivery_outcome(job_info, timeout=10)
        if popup_sent:
            sent_greeting = True

    # 6. 最终状态检测；不重复点击立即沟通来补充证据
    fatal_status, fatal_detail = _check_fatal_patterns()
    if fatal_status:
        return fatal_status, fatal_detail, greeting_before

    evidence = _chat_evidence(job_info)
    if greeting_before.get('auto_greeting_state') in ('enabled', 'disabled'):
        evidence['auto_greeting_state'] = greeting_before.get('auto_greeting_state')
    if greeting_before.get('greeting_triggered'):
        evidence['greeting_triggered'] = True
    evidence['popup_sent'] = sent_greeting
    evidence['stayed_on_page'] = stayed_on_page
    # ★ 修复①：点击「留在此页」即说明招呼已发送，作为成功证据并入
    #   （弹窗被点掉后 _chat_evidence 已读不到该按钮，必须从过程标志补全）
    if stayed_on_page:
        evidence['stay_btn'] = True
    evidence['reached_chat'] = reached_chat
    status, detail, evidence = classify_delivery(evidence, popup_sent=sent_greeting, stayed_on_page=stayed_on_page)

    # 6b. ★ 修复①：若因跳转到聊天页而成功，返回岗位列表以延续串行循环
    if reached_chat and not stayed_on_page:
        try:
            navigate(f"https://www.zhipin.com/web/geek/jobs?city={CITY_CODE}", wait_range=(4, 6))
        except Exception:
            pass

    return status, f"{detail}: {json.dumps(evidence, ensure_ascii=False)}", evidence



def run_batch(jobs_file, progress_file="stream_progress.json", max_count=0):
    """批量投递（兼容旧接口，v5.0推荐使用serial_loop.py串行控制）"""
    register_signal_guard()

    if not health_check():
        print("WebBridge 不可达，请先运行 env_check.py")
        return None

    if not ensure_active_tab():
        print("无法建立标签页")
        return None

    with open(jobs_file, 'r', encoding='utf-8') as f:
        jobs = json.load(f)

    unapproved = [j for j in jobs if j.get('decision') != 'APPROVE']
    if unapproved:
        print(f"AI 审核守卫: 发现 {len(unapproved)} 条未通过 AI 审核的岗位，拒绝投递")
        return None

    pm = ProgressManager(progress_file)
    pm.load()

    to_deliver = [j for j in jobs if not pm.is_done(j.get('jobId', ''))]
    max_to_deliver = max_count if max_count > 0 else len(to_deliver)
    actual_to_deliver = min(len(to_deliver), max_to_deliver)

    print(f"SESSION: {SESSION}")
    print(f"本批 {len(jobs)} 条，已投 {pm.delivered_count} 条，待投 {len(to_deliver)} 条，本批上限 {max_to_deliver}")
    print("=" * 60)

    stats = {
        "success": 0, "skip": 0, "fail": 0, "fatal_limit": 0,
        "login_expired": 0, "unknown": 0, "total": 0,
    }
    consecutive_unknown = 0

    for idx, job in enumerate(to_deliver[:actual_to_deliver]):
        job_id = job.get("jobId", "")
        job_title = job.get("title", "?")[:25]

        if not job_id:
            continue

        print(f"[{idx+1}/{actual_to_deliver}] 投递 {job_title} ({job_id}) ...", end=" ")

        status, detail, evidence = deliver_inplace(job_id, job_info=job)

        if status == 'success':
            pm.add_delivered(job_id, job, evidence=evidence)
        else:
            pm.add_failed(job_id, job, f"{status}: {detail}", evidence=evidence, status=status if status not in ('fatal_limit','login_expired','skip') else 'fail')
        pm.save()

        stats["total"] += 1
        stats[status] = stats.get(status, 0) + 1

        print(f"{status.upper()}: {detail[:60]}")

        if status == 'unknown':
            consecutive_unknown += 1
            if consecutive_unknown >= MAX_CONSECUTIVE_UNKNOWN:
                print(f"\n连续 {MAX_CONSECUTIVE_UNKNOWN} 次未知状态，熔断暂停")
                break
        else:
            consecutive_unknown = 0

        if status in ('fatal_limit', 'login_expired'):
            print(f"\n致命错误，整批停止")
            break

        # ★ v5.0 投递目标检查
        target_check = check_delivery_target(progress_file)
        if target_check["target_met"]:
            print(f"\n★ 投递目标 {DAILY_TARGET} 份已达成！停止投递")
            break

        time.sleep(random.uniform(2, 3.5))

    print("\n" + "=" * 60)
    print(f"投递完成: 成功 {stats['success']} / 跳过 {stats['skip']} / 失败 {stats['fail']}")
    print(f"         上限 {stats['fatal_limit']} / 登录过期 {stats['login_expired']} / 未知 {stats['unknown']}")
    print("=" * 60)

    stats["delivered_total"] = pm.delivered_count
    return stats


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="投递执行引擎")
    parser.add_argument("jobs_file", help="待投递岗位 JSON 文件")
    parser.add_argument("--progress", default="stream_progress.json", help="进度文件")
    parser.add_argument("--max", type=int, default=0, help="本批最多投递数量")
    args = parser.parse_args()

    run_batch(args.jobs_file, args.progress, args.max)
