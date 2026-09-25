"""页面“填入示例”按钮使用的示例邮件头。"""

SAMPLE_HEADERS = """\
Return-Path: <sender@example.com>
Received: from mailbox.final.example (127.0.0.1)
	by mailbox.final.example (Dovecot) with LMTP id zX92kQ
	for <user@final.example>; Tue, 23 Sep 2026 10:02:10 +0800 (CST)
Received: from mx1.final.example (mx1.final.example [198.51.100.10])
	by mailbox.final.example (Postfix) with ESMTPS id 7F3A2C9
	for <user@final.example>; Tue, 23 Sep 2026 10:02:10 +0800
Received: from relay2.provider.example (relay2.provider.example [203.0.113.22])
	by mx1.final.example (Postfix) with ESMTP id B4D91
	for <user@final.example>; Tue, 23 Sep 2026 10:02:05 +0800
Received: from relay1.provider.example (relay1.provider.example
	[203.0.113.11])
	by relay2.provider.example (Postfix) with ESMTP id 99C10
	for <user@final.example>; Tue, 23 Sep 2026 02:01:55 +0000 (UTC)
Received: from outgoing.example.org (outgoing.example.org [192.0.2.50])
	by relay1.provider.example (Postfix) with ESMTP id 41AB8
	for <user@final.example>; Tue, 23 Sep 2026 02:01:30 +0000
Received: from smtp01.corp.example.net (smtp01.corp.example.net [10.10.0.5])
	by outgoing.example.org with ESMTP
	for user@final.example
Received: from [10.10.0.5] (helo=smtp01.corp.example.net)
	by smtp01.corp.example.net with ESMTP id 88FF21
	for user@final.example; not-a-valid-date (server clock lost)
Date: Tue, 23 Sep 2026 02:00:00 +0000
From: Sender <sender@example.com>
To: User <user@final.example>
Subject: Delivery path demo
	with folding
Message-ID: <demo@example.com>
"""

# 对照示例（B 侧）：与 SAMPLE_HEADERS 同一条投递链路，但
# - 开头多一跳 smtp00 -> smtp01（新增节点，且与既有 smtp01 同名，演示保序对齐）；
# - 末尾少了 Dovecot LMTP 一跳（缺失节点）；
# - 各跳时间不同（演示相邻耗时差值），smtp01 一跳时间有效而 A 侧无效（不可比较）。
SAMPLE_HEADERS_B = """\
Return-Path: <sender@example.com>
Received: from mx1.final.example (mx1.final.example [198.51.100.10])
	by mailbox.final.example (Postfix) with ESMTPS id 8C11D2
	for <user@final.example>; Tue, 23 Sep 2026 10:02:12 +0800
Received: from relay2.provider.example (relay2.provider.example [203.0.113.22])
	by mx1.final.example (Postfix) with ESMTP id C5E20
	for <user@final.example>; Tue, 23 Sep 2026 10:02:06 +0800
Received: from relay1.provider.example (relay1.provider.example [203.0.113.11])
	by relay2.provider.example (Postfix) with ESMTP id A1B33
	for <user@final.example>; Tue, 23 Sep 2026 02:01:58 +0000 (UTC)
Received: from outgoing.example.org (outgoing.example.org [192.0.2.50])
	by relay1.provider.example (Postfix) with ESMTP id 55BC9
	for <user@final.example>; Tue, 23 Sep 2026 02:01:33 +0000
Received: from smtp01.corp.example.net (smtp01.corp.example.net [10.10.0.5])
	by outgoing.example.org with ESMTP id 77D21
	for user@final.example; Tue, 23 Sep 2026 02:00:40 +0000
Received: from [10.10.0.5] (helo=smtp01.corp.example.net)
	by smtp01.corp.example.net with ESMTP id 91AA02
	for user@final.example; Tue, 23 Sep 2026 02:00:12 +0000
Received: from smtp00.corp.example.net (smtp00.corp.example.net [10.10.0.9])
	by smtp01.corp.example.net with ESMTP id 02BB77
	for user@final.example; Tue, 23 Sep 2026 02:00:05 +0000
Date: Tue, 23 Sep 2026 02:00:00 +0000
From: Sender <sender@example.com>
To: User <user@final.example>
Subject: Delivery path demo
"""


