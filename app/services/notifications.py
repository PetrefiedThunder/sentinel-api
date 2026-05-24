import asyncio
import json
import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


async def dispatch_approval_notifications(approval, tenant):
    await asyncio.gather(
        _send_slack(approval, tenant),
        _send_email(approval, tenant),
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
        if isinstance(approver, str) and approver.startswith("mailto:"):
            recipients.append(approver[len("mailto:") :])
    if not recipients:
        return
    try:
        approve_url = f"{settings.PUBLIC_APP_URL}/approve/{approval.id}?d=approved"
        reject_url = f"{settings.PUBLIC_APP_URL}/approve/{approval.id}?d=rejected"
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
                    "from": "approvals@oversight.sh",
                    "to": recipients,
                    "subject": f"Approval needed: {approval.function_name}",
                    "html": html,
                },
            )
    except Exception as e:
        logger.warning("email notify failed: %s", e)
