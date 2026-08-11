# mySails.ai — sales management system

A file-based sales management system run by Claude skills. This repo contains the generic system layer only: schemas, scripts, and conventions under `.sales-system/`.

Working data (lead/opportunity registries, quotes, briefs, CRM profile, company config) lives in numbered folders alongside this repo and is deliberately excluded by `.gitignore` — it never belongs in version control.

The distributable plugin lives in `sales-system-plugin/` as its own repository.
