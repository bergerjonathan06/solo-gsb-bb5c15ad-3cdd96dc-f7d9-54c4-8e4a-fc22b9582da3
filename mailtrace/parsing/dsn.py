"""退信回执（DSN, RFC 3464）判读，仅依赖 Python 标准库解析 MIME。

判读口径：
- 用 :mod:`email`（标准库）解析完整原始邮件（MIME），只读取其中
  Content-Type 为 ``message/delivery-status`` 的部分（与参数无关，
  比较忽略大小写）；``text/plain`` 的人类可读说明、``message/rfc822``
  的原信副本等部分一律不参与判读。
- 每个 DSN 部分由若干**字段块**组成：第一块通常是每消息字段
  （``Reporting-MTA`` 等，不含 ``Final-Recipient``），其后每个
  含 ``Final-Recipient`` 的块对应一个收件人报告。收件人严格按其块在
  各 DSN 部分中出现的**原有顺序**提取，绝不把整封回执归为单一结果。
- 每个收件人报告块提取 ``Final-Recipient`` / ``Action`` / ``Status``
  / ``Diagnostic-Code`` 四项（字段名大小写不敏感，保留折行原文）。
- 分类以 ``Status`` 增强状态码的首位类别为准（RFC 3463）：
  ``2.x.x`` → 成功，``4.x.x`` → 暂缓（临时性），``5.x.x`` → 永久失败。
- ``Status`` 缺失 / 无法识别，或其类别与 ``Action`` 语义矛盾时，
  该收件人标为**待核对**（``review``）并逐条说明原因，不强行归类。
"""

from __future__ import annotations

import re
from email import message_from_string
from email.message import Message

DSN_MAIN_TYPE = "message"
DSN_SUB_TYPE = "delivery-status"

# 收件人判读结果
RESULT_SUCCESS = "success"
RESULT_DEFERRED = "deferred"
RESULT_PERMANENT = "permanent"
RESULT_REVIEW = "review"

_STATUS_LABELS = {
    RESULT_SUCCESS: "成功（投递成功）",
    RESULT_DEFERRED: "暂缓（临时失败，仍可能重试）",
    RESULT_PERMANENT: "永久失败（退信）",
    RESULT_REVIEW: "待核对（字段缺失或自相矛盾）",
}

# RFC 3463 增强状态码：class "." subject "." detail，每段为 1-3 位数字。
# 要求两侧为单词边界，避免 “550-5.7.1” 之类夹带文本被误判。
_ENHANCED_STATUS_RE = re.compile(
    r"(?<![\w.])([245])\.(\d{1,3})\.(\d{1,3})(?![\w.])"
)

# Action 合法值（RFC 3464 §2.6），大小写不敏感
_KNOWN_ACTIONS = {"failed", "delayed", "delivered", "relayed", "expanded"}

# 每个 Status 首位类别在语义上对应的 Action 集合（Action 允许缺失）
_CLASS_ACTIONS = {
    "2": {"delivered", "relayed", "expanded"},
    "4": {"delayed"},
    "5": {"failed"},
}
_CLASS_NUMERIC = {"2": 2, "4": 4, "5": 5}


def _unfold(value: str | None) -> str:
    """展开 RFC 5322 折行：折叠空白（含换行）规整为单个空格。"""
    if not value:
        return ""
    return re.sub(r"\s+", " ", value).strip()


def _split_type_value(raw: str | None) -> tuple[str | None, str]:
    """拆分 ``type; value`` 形式的字段（Final-Recipient / Diagnostic-Code）。

    返回 ``(type, value)``；没有分号时 type 为 None，整体作为 value。
    """
    text = _unfold(raw)
    if ";" in text:
        typ, _, val = text.partition(";")
        return typ.strip().lower() or None, val.strip()
    return None, text


def _parse_status(raw: str | None) -> tuple[str | None, str | None, str | None]:
    """解析增强状态码。

    返回 ``(完整状态码, 首位类别（"2"/"4"/"5"）, 规范化原文)``；
    无法识别时各项为 None。取字段中第一个匹配的增强状态码
    （Status 字段按 RFC 只应含一个状态码）。
    """
    text = _unfold(raw)
    if not text:
        return None, None, None
    m = _ENHANCED_STATUS_RE.search(text)
    if not m:
        return None, None, None
    code = f"{m.group(1)}.{m.group(2)}.{m.group(3)}"
    return code, m.group(1), text


def _field_raw(block: Message, name: str, value: str | None) -> str | None:
    """重建单个字段的原始折行文本（字段名: 值）。"""
    if value is None:
        return None
    return f"{name}: {value}"


