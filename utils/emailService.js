// utils/emailService.js
// Transactional email via Resend.
//
// Fix #11: the "from" address is now driven by EMAIL_FROM env var.
// The hardcoded "onboarding@resend.dev" sandbox address only works in dev —
// in production you must set a verified custom domain in Resend and point
// EMAIL_FROM at it, e.g. "CodeBox <noreply@yourdomain.com>".

const { Resend } = require('resend');
require('dotenv').config();

if (!process.env.RESEND_API_KEY) {
  throw new Error('RESEND_API_KEY environment variable is not set. Check your .env file.');
}

const resend = new Resend(process.env.RESEND_API_KEY);

// Falls back to the Resend sandbox address in dev only.
const FROM_ADDRESS = process.env.EMAIL_FROM || 'CodeBox <onboarding@resend.dev>';

const generateOTP = () => Math.floor(100000 + Math.random() * 900000).toString();

exports.sendPasswordResetOTP = async (email, name, otp) => {
  const { data, error } = await resend.emails.send({
    from: FROM_ADDRESS,
    to: email,
    subject: `${otp} — Your CodeBox Password Reset Code`,
    html: `
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="margin:0;padding:0;background:#09090b;font-family:'Segoe UI',Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#09090b;padding:40px 20px;">
    <tr>
      <td align="center">
        <table width="560" cellpadding="0" cellspacing="0" style="background:#111113;border-radius:16px;border:1px solid #2a2a35;overflow:hidden;">

          <tr>
            <td style="padding:32px 40px 24px;border-bottom:1px solid #2a2a35;">
              <table cellpadding="0" cellspacing="0">
                <tr>
                  <td style="background:linear-gradient(135deg,#6366f1,#a78bfa);width:40px;height:40px;border-radius:10px;text-align:center;vertical-align:middle;">
                    <span style="color:white;font-size:18px;font-weight:bold;">&lt;/&gt;</span>
                  </td>
                  <td style="padding-left:12px;">
                    <span style="color:#f0f0f5;font-size:18px;font-weight:700;">CodeBox</span>
                  </td>
                </tr>
              </table>
            </td>
          </tr>

          <tr>
            <td style="padding:32px 40px;">
              <h1 style="color:#f0f0f5;font-size:22px;font-weight:700;margin:0 0 8px;">Password Reset Request</h1>
              <p style="color:#9090a8;font-size:14px;line-height:1.6;margin:0 0 28px;">
                Hi ${name}, we received a request to reset your password. Use the code below to continue.
              </p>

              <div style="background:#1a1a1f;border:2px solid #6366f1;border-radius:12px;padding:24px;text-align:center;margin:0 0 24px;">
                <p style="color:#9090a8;font-size:12px;text-transform:uppercase;letter-spacing:2px;margin:0 0 12px;">Your Reset Code</p>
                <p style="color:#6366f1;font-size:40px;font-weight:800;letter-spacing:8px;margin:0;font-family:'Courier New',monospace;">${otp}</p>
                <p style="color:#5a5a70;font-size:12px;margin:12px 0 0;">Expires in <strong style="color:#f59e0b;">10 minutes</strong></p>
              </div>

              <div style="background:#1a1a1f;border-radius:10px;padding:16px;margin:0 0 24px;">
                <p style="color:#9090a8;font-size:13px;margin:0;line-height:1.6;">
                  ⚠️ <strong style="color:#f0f0f5;">Security notice:</strong> If you did not request a password reset, please ignore this email.
                </p>
              </div>

              <p style="color:#5a5a70;font-size:12px;margin:0;line-height:1.6;">
                This code can only be used once. Do not share it with anyone.
              </p>
            </td>
          </tr>

          <tr>
            <td style="padding:20px 40px;border-top:1px solid #2a2a35;">
              <p style="color:#5a5a70;font-size:11px;margin:0;text-align:center;">
                © ${new Date().getFullYear()} CodeBox · AI-powered coding assistant
              </p>
            </td>
          </tr>

        </table>
      </td>
    </tr>
  </table>
</body>
</html>
    `,
  });

  if (error) {
    console.error('Resend error:', error);
    throw new Error(error.message);
  }

  console.log(`📧 OTP sent to ${email} via Resend (id: ${data.id})`);
  return data;
};

exports.generateOTP = generateOTP;