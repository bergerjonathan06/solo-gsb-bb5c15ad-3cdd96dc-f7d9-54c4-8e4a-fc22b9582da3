"""退信回执（DSN）判读单元测试。"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mailtrace.parsing import inspect_dsn  # noqa: E402
from mailtrace.parsing.sample import SAMPLE_DSN  # noqa: E402

try:  # Flask 相关测试在未安装 Flask 时跳过（解析核心仅需标准库）
    from app import create_app
except ImportError:  # pragma: no cover
    create_app = None


def dsn_mail(body: str, boundary: str = "B") -> str:
    """构造一封含单个 message/delivery-status 部分的完整 multipart/report。"""
    return (
        "From: Mailer-Daemon <md@mx.example>\r\n"
        "Content-Type: multipart/report; report-type=delivery-status;\r\n"
        f' boundary="{boundary}"\r\n\r\n'
        f"--{boundary}\r\n"
        "Content-Type: text/plain\r\n\r\n"
        "human readable bounce notice\r\n"
        f"--{boundary}\r\n"
        "Content-Type: message/delivery-status\r\n\r\n"
        f"{body}\r\n"
        f"--{boundary}\r\n"
        "Content-Type: message/rfc822\r\n\r\n"
        "Subject: original message\r\n\r\noriginal body\r\n"
        f"--{boundary}--\r\n"
    )


def recipient_block(recipient, action, status, diag=None, extra=""):
    lines = [
        f"Final-Recipient: rfc822; {recipient}",
        f"Action: {action}",
        f"Status: {status}",
    ]
    if diag is not None:
        lines.append(f"Diagnostic-Code: smtp;{diag}")
    if extra:
        lines.append(extra)
    # DSN 字段块之间必须以空行分隔（RFC 3464）
    return "\n".join(lines) + "\n\n"


ENVELOPE = "Reporting-MTA: dns;mx.example\n\n"


class BasicExtractionTests(unittest.TestCase):
    def test_full_mail_parsed_per_recipient(self):
        body = ENVELOPE + recipient_block(
            "gone@example.com", "failed", "5.1.1", "550 5.1.1 no such user"
        )
        result = inspect_dsn(dsn_mail(body))
        self.assertNotIn("error", result)
        self.assertEqual(result["dsn_part_count"], 1)
        self.assertEqual(result["recipient_count"], 1)
        r = result["recipients"][0]
        self.assertEqual(r["final_recipient"], "gone@example.com")
        self.assertEqual(r["recipient_type"], "rfc822")
        self.assertEqual(r["action"], "failed")
        self.assertEqual(r["status"], "5.1.1")
        self.assertEqual(r["status_class"], "5")
        self.assertEqual(r["result"], "permanent")
        self.assertFalse(r["review"])
        self.assertEqual(r["diagnostic_type"], "smtp")
        self.assertEqual(r["diagnostic_code"], "550 5.1.1 no such user")
        self.assertEqual(r["reporting_mta"], "dns;mx.example")
        # 原始字段文本保留（含字段名）
        self.assertIn("Final-Recipient: rfc822; gone@example.com",
                      r["raw_fields"]["final_recipient"])

    def test_order_preserved_for_multiple_recipients(self):
        body = ENVELOPE
        body += recipient_block("a@example.com", "failed", "5.1.1")
        body += recipient_block("b@example.com", "delayed", "4.7.1")
        body += recipient_block("c@example.com", "delivered", "2.0.0")
        result = inspect_dsn(dsn_mail(body))
        self.assertEqual(
            [r["final_recipient"] for r in result["recipients"]],
            ["a@example.com", "b@example.com", "c@example.com"],
        )
        self.assertEqual([r["index"] for r in result["recipients"]], [1, 2, 3])

    def test_status_classes_classify_independently(self):
        body = ENVELOPE
        body += recipient_block("ok@example.com", "delivered", "2.0.0")
        body += recipient_block("wait@example.com", "delayed", "4.2.2")
        body += recipient_block("dead@example.com", "failed", "5.7.1")
        result = inspect_dsn(dsn_mail(body))
        by_addr = {r["final_recipient"]: r["result"]
                   for r in result["recipients"]}
        self.assertEqual(by_addr["ok@example.com"], "success")
        self.assertEqual(by_addr["wait@example.com"], "deferred")
        self.assertEqual(by_addr["dead@example.com"], "permanent")
        self.assertEqual(result["success_count"], 1)
        self.assertEqual(result["deferred_count"], 1)
        self.assertEqual(result["permanent_count"], 1)
        self.assertEqual(result["review_count"], 0)


class FoldingTests(unittest.TestCase):
    def test_folded_diagnostic_code_is_extracted_and_raw_kept(self):
        body = ENVELOPE + (
            "Final-Recipient: rfc822; gone@example.com\n"
            "Action: failed\n"
            "Status: 5.1.1\n"
            "Diagnostic-Code: smtp;550 mailbox\n"
            "\tdoes not exist (folded line)\n"
        )
        result = inspect_dsn(dsn_mail(body))
        r = result["recipients"][0]
        # 展示用的诊断原文：折行展开为可读文本
        self.assertEqual(
            r["diagnostic_code"],
            "550 mailbox does not exist (folded line)",
        )
        # 原始字段仍保留折行
        self.assertIn("\n", r["raw_fields"]["diagnostic_code"])
        self.assertIn("\tdoes not exist", r["raw_block"])


class ReviewTests(unittest.TestCase):
    def test_missing_status_is_review(self):
        body = ENVELOPE + (
            "Final-Recipient: rfc822; a@example.com\n"
            "Action: failed\n"
            "Diagnostic-Code: smtp;550 rejected\n"
        )
        result = inspect_dsn(dsn_mail(body))
        r = result["recipients"][0]
        self.assertEqual(r["result"], "review")
        self.assertTrue(r["review"])
        self.assertIsNone(r["status"])
        self.assertTrue(any("Status" in why for why in r["review_reasons"]))

    def test_unparseable_status_is_review(self):
        body = ENVELOPE + recipient_block("a@example.com", "failed", "bogus")
        result = inspect_dsn(dsn_mail(body))
        r = result["recipients"][0]
        self.assertEqual(r["result"], "review")
        self.assertTrue(any("增强状态码" in why for why in r["review_reasons"]))

    def test_status_5_vs_delayed_action_contradiction(self):
        body = ENVELOPE + recipient_block(
            "a@example.com", "delayed", "5.1.1"
        )
        result = inspect_dsn(dsn_mail(body))
        r = result["recipients"][0]
        self.assertEqual(r["result"], "review")
        self.assertTrue(any("矛盾" in why for why in r["review_reasons"]))

    def test_status_4_vs_failed_action_contradiction(self):
        body = ENVELOPE + recipient_block(
            "a@example.com", "failed", "4.4.1"
        )
        result = inspect_dsn(dsn_mail(body))
        r = result["recipients"][0]
        self.assertEqual(r["result"], "review")
        self.assertTrue(any("矛盾" in why for why in r["review_reasons"]))

    def test_status_2_vs_failed_action_contradiction(self):
        body = ENVELOPE + recipient_block(
            "a@example.com", "failed", "2.0.0"
        )
        result = inspect_dsn(dsn_mail(body))
        self.assertEqual(result["recipients"][0]["result"], "review")

    def test_action_value_case_insensitive(self):
        body = ENVELOPE + recipient_block(
            "a@example.com", "FAILED", "5.1.1"
        )
        result = inspect_dsn(dsn_mail(body))
        r = result["recipients"][0]
        self.assertEqual(r["action"], "failed")
        self.assertEqual(r["result"], "permanent")

    def test_unknown_action_noted(self):
        body = ENVELOPE + recipient_block(
            "a@example.com", "bounced", "5.1.1"
        )
        result = inspect_dsn(dsn_mail(body))
        r = result["recipients"][0]
        # Status=5 明确，不判成待核对；但 Action 无法识别被记入提示
        self.assertEqual(r["result"], "permanent")
        self.assertFalse(r["review"])
        self.assertTrue(any("bounced" in why for why in r["notes"]))

    def test_action_missing_with_status_still_classified(self):
        body = ENVELOPE + (
            "Final-Recipient: rfc822; a@example.com\n"
            "Status: 4.7.1\n"
        )
        result = inspect_dsn(dsn_mail(body))
        r = result["recipients"][0]
        self.assertEqual(r["result"], "deferred")
        self.assertIsNone(r["action"])
        self.assertEqual(r["review_reasons"], [])

    def test_missing_diagnostic_code_reported_as_none(self):
        body = ENVELOPE + recipient_block(
            "a@example.com", "failed", "5.1.1", diag=None
        )
        result = inspect_dsn(dsn_mail(body))
        r = result["recipients"][0]
        self.assertIsNone(r["diagnostic_code"])
        self.assertIsNone(r["raw_fields"]["diagnostic_code"])
        self.assertEqual(r["result"], "permanent")

    def test_relayed_and_expanded_match_class_2(self):
        for action in ("relayed", "expanded"):
            with self.subTest(action=action):
                body = ENVELOPE + recipient_block(
                    f"{action}@example.com", action, "2.0.0"
                )
                result = inspect_dsn(dsn_mail(body))
                self.assertEqual(
                    result["recipients"][0]["result"], "success"
                )

    def test_duplicate_field_flagged(self):
        body = ENVELOPE + (
            "Final-Recipient: rfc822; a@example.com\n"
            "Action: failed\n"
            "Status: 5.1.1\n"
            "Status: 4.7.1\n"
            "Diagnostic-Code: smtp;550 rejected\n\n"
        )
        result = inspect_dsn(dsn_mail(body))
        r = result["recipients"][0]
        self.assertEqual(r["result"], "review")
        self.assertTrue(r["review"])
        self.assertTrue(
            any("Status 字段" in why and "出现 2 次" in why
                for why in r["review_reasons"])
        )

    def test_empty_recipient_value_forces_review(self):
        body = ENVELOPE + (
            "Final-Recipient: rfc822;\n"
            "Action: failed\n"
            "Status: 5.1.1\n\n"
        )
        result = inspect_dsn(dsn_mail(body))
        r = result["recipients"][0]
        self.assertEqual(r["result"], "review")
        self.assertIsNone(r["final_recipient"])
        self.assertTrue(
            any("Final-Recipient" in why for why in r["review_reasons"])
        )


class MIMEStructureTests(unittest.TestCase):
    def test_no_dsn_part_returns_error(self):
        result = inspect_dsn(
            "Subject: just a normal mail\n\nhello\n"
        )
        self.assertIn("error", result)
        self.assertIn("message/delivery-status", result["error"])

    def test_text_plain_bounce_notice_is_not_enough(self):
        mail = (
            "Content-Type: multipart/mixed; boundary=B\n\n"
            "--B\nContent-Type: text/plain\n\n"
            "Delivery Status Notification (Failure): 550 user unknown\n"
            "--B--\n"
        )
        result = inspect_dsn(mail)
        self.assertIn("error", result)

    def test_headers_only_delivery_status_text_not_enough(self):
        # 只有头部文本（其他模块的输入），没有 MIME DSN 部分
        result = inspect_dsn(
            "Received: by mx.example\n"
            "Status: 5.1.1\n"
            "Final-Recipient: rfc822; a@example.com\n"
        )
        self.assertIn("error", result)

    def test_multiple_dsn_parts_concatenated_in_order(self):
        # 同一邮件中两个 DSN 部分（非典型，但解析应按顺序合并）
        source = (
            "Content-Type: multipart/mixed; boundary=B\n\n"
            "--B\n"
            "Content-Type: message/delivery-status\n\n"
            "Final-Recipient: rfc822; first@example.com\n"
            "Action: failed\nStatus: 5.1.1\n\n"
            "--B\n"
            "Content-Type: message/delivery-status\n\n"
            "Final-Recipient: rfc822; second@example.com\n"
            "Action: delayed\nStatus: 4.7.1\n\n"
            "--B--\n"
        )
        result = inspect_dsn(source)
        self.assertEqual(result["dsn_part_count"], 2)
        self.assertEqual(
            [(r["final_recipient"], r["dsn_part"])
             for r in result["recipients"]],
            [("first@example.com", 1), ("second@example.com", 2)],
        )

    def test_dsn_without_envelope_block_still_extracts(self):
        body = recipient_block("a@example.com", "failed", "5.1.1")
        result = inspect_dsn(dsn_mail(body))
        self.assertEqual(result["envelope_count"], 0)
        self.assertEqual(result["recipient_count"], 1)
        self.assertIsNone(result["recipients"][0]["reporting_mta"])

    def test_diagnostic_code_without_type(self):
        body = ENVELOPE + (
            "Final-Recipient: rfc822; a@example.com\n"
            "Action: failed\n"
            "Status: 5.1.1\n"
            "Diagnostic-Code: connection refused by destination\n"
        )
        result = inspect_dsn(dsn_mail(body))
        r = result["recipients"][0]
        self.assertIsNone(r["diagnostic_type"])
        self.assertEqual(
            r["diagnostic_code"], "connection refused by destination"
        )

    def test_final_recipient_without_type(self):
        body = ENVELOPE + (
            "Final-Recipient: plain@example.com\n"
            "Action: failed\nStatus: 5.1.1\n"
        )
        result = inspect_dsn(dsn_mail(body))
        r = result["recipients"][0]
        self.assertEqual(r["final_recipient"], "plain@example.com")
        self.assertIsNone(r["recipient_type"])


class SampleTests(unittest.TestCase):
    def test_sample_has_mixed_results(self):
        result = inspect_dsn(SAMPLE_DSN)
        self.assertNotIn("error", result)
        self.assertEqual(result["recipient_count"], 4)
        self.assertEqual(result["success_count"], 1)
        self.assertEqual(result["deferred_count"], 1)
        self.assertEqual(result["permanent_count"], 1)
        self.assertEqual(result["review_count"], 1)
        results = [r["result"] for r in result["recipients"]]
        self.assertEqual(
            results, ["permanent", "deferred", "success", "review"]
        )


@unittest.skipIf(create_app is None, "未安装 Flask")
class DsnApiTests(unittest.TestCase):
    def setUp(self):
        self.client = create_app().test_client()

    def test_api_success_structure(self):
        resp = self.client.post(
            "/api/dsn/inspect", json={"source": SAMPLE_DSN}
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data, inspect_dsn(SAMPLE_DSN))
        self.assertEqual(data["recipient_count"], 4)

    def test_api_no_dsn_returns_400(self):
        resp = self.client.post(
            "/api/dsn/inspect",
            json={"source": "Subject: hi\n\nbody"},
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("message/delivery-status", resp.get_json()["error"])

    def test_api_empty_returns_400(self):
        resp = self.client.post(
            "/api/dsn/inspect", json={"source": "  "}
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("error", resp.get_json())

    def test_api_non_json_returns_400(self):
        resp = self.client.post(
            "/api/dsn/inspect", data={"source": SAMPLE_DSN}
        )
        self.assertEqual(resp.status_code, 400)

    def test_api_non_string_source_returns_400(self):
        resp = self.client.post(
            "/api/dsn/inspect", json={"source": 123}
        )
        self.assertEqual(resp.status_code, 400)

    def test_api_size_limit_returns_400(self):
        app = create_app()
        app.config["MAX_INPUT_BYTES"] = 64
        client = app.test_client()
        resp = client.post(
            "/api/dsn/inspect", json={"source": "x" * 1024}
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("上限", resp.get_json()["error"])

    def test_form_page_renders_recipients(self):
        resp = self.client.post(
            "/dsn-inspect", data={"source_dsn": SAMPLE_DSN}
        )
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn("退信回执判读结果", html)
        self.assertIn("gone@final.example", html)
        self.assertIn("weird@final.example", html)
        self.assertIn("待核对", html)
        self.assertIn("550 5.1.1", html)

    def test_index_page_has_dsn_section(self):
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn("退信回执判读", html)
        self.assertIn("/api/dsn/inspect", html)


if __name__ == "__main__":
    unittest.main()