def _header_value(block: Message, name: str) -> tuple[str | None, str | None]:
    """取字段（大小写不敏感）的原始折行值与重建后的原始字段文本。

    同名字段出现多次时取第一条（RFC 3464 规定收件人块中这些字段至多一条），
    并由调用方根据需要记录重复。
    """
    raw_value = block.get(name)  # compat32：返回保留折行的原始值
    if raw_value is None:
        return None, None
    return raw_value, _field_raw(block, name, raw_value)


def _header_count(block: Message, name: str) -> int:
    return len(block.get_all(name, []))


def _parse_dsn_blocks(part: Message) -> list[Message]:
    """取一个 DSN 部分的字段块列表（兼容非标准字符串载荷）。

    标准库对 ``message/delivery-status`` 有专门支持：每个字段块解析为一个
    嵌套 :class:`email.message.Message`，载荷即该块字段列表，顺序与原文一致。
    遇到非标准实现把整个 DSN 文本作为字符串载荷时，退回手工按空行切块。
    """
    payload = part.get_payload()
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, Message)]
    text: str
    if isinstance(payload, bytes):
        text = payload.decode("utf-8", errors="replace")
    elif isinstance(payload, str):
        text = payload
    else:
        return []
    return _manual_blocks(text)


def _manual_blocks(text: str) -> list[Message]:
    """把未被标准库分块的 DSN 原文按“空行分隔的字段块”手工解析。"""
    blocks: list[Message] = []
    # 展开 CRLF，按一个及以上空行切块；续行（空白开头）不视为块边界
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    chunks = re.split(r"\n[ \t]*\n", text)
    for chunk in chunks:
        chunk = chunk.strip("\n")
        if not chunk.strip():
            continue
        blocks.append(message_from_string(chunk))
    return blocks


def _classify(
    status_class: str | None,
    action_raw: str | None,
) -> tuple[str, list[str], list[str]]:
    """按 Status 类别分类，并检查缺失 / 与 Action 矛盾。

    返回 ``(结果代码, 待核对原因列表, 提示列表)``；待核对原因列表非空即
    应标为待核对；提示列表仅记录不影响 Status 判定的信息（如 Action 值
    不在 RFC 3464 合法集合内——Status 明确时仍按 Status 分类）。
    """
    reasons: list[str] = []
    notes: list[str] = []
    action = action_raw.strip().lower() if action_raw and action_raw.strip() else None

    if action is not None and action not in _KNOWN_ACTIONS:
        notes.append(f"Action 值 “{action_raw.strip()}” 不是 RFC 3464 合法值"
                     "（failed / delayed / delivered / relayed / expanded），"
                     "已按 Status 类别分类，建议核对原文")

    if status_class is None:
        reasons.append("缺少可识别的增强状态码 Status（应为 2/4/5.x.x 形式），"
                       "无法按状态码判定成功 / 暂缓 / 永久失败")
        return RESULT_REVIEW, reasons, notes

    if action is not None and action in _KNOWN_ACTIONS:
        expected = _CLASS_ACTIONS[status_class]
        if action not in expected:
            expected_label = "、".join(sorted(expected))
            reasons.append(
                f"Status 类别 {_CLASS_NUMERIC[status_class]}.x.x 与 Action={action} "
                f"语义矛盾（{_CLASS_NUMERIC[status_class]}.x.x 对应的 Action 应为："
                f"{expected_label}）"
            )

    if reasons:
        return RESULT_REVIEW, reasons, notes
    if status_class == "2":
        return RESULT_SUCCESS, reasons, notes
    if status_class == "4":
        return RESULT_DEFERRED, reasons, notes
    return RESULT_PERMANENT, reasons, notes


