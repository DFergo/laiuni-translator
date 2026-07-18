// Default branding page content shipped with the app (English, Markdown).
// Used by the "Load default template" buttons in the branding editor so an
// admin can edit the WHOLE page (headings included) instead of starting blank.
// When a frontend's branding text is set, it replaces the default page entirely
// and is translated to all languages. `[DATA_PROTECTION_EMAIL]` is substituted
// at render time (or by the SMTP sender address).

export const DEFAULT_DISCLAIMER_MD = `## HRDD Helper — Workers' Rights Documentation Tool

This tool supports workers and trade unions in documenting violations of fundamental workers' rights.

Its primary function is to help you build a structured record of what is happening in your workplace, so that your trade union — and UNI Global Union — can take informed action on your behalf.

The tool also provides context from international labour standards (ILO Conventions, OECD Guidelines, UN Guiding Principles, EU Corporate Sustainability Due Diligence Directive, and FSC Standards) to support workers and local unions in dialogue with employers.

HRDD Helper is an AI system. It can make mistakes. It does not replace legal advice, union representation, or professional counsel. Always verify important information with your trade union.

## How Your Data Is Handled

Your data is processed and stored exclusively by UNI Global Union on its own infrastructure. No data is sent to external cloud services or third-party AI providers.

The purpose of collecting this information is to document evidence of fundamental rights violations in order to support strategies — together with local trade unions affiliated to UNI Global Union — to end those violations. This may include dialogue with the employer, formal complaints to international bodies, or other actions coordinated with your union.

Worker identity information linked to a report is kept anonymous in all documents shared outside UNI Global Union. UNI will never disclose your personal information to third parties without your prior explicit consent.

You may use this tool fully anonymously if you choose. Providing your name or contact details is optional and will only be used to follow up on your case if you request it.

## Disclaimer

By continuing, you acknowledge that:

- This tool is provided by UNI Global Union for informational and documentation purposes only. It does not constitute legal advice.
- The AI system may produce inaccurate or incomplete information. UNI Global Union is not liable for errors in AI-generated content.
- Your data is processed in accordance with the EU General Data Protection Regulation (GDPR).
- Session data is retained for the period necessary to process your case and is deleted thereafter, unless you request earlier deletion.
- You may withdraw your consent to data processing at any time. Withdrawal does not affect the lawfulness of processing carried out before withdrawal.`

export const DEFAULT_INSTRUCTIONS_MD = `## How This Works

You are about to have a conversation with an AI assistant. It will listen to your situation and help you document what is happening.

What the tool does:

- Listens to your account of what is happening at your workplace
- Helps place your situation within international labour standards that your employer is expected to respect
- Creates a documented record that your trade union can use to take action

What the tool does not do:

- It cannot access external websites, databases, or legal libraries in real time
- It does not have all the answers — it works with what you tell it
- It is not a substitute for your trade union or legal advice

During the conversation:

- Describe your situation in your own words. There is no wrong way to start.
- The assistant will ask you questions to understand what happened, when, where, and who was involved.
- If you have documents, messages, or other evidence, you can upload them during the conversation using the upload button.
- You can remain anonymous. You do not have to share your name or any personal details.

When you are done:

- Press the "End Session" button when you feel you have shared everything relevant.
- The tool will generate a summary for you with the key points of your situation and how they relate to international standards.
- A full report will be sent to UNI Global Union to support follow-up with your trade union.

The most important step you can take is to contact your local trade union. This tool supports that process — it does not replace it.`
