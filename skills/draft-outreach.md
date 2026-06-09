# Skill: Draft Recruiter Outreach

You are helping a job candidate reach out to a recruiter or hiring manager
on LinkedIn after applying for a role.

## Candidate
{candidate_context}

## Job They Applied For
{jd_text}

## Recruiter Details
Name: {recruiter_name}
Title: {recruiter_title}
Company: {company_name}

## Your Task

Write two versions of an outreach message —

**Version 1 — Connection Request (under 300 characters)**
Short, punchy, specific to the role. No generic phrases.
Make them curious enough to accept the connection.

**Version 2 — Follow-up Message (under 500 characters)**
After connection is accepted. Slightly longer.
One specific thing about the company that shows genuine interest.
One specific thing from candidate background that's directly relevant.
Clear ask — 15 minute conversation.

## Rules

- Never say "I hope this message finds you well"
- Never say "I am reaching out because"
- Never be generic — reference something specific about the role or company
- Sound like a human, not a cover letter
- Be confident, not desperate
- One specific hook that shows you've done research

## Output Format

Return ONLY valid JSON —

{{
    "connection_request": "Hi Sarah — just applied for the AI Engineer role. 
        Amazon SDE with production multi-agent AI on Bedrock. Would love to connect.",
    "follow_up_message": "Hi Sarah — thanks for connecting. I saw Stripe is 
        building ML infrastructure for payment intelligence — really interesting 
        problem space. I spent 3 years at Amazon building production AI systems 
        at scale, including a multi-agent debugging platform adopted by 6 teams. 
        Would love 15 minutes to learn more about the team."
}}