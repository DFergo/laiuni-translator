# Email for the app (SMTP)

Used for: the **sign-in codes** and the **result emails** (a one-time download link). Without email nobody can sign in, so it is required.

## Choose the account
Best: a **dedicated mailbox** (e.g. `translator@union.org` or on the app's own domain), not a person's mailbox. The app sends with **STARTTLS on port 587** (username + password). Implicit TLS on port 465 is not supported: use 587.

| Organisation uses | How |
|---|---|
| Google Workspace / Gmail | Server `smtp.gmail.com`, port 587. The account needs 2-Step Verification and an **app password** (Google account → Security → App passwords). Workspace admins can disable app passwords — check with them. |
| Microsoft 365 | Server `smtp.office365.com`, port 587, only if **SMTP AUTH** is enabled for that mailbox (often disabled by default). Microsoft is phasing out password-based SMTP — if their IT cannot enable it, use a transactional provider instead. |
| Own mail server / hosting (e.g. Infomaniak Mail) | The SMTP server, port 587 and mailbox credentials from the provider's help pages. |
| None of the above / problems | A transactional email service (e.g. Brevo, Mailjet — EU-based) with a sender on the app's domain; they explain the DNS records (SPF/DKIM) to add in Cloudflare. |

## Configure
The user puts the password in the local keys file (`~/.config/translator-ops/keys.env`, `SMTP_PASSWORD=...`):
```
admin_api PUT /admin/smtp
  {"host": "smtp.gmail.com", "port": 587, "use_tls": true,
   "username": "translator@union.org", "password": "env:~/.config/translator-ops/keys.env#SMTP_PASSWORD",
   "from_address": "translator@union.org", "notification_emails": ["admin@union.org"]}
admin_api POST /admin/smtp/test
```
`use_tls: true` means STARTTLS. `notification_emails` are the administrators' addresses (alerts); `data_protection_email` is the contact shown in messages. Per-frontend notification addresses: `/admin/smtp/frontend-notifications/{id}`. See `admin_api_reference filter="smtp"` for every field.

## If the test fails
Authentication error → app password / SMTP AUTH; timeout → port blocked (some networks block 587 outbound) or wrong host; messages in spam → sender domain without SPF/DKIM. A user who gets no code: is their address on the whitelist (guide `frontends`)? The app answers the same way for listed and unlisted addresses, on purpose.
