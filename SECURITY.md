# Security Policy

## Supported versions

Only the latest released version receives security-related updates.

| Version | Supported          |
| ------- | ------------------ |
| Latest  | :white_check_mark: |
| Older   | :x:                |

## Reporting a vulnerability

If you discover a security vulnerability, please report it privately rather than opening
a public issue.

Use GitHub's **[Private vulnerability reporting](https://github.com/Dxx-OTG/TGArchive/security/advisories/new)**
feature (Security tab -> Report a vulnerability), which lets us discuss and fix the issue
before any public disclosure.

Please include:

- A description of the vulnerability and its potential impact.
- Steps to reproduce it.
- Any suggested mitigation, if known.

## Scope note

TGArchive handles sensitive credentials (bot token, API credentials, Telegram session
files). These are stored locally in `.env` and `*.session` files, which are excluded from
the repository via `.gitignore`. Never share these files when reporting an issue.
