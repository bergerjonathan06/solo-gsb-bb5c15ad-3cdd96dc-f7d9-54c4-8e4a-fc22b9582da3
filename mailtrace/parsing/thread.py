"""多封邮件的会话关系（threading）分析：构建 Message-ID 引用树。

设计要点：
- 复用 :func:`mailtrace.parsing.parser.parse_header_blocks` 的折行展开
  （RFC 5322 unfolding），逐封提取 ``Message-ID`` / ``In-Reply-To`` /
  ``References`` 字段中**尖括号内**的消息 ID（``<local-part@domain>``）；
  尖括号外的文字（如裸 token、无结构注释）一律不采信。
- 父邮件选取：``In-Reply-To`` 只解析出恰好一个 ID 时以它为父；
  该字段缺失、为空或没有可用尖括号 ID 时，回退取 ``References`` 的末项；
  两者都没有时该邮件是会话根（root）。
- **歧义不强连**：重复 Message-ID（跨封重复，或单封字段内/字段间出现
  多个 ID）、``In-Reply-To`` 含多个 ID、以及形成环（含自环）的关联，
  逐项标记为歧义并删除连边，其余邮件照常建树。
- 父 ID 不在本批次内时显示为**外部引用**（external reference），
  该邮件作为会话树根；没有任何父引用也没有子邮件的邮件列为**孤立邮件**。
- 输出会话森林（树）、外部引用、孤立邮件与逐封关联依据。
"""

from __future__ import annotations

import re

from mailtrace.parsing.parser import parse_header_blocks

    # 尖括号内的 msg-id（RFC 5322：<local-part@domain>，内部不含尖括号，
    # 与折叠空白；候选内容须含非空白字符，空的 <> 不采信）
_MSG_ID_RE = re.compile(r"<([^<>]*?[^<>\s][^<>]*?)>")

# 关联依据
BASIS_IN_REPLY_TO = "in_reply_to"
BASIS_REFERENCES = "references"
BASIS_NONE = "none"

BASIS_LABELS = {
    BASIS_IN_REPLY_TO: "In-Reply-To 唯一 ID",
    BASIS_REFERENCES: "References 末项（In-Reply-To 缺失 / 不可用）",
    BASIS_NONE: "无父引用字段",
}

# 关联状态
RELATION_LINKED = "linked"        # 已连接到批次内父邮件
RELATION_EXTERNAL = "external"    # 父 ID 在批次外（外部引用）
RELATION_ROOT = "root"            # 没有任何父引用
RELATION_AMBIGUOUS = "ambiguous"  # 关联歧义，不连边
RELATION_NO_ID = "no_id"          # 本封没有声明 Message-ID（无法被引用）

RELATION_LABELS = {
    RELATION_LINKED: "已连接父邮件",
    RELATION_EXTERNAL: "外部引用（批次外父邮件）",
    RELATION_ROOT: "会话根（无父引用）",
    RELATION_AMBIGUOUS: "关联歧义，未连边",
    RELATION_NO_ID: "未声明 Message-ID",
}

# 歧义代码
AMB_DUPLICATE_MESSAGE_ID = "duplicate_message_id"
AMB_MULTI_IN_REPLY_TO = "multiple_in_reply_to"
AMB_CYCLE = "cycle"


def extract_message_ids(value: str) -> list[str]:
    """从一个字段值中按出现顺序提取尖括号内的消息 ID（去重）。

    只采信尖括号包裹的内容；尖括号外的裸 token 不视为消息 ID。
    """
    seen: set[str] = set()
    ids: list[str] = []
    for match in _MSG_ID_RE.finditer(value or ""):
        candidate = match.group(1).strip()
        if candidate and candidate not in seen:
            seen.add(candidate)
            ids.append(candidate)
    return ids


def _collect_field_values(blocks, name: str) -> list[dict]:
    """收集指定字段（忽略大小写）的全部副本，保留出现顺序。"""
    return [
        {"value": block.value, "position": block.order + 1}
        for block in blocks
        if block.name.lower() == name
    ]


def _empty_result(message_count: int, message_errors: list[dict]) -> dict:
    return {
        "message_count": message_count,
        "parsed_count": 0,
        "message_errors": message_errors,
        "id_count": 0,
        "edge_count": 0,
        "tree_count": 0,
        "orphan_count": 0,
        "external_count": 0,
        "ambiguous_count": 0,
        "duplicate_id_sets": [],
        "external_refs": [],
        "ambiguities": [],
        "trees": [],
        "orphans": [],
        "ambiguous_messages": [],
        "messages": [],
    }


