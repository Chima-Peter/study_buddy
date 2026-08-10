from html import escape


def password_reset_email(
    *,
    name: str,
    app_name: str,
    code: str,
) -> tuple[str, str, str]:
    """Return (subject, text_body, html_body) for a password reset email."""
    display_name = name.strip() or "there"
    safe_name = escape(display_name)
    safe_app = escape(app_name)
    safe_code = escape(code)

    subject = f"Your {app_name} password reset code"

    text = (
        f"Hi {display_name},\n\n"
        f"Use this code to reset your {app_name} password:\n\n"
        f"  {code}\n\n"
        "This code expires in 10 minutes. If you did not request a reset, "
        "you can ignore this email.\n\n"
        f"— The {app_name} team\n"
    )

    html = f"""\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <meta name="color-scheme" content="light" />
  <title>{safe_app}</title>
</head>
<body style="margin:0;padding:0;background:#e8f3ef;font-family:Georgia,'Times New Roman',serif;color:#0c2420;-webkit-text-size-adjust:100%;">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#e8f3ef;padding:48px 16px;">
    <tr>
      <td align="center">
        <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="max-width:560px;background:#ffffff;border-radius:16px;overflow:hidden;border:1px solid #c5ddd6;">
          <!-- Header -->
          <tr>
            <td style="background:#0c2420;padding:36px 40px 28px;">
              <p style="margin:0 0 18px;font-family:'Segoe UI',Roboto,Helvetica,Arial,sans-serif;font-size:12px;letter-spacing:0.2em;text-transform:uppercase;color:#5eead4;font-weight:700;">
                {safe_app}
              </p>
              <h1 style="margin:0;font-family:Georgia,'Times New Roman',serif;font-size:32px;line-height:1.2;font-weight:700;color:#e8f5f1;">
                Password reset
              </h1>
              <p style="margin:12px 0 0;font-family:'Segoe UI',Roboto,Helvetica,Arial,sans-serif;font-size:15px;line-height:1.5;color:#9eb8b1;">
                Use the code below to continue.
              </p>
            </td>
          </tr>

          <!-- Accent bar -->
          <tr>
            <td style="height:4px;background:#f0c419;font-size:0;line-height:0;">&nbsp;</td>
          </tr>

          <!-- Body -->
          <tr>
            <td style="padding:36px 40px 16px;font-family:'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">
              <p style="margin:0 0 18px;font-size:17px;line-height:1.6;color:#0c2420;font-weight:600;">
                Hi {safe_name},
              </p>
              <p style="margin:0 0 28px;font-size:16px;line-height:1.65;color:#3d5c56;">
                Enter this code to reset your password. It expires in
                <strong style="color:#0c2420;font-weight:700;">10 minutes</strong>.
              </p>
            </td>
          </tr>

          <!-- Code block -->
          <tr>
            <td style="padding:0 40px 28px;font-family:'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">
              <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#f3faf7;border-radius:12px;border:1px solid #d5ebe4;">
                <tr>
                  <td style="padding:28px 22px;text-align:center;">
                    <p style="margin:0 0 12px;font-size:12px;letter-spacing:0.16em;text-transform:uppercase;color:#0f766e;font-weight:700;">
                      Reset code
                    </p>
                    <p style="margin:0;font-size:36px;line-height:1.2;letter-spacing:0.32em;font-weight:700;color:#0c2420;font-family:'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">
                      {safe_code}
                    </p>
                  </td>
                </tr>
              </table>
            </td>
          </tr>

          <!-- Security note -->
          <tr>
            <td style="padding:0 40px 36px;font-family:'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">
              <p style="margin:0 0 24px;font-size:14px;line-height:1.55;color:#5a7a73;">
                If you did not request a reset, you can safely ignore this email.
                Your password will stay the same.
              </p>
              <p style="margin:0;font-size:14px;line-height:1.5;color:#5a7a73;">
                — The {safe_app} team
              </p>
            </td>
          </tr>

          <!-- Footer -->
          <tr>
            <td style="background:#f7fbf9;border-top:1px solid #d5ebe4;padding:18px 40px;font-family:'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">
              <p style="margin:0;font-size:12px;line-height:1.5;color:#7a9a92;text-align:center;">
                Never share this code with anyone. {safe_app} will never ask for it.
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