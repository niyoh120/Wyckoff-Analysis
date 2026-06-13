# Config Profiles

This directory stores safe, shareable strategy profiles.

Commit profiles only when they contain public defaults and no personal data.
Private overrides should use `.env`, `config/profiles/*.local.yml`, or
`config/profiles/*private*.yml`; these paths are ignored by git.

`a_share_prod.yml` is the default production-style profile. Environment
variables still win over profile values for runtime jobs.
