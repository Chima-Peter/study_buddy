from html import escape


def signup_email(*, name: str, app_name: str) -> tuple[str, str, str]:
    """Return (subject, text_body, html_body) for a welcome email."""
    safe_name = escape(name.strip() or "there")
    safe_app = escape(app_name)

    subject = f"Welcome to {app_name}"

    text = (
        f"Hi {name.strip() or 'there'},\n\n"
        f"Welcome to {app_name}. Your account is ready.\n\n"
        "Upload your materials, generate study cards, and ask questions "
        "whenever you need a study partner.\n\n"
        f"— The {app_name} team\n"
    )

    html = f"""\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{safe_app}</title>
</head>
<body style="margin:0;padding:0;background:#e8eef2;font-family:'Segoe UI',Roboto,Helvetica,Arial,sans-serif;color:#1a2332;">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#e8eef2;padding:40px 16px;">
    <tr>
      <td align="center">
        <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="max-width:560px;background:#ffffff;border-radius:4px;overflow:hidden;">
          <tr>
            <td style="background:linear-gradient(145deg,#0b3d4a 0%,#146b7a 100%);padding:40px 36px 32px;">
              <p style="margin:0 0 8px;font-size:13px;letter-spacing:0.14em;text-transform:uppercase;color:#9ad4de;font-weight:600;">
                {safe_app}
              </p>
              <h1 style="margin:0;font-size:28px;line-height:1.25;font-weight:700;color:#ffffff;">
                Welcome aboard
              </h1>
            </td>
          </tr>
          <tr>
            <td style="padding:36px;">
              <p style="margin:0 0 16px;font-size:16px;line-height:1.6;color:#1a2332;">
                Hi {safe_name},
              </p>
              <p style="margin:0 0 16px;font-size:16px;line-height:1.6;color:#3d4a5c;">
                Your account is ready. Upload your materials, generate study cards,
                and ask questions whenever you need a study partner.
              </p>
              <p style="margin:28px 0 0;font-size:14px;line-height:1.5;color:#6b7a8d;">
                — The {safe_app} team
              </p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>
"""
    return subject, text, html
