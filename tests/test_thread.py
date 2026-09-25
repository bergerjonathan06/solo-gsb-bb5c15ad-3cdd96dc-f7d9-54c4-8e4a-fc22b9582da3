import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mailtrace.parsing import split_batch_headers, thread_analysis  # noqa: E402
from mailtrace.parsing.sample import SAMPLE_HEADERS_THREAD  # noqa: E402
from mailtrace.parsing.thread import extract_message_ids  # noqa: E402

try:  # Flask 相关测试在未安装 Flask 时跳过（解析核心仅需标准库）
    from app import create_app
except ImportError:  # pragma: no cover
    create_app = None


def _mail(index, *, mid=None, irt=None, refs=None, subject=None, extra=""):
    """构造一封仅含会话字段的最小头部。"""
    lines = []
    if mid is not None:
        lines.append(f"Message-ID: <{mid}>")
    if irt is not None:
        lines.append(f"In-Reply-To: {irt}")
    if refs is not None:
        lines.append(f"References: {refs}")
    if subject is not None:
        lines.append(f"Subject: {subject}")
    lines.append(extra.rstrip("\n"))
    return "\n".join(line for line in lines if line is not None)


class ExtractIdTests(unittest.TestCase):
    def test_extracts_angle_bracket_ids_in_order_dedup(self):
        value = "<a@x> text <b@y> <a@x> <c@z>"
        self.assertEqual(extract_message_ids(value), ["a@x", "b@y", "c@z"])

    def test_bare_tokens_outside_brackets_ignored(self):
        self.assertEqual(extract_message_ids("not-an-id <a@x> trailing"), ["a@x"])
        self.assertEqual(extract_message_ids("plain-no-brackets at all"), [])

    def test_empty_and_nested_like(self):
        self.assertEqual(extract_message_ids(""), [])
        self.assertEqual(extract_message_ids("<>"), [])
        # 内层最先匹配，尖括号不作为合法 ID 字符保留
        self.assertEqual(extract_message_ids("<<a@x>>"), ["a@x"])

    def test_folded_value_is_already_unfolded_by_parser(self):
        raw = (
            "References: <a@x>\n"
            "\t<b@y>\n"
            "\t<c@z>\n"
            "Message-ID: <d@x>\n"
        )
        from mailtrace.parsing.parser import parse_header_blocks

        blocks = {b.name.lower(): b for b in parse_header_blocks(raw)}
        self.assertEqual(
            extract_message_ids(blocks["references"].value), ["a@x", "b@y", "c@z"]
        )


