"""
gmail.py — Gmail SMTP email sender and HTML email builder.

Authentication uses an App Password (not your account password):
  https://support.google.com/accounts/answer/185833

Environment variables required:
  GMAIL_USER         your Gmail address
  GMAIL_APP_PASSWORD the 16-character App Password
  RECIPIENT_EMAIL    (optional) defaults to GMAIL_USER
"""
from __future__ import annotations

import logging
import smtplib
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from jinja2 import Environment, BaseLoader

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
import config
from job_hunter.pipeline.ranker import RankedJob

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# HTML template
# ---------------------------------------------------------------------------
_EMAIL_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>Job Opportunities</title>
<style>
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
         background: #f4f6f9; color: #1a1a2e; margin: 0; padding: 20px; }
  .container { max-width: 680px; margin: 0 auto; }
  .header { background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white; padding: 24px 28px; border-radius: 12px 12px 0 0; }
  .header h1 { margin: 0; font-size: 22px; }
  .header p  { margin: 4px 0 0; opacity: 0.9; font-size: 13px; }
  .job-card  { background: white; border-radius: 10px; padding: 20px 24px;
               margin: 14px 0; box-shadow: 0 2px 8px rgba(0,0,0,0.07); }
  .job-rank  { display: inline-block; background: #764ba2; color: white;
               font-size: 11px; font-weight: 700; padding: 2px 8px;
               border-radius: 10px; margin-bottom: 8px; }
  .job-title { font-size: 18px; font-weight: 700; color: #1a1a2e; margin: 0 0 4px; }
  .job-meta  { font-size: 13px; color: #666; margin-bottom: 12px; }
  .score-bar-wrap { background: #e8e8e8; border-radius: 8px; height: 7px; margin: 10px 0 14px; }
  .score-bar { background: linear-gradient(90deg,#667eea,#764ba2); border-radius: 8px; height: 7px; }
  .section-label { font-size: 11px; font-weight: 700; text-transform: uppercase;
                   letter-spacing: 0.5px; color: #764ba2; margin: 10px 0 4px; }
  ul.bullets { margin: 0 0 10px; padding-left: 18px; }
  ul.bullets li { font-size: 13.5px; margin-bottom: 3px; }
  .cover-note { background: #f0eeff; border-left: 3px solid #764ba2;
                padding: 12px 16px; border-radius: 0 8px 8px 0;
                font-size: 13.5px; line-height: 1.6; margin-top: 10px; }
  .apply-btn  { display: inline-block; background: #667eea; color: white;
                padding: 9px 20px; border-radius: 8px; text-decoration: none;
                font-size: 13px; font-weight: 600; margin-top: 12px; }
  .footer { text-align: center; font-size: 11px; color: #999; margin-top: 20px; }
  .source-report { background: white; border-radius: 10px; padding: 16px 20px;
                   margin: 14px 0; font-size: 12px; }
  .ok  { color: #2e7d32; }
  .err { color: #c62828; }
  .warn { color: #ef6c00; }
</style>
</head>
<body>
<div class="container">

  <div class="header">
    <h1>🤖 AI Job Hunter — {{ run_time }}</h1>
    <p>{{ jobs|length }} new opportunit{{ 'y' if jobs|length == 1 else 'ies' }} matched your profile today</p>
  </div>

  {% for ranked in jobs %}
  <div class="job-card">
    <span class="job-rank">#{{ loop.index }}</span>
    {% if loop.index == 1 %}<span style="font-size:11px;background:#ffd700;color:#333;padding:2px 8px;border-radius:10px;margin-left:6px;font-weight:700;">⭐ TOP MATCH</span>{% endif %}
    <div class="job-title">{{ ranked.job.title }}</div>
    <div class="job-meta">
      🏢 {{ ranked.job.company }} &nbsp;|&nbsp;
      📍 {{ ranked.job.location }} &nbsp;|&nbsp;
      🔗 {{ ranked.job.source }}
      {% if ranked.job.salary %}&nbsp;|&nbsp; 💰 {{ ranked.job.salary }}{% endif %}
      {% if ranked.job.posted_at %}&nbsp;|&nbsp; 🕐 {{ ranked.job.posted_at.strftime('%d %b %Y %H:%M UTC') }}{% endif %}
    </div>

    <div class="section-label">Match Score</div>
    <div class="score-bar-wrap">
      <div class="score-bar" style="width:{{ ranked.score }}%"></div>
    </div>
    <div style="font-size:12px;color:#555;">{{ ranked.score }}/100</div>

    {% if ranked.match_reasons %}
    <div class="section-label">Why You Qualify</div>
    <ul class="bullets">
      {% for reason in ranked.match_reasons %}<li>{{ reason }}</li>{% endfor %}
    </ul>
    {% endif %}

    {% if ranked.missing_skills %}
    <div class="section-label">Skills to Develop</div>
    <ul class="bullets">
      {% for skill in ranked.missing_skills %}<li>{{ skill }}</li>{% endfor %}
    </ul>
    {% endif %}

    {% if loop.index == 1 and ranked.cover_note %}
    <div class="section-label">Tailored Cover Note</div>
    <div class="cover-note">{{ ranked.cover_note }}</div>
    {% endif %}

    <div style="font-size:11px;color:#aaa;margin-top:10px;">
      📄 Resume used: <strong>{{ resume_label(ranked.resume_used) }}</strong>
    </div>

    <a class="apply-btn" href="{{ ranked.job.url }}" target="_blank">Apply Now →</a>
  </div>
  {% endfor %}

  {% if health %}
  <div class="source-report">
    <strong>Source Health Report</strong><br/>
    {% for h in health %}
    <span class="{{ 'ok' if h.status == 'ok' else 'err' }}">
      {{ '✅' if h.status == 'ok' else '❌' }} {{ h.source }}
      ({{ h.jobs_fetched if h.status == 'ok' else h.error }})
      {% if h.unofficial %}<span class="warn">[unofficial]</span>{% endif %}
    </span><br/>
    {% endfor %}
  </div>
  {% endif %}

  <div class="footer">
    Generated by AI Job Hunter &nbsp;•&nbsp; Data from public job boards &nbsp;•&nbsp;
    <a href="https://github.com/{{ gh_repo }}">GitHub</a>
  </div>
</div>
</body>
</html>
""".strip()


def _resume_label(key: str) -> str:
    return {
        "aiml":    "AI/ML Resume",
        "data":    "Data Resume",
        "backend": "Backend Resume",
        "main":    "General Resume",
    }.get(key, key)


def _build_html(ranked_jobs: list, health: list[dict]) -> str:
    env = Environment(loader=BaseLoader())  # type: ignore[arg-type]
    env.globals["resume_label"] = _resume_label
    tmpl = env.from_string(_EMAIL_TEMPLATE)
    run_time = datetime.now(timezone.utc).strftime("%d %b %Y, %H:%M UTC")
    return tmpl.render(
        jobs=ranked_jobs,
        health=health,
        run_time=run_time,
        gh_repo=os.getenv("GITHUB_REPOSITORY", "your-repo"),
    )


def send_email(
    ranked_jobs: list[RankedJob],
    health: list[dict],
    subject: str | None = None,
    dry_run: bool = False,
) -> None:
    if not ranked_jobs:
        logger.info("Email: nothing to send (no jobs passed all filters)")
        return

    if subject is None:
        subject = (
            f"[Job Hunter] {len(ranked_jobs)} new job"
            f"{'s' if len(ranked_jobs) != 1 else ''} matched"
            f" — {datetime.now(timezone.utc).strftime('%d %b %Y %H:%M UTC')}"
        )

    html_body = _build_html(ranked_jobs, health)

    # Resolve sender/recipient — use accessors so tests can patch via env
    sender = config.GMAIL_USER or os.getenv("GMAIL_USER", "")
    recipient = config.RECIPIENT_EMAIL or config.GMAIL_USER or os.getenv("GMAIL_USER", "")

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = recipient
    msg.attach(MIMEText(html_body, "html"))

    if dry_run:
        logger.info("Email (dry-run): would send '%s' to %s", subject, recipient)
        # Write the HTML to a local file for inspection
        preview_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            "data", "email_preview.html",
        )
        with open(preview_path, "w", encoding="utf-8") as fh:
            fh.write(html_body)
        logger.info("Email (dry-run): preview written to %s", preview_path)
        return

    gmail_user = config.get_gmail_user()
    gmail_pass = config.get_gmail_app_password()

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
            smtp.login(gmail_user, gmail_pass)
            smtp.send_message(msg)
        logger.info("Email: sent '%s' to %s", subject, recipient)
    except smtplib.SMTPAuthenticationError:
        logger.error(
            "Email: SMTP authentication failed. "
            "Check GMAIL_USER and GMAIL_APP_PASSWORD. "
            "You need a Gmail App Password (not your account password): "
            "https://support.google.com/accounts/answer/185833"
        )
        raise
    except Exception as exc:  # noqa: BLE001
        logger.error("Email: failed to send: %s", exc)
        raise