# 多封慢段归因示例：三封走同一条 edge -> mid -> final 链路的邮件，
# 用页面规范分隔符 BATCH_DELIMITER（===== 下一封邮件 =====）分开。
# - 邮件 1：正常投递，mid->final 段耗时 150 秒；
# - 邮件 2：edge->mid 耗时 600 秒（最慢段），mid->final 时间倒灌 -20 秒（排除）；
# - 邮件 3：mid->final 段时间无效（排除）；退信后发件方从同一 IP 重新注入，
#   edge->mid 同键区段在本封内出现两次（60 秒、150 秒），仅取最大有效
#   非负耗时 150 秒作为该邮件样本；退信/重注入路径另有仅本封出现的
#   mid->edge 回流段（60 秒）。
SAMPLE_HEADERS_BATCH = """\
Received: from mid.example (mid.example [198.51.100.20])
\tby final.example with ESMTP id M1C
\t; Tue, 23 Sep 2026 02:06:30 +0000
Received: from edge.example (edge.example [198.51.100.10])
\tby mid.example with ESMTP id M1B
\t; Tue, 23 Sep 2026 02:04:00 +0000
Received: from sender.example (sender.example [203.0.113.50])
\tby edge.example with ESMTP id M1A
\t; Tue, 23 Sep 2026 02:03:00 +0000
Date: Tue, 23 Sep 2026 02:03:00 +0000
From: sender@example.com
To: user@final.example
Subject: batch message 1
===== 下一封邮件 =====
Received: from mid.example (mid.example [198.51.100.20])
\tby final.example with ESMTP id M2C
\t; Tue, 23 Sep 2026 02:13:40 +0000
Received: from edge.example (edge.example [198.51.100.10])
\tby mid.example with ESMTP id M2B
\t; Tue, 23 Sep 2026 02:14:00 +0000
Received: from sender.example (sender.example [203.0.113.50])
\tby edge.example with ESMTP id M2A
\t; Tue, 23 Sep 2026 02:04:00 +0000
Date: Tue, 23 Sep 2026 02:04:00 +0000
From: sender@example.com
To: user@final.example
Subject: batch message 2
===== 下一封邮件 =====
Received: from mid.example (mid.example [198.51.100.20])
\tby final.example with ESMTP id M3D
\t; not-a-valid-date (clock lost on final)
Received: from edge.example (edge.example [198.51.100.10])
\tby mid.example with ESMTP id M3C
\t; Tue, 23 Sep 2026 02:21:00 +0000
Received: from sender.example (sender.example [203.0.113.50])
\tby edge.example with ESMTP id M3B
\t; Tue, 23 Sep 2026 02:18:30 +0000
Received: from edge.example (edge.example [198.51.100.10])
\tby mid.example with ESMTP id M3A2
\t; Tue, 23 Sep 2026 02:17:30 +0000
Received: from sender.example (sender.example [203.0.113.50])
\tby edge.example with ESMTP id M3A
\t; Tue, 23 Sep 2026 02:16:30 +0000
Date: Tue, 23 Sep 2026 02:16:30 +0000
From: sender@example.com
To: user@final.example
Subject: batch message 3
"""

