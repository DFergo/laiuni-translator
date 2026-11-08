# Onboarding survey

Ask before recommending anything. A few questions at a time, in the user's language, plain words. Skip what `check_machine` already tells you. Save the answers with `profile_save`.

## 1. About them
- Have you used a terminal / command line before? (never · a little · regularly)
- Have you run a server or Docker before? (no · a little · yes)
- Is there someone technical who can help (IT person, volunteer)?
→ Sets how much you explain. For "never", explain each step in one or two sentences, avoid jargon, and confirm what they see on screen.

## 2. What they want
- Who will use it: staff of one organisation, affiliated unions, an open group? Roughly how many people, and how many documents a day or a week?
- What kind of documents (reports, agreements, presentations)? Which formats: `.txt`/`.md` work best, `.docx` and `.rtf` are supported (small formatting shifts possible), `.pptx` is experimental.
- Which languages are needed (the app offers 17)? Is there an organisation glossary of terms that must always be translated the same way?
- Should it be reachable from the Internet, or only inside the office network?
- Do they want translations to run **at night** (scheduled window, cheaper on busy machines) or immediately, or let users choose?
- Will an AI agent or a script also send documents through the machine API (`/api/v1`)? → guide `api`.

## 3. Machines
- Run `check_machine` on this computer (explain what it checks).
- Is this the machine that will run the backend? Will it stay on all the time? (A laptop that sleeps is fine to try, not for production.)
- Other machines available: another computer in the office? A VPS already? (provider, OS)
- For a local AI model: does any machine have 32 GB of memory or more (Mac with Apple Silicon, or a PC with a strong NVIDIA GPU)?

## 4. Network and accounts
- Do they have a domain? (Usually yes, for the organisation website and email.) → explain in guide `domain-cloudflare` why the app should get **its own new domain**.
- Cloudflare account? Tailscale account? (Fine if not: we create them when needed.)

## 5. AI models
- Budget per month for AI (none · small · flexible)?
- Privacy requirements: **the text of every document is sent to the AI provider**. Is a cloud provider acceptable? Only EU providers? Must everything stay in-house?
→ guides `inference` and `models`.

## 6. Email
- What email does the organisation use: Google Workspace / Gmail, Microsoft 365, its own mail server, other? Can they create a dedicated mailbox (e.g. `translator@union.org`)? Email sends the sign-in codes and the result links, so the app cannot be used without it. → guide `email`.
- Who may sign in? A list of addresses (the whitelist) to start with. → guide `frontends`.

## Then
Summarise what you understood and recommend a topology (guide `topologies`), with the reason, in a few lines. Let them choose.
