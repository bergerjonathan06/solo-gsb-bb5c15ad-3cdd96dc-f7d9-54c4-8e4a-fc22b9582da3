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


def _block(final=None, action=None, status=None, diag=None, extra=None):
    """构造一个收件人报告块（字段按给定顺序书写）。"""
    lines = []
    if final:
        lines.append(f"Final-Recipient: {final}")
    if action:
        lines.append(f"Action: {action}")
    if status:
        lines.append(f"Status: {status}")
    if diag:
        lines.append(f"Diagnostic-Code: {diag}")
    if extra:
        lines.extend(extra)
    return "\n".join(lines)


def _dsn(*blocks, per_message="Reporting-MTA: dns; mx.example"):
    """把若干收件人报告块包装成完整的 multipart/report 退信邮件。"""
    body = per_message + "\n\n" + "\n\n".join(blocks)
    return (
        "From: MAILER-DAEMON@mx.example\n"
        "To: sender@example.com\n"
        "Subject: Undelivered Mail Returned to Sender\n"
        "MIME-Version: 1.0\n"
        'Content-Type: multipart/report; report-type=delivery-status; boundary="BB"\n'
        "\n"
        "--BB\n"
        "Content-Type: text/plain; charset=us-ascii\n"
        "\n"
        "human readable explanation (not parsed)\n"
        "--BB\n"
        "Content-Type: message/delivery-status\n"
        "\n"
        + body
        + "\n--BB--\n"
    )


FAILED_5 = _block(
    "rfc822; alice@dest.example",
    "failed",
    "5.1.1",
    "smtp; 550 5.1.1 <alice@dest.example>: Recipient address rejected",
)
DELAYED_4 = _block(
    "rfc822; bob@slow.example",
    "delayed",
    "4.4.1",
    "smtp; 454 4.4.1 <bob@slow.example>: Connection timed out",
)
DELIVERED_2 = _block(
    "rfc822; carol@ok.example",
    "delivered",
    "2.0.0",
    "smtp; 250 2.0.0 Ok: queued as 9F1C2E",
)


class ClassifyTests(unittest.TestCase):
    def test_status_classes_2_4_5(self):
        result = inspect_dsn(_dsn(DELIVERED_2, DELAYED_4, FAILED_5))
        self.assertEqual(result["recipient_count"], 3)
        verdicts = [r["verdict"] for r in result["recipients"]]
        self.assertEqual(verdicts, ["success", "transient", "permanent"])
        self.assertEqual(result["success_count"], 1)
        self.assertEqual(result["transient_count"], 1)
        self.assertEqual(result["permanent_count"], 1)
        self.assertEqual(result["review_count"], 0)

    def test_recipient_order_preserved(self):
        result = inspect_dsn(_dsn(FAILED_5, DELIVERED_2, DELAYED_4))
        addresses = [r["final_recipient_address"] for r in result["recipients"]]
        self.assertEqual(
            addresses,
            ["alice@dest.example", "carol@ok.example", "bob@slow.example"],
        )
        self.assertEqual([r["index"] for r in result["recipients"]], [1, 2, 3])

    def test_missing_status_is_review(self):
        block = _block("rfc822; a@b.example", "failed", None, "smtp; 550 nope")
        result = inspect_dsn(_dsn(block))
        entry = result["recipients"][0]
        self.assertEqual(entry["verdict"], "review")
        self.assertEqual(entry["verdict_label"], "待核对")
        self.assertIsNone(entry["status"])
        self.assertTrue(any("缺少 Status" in r for r in entry["reasons"]))
        self.assertEqual(result["review_count"], 1)

    def test_unparseable_status_is_review(self):
        block = _block("rfc822; a@b.example", "failed", "permanent error")
        result = inspect_dsn(_dsn(block))
        entry = result["recipients"][0]
        self.assertEqual(entry["verdict"], "review")
        self.assertTrue(any("无法解析" in r for r in entry["reasons"]))

    def test_status_class_out_of_range_is_review(self):
        block = _block("rfc822; a@b.example", "failed", "1.2.3")
        result = inspect_dsn(_dsn(block))
        entry = result["recipients"][0]
        self.assertEqual(entry["verdict"], "review")
        self.assertTrue(any("不在 2/4/5" in r for r in entry["reasons"]))

    def test_action_status_contradiction_is_review(self):
        # Action=failed 却配 2.x 成功状态
        block = _block("rfc822; a@b.example", "failed", "2.0.0")
        result = inspect_dsn(_dsn(block))
        entry = result["recipients"][0]
        self.assertEqual(entry["verdict"], "review")
        self.assertEqual(entry["status_class"], 2)
        self.assertTrue(any("矛盾" in r for r in entry["reasons"]))

    def test_action_delivered_with_5xx_is_review(self):
        block = _block("rfc822; a@b.example", "delivered", "5.1.1")
        result = inspect_dsn(_dsn(block))
        entry = result["recipients"][0]
        self.assertEqual(entry["verdict"], "review")
        self.assertTrue(any("矛盾" in r for r in entry["reasons"]))

    def test_consistent_action_not_review(self):
        result = inspect_dsn(_dsn(FAILED_5))
        entry = result["recipients"][0]
        self.assertEqual(entry["verdict"], "permanent")
        self.assertEqual(entry["reasons"], [])

    def test_relayed_action_not_cross_checked(self):
        # relayed / expanded 不对应确定 Status 类别，不做矛盾检查
        block = _block("rfc822; a@b.example", "relayed", "2.0.0")
        result = inspect_dsn(_dsn(block))
        self.assertEqual(result["recipients"][0]["verdict"], "success")

    def test_missing_action_still_classified_by_status(self):
        block = _block("rfc822; a@b.example", None, "5.0.0")
        result = inspect_dsn(_dsn(block))
        entry = result["recipients"][0]
        self.assertEqual(entry["verdict"], "permanent")
        self.assertIsNone(entry["action"])

    def test_no_single_overall_verdict(self):
        # 混合结果不归并：每个收件人各自判定，整体只给计数
        result = inspect_dsn(_dsn(FAILED_5, DELIVERED_2))
        self.assertEqual(result["permanent_count"], 1)
        self.assertEqual(result["success_count"], 1)
        self.assertNotIn("verdict", result)
        self.assertNotIn("status", result)