class ThreadStructureTests(unittest.TestCase):
    def test_in_reply_to_single_id_is_parent(self):
        mails = [
            _mail(1, mid="a@x", subject="root"),
            _mail(2, mid="b@x", irt="<a@x>", subject="reply"),
        ]
        r = thread_analysis(mails)
        self.assertEqual(r["edge_count"], 1)
        self.assertEqual(r["tree_count"], 1)
        self.assertEqual(r["orphan_count"], 0)
        tree = r["trees"][0]["node"]
        self.assertEqual(tree["index"], 1)
        self.assertEqual([c["index"] for c in tree["children"]], [2])
        msg2 = r["messages"][1]
        self.assertEqual(msg2["relation"], "linked")
        self.assertEqual(msg2["parent_index"], 1)
        self.assertEqual(msg2["basis"], "in_reply_to")

    def test_missing_in_reply_to_falls_back_to_last_reference(self):
        mails = [
            _mail(1, mid="a@x"),
            _mail(2, mid="b@x", irt="<a@x>"),
            # 没有 In-Reply-To 字段：References 有两项，取末项 b@x
            _mail(3, mid="c@x", refs="<a@x> <b@x>"),
        ]
        r = thread_analysis(mails)
        msg3 = next(m for m in r["messages"] if m["index"] == 3)
        self.assertEqual(msg3["parent_index"], 2)
        self.assertEqual(msg3["basis"], "references")
        self.assertEqual(msg3["parent_id"], "b@x")

    def test_empty_in_reply_to_field_falls_back_to_references(self):
        mails = [
            _mail(1, mid="a@x"),
            _mail(2, mid="b@x", irt="(no bracket id here)",
                  refs="<a@x>"),
        ]
        r = thread_analysis(mails)
        msg2 = r["messages"][1]
        self.assertEqual(msg2["relation"], "linked")
        self.assertEqual(msg2["parent_index"], 1)
        self.assertEqual(msg2["basis"], "references")

    def test_references_last_item_takes_precedence_over_earlier(self):
        # References 末项是批次内最近的父（b@x），前项 a@x 只是链路上的祖先
        mails = [
            _mail(1, mid="a@x"),
            _mail(2, mid="b@x", irt="<a@x>"),
            _mail(3, mid="d@x", refs="<a@x> <b@x>"),
        ]
        r = thread_analysis(mails)
        msg3 = next(m for m in r["messages"] if m["index"] == 3)
        self.assertEqual(msg3["parent_index"], 2)
        self.assertEqual(msg3["parent_id"], "b@x")
        # 不产生 d@x -> a@x 的越级连边
        self.assertEqual(r["edge_count"], 2)

    def test_external_parent_is_tree_root_and_listed_once(self):
        mails = [
            _mail(1, mid="a@x", irt="<outside@ext>"),
            _mail(2, mid="b@x", irt="<outside@ext>"),
        ]
        r = thread_analysis(mails)
        self.assertEqual(r["external_count"], 1)
        ext = r["external_refs"][0]
        self.assertEqual(ext["message_id"], "outside@ext")
        self.assertEqual(ext["referenced_by"], [1, 2])
        self.assertEqual(r["tree_count"], 2)  # 两封都是外部引用根（均无子）
        for tree in r["trees"]:
            self.assertEqual(tree["external_parent_id"], "outside@ext")
        for m in r["messages"]:
            self.assertEqual(m["relation"], "external")
            self.assertTrue(m["parent_external"])

    def test_orphan_is_root_without_children(self):
        r = thread_analysis([_mail(1, mid="lonely@x")])
        self.assertEqual(r["tree_count"], 0)
        self.assertEqual(r["orphan_count"], 1)
        self.assertEqual(r["orphans"][0]["index"], 1)
        self.assertEqual(r["orphans"][0]["relation"], "root")

    def test_no_message_id_is_not_an_error_but_cannot_be_parent(self):
        mails = [
            _mail(1, mid=None, subject="no id"),
            _mail(2, mid="b@x", refs="<a@x>"),  # a@x 批次外
        ]
        r = thread_analysis(mails)
        self.assertNotIn("error", r)
        no_id = r["messages"][0]
        self.assertEqual(no_id["relation"], "no_id")
        self.assertEqual(r["id_count"], 1)
        # #2 引用的 a@x 既不在批次内（#1 没有 ID），算外部引用
        self.assertEqual(r["messages"][1]["relation"], "external")

    def test_multiple_in_reply_to_ids_is_ambiguous_no_fallback(self):
        mails = [
            _mail(1, mid="a@x"),
            _mail(2, mid="b@x"),
            _mail(3, mid="c@x", irt="<a@x> <b@x>", refs="<a@x>"),
        ]
        r = thread_analysis(mails)
        msg3 = next(m for m in r["messages"] if m["index"] == 3)
        self.assertEqual(msg3["relation"], "ambiguous")
        self.assertIn("multiple_in_reply_to", msg3["ambiguity_codes"])
        # 明确不回退 References：没有任何连边涉及 #3
        self.assertEqual(r["edge_count"], 0)
        # #1、#2 为无根无子的普通邮件（孤立）；#3 进歧义桶而非孤立桶
        self.assertEqual(r["tree_count"], 0)
        self.assertEqual(r["orphan_count"], 2)
        self.assertEqual([m["index"] for m in r["ambiguous_messages"]], [3])

    def test_duplicate_message_id_across_messages_marks_both(self):
        mails = [
            _mail(1, mid="dup@x"),
            _mail(2, mid="dup@x"),
        ]
        r = thread_analysis(mails)
        self.assertEqual(
            r["duplicate_id_sets"],
            [{"message_id": "dup@x", "owner_indexes": [1, 2]}],
        )
        for m in r["messages"]:
            self.assertEqual(m["relation"], "ambiguous")
            self.assertIn("duplicate_message_id", m["ambiguity_codes"])
        self.assertEqual(r["edge_count"], 0)

    def test_child_pointing_to_duplicate_id_is_ambiguous(self):
        mails = [
            _mail(1, mid="dup@x"),
            _mail(2, mid="dup@x"),
            _mail(3, mid="c@x", irt="<dup@x>"),
        ]
        r = thread_analysis(mails)
        msg3 = r["messages"][2]
        self.assertEqual(msg3["relation"], "ambiguous")
        self.assertIn("duplicate_message_id", msg3["ambiguity_codes"])
        self.assertEqual(r["edge_count"], 0)

    def test_multiple_message_ids_in_one_field_is_ambiguous(self):
        raw = "Message-ID: <a@x> <b@x>\nSubject: two ids in one field\n"
        r = thread_analysis([raw])
        m = r["messages"][0]
        self.assertIsNone(m["message_id"])
        self.assertEqual(m["message_id_all"], ["a@x", "b@x"])
        self.assertEqual(m["relation"], "ambiguous")
        self.assertIn("duplicate_message_id", m["ambiguity_codes"])

    def test_two_message_id_fields_is_ambiguous(self):
        raw = (
            "Message-ID: <a@x>\n"
            "Message-ID: <b@x>\n"
            "Subject: two mid fields\n"
        )
        r = thread_analysis([raw])
        m = r["messages"][0]
        self.assertEqual(m["message_id_field_count"], 2)
        self.assertEqual(m["message_id_positions"], [1, 2])
        self.assertEqual(m["relation"], "ambiguous")

    def test_two_node_cycle_drops_both_edges(self):
        mails = [
            _mail(1, mid="a@x", irt="<b@x>"),
            _mail(2, mid="b@x", irt="<a@x>"),
        ]
        r = thread_analysis(mails)
        self.assertEqual(r["edge_count"], 0)
        for m in r["messages"]:
            self.assertEqual(m["relation"], "ambiguous")
            self.assertIn("cycle", m["ambiguity_codes"])
        self.assertEqual(r["tree_count"], 0)
        self.assertEqual(r["orphan_count"], 0)

    def test_self_loop_drops_edge(self):
        r = thread_analysis([_mail(1, mid="a@x", irt="<a@x>")])
        m = r["messages"][0]
        self.assertEqual(m["relation"], "ambiguous")
        self.assertIn("cycle", m["ambiguity_codes"])
        self.assertEqual(r["edge_count"], 0)

    def test_three_node_cycle_with_incoming_branch(self):
        # a <- b <- c <- a 成环；d 正常引用 a（挂在环上）。
        mails = [
            _mail(1, mid="a@x", irt="<c@x>"),
            _mail(2, mid="b@x", irt="<a@x>"),
            _mail(3, mid="c@x", irt="<b@x>"),
            _mail(4, mid="d@x", irt="<a@x>"),
        ]
        r = thread_analysis(mails)
        # 环上三封的出边全部删除；#4 -> #1 的入边保留
        self.assertEqual(r["edge_count"], 1)
        for idx in (1, 2, 3):
            self.assertEqual(r["messages"][idx - 1]["relation"], "ambiguous")
        msg4 = r["messages"][3]
        self.assertEqual(msg4["relation"], "linked")
        self.assertEqual(msg4["parent_index"], 1)
        # #1 有子 #4，仍作为一棵树的根展示（#1 本身带歧义标记）
        self.assertEqual(r["tree_count"], 1)

    def test_normal_tree_not_affected_by_ambiguous_mail(self):
        mails = [
            _mail(1, mid="a@x"),
            _mail(2, mid="b@x", irt="<a@x>"),
            _mail(3, mid="c@x", irt="<a@x> <b@x>"),  # 歧义
        ]
        r = thread_analysis(mails)
        self.assertEqual(r["edge_count"], 1)
        tree = r["trees"][0]["node"]
        self.assertEqual(tree["index"], 1)
        self.assertEqual([c["index"] for c in tree["children"]], [2])

    def test_case_insensitive_field_names_and_folding(self):
        # 字段名大小写不敏感；In-Reply-To 折行续行展开后仍能取出尖括号 ID
        raw = (
            "message-id: <child@x>\n"
            "IN-REPLY-TO: pre\n"
            "\t<a@x> post\n"
        )
        mails = [_mail(1, mid="a@x"), raw]
        r = thread_analysis(mails)
        self.assertEqual(r["messages"][1]["parent_index"], 1)

    def test_unparseable_header_reports_error_but_others_continue(self):
        mails = [_mail(1, mid="a@x"), "   ", _mail(3, mid="b@x", irt="<a@x>")]
        r = thread_analysis(mails)
        self.assertNotIn("error", r)
        self.assertEqual(r["message_count"], 3)
        self.assertEqual(r["parsed_count"], 2)
        self.assertEqual(r["message_errors"],
                         [{"index": 2, "error": "该头部无法解析为任何邮件字段"}])
        self.assertEqual(r["edge_count"], 1)

    def test_all_unparseable_is_error(self):
        r = thread_analysis(["   ", "\n"])
        self.assertIn("error", r)
        self.assertEqual(r["parsed_count"], 0)
        self.assertEqual(len(r["message_errors"]), 2)

    def test_empty_list_is_error(self):
        self.assertIn("error", thread_analysis([]))


