import asyncio
import json
import logging
from urllib.parse import urlencode

import httpx

from app.config import settings
from app.services.approval_tokens import create_decision_token

logger = logging.getLogger(__name__)


async def dispatch_approval_notifications(approval, tenant):
    await asyncio.gather(
        _send_slack(approval, tenant),
        _send_email(approval, tenant),
        _send_sms(approval, tenant),
        return_exceptions=True,
    )


async def _send_slack(approval, tenant):
    token = settings.SLACK_BOT_TOKEN
    if not token:
        return
    channel = settings.SLACK_CHANNEL or ""
    if not channel:
        for approver in approval.approvers or []:
            if isinstance(approver, str) and approver.startswith("slack://"):
                channel = approver.split("slack://channel/")[-1]
                break
    if not channel:
        return
    try:
        args_str = json.dumps(approval.arguments, indent=2, default=str)[:2500]
        blocks = [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f"*Approval needed:* `{approval.function_name}`\n"
                        f"*Risk:* {approval.risk_level}\n"
                        f"*Arguments:*\n```{args_str}```"
                    ),
                },
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Approve"},
                        "style": "primary",
                        "value": approval.id,
                        "action_id": "approve",
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Reject"},
                        "style": "danger",
                        "value": approval.id,
                        "action_id": "reject",
                    },
                ],
            },
        ]
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(
                "https://slack.com/api/chat.postMessage",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json; charset=utf-8",
                },
                json={
                    "channel": channel,
                    "blocks": blocks,
                    "text": f"Approval needed: {approval.function_name}",
                },
            )
    except Exception as e:
        logger.warning("slack notify failed: %s", e)


async def _send_email(approval, tenant):
    api_key = settings.RESEND_API_KEY
    if not api_key:
        return
    recipients: list[str] = []
    for approver in approval.approvers or []:
        if not isinstance(approver, str):
            continue
        if approver.startswith("mailto:"):
            recipients.append(approver[len("mailto:"):])
        elif "@" in approver and not approver.startswith(("slack://", "sms:")):
            recipients.append(approver)
    if not recipients:
        return
    try:
        approve_url = _decision_url(approval, "approved")
        reject_url = _decision_url(approval, "rejected")
        args_str = json.dumps(approval.arguments, indent=2, default=str)
        html = (
            f"<h2>Approval needed: {approval.function_name}</h2>"
            f"<p><b>Risk:</b> {approval.risk_level}</p>"
            f"<pre>{args_str}</pre>"
            f'<p><a href="{approve_url}">Approve</a> &middot; '
            f'<a href="{reject_url}">Reject</a></p>'
        )
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(
                "https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "from": "Sentinel <onboarding@resend.dev>",
                    "to": recipients,
                    "subject": f"Approval needed: {approval.function_name}",
                    "html": html,
                },
            )
    except Exception as e:
        logger.warning("email notify failed: %s", e)


async def _send_sms(approval, tenant):
    account_sid = settings.TWILIO_ACCOUNT_SID
    auth_token = settings.TWILIO_AUTH_TOKEN
    from_number = settings.TWILIO_FROM_NUMBER
    if not account_sid or not auth_token or not from_number:
        return
    recipients: list[str] = []
    for approver in approval.approvers or []:
        if isinstance(approver, str) and approver.startswith("sms:"):
            recipients.append(approver[len("sms:"):])
    if not recipients:
        return
    try:
        approve_url = _decision_url(approval, "approved")
        reject_url = _decision_url(approval, "rejected")
        body = (
            f"Sentinel approval needed: {approval.function_name}\n"
            f"Risk: {approval.risk_level}\n"
            f"Approve: {approve_url}\n"
            f"Reject: {reject_url}"
        )
        url = (
            "https://api.twilio.com/2010-04-01/Accounts/"
            f"{account_sid}/Messages.json"
        )
        async with httpx.AsyncClient(timeout=10.0) as client:
            for recipient in recipients:
                await client.post(
                    url,
                    auth=(account_sid, auth_token),
                    data={"From": from_number, "To": recipient, "Body": body},
                )
    except Exception as e:
        logger.warning("sms notify failed: %s", e)


def _decision_url(approval, decision: str) -> str:
    token = create_decision_token(
        approval.id,
        decision,
        expires_in_seconds=approval.timeout_seconds,
    )
    query = urlencode({"d": decision, "t": token})
    return f"{settings.PUBLIC_APP_URL}/approve/{approval.id}?{query}"