# ARC 链结构检查示例：完整的两实例 ARC 链（i=1 为首个实例，cv=none；
# i=2 为后续实例，cv=pass）。ARC 字段由接收方在顶部追加，因此原文中
# i=2 的字段组写在 i=1 之前；字段含折行，且 i=1 的 ARC-Seal 故意把
# cv 写在 i 前面（解析与标签书写顺序无关）。
SAMPLE_HEADERS_ARC = """\
ARC-Seal: i=2; a=rsa-sha256; t=1790216000; cv=pass;
\td=relay.provider.example; s=arc2026;
\tb=Pm9fKq2wRelaySealSignature==
ARC-Message-Signature: i=2; a=rsa-sha256; c=relaxed/relaxed;
\td=relay.provider.example; s=arc2026; t=1790216000;
\tbh=3vBsRelayBodyHash==; h=From:To:Subject:Date;
\tb=Zq8wRelayMessageSignature==
ARC-Authentication-Results: i=2; relay.provider.example;
\tspf=pass smtp.mailfrom=example.com;
\tdkim=pass header.d=example.com; dmarc=pass header.from=example.com
ARC-Seal: cv=none; i=1; a=rsa-sha256; t=1790215940;
\td=mx.final.example; s=arc2026; b=Xy7zEdgeSealSignature==
ARC-Message-Signature: i=1; a=rsa-sha256; c=relaxed/relaxed;
\td=mx.final.example; s=arc2026; t=1790215940;
\tbh=9wQzEdgeBodyHash==; h=From:To:Subject:Date;
\tb=Mn4vEdgeMessageSignature==
ARC-Authentication-Results: i=1; mx.final.example;
\tspf=pass smtp.mailfrom=example.com; dkim=pass header.d=example.com
Received: from relay.provider.example (relay.provider.example [203.0.113.22])
\tby mx.final.example with ESMTPS id A1B2C3
\tfor <user@final.example>; Thu, 24 Sep 2026 02:13:20 +0000
Date: Thu, 24 Sep 2026 02:12:40 +0000
From: Sender <sender@example.com>
To: User <user@final.example>
Subject: ARC chain demo
Message-ID: <arc-demo@example.com>
"""

# DKIM 头字段覆盖审计示例：两条 DKIM-Signature（由后到先的中继依次在顶部
# 追加，因此原文中转发方签名写在原始签名之前），字段名大小写与折行不影响解析。
# - 签名 2（example.com，第 2 个字段）h= 里 Received 出现两次：按 RFC 6376
#   自底部向上匹配，分别命中第 4、第 3 个字段（两个 Received 副本），
#   重复字段名不按集合合并；From/To/Subject/Date 各匹配一次。
# - 签名 1（forwarder.example，顶部字段）对第 2 条签名做了 countersignature
#   （h= 中含 dkim-signature，自底部向上命中第 2 条签名而不会匹配自身），
#   但未覆盖 To 与 Date，且多写了一个不存在的 X-Missing 字段。
# - To 有两个实际副本：转发时被注入到顶部的 extra-injected（第 7 个字段）
#   与原始的 User（第 8 个字段）；两条签名的 h= 都只有一个 To，自底部向上
#   命中原始副本后，被注入的第 7 个副本对每条签名都显示为“未覆盖”。
SAMPLE_HEADERS_DKIM = """\
DKIM-Signature: v=1; a=rsa-sha256; c=relaxed/relaxed;
\td=forwarder.example; s=sel2; t=1790216000;
\tbh=Rm9yd2FyZGVyQm9keUhhc2g=;
\th=Received:Received:DKIM-Signature:From:Subject:X-Missing;
\tb=Rm9yd2FyZGVyU2lnbmF0dXJl
DKIM-Signature: v=1; a=rsa-sha256; c=relaxed/relaxed;
\td=example.com; s=sel1; t=1790215940;
\tbh=T3JpZ2luYWxCb2R5SGFzaA==;
\th=Received:Received:From:To:Subject:Date:Message-ID;
\tb=T3JpZ2luYWxTaWduYXR1cmU=
Received: from mx.forwarder.example (mx.forwarder.example [198.51.100.8])
\tby gateway.final.example with ESMTPS id F9E8D7
\tfor <user@final.example>; Thu, 24 Sep 2026 02:13:30 +0000
Received: from relay.provider.example (relay.provider.example [203.0.113.22])
\tby mx.forwarder.example with ESMTPS id C6B5A4
\tfor <user@final.example>; Thu, 24 Sep 2026 02:13:00 +0000
Date: Thu, 24 Sep 2026 02:12:40 +0000
From: Sender <sender@example.com>
To: extra-injected@evil.example
To: User <user@final.example>
Subject: DKIM coverage demo
Message-ID: <dkim-demo@example.com>
"""