class StructureTests(unittest.TestCase):
    def test_no_delivery_status_part_is_error(self):
        raw = "From: a@b.example\nTo: c@d.example\nSubject: hi\n\nplain body\n"
        result = inspect_dsn(raw)
        self.assertIn("error", result)
        self.assertIn("message/delivery-status", result["error"])

    def test_delivery_status_without_recipient_block_is_error(self):
        raw = _dsn("", per_message="Reporting-MTA: dns; mx.example")
        result = inspect_dsn(raw)
        self.assertIn("error", result)
        self.assertIn("收件人报告块", result["error"])

    def test_only_delivery_status_part_is_read(self):
        # text/plain 部分里的“字段样”文本不得被当作报告块
        raw = _dsn(FAILED_5).replace(
            "human readable explanation (not parsed)",
            "Final-Recipient: rfc822; fake@evil.example\n"
            "Action: failed\n"
            "Status: 5.9.9\n",
        )
        result = inspect_dsn(raw)
        self.assertEqual(result["recipient_count"], 1)
        self.assertEqual(
            result["recipients"][0]["final_recipient_address"],
            "alice@dest.example",
        )

    def test_top_level_delivery_status_message(self):
        raw = (
            "Content-Type: message/delivery-status\n"
            "\n"
            "Reporting-MTA: dns; mx.example\n"
            "\n"
            "Final-Recipient: rfc822; a@b.example\n"
            "Action: failed\n"
            "Status: 5.0.0\n"
        )
        result = inspect_dsn(raw)
        self.assertEqual(result["recipient_count"], 1)
        self.assertEqual(result["recipients"][0]["verdict"], "permanent")

    def test_mbox_from_line_tolerated(self):
        raw = "From MAILER-DAEMON Thu Sep 24 03:05:00 2026\n" + _dsn(FAILED_5)
        result = inspect_dsn(raw)
        self.assertEqual(result["recipient_count"], 1)

    def test_crlf_line_endings(self):
        raw = _dsn(FAILED_5, DELIVERED_2).replace("\n", "\r\n")
        result = inspect_dsn(raw)
        self.assertEqual(result["recipient_count"], 2)

    def test_folded_diagnostic_code_unfolded(self):
        block = _block(
            "rfc822; a@b.example",
            "failed",
            "5.1.1",
            "smtp; 550 5.1.1 <a@b.example>: Recipient address\n\trejected: User unknown",
        )
        result = inspect_dsn(_dsn(block))
        diag = result["recipients"][0]["diagnostic_code"]
        self.assertNotIn("\n", diag)
        self.assertIn("Recipient address rejected: User unknown", diag)

    def test_multiple_delivery_status_parts_keep_order(self):
        inner = _dsn(DELAYED_4)
        raw = _dsn(FAILED_5).replace(
            "--BB--",
            "--BB\n"
            "Content-Type: message/rfc822\n"
            "\n"
            + inner
            + "\n--BB--",
        )
        result = inspect_dsn(raw)
        self.assertEqual(result["part_count"], 2)
        self.assertEqual(result["recipient_count"], 2)
        self.assertEqual(
            [r["verdict"] for r in result["recipients"]],
            ["permanent", "transient"],
        )
        self.assertEqual(
            [r["part_index"] for r in result["recipients"]], [1, 2]
        )

    def test_final_recipient_address_extraction(self):
        result = inspect_dsn(_dsn(FAILED_5))
        entry = result["recipients"][0]
        self.assertEqual(entry["final_recipient"], "rfc822; alice@dest.example")
        self.assertEqual(entry["final_recipient_address"], "alice@dest.example")

    def test_fields_extracted_per_block(self):
        result = inspect_dsn(_dsn(FAILED_5))
        entry = result["recipients"][0]
        self.assertEqual(entry["action"], "failed")
        self.assertEqual(entry["status"], "5.1.1")
        self.assertEqual(entry["status_class"], 5)
        self.assertIn("550 5.1.1", entry["diagnostic_code"])

    def test_sample_dsn_covers_all_verdicts(self):
        result = inspect_dsn(SAMPLE_DSN)
        self.assertEqual(result["recipient_count"], 4)
        self.assertEqual(result["success_count"], 1)
        self.assertEqual(result["transient_count"], 1)
        self.assertEqual(result["permanent_count"], 1)
        self.assertEqual(result["review_count"], 1)
        review = [r for r in result["recipients"] if r["verdict"] == "review"][0]
        self.assertEqual(review["final_recipient_address"], "dave@conflict.example")
        self.assertTrue(any("矛盾" in r for r in review["reasons"]))