class SampleThreadTests(unittest.TestCase):
    def setUp(self):
        self.parts = split_batch_headers(SAMPLE_HEADERS_THREAD)

    def test_sample_splits_into_twelve(self):
        self.assertEqual(len(self.parts), 12)

    def test_sample_overall_counts(self):
        r = thread_analysis(self.parts)
        self.assertEqual(r["parsed_count"], 12)
        self.assertEqual(r["edge_count"], 3)      # 1->2, 2->3, 2->4
        self.assertEqual(r["tree_count"], 2)      # 主树 + 外部引用根 #5
        self.assertEqual(r["orphan_count"], 1)    # #6
        self.assertEqual(r["external_count"], 1)  # #5 的批次外父 ID
        # #7 多 ID、#8/#9 重复 MID、#10 指向重复 ID、#11/#12 成环
        self.assertEqual(r["ambiguous_count"], 6)

    def test_sample_main_tree_shape(self):
        r = thread_analysis(self.parts)
        main_tree = next(t for t in r["trees"] if t["root_index"] == 1)
        root = main_tree["node"]
        self.assertIsNone(main_tree["external_parent_id"])
        self.assertEqual([c["index"] for c in root["children"]], [2])
        child2 = root["children"][0]
        self.assertEqual(sorted(c["index"] for c in child2["children"]), [3, 4])
        # #4 通过 References 末项连到 #2
        msg4 = next(m for m in r["messages"] if m["index"] == 4)
        self.assertEqual(msg4["basis"], "references")

    def test_sample_external_ref(self):
        r = thread_analysis(self.parts)
        ext = r["external_refs"]
        self.assertEqual(ext[0]["message_id"], "message-outside-batch@external.example")
        self.assertEqual(ext[0]["referenced_by"], [5])

    def test_sample_ambiguity_codes(self):
        r = thread_analysis(self.parts)
        codes = {m["index"]: m["ambiguity_codes"] for m in r["messages"]}
        self.assertEqual(codes[7], ["multiple_in_reply_to"])
        self.assertEqual(codes[8], ["duplicate_message_id"])
        self.assertEqual(codes[9], ["duplicate_message_id"])
        self.assertEqual(codes[10], ["duplicate_message_id"])
        self.assertEqual(codes[11], ["cycle"])
        self.assertEqual(codes[12], ["cycle"])