# 接收链可信边界示例：
# 头部自上而下的 by 主机为
#   edge.internal.corp -> gw2.internal.corp -> relay2.partner.example
#   -> gw2.internal.corp（边界之外再次出现本组织主机名：外部主机冒用 /
#      伪造的 Received，不得重新接入可信链）-> edge.external.example
# 本组织名单 edge.internal.corp / gw2.internal.corp 命中前两跳，
# 边界在第 3 跳（relay2.partner.example），最后可信跳（第 2 跳）记录的
# from 主机 gateway.partner.example 与对端 IP 203.0.113.55 即外部交接点；
# 第 4 跳 by 虽再次命中名单，也明确标记为“边界之后，不重新接入”。
SAMPLE_HEADERS_TRUST = """\
Received: from gw2.internal.corp (gw2.internal.corp [10.20.0.2])
\tby edge.internal.corp (Postfix) with ESMTPS id A101
\tfor <user@corp.example>; Thu, 24 Sep 2026 03:05:10 +0000
Received: from gateway.partner.example (gateway.partner.example [203.0.113.55])
\tby gw2.internal.corp (Postfix) with ESMTP id B202
\tfor <user@corp.example>; Thu, 24 Sep 2026 03:04:30 +0000
Received: from relay1.external.example (relay1.external.example [198.51.100.20])
\tby relay2.partner.example (Postfix) with ESMTP id C303
\tfor <user@corp.example>; Thu, 24 Sep 2026 03:03:50 +0000
Received: from edge.external.example (edge.external.example [192.0.2.77])
\tby gw2.internal.corp (Postfix) with ESMTP id D404
\tfor <user@corp.example>; Thu, 24 Sep 2026 03:03:00 +0000
Received: from sender.external.example (sender.external.example [192.0.2.90])
\tby edge.external.example (Postfix) with ESMTP id E505
\tfor <user@corp.example>; Thu, 24 Sep 2026 03:02:10 +0000
Date: Thu, 24 Sep 2026 03:02:00 +0000
From: Sender <sender@external.example>
To: User <user@corp.example>
Subject: Trust boundary demo
Message-ID: <trust-demo@external.example>
"""

# 本组织接收服务器主机名示例名单（每行一个；末尾点演示规范化去重）
SAMPLE_TRUSTED_HOSTS = """\
edge.internal.corp
GW2.Internal.Corp.
"""

# 认证结果来源示例（与可信边界示例同一条链路，可信前缀为
# edge.internal.corp / gw2.internal.corp 两跳）：
# - 第 1 条 AR（mx.forged.example）：其后紧邻的 Received 是第 1 跳
#   （可信），但 authserv-id 与该跳 by 主机不一致 → 身份不符；
# - 第 2 条 AR（edge.internal.corp）：归属第 1 跳 → 本组织声明，
#   含两条 dkim 声明（pass / fail 各一，按原文顺序保留重复）；
# - 第 3 条 AR（gw2.internal.corp）：归属第 2 跳 → 本组织声明；
# - 第 4 条 AR（relay2.partner.example）：对应第 3 跳（即可信边界）
#   → 越过边界；
# - 第 5 条 AR（gw2.internal.corp）：对应第 4 跳（边界之后再次冒用
#   本组织主机名的伪造 Received）→ 越过边界（authserv-id 与 by
#   一致也不接入）；
# - 第 6 条 AR（archive.external.example）：写在最后一条 Received
#   之下 → 无对应跳。
SAMPLE_HEADERS_AUTHRES = """\
Authentication-Results: mx.forged.example;
\tspf=pass smtp.mailfrom=spoof.example; dmarc=pass header.from=spoof.example
Authentication-Results: edge.internal.corp;
\tspf=pass smtp.mailfrom=partner.example;
\tdkim=pass header.d=partner.example; dkim=fail header.d=attacker.example;
\tdmarc=pass header.from=partner.example
Received: from gw2.internal.corp (gw2.internal.corp [10.20.0.2])
\tby edge.internal.corp (Postfix) with ESMTPS id A101
\tfor <user@corp.example>; Thu, 24 Sep 2026 03:05:10 +0000
Authentication-Results: gw2.internal.corp;
\tspf=softfail smtp.mailfrom=partner.example;
\tdkim=pass header.d=partner.example; dmarc=fail header.from=partner.example
Received: from gateway.partner.example (gateway.partner.example [203.0.113.55])
\tby gw2.internal.corp (Postfix) with ESMTP id B202
\tfor <user@corp.example>; Thu, 24 Sep 2026 03:04:30 +0000
Authentication-Results: relay2.partner.example;
\tspf=pass smtp.mailfrom=external.example;
\tdkim=pass header.d=external.example; dmarc=pass header.from=external.example
Received: from relay1.external.example (relay1.external.example [198.51.100.20])
\tby relay2.partner.example (Postfix) with ESMTP id C303
\tfor <user@corp.example>; Thu, 24 Sep 2026 03:03:50 +0000
Authentication-Results: gw2.internal.corp; spf=pass smtp.mailfrom=spoof.example
Received: from edge.external.example (edge.external.example [192.0.2.77])
\tby gw2.internal.corp (Postfix) with ESMTP id D404
\tfor <user@corp.example>; Thu, 24 Sep 2026 03:03:00 +0000
Received: from sender.external.example (sender.external.example [192.0.2.90])
\tby edge.external.example (Postfix) with ESMTP id E505
\tfor <user@corp.example>; Thu, 24 Sep 2026 03:02:10 +0000
Authentication-Results: archive.external.example; spf=none
Date: Thu, 24 Sep 2026 03:02:00 +0000
From: Sender <sender@external.example>
To: User <user@corp.example>
Subject: Authentication-Results source demo
Message-ID: <authres-demo@external.example>
"""