def inspect_dsn(source: str) -> dict:
    """解析完整原始邮件中的退信回执（DSN）并按收件人给出判读结果。

    返回页面与 ``POST /api/dsn/inspect`` 共用的结构化结果；没有任何
    ``message/delivery-status`` 部分时返回 ``{"error": ...}``（调用方
    据此返回 400）。
    """
    try:
        root = message_from_string(source)
    except Exception as exc:  # 标准库通常不抛，但畸形输入仍兜底
        return {"error": f"原始邮件无法按 MIME 解析：{exc}"}

    dsn_parts = [
        part
        for part in root.walk()
        if part.get_content_maintype() == DSN_MAIN_TYPE
        and part.get_content_subtype() == DSN_SUB_TYPE
    ]
    if not dsn_parts:
        return {
            "error": "未在邮件中找到 message/delivery-status 投递状态部分："
                     "请确认粘贴的是完整原始退信回执（multipart/report，"
                     "Content-Type: message/delivery-status），"
                     "而不只是退信的文字说明或原信头部。"
        }

    envelope_blocks: list[dict] = []
    recipients: list[dict] = []

    # walk() 已按 MIME 文档顺序产出；此处保持各 DSN 部分的原有顺序
    for dsn_index, part in enumerate(dsn_parts, start=1):
        blocks = _parse_dsn_blocks(part)
        per_message: dict | None = None
        for block_index, block in enumerate(blocks):
            fr_raw, fr_field = _header_value(block, "Final-Recipient")
            if fr_raw is None:
                # 每消息字段块（无 Final-Recipient）：收集信封级信息
                reporting = _unfold(block.get("Reporting-MTA"))
                if reporting or block.keys():
                    env = {
                        "dsn_part": dsn_index,
                        "block_index": block_index,
                        "reporting_mta": reporting or None,
                        "arrival_date": _unfold(block.get("Arrival-Date")) or None,
                        "fields": [
                            {"name": key, "value": _unfold(val)}
                            for key, val in block.items()
                        ],
                    }
                    envelope_blocks.append(env)
                    if per_message is None:
                        per_message = env
                continue

            action_raw, action_field = _header_value(block, "Action")
            status_value, status_field = _header_value(block, "Status")
            diag_raw, diag_field = _header_value(block, "Diagnostic-Code")

            fr_type, recipient = _split_type_value(fr_raw)
            status_code, status_class, status_text = _parse_status(status_value)
            diag_type, diag_text = _split_type_value(diag_raw)
            action_value = _unfold(action_raw)

            result, review_reasons, notes = _classify(status_class, action_raw)

            # 以下字段级问题同样需要把该收件人标为待核对
            structure_reasons: list[str] = []

            # 重复字段（RFC 3464 规定这些字段每块至多一条）
            for fname in ("Final-Recipient", "Action", "Status", "Diagnostic-Code"):
                count = _header_count(block, fname)
                if count > 1:
                    structure_reasons.append(
                        f"{fname} 字段在本收件人块中出现 {count} 次"
                        "（RFC 3464 规定至多一条），已取第一条，请核对"
                    )

            if not recipient:
                structure_reasons.insert(
                    0, "Final-Recipient 字段存在但未解析到收件人地址，请核对"
                )

            review_reasons.extend(structure_reasons)
            if structure_reasons:
                result = RESULT_REVIEW

            entry = {
                "index": len(recipients) + 1,
                "dsn_part": dsn_index,
                "block_index": block_index,
                "final_recipient": recipient or None,
                "recipient_type": fr_type,
                "final_recipient_raw": _unfold(fr_raw) or None,
                "action": action_value.lower() if action_raw is not None else None,
                "action_raw": action_value if action_raw is not None else None,
                "status": status_code,
                "status_class": status_class,
                "status_text": status_text,
                "result": result,
                "result_label": _STATUS_LABELS[result],
                "review": result == RESULT_REVIEW,
                "review_reasons": review_reasons,
                "notes": notes,
                "diagnostic_type": diag_type,
                "diagnostic_code": diag_text or None,
                "diagnostic_raw": _unfold(diag_raw) or None,
                "raw_fields": {
                    "final_recipient": fr_field,
                    "action": action_field,
                    "status": status_field,
                    "diagnostic_code": diag_field,
                },
                "raw_block": block.as_string().rstrip("\n"),
                "reporting_mta": (
                    per_message["reporting_mta"] if per_message else None
                ),
            }
            recipients.append(entry)

    counts = {
        RESULT_SUCCESS: 0,
        RESULT_DEFERRED: 0,
        RESULT_PERMANENT: 0,
        RESULT_REVIEW: 0,
    }
    for item in recipients:
        counts[item["result"]] += 1

    return {
        "dsn_part_count": len(dsn_parts),
        "envelope_count": len(envelope_blocks),
        "recipient_count": len(recipients),
        "success_count": counts[RESULT_SUCCESS],
        "deferred_count": counts[RESULT_DEFERRED],
        "permanent_count": counts[RESULT_PERMANENT],
        "review_count": counts[RESULT_REVIEW],
        "envelope_blocks": envelope_blocks,
        "recipients": recipients,
        "notice": "判读以每个收件人报告块为单位，按其原有顺序逐个展示；"
                  "分类依据 Status 首位类别（2=成功 / 4=暂缓 / 5=永久失败），"
                  "Status 缺失或与 Action 矛盾时该收件人单独标为“待核对”，"
                  "不把整封回执归为单一结果。",
    }
