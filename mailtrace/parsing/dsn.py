"""退信回执（DSN）判读：解析 message/delivery-status 收件人报告块。

只读取原始邮件中的 ``message/delivery-status`` MIME 部分（RFC 3464），
按收件人报告块在原文中的顺序提取 ``Final-Recipient`` / ``Action`` /
``Status`` / ``Diagnostic-Code``，并按 ``Status`` 的类别码（2/4/5）
逐收件人标记 成功 / 暂缓 / 永久失败：

- ``Status`` 缺失、无法解析或类别不在 2/4/5 → **待核对**（说明原因）；
- ``Status`` 类别与 ``Action`` 矛盾（如 ``Action: failed`` 却配
  ``Status: 2.0.0``）→ **待核对**（说明原因）；
- 其余以 ``Status`` 类别为准：2.x 成功、4.x 暂缓、5.x 永久失败。

每个收件人报告块**独立判定**，不把整封回执归为单一结果；人读说明
（text/plain）与原始邮件副本（message/rfc822）等其他部分一律不读取。
仅依赖 Python 标准库（email 包）。
"""

from __future__ import annotations

import re
from email import message_from_string
from email.message import Message

# 逐收件人判定结论
VERDICT_SUCCESS = "success"  # 成功（Status 2.x）
VERDICT_TRANSIENT = "transient"  # 暂缓（Status 4.x）
VERDICT_PERMANENT = "permanent"  # 永久失败（Status 5.x）
VERDICT_REVIEW = "review"  # 待核对（Status 缺失 / 无法解析 / 与 Action 矛盾）

_VERDICT_LABELS = {
    VERDICT_SUCCESS: "成功",
    VERDICT_TRANSIENT: "暂缓",
    VERDICT_PERMANENT: "永久失败",
    VERDICT_REVIEW: "待核对",
}

# Status 类别码 -> 判定结论
_CLASS_VERDICTS = {
    2: VERDICT_SUCCESS,
    4: VERDICT_TRANSIENT,
    5: VERDICT_PERMANENT,
}

# Action -> 期望的 Status 类别码（RFC 3464 §2.3.3）；
# relayed / expanded 不对应确定类别，不做矛盾检查
_ACTION_EXPECTED_CLASS = {
    "delivered": 2,
    "delayed": 4,
    "failed": 5,
}

# RFC 3464 §2.3.4：状态码为 类别.细节.主题 三段数字（允许尾部多余文本）
_STATUS_RE = re.compile(r"^(\d)\.(\d{1,3})\.(\d{1,3})(?:\s|$)")

_WS_RUN_RE = re.compile(r"[ \t\r\n]+")

# 收件人报告块可能出现的字段（用于区分每封邮件级字段块与收件人块）
_RECIPIENT_BLOCK_FIELDS = {
    "original-recipient",
    "final-recipient",
    "action",
    "status",
    "remote-mta",
    "diagnostic-code",
    "last-attempt-date",
    "final-log-id",
    "will-retry-until",
}


def _clean(value: object) -> str | None:
    """展开折行并规整空白；空值返回 ``None``。"""
    if value is None:
        return None
    text = _WS_RUN_RE.sub(" ", str(value)).strip()
    return text or None


def _dsn_blocks(part: Message) -> list[Message]:
    """取出一个 message/delivery-status 部分中的全部字段块。

    标准库解析器会把该部分的正文按空行切成若干 Message 块
    （首块为每封邮件级字段，其后为各收件人报告块）；个别构造异常的
    部分可能仍是纯字符串，此时按空行手动切块兜底。
    """
    payload = part.get_payload()
    if isinstance(payload, list):
        return [block for block in payload if isinstance(block, Message)]
    if isinstance(payload, str):
        blocks: list[Message] = []
        text = payload.replace("\r\n", "\n").replace("\r", "\n")
        for chunk in re.split(r"\n[ \t]*\n", text):
            if chunk.strip():
                blocks.append(message_from_string(chunk))
        return blocks
    return []


def _is_recipient_block(block: Message) -> bool:
    """字段块是否为收件人报告块（含任一收件人级字段）。"""
    names = {str(key).lower() for key in block.keys()}
    return bool(names & _RECIPIENT_BLOCK_FIELDS)


def _recipient_address(final_recipient: str | None) -> str | None:
    """从 ``Final-Recipient`` 原文取分号后的地址部分（无分号时取整体）。"""
    if not final_recipient:
        return None
    if ";" in final_recipient:
        address = final_recipient.split(";", 1)[1].strip()
    else:
        address = final_recipient.strip()
    return address or None