# 发件域对齐审计示例（与认证结果来源示例同一条链路，可信前缀为
# edge.internal.corp / gw2.internal.corp 两跳），发件组织域
# partner.example，唯一 From 域 mail.partner.example：
# - 第 1 条 AR（edge.internal.corp，归属第 1 跳）：本组织声明——
#   spf=pass smtp.mailfrom=news@mail.partner.example 与
#   dkim=pass header.d=mail.partner.example，严格模式即与 From 域
#   完全相同（对齐）；另含 dkim=fail / dmarc=none（非 pass，不作证据）；
# - 第 2 条 AR（gw2.internal.corp，归属第 2 跳）：本组织声明——
#   spf=pass smtp.mailfrom=partner.example、dkim=pass header.d=partner.example，
#   严格模式与 From 子域不完全相同（不对齐），宽松模式两域均为
#   partner.example 或其子域（按标签边界匹配，对齐）；
# - 第 3 条 AR（relay2.partner.example，越过可信边界）与第 4 条
#   （archive.external.example，无对应跳）中的 pass 声明均不予采纳。
# 严格 / 宽松两种模式下总体结论均为“有对齐证据”，但逐条比较结果不同。
SAMPLE_HEADERS_ALIGN = """\
Authentication-Results: edge.internal.corp;
\tspf=pass smtp.mailfrom=news@mail.partner.example;
\tdkim=pass header.d=mail.partner.example;
\tdkim=fail header.d=attacker.example;
\tdmarc=none header.from=mail.partner.example
Received: from gw2.internal.corp (gw2.internal.corp [10.20.0.2])
\tby edge.internal.corp (Postfix) with ESMTPS id A101
\tfor <user@corp.example>; Thu, 24 Sep 2026 03:05:10 +0000
Authentication-Results: gw2.internal.corp;
\tspf=pass smtp.mailfrom=partner.example;
\tdkim=pass header.d=partner.example
Received: from gateway.partner.example (gateway.partner.example [203.0.113.55])
\tby gw2.internal.corp (Postfix) with ESMTP id B202
\tfor <user@corp.example>; Thu, 24 Sep 2026 03:04:30 +0000
Authentication-Results: relay2.partner.example;
\tspf=pass smtp.mailfrom=spoof.example;
\tdkim=pass header.d=spoof.example
Received: from relay1.external.example (relay1.external.example [198.51.100.20])
\tby relay2.partner.example (Postfix) with ESMTP id C303
\tfor <user@corp.example>; Thu, 24 Sep 2026 03:03:50 +0000
Received: from sender.external.example (sender.external.example [192.0.2.90])
\tby edge.external.example (Postfix) with ESMTP id E505
\tfor <user@corp.example>; Thu, 24 Sep 2026 03:02:10 +0000
Authentication-Results: archive.external.example;
\tspf=pass smtp.mailfrom=spoof.example
Date: Thu, 24 Sep 2026 03:02:00 +0000
From: Partner Newsletter <news@mail.partner.example>
To: User <user@corp.example>
Subject: Sender alignment demo
Message-ID: <align-demo@mail.partner.example>
"""