def thread_analysis(headers_list: list[str]) -> dict:
    """对多封邮件原始头部做会话关系分析。

    参数为头部字符串列表（页面粘贴文本可先用
    :func:`mailtrace.parsing.batch.split_batch_headers` 切分）。
    """
    message_errors: list[dict] = []
    messages: list[dict] = []

    if not headers_list:
        return {
            "error": "请至少提供一封邮件的原始头部（含 Message-ID / "
            "In-Reply-To / References 等会话字段）",
            **_empty_result(0, message_errors),
        }

    for index, raw in enumerate(headers_list):
        blocks = parse_header_blocks(raw)
        if not blocks:
            message_errors.append(
                {"index": index + 1, "error": "该头部无法解析为任何邮件字段"}
            )
            continue

        mid_fields = _collect_field_values(blocks, "message-id")
        irt_fields = _collect_field_values(blocks, "in-reply-to")
        ref_fields = _collect_field_values(blocks, "references")
        subjects = _collect_field_values(blocks, "subject")
        froms = _collect_field_values(blocks, "from")
        dates = _collect_field_values(blocks, "date")

        mid_ids: list[str] = []
        for field in mid_fields:
            for ident in extract_message_ids(field["value"]):
                if ident not in mid_ids:
                    mid_ids.append(ident)
        irt_ids: list[str] = []
        for field in irt_fields:
            for ident in extract_message_ids(field["value"]):
                if ident not in irt_ids:
                    irt_ids.append(ident)
        ref_ids: list[str] = []
        for field in ref_fields:
            for ident in extract_message_ids(field["value"]):
                if ident not in ref_ids:
                    ref_ids.append(ident)

        messages.append(
            {
                "index": index + 1,
                "parsed": True,
                "parse_error": None,
                "subject": subjects[0]["value"] if subjects else None,
                "from": froms[0]["value"] if froms else None,
                "date": dates[0]["value"] if dates else None,
                "message_id_field_count": len(mid_fields),
                "in_reply_to_field_count": len(irt_fields),
                "references_field_count": len(ref_fields),
                "message_id_positions": [f["position"] for f in mid_fields],
                "message_id_ids": mid_ids,
                "message_id": mid_ids[0] if len(mid_ids) == 1 else None,
                "in_reply_to_ids": irt_ids,
                "references_ids": ref_ids,
                "parent_id": None,
                "parent_index": None,
                "parent_external": False,
                "basis": BASIS_NONE,
                "relation": RELATION_ROOT,
                "ambiguity_codes": [],
                "reasons": [],
                "children": [],
            }
        )

    if not messages:
        result = _empty_result(len(headers_list), message_errors)
        result["error"] = "所有头部均无法解析为邮件字段，无法进行会话关系分析"
        return result

    # ---- 身份：Message-ID 归属统计 ----
    id_owners: dict[str, list[int]] = {}
    for msg in messages:
        for ident in msg["message_id_ids"]:
            id_owners.setdefault(ident, []).append(msg["index"])
    duplicate_sets = {
        ident: owners for ident, owners in id_owners.items() if len(owners) > 1
    }

    ambiguities: list[dict] = []

    def mark_ambiguous(msg: dict, code: str, reason: str) -> None:
        if code not in msg["ambiguity_codes"]:
            msg["ambiguity_codes"].append(code)
        msg["reasons"].append(reason)

    # 单封自身身份歧义：无 Message-ID 字段 / 多副本或字段内多个 ID
    for msg in messages:
        ids = msg["message_id_ids"]
        if len(ids) == 0:
            msg["relation"] = RELATION_NO_ID
            if msg["message_id_field_count"] > 0:
                msg["reasons"].append(
                    "Message-ID 字段中没有尖括号包裹的消息 ID，无法确定本封身份"
                )
            else:
                msg["reasons"].append("本封未声明 Message-ID，无法被其他邮件引用为父")
        elif len(ids) > 1:
            mark_ambiguous(
                msg,
                AMB_DUPLICATE_MESSAGE_ID,
                f"本封 Message-ID 声明了 {len(ids)} 个不同 ID（"
                f"{'、'.join(ids)}），身份不唯一，不参与连边",
            )
        for ident in ids:
            if ident in duplicate_sets:
                mark_ambiguous(
                    msg,
                    AMB_DUPLICATE_MESSAGE_ID,
                    f"Message-ID {ident} 在批次内第 "
                    f"{'、'.join(str(i) for i in duplicate_sets[ident])} 封重复出现，"
                    "身份不唯一，不参与连边",
                )

    # ---- 选父：In-Reply-To 唯一 ID，否则回退 References 末项 ----
    for msg in messages:
        if msg["ambiguity_codes"]:
            # 身份本身有歧义：不主动选父，也不会被选作父
            continue
        irt = msg["in_reply_to_ids"]
        refs = msg["references_ids"]
        if len(irt) > 1:
            mark_ambiguous(
                msg,
                AMB_MULTI_IN_REPLY_TO,
                f"In-Reply-To 含 {len(irt)} 个消息 ID（{'、'.join(irt)}），"
                "无法确定唯一父邮件，不强行连边（不回退 References）",
            )
            continue
        if len(irt) == 1:
            msg["parent_id"] = irt[0]
            msg["basis"] = BASIS_IN_REPLY_TO
        elif refs:
            msg["parent_id"] = refs[-1]
            msg["basis"] = BASIS_REFERENCES
        else:
            msg["parent_id"] = None
            msg["basis"] = BASIS_NONE

    # ---- 连边：父 ID -> 批次内唯一且无歧义的邮件 ----
    by_index = {msg["index"]: msg for msg in messages}
    edges: dict[int, int] = {}
    for msg in messages:
        if msg["ambiguity_codes"] or msg["parent_id"] is None:
            continue
        parent_id = msg["parent_id"]
        owners = id_owners.get(parent_id, [])
        if len(owners) == 1:
            parent = by_index[owners[0]]
            if parent["ambiguity_codes"]:
                mark_ambiguous(
                    msg,
                    AMB_DUPLICATE_MESSAGE_ID,
                    f"父邮件（Message-ID {parent_id}，第 {parent['index']} 封）"
                    "自身 Message-ID 存在歧义，不强行连边",
                )
                continue
            edges[msg["index"]] = parent["index"]
        elif len(owners) > 1:
            mark_ambiguous(
                msg,
                AMB_DUPLICATE_MESSAGE_ID,
                f"父 Message-ID {parent_id} 对应批次内 {len(owners)} 封邮件"
                f"（第 {'、'.join(str(i) for i in owners)} 封），父身份不唯一，不强行连边",
            )
        else:
            msg["parent_external"] = True

    # ---- 环检测：迭代找出一个环，删除环上各节点的出边并标记歧义 ----
    def find_cycle() -> list[int] | None:
        """沿父指针走链：再次遇到本链上的节点即得到一个环。

        每个节点至多一条出边（父指针），故任一节点都不可能同时属于两个环；
        已完成的链（尽头为无边节点或之前标记过的环）可安全跳过。
        """
        finished: set[int] = set()
        for start in edges:
            if start in finished:
                continue
            seen_at: dict[int, int] = {}
            chain: list[int] = []
            node: int | None = start
            while node is not None and node in edges:
                if node in finished:
                    break
                if node in seen_at:
                    return chain[seen_at[node]:]
                seen_at[node] = len(chain)
                chain.append(node)
                node = edges[node]
            finished.update(chain)
        return None

    while True:
        cycle = find_cycle()
        if cycle is None:
            break
        path_ids = [by_index[i]["message_id"] or f"# {i}" for i in cycle]
        chain = " → ".join(f"#{i}（{label}）" for i, label in zip(cycle, path_ids))
        for node_index in cycle:
            parent_index = edges.get(node_index)
            if parent_index is not None:
                edges.pop(node_index)
                mark_ambiguous(
                    by_index[node_index],
                    AMB_CYCLE,
                    f"与父邮件第 {parent_index} 封形成引用环（{chain}），"
                    "该关联不强行连边",
                )

    # ---- 最终关系状态与子节点 ----
    for msg in messages:
        if msg["ambiguity_codes"]:
            msg["relation"] = RELATION_AMBIGUOUS
            msg["parent_id"] = None
            msg["parent_index"] = None
            msg["parent_external"] = False
        elif msg["index"] in edges:
            parent_index = edges[msg["index"]]
            msg["relation"] = RELATION_LINKED
            msg["parent_index"] = parent_index
            by_index[parent_index]["children"].append(msg["index"])
        elif msg["parent_external"]:
            msg["relation"] = RELATION_EXTERNAL
            msg["parent_index"] = None
        elif len(msg["message_id_ids"]) == 0:
            # 未声明可用 Message-ID：保留 no_id 状态（无父引用时不会被当作会话根）
            msg["relation"] = RELATION_NO_ID
            msg["parent_index"] = None
        else:
            msg["relation"] = RELATION_ROOT
            msg["parent_index"] = None

    # 子节点按批次顺序展示
    for msg in messages:
        msg["children"].sort()

    # ---- 外部引用汇总（去重，按首次出现顺序）----
    external_refs: list[dict] = []
    seen_external: set[str] = set()
    for msg in messages:
        if msg["relation"] != RELATION_EXTERNAL:
            continue
        pid = msg["parent_id"]
        if pid not in seen_external:
            seen_external.add(pid)
            external_refs.append(
                {
                    "message_id": pid,
                    "referenced_by": [
                        m["index"]
                        for m in messages
                        if m["relation"] == RELATION_EXTERNAL and m["parent_id"] == pid
                    ],
                }
            )

    # ---- 歧义清单（按封序号）----
    for msg in messages:
        if msg["ambiguity_codes"]:
            ambiguities.append(
                {
                    "index": msg["index"],
                    "message_id": msg["message_id"],
                    "codes": list(msg["ambiguity_codes"]),
                    "reasons": list(msg["reasons"]),
                }
            )

    # ---- 森林构建：展示桶（歧义邮件若仍被子邮件引用，仍作为树根展示）----
    # 1) 会话树：没有父连边但有子邮件的节点（含出边因成环被删、却仍收到
    #    正常回复的歧义节点），或父引用在批次外（外部引用）的根；
    # 2) 关联歧义：身份/父引用/成环存在歧义的邮件全部进歧义清单
    #    （有子树者同时出现在会话树中，并带歧义标记）；
    # 3) 孤立邮件：无父引用、无子邮件、无歧义的邮件。
    roots: list[int] = []
    orphans: list[int] = []
    ambiguous_indexes: list[int] = []
    for msg in messages:
        idx = msg["index"]
        if msg["ambiguity_codes"]:
            ambiguous_indexes.append(idx)
        if msg["relation"] == RELATION_LINKED:
            continue
        if msg["children"] or msg["relation"] == RELATION_EXTERNAL:
            roots.append(idx)
        elif not msg["ambiguity_codes"]:
            orphans.append(idx)
    roots.sort()
    orphans.sort()
    ambiguous_indexes.sort()

    def node_view(idx: int) -> dict:
        msg = by_index[idx]
        return {
            "index": idx,
            "message_id": msg["message_id"],
            "subject": msg["subject"],
            "from": msg["from"],
            "date": msg["date"],
            "relation": msg["relation"],
            "relation_label": RELATION_LABELS[msg["relation"]],
            "basis": msg["basis"],
            "basis_label": BASIS_LABELS[msg["basis"]],
            "parent_id": msg["parent_id"],
            "parent_index": msg["parent_index"],
            "ambiguity_codes": list(msg["ambiguity_codes"]),
            "children": [node_view(child) for child in msg["children"]],
        }

    trees: list[dict] = []
    for root_index in roots:
        root = by_index[root_index]
        trees.append(
            {
                "root_index": root_index,
                "external_parent_id": root["parent_id"]
                if root["relation"] == RELATION_EXTERNAL
                else None,
                "node": node_view(root_index),
            }
        )

    duplicate_id_sets = [
        {
            "message_id": ident,
            "owner_indexes": list(owners),
        }
        for ident, owners in sorted(duplicate_sets.items())
    ]

    flat_messages = [_message_view(by_index[idx]) for idx in sorted(by_index)]

    return {
        "message_count": len(headers_list),
        "parsed_count": len(messages),
        "message_errors": message_errors,
        "id_count": sum(1 for m in messages if m["message_id"]),
        "edge_count": len(edges),
        "tree_count": len(trees),
        "orphan_count": len(orphans),
        "external_count": len(external_refs),
        "ambiguous_count": len(ambiguities),
        "duplicate_id_sets": duplicate_id_sets,
        "external_refs": external_refs,
        "ambiguities": ambiguities,
        "trees": trees,
        "orphans": [_message_view(by_index[idx]) for idx in orphans],
        "ambiguous_messages": [
            _message_view(by_index[idx]) for idx in ambiguous_indexes
        ],
        "messages": flat_messages,
    }


def _message_view(msg: dict) -> dict:
    """逐封关联依据视图（JSON / 页面共用）。"""
    return {
        "index": msg["index"],
        "parsed": msg["parsed"],
        "parse_error": msg["parse_error"],
        "subject": msg["subject"],
        "from": msg["from"],
        "date": msg["date"],
        "message_id": msg["message_id"],
        "message_id_all": list(msg["message_id_ids"]),
        "message_id_positions": list(msg["message_id_positions"]),
        "message_id_field_count": msg["message_id_field_count"],
        "in_reply_to_ids": list(msg["in_reply_to_ids"]),
        "in_reply_to_field_count": msg["in_reply_to_field_count"],
        "references_ids": list(msg["references_ids"]),
        "references_field_count": msg["references_field_count"],
        "parent_id": msg["parent_id"],
        "parent_index": msg["parent_index"],
        "parent_external": msg["parent_external"],
        "basis": msg["basis"],
        "basis_label": BASIS_LABELS[msg["basis"]],
        "relation": msg["relation"],
        "relation_label": RELATION_LABELS[msg["relation"]],
        "ambiguity_codes": list(msg["ambiguity_codes"]),
        "child_indexes": list(msg["children"]),
        "reasons": list(msg["reasons"]),
    }