@unittest.skipIf(create_app is None, "Flask 未安装")
class DsnApiTests(unittest.TestCase):
    def setUp(self):
        self.client = create_app().test_client()

    def test_api_json_ok(self):
        resp = self.client.post("/api/dsn/inspect", json={"source": _dsn(FAILED_5)})
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data["recipient_count"], 1)
        self.assertEqual(data["recipients"][0]["verdict"], "permanent")
        self.assertEqual(data["recipients"][0]["status"], "5.1.1")
        self.assertIn("550 5.1.1", data["recipients"][0]["diagnostic_code"])

    def test_api_no_delivery_status_part_400(self):
        resp = self.client.post(
            "/api/dsn/inspect", json={"source": "Subject: hi\n\nbody\n"}
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("message/delivery-status", resp.get_json()["error"])

    def test_api_blank_source_400(self):
        resp = self.client.post("/api/dsn/inspect", json={"source": "   "})
        self.assertEqual(resp.status_code, 400)

    def test_api_non_string_source_400(self):
        resp = self.client.post("/api/dsn/inspect", json={"source": 123})
        self.assertEqual(resp.status_code, 400)
        self.assertIn("source", resp.get_json()["error"])

    def test_api_form_encoded(self):
        resp = self.client.post("/api/dsn/inspect", data={"source": _dsn(DELAYED_4)})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["transient_count"], 1)

    def test_api_oversize_returns_400(self):
        app = create_app()
        app.config["MAX_INPUT_BYTES"] = 64
        client = app.test_client()
        resp = client.post("/api/dsn/inspect", json={"source": "x" * 200})
        self.assertEqual(resp.status_code, 400)
        self.assertIn("上限", resp.get_json()["error"])

    def test_page_form_renders(self):
        resp = self.client.post("/dsn-inspect", data={"source_dsn": SAMPLE_DSN})
        self.assertEqual(resp.status_code, 200)
        body = resp.get_data(as_text=True)
        self.assertIn("退信回执判读结果", body)
        self.assertIn("alice@dest.example", body)
        self.assertIn("永久失败", body)
        self.assertIn("待核对", body)
        self.assertIn("550 5.1.1", body)

    def test_page_form_error_banner(self):
        resp = self.client.post("/dsn-inspect", data={"source_dsn": "Subject: hi\n"})
        self.assertEqual(resp.status_code, 200)
        self.assertIn("message/delivery-status", resp.get_data(as_text=True))

    def test_index_page_has_dsn_section(self):
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        html = resp.get_data(as_text=True)
        self.assertIn("退信回执判读", html)
        self.assertIn("/api/dsn/inspect", html)


if __name__ == "__main__":
    unittest.main()