# 发件域对齐示例的发件组织域（宽松模式使用）
SAMPLE_ORG_DOMAIN = "partner.example"


# 退信回执（DSN）判读示例：一封完整的 multipart/report 原始退信邮件，
# 含 text/plain 人类可读说明、message/delivery-status 投递状态与
# message/rfc822 原信副本。投递状态部分有 4 个收件人报告块，按原文顺序：
# - gone@example.com：Action=failed + Status=5.1.1 → 永久失败；
# - retry@example.com：Action=delayed + Status=4.7.1 → 暂缓；
# - delivered@example.com：Action=delivered + Status=2.0.0 → 成功；
# - weird@example.com：Action=failed 但 Status=4.4.1（类别 4 与 failed
#   矛盾）→ 待核对，不把整封回执判成单一“退信”。
SAMPLE_DSN = """\
Received: by mx.final.example with ESMTPS id B7E9C2
\tfor <multi@final.example>; Fri, 25 Sep 2026 04:00:10 +0000
Return-Path: <>
Date: Fri, 25 Sep 2026 04:00:10 +0000
From: Mail Delivery System <mailer-daemon@mx.final.example>
To: <sender@origin.example>
Subject: Warning: message could not be delivered for some recipients
Auto-Submitted: auto-replied
Content-Type: multipart/report; report-type=delivery-status;
\tboundary="DSNBOUND"

--DSNBOUND
Content-Type: text/plain; charset="utf-8"

This is a MIME-formatted delivery status notification.
One recipient failed permanently, one is still being retried,
one was delivered, and one report has conflicting fields.

--DSNBOUND
Content-Type: message/delivery-status

Reporting-MTA: dns;mx.final.example
X-Postfix-Queue-ID: B7E9C2
Arrival-Date: Fri, 25 Sep 2026 03:58:02 +0000

Final-Recipient: rfc822; gone@final.example
Original-Recipient: rfc822;user@final.example
Action: failed
Status: 5.1.1
Remote-MTA: dns;mailstore.final.example
Diagnostic-Code: smtp;550 5.1.1 <gone@final.example> user doesn't exist
\t(permanent delivery failure, no more retries)

Final-Recipient: rfc822; retry@final.example
Action: delayed
Status: 4.7.1
Remote-MTA: dns;mailstore.final.example
Diagnostic-Code: smtp;450 4.7.1 mailbox temporarily busy; will retry
Last-Attempt-Date: Fri, 25 Sep 2026 03:59:30 +0000
Will-Retry-Until: Fri, 25 Sep 2026 08:00:00 +0000

Final-Recipient: rfc822; delivered@final.example
Action: delivered
Status: 2.0.0
Diagnostic-Code: smtp;250 2.0.0 message accepted for delivery

Final-Recipient: rfc822; weird@final.example
Action: failed
Status: 4.4.1
Diagnostic-Code: smtp;421 4.4.1 connection timed out (but Action says failed?)

--DSNBOUND
Content-Type: message/rfc822
Content-Disposition: inline

Received: by mx.final.example with ESMTP id A1B2C3
\tfor <multi@final.example>; Fri, 25 Sep 2026 03:58:00 +0000
From: Sender <sender@origin.example>
To: gone@final.example, retry@final.example,
 delivered@final.example, weird@final.example
Subject: original message copy follows
Message-ID: <orig-msg-001@origin.example>

original message body...

--DSNBOUND--
"""


