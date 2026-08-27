# Security Rules — Claude Code

Esta carpeta contiene las reglas de seguridad de Cashea que Claude Code carga automáticamente al iniciar sesión en este repo.

> **No las modifiques directamente acá.** La fuente de verdad vive en [ai-forge](https://github.com/cashea-bnpl/ai-forge). Los updates llegan vía PR automático del workflow `publish-rules.yml`.

## ¿Cómo funcionan?

Cuando arrancás Claude Code en este repo, lee todos los archivos en `.claude/rules/` y los inyecta como el primer mensaje del modelo. Eso garantiza que las reglas aplican a TODO lo que generes, sin que tengas que invocarlas.

## ¿Qué incluyen?

- `SKILL.md`: 12 reglas universales (secrets, auth, validation, errors, queries, logging, deps, data, headers, AI rules, detección de datos sensibles en prompts)
- 9 referencias por dominio: auth, input-validation, data-security, logging, docker, iac-terraform, node-nestjs, python, frontend

## ¿Y si tengo dudas?

- Slack: #appsec
- Email: security@cashea.app
- Notion: AI Security workspace