@unittest.skipIf(create_app is None, "未安装 Flask，跳过 API 测试")
class ThreadApiTests(unittest.TestCase):
    def setUp(self):
        self.client = create_app().test_client()

    def test_api_thread_ok(self):
        parts = split_batch_headers(SAMPLE_HEADERS_THREAD)
        resp = self.client.post("/api/thread-relations", json={"headers": parts})
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["parsed_count"], 12)
        self.assertEqual(data["tree_count"], 2)
        self.assertIn("messages", data)
        self.assertIn("ambiguous_messages", data)

    def test_api_thread_accepts_single_header(self):
        resp = self.client.post(
            "/api/thread-relations",
            json={"headers": ["Message-ID: <a@x>\nSubject: one\n"]},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["orphan_count"], 1)

    def test_api_thread_requires_json(self):
        resp = self.client.post("/api/thread-relations", data={"headers": "x"})
        self.assertEqual(resp.status_code, 400)

    def test_api_thread_rejects_non_list(self):
        resp = self.client.post("/api/thread-relations", json={"headers": "nope"})
        self.assertEqual(resp.status_code, 400)
        self.assertIn("字符串数组", resp.get_json()["error"])

    def test_api_thread_rejects_non_string_items(self):
        resp = self.client.post(
            "/api/thread-relations", json={"headers": ["Message-ID: <a@x>", 1]}
        )
        self.assertEqual(resp.status_code, 400)

    def test_api_thread_rejects_empty_list_and_blank_items(self):
        self.assertEqual(
            self.client.post("/api/thread-relations", json={"headers": []}).status_code,
            400,
        )
        resp = self.client.post(
            "/api/thread-relations", json={"headers": ["Message-ID: <a@x>", " "]}
        )
        self.assertEqual(resp.status_code, 400)

    def test_form_page_renders_tree(self):
        resp = self.client.post(
            "/thread-relations", data={"headers_thread": SAMPLE_HEADERS_THREAD}
        )
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn("邮件会话关系结果", html)
        self.assertIn("会话树", html)
        self.assertIn("孤立邮件", html)
        self.assertIn("外部引用", html)
        self.assertIn("逐封关联依据", html)

    def test_form_page_no_delimiter_single(self):
        resp = self.client.post(
            "/thread-relations",
            data={"headers_thread": "Message-ID: <a@x>\nSubject: single\n"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn("邮件会话关系结果", resp.get_data(as_text=True))

    def test_form_page_empty_input_shows_banner(self):
        resp = self.client.post("/thread-relations", data={"headers_thread": "   "})
        self.assertEqual(resp.status_code, 200)
        self.assertIn("未识别到任何邮件头部", resp.get_data(as_text=True))


if __name__ == "__main__":
    unittest.main()