# 邮件会话关系示例：多封邮件用页面规范分隔行分开，覆盖
# - 正常会话树：#1（根）<- #2 <- #3，#3 的 References 跨两封且带折行，
#   按“末项”连到 #2；#4 缺失 In-Reply-To，回退 References 末项连到 #2；
# - 外部引用：#5 的父 Message-ID 不在批次内（作为树根单独标出）；
# - 孤立邮件：#6 没有任何父引用字段，也不被其他邮件引用；
# - In-Reply-To 多 ID 歧义：#7 含两个尖括号 ID，不强行连边（不回退 References）；
# - 重复 Message-ID：#8 与 #9 声明了同一个 Message-ID，两封均标为歧义，
#   引用该 ID 的 #10 无法确定唯一父邮件，也不连边；
# - 引用环：#11 与 #12 互相把对方写作 In-Reply-To（自环同理），环上两封
#   均标为歧义、删除连边。
SAMPLE_HEADERS_THREAD = """\
Message-ID: <thread-root-001@example.com>
From: Alice <alice@example.com>
To: team@example.com
Date: Fri, 25 Sep 2026 01:00:00 +0000
Subject: Thread demo: release plan
===== 下一封邮件 =====
Message-ID: <thread-reply-002@example.com>
In-Reply-To: <thread-root-001@example.com>
References: <thread-root-001@example.com>
From: Bob <bob@example.com>
To: Alice <alice@example.com>
Date: Fri, 25 Sep 2026 01:10:00 +0000
Subject: Re: Thread demo: release plan
===== 下一封邮件 =====
Message-ID: <thread-reply-003@example.com>
In-Reply-To: <thread-reply-002@example.com>
References: <thread-root-001@example.com>
\t<thread-reply-002@example.com>
From: Carol <carol@example.com>
To: Bob <bob@example.com>
Date: Fri, 25 Sep 2026 01:20:00 +0000
Subject: Re: Thread demo: release plan
===== 下一封邮件 =====
Message-ID: <thread-reply-004@example.com>
References: <thread-root-001@example.com> <thread-reply-002@example.com>
From: Dave <dave@example.com>
To: team@example.com
Date: Fri, 25 Sep 2026 01:30:00 +0000
Subject: Re: Thread demo: release plan
===== 下一封邮件 =====
Message-ID: <thread-ext-005@example.com>
In-Reply-To: <message-outside-batch@external.example>
From: Eve <eve@example.com>
To: team@example.com
Date: Fri, 25 Sep 2026 02:00:00 +0000
Subject: Fwd: an older thread not in this batch
===== 下一封邮件 =====
Message-ID: <thread-orphan-006@example.com>
From: Frank <frank@example.com>
To: team@example.com
Date: Fri, 25 Sep 2026 02:10:00 +0000
Subject: Standalone note, unrelated to anything pasted
===== 下一封邮件 =====
Message-ID: <thread-amb-irt-007@example.com>
In-Reply-To: <thread-root-001@example.com> <thread-reply-002@example.com>
References: <thread-root-001@example.com>
From: Grace <grace@example.com>
To: team@example.com
Date: Fri, 25 Sep 2026 02:20:00 +0000
Subject: Re: Thread demo: release plan (two In-Reply-To ids)
===== 下一封邮件 =====
Message-ID: <thread-dup-id-008@example.com>
From: Heidi <heidi@example.com>
To: team@example.com
Date: Fri, 25 Sep 2026 02:30:00 +0000
Subject: Duplicate Message-ID case A
===== 下一封邮件 =====
Message-ID: <thread-dup-id-008@example.com>
From: Ivan <ivan@example.com>
To: team@example.com
Date: Fri, 25 Sep 2026 02:40:00 +0000
Subject: Duplicate Message-ID case B
===== 下一封邮件 =====
Message-ID: <thread-points-dup-010@example.com>
In-Reply-To: <thread-dup-id-008@example.com>
From: Judy <judy@example.com>
To: team@example.com
Date: Fri, 25 Sep 2026 02:50:00 +0000
Subject: Re: Duplicate Message-ID case A
===== 下一封邮件 =====
Message-ID: <thread-cycle-a-011@example.com>
In-Reply-To: <thread-cycle-b-012@example.com>
From: Karl <karl@example.com>
To: team@example.com
Date: Fri, 25 Sep 2026 03:00:00 +0000
Subject: Cycle case A
===== 下一封邮件 =====
Message-ID: <thread-cycle-b-012@example.com>
In-Reply-To: <thread-cycle-a-011@example.com>
From: Leo <leo@example.com>
To: team@example.com
Date: Fri, 25 Sep 2026 03:10:00 +0000
Subject: Cycle case B
"""