def _classify(
    status_raw: str | None, action_raw: str | None
) -> tuple[str, int | None, list[str]]:
    """按 Status 类别码判定单个收件人报告块。

    返回 ``(verdict, status_class, reasons)``；``reasons`` 非空时
    ``verdict`` 为待核对。
    """
    reasons: list[str] = []
    status_class: int | None = None

    if status_raw is None:
        reasons.append("缺少 Status 字段，无法按 2/4/5 类别判定")
    else:
        match = _STATUS_RE.match(status_raw)
        if match is None:
            reasons.append(
                f"Status 值（{status_raw}）不是“类别.细节.主题”三段数字格式，"
                "无法解析"
            )
        else:
            status_class = int(match.group(1))
            if status_class not in _CLASS_VERDICTS:
                reasons.append(
                    f"Status 类别码 {status_class} 不在 2/4/5 范围内，无法归类"
                )
                status_class = None

    action_norm = action_raw.lower() if action_raw else None
    if status_class is not None and action_norm in _ACTION_EXPECTED_CLASS:
        expected = _ACTION_EXPECTED_CLASS[action_norm]
        if expected != status_class:
            reasons.append(
                f"Action 为 {action_raw}（应对应 {expected}.x），"
                f"与 Status {status_raw}（{status_class}.x 类别）矛盾"
            )

    if reasons:
        return VERDICT_REVIEW, status_class, reasons
    return _CLASS_VERDICTS[status_class], status_class, reasons


def inspect_dsn(source: str) -> dict:
    """判读完整原始邮件中的退信回执，返回页面 / API 共用的结构化结果。

    只读取 ``message/delivery-status`` 部分；没有该部分或其中没有
    收件人报告块时返回 ``{"error": ...}``（调用方据此回 400）。
    """
    if source.startswith("From "):
        # mbox 邮箱格式的分隔行不是邮件字段，剥掉后再交给 email 解析器
        source = source.split("\n", 1)[1] if "\n" in source else ""
    message = message_from_string(source)
    dsn_parts = [
        part
        for part in message.walk()
        if part.get_content_type() == "message/delivery-status"
    ]
    if not dsn_parts:
        return {
            "error": "未找到 message/delivery-status 投递状态部分："
            "这封邮件不是可判读的退信回执（DSN），"
            "请粘贴包含投递状态部分的完整原始邮件"
        }

    recipients: list[dict] = []
    for part_index, part in enumerate(dsn_parts, start=1):
        block_index = 0
        for block in _dsn_blocks(part):
            if not _is_recipient_block(block):
                # 首块通常是每封邮件级字段（Reporting-MTA 等），跳过
                continue
            block_index += 1
            final_recipient = _clean(block.get("Final-Recipient"))
            action = _clean(block.get("Action"))
            status = _clean(block.get("Status"))
            diagnostic = _clean(block.get("Diagnostic-Code"))
            verdict, status_class, reasons = _classify(status, action)
            recipients.append(
                {
                    "index": len(recipients) + 1,
                    "part_index": part_index,
                    "block_index": block_index,
                    "final_recipient": final_recipient,
                    "final_recipient_address": _recipient_address(final_recipient),
                    "action": action,
                    "status": status,
                    "status_class": status_class,
                    "diagnostic_code": diagnostic,
                    "verdict": verdict,
                    "verdict_label": _VERDICT_LABELS[verdict],
                    "reasons": reasons,
                }
            )

    if not recipients:
        return {
            "error": "message/delivery-status 部分中没有收件人报告块"
            "（Final-Recipient / Action / Status 等字段），无法判读"
        }

    counts = {verdict: 0 for verdict in _VERDICT_LABELS}
    for entry in recipients:
        counts[entry["verdict"]] += 1

    return {
        "part_count": len(dsn_parts),
        "recipient_count": len(recipients),
        "success_count": counts[VERDICT_SUCCESS],
        "transient_count": counts[VERDICT_TRANSIENT],
        "permanent_count": counts[VERDICT_PERMANENT],
        "review_count": counts[VERDICT_REVIEW],
        "recipients": recipients,
        "notice": "每个收件人报告块按各自 Status 类别独立判定，"
        "整封回执不归为单一结果；仅读取 message/delivery-status 部分，"
        "人读说明与原始邮件副本不参与判读。",
    }
