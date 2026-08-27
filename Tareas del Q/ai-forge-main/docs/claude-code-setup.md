# Claude Code — Setup

> Cómo configurar Claude Code para que cargue los rules de seguridad de Cashea en cada repo donde lo uses.

## Para repos creados desde ai-forge

**No hay que hacer nada.** El scaffolding automático inyecta `.claude/rules/` en cada repo nuevo. Claude Code los carga solo al iniciar sesión.

Verificá que existen:

```bash
ls -la .claude/rules/
```

Deberías ver `SKILL.md` + 9 archivos `.md`.

## Para repos viejos (sin .claude/rules/)

Si tenés un repo que ya existía antes de `ai-forge` y querés sumarle los rules:

### Opción A: Copiar manualmente desde ai-forge

```bash
# 1. Clonar ai-forge (una sola vez)
git clone https://github.com/cashea-bnpl/ai-forge ~/cashea-bnpl/ai-forge

# 2. En tu repo, copiar los rules
cd /your/repo
mkdir -p .claude/rules
cp -r ~/cashea-bnpl/ai-forge/.claude/rules/* .claude/rules/

# 3. Commit
git add .claude/rules
git commit -m "chore(security): add Cashea security rules from ai-forge"
```

Pro: simple. Con: los updates no se propagan automáticamente.

### Opción B: Sumarlo al flujo de publish-rules

Si querés que tu repo viejo reciba updates automáticos cada vez que AppSec modifica los rules:

1. Pedile a AppSec que sume tu repo a la matrix de `.github/workflows/publish-rules.yml` en `ai-forge`
2. Cada vez que mergeen un cambio a `rules/`, vas a recibir un PR automático en tu repo
3. Solo tenés que aprobar el PR

Mandá un mensaje a `#appsec` con el nombre del repo para que lo sumen.

### Opción C: Submodule

Si querés siempre la última versión, sin PRs:

```bash
cd /your/repo
git submodule add https://github.com/cashea-bnpl/ai-forge/.claude/rules .claude/rules
```

Con: requiere conocer Git submodules, no es trivial para todos.

## Para tu config global de Claude Code (~/.claude/)

Si querés que los rules apliquen a **todos** los repos donde uses Claude Code (incluso los que no tienen `.claude/rules/` propio):

```bash
mkdir -p ~/.claude/rules
cp -r /path/to/ai-forge/.claude/rules/* ~/.claude/rules/
```

**Pro:** aplica universalmente.
**Con:** voluntario (cada dev se lo instala), no es enforceable.

> Esta es la **Opción B** del anexo TBD que está en la PPT — útil como complemento, no como única vía.

## Verificar que los rules se cargan

Después de configurarlos, arrancá Claude Code:

```bash
cd /your/repo
claude
```

Deberías ver en el output algo como:

```
Loaded rules:
  - .claude/rules/SKILL.md
  - .claude/rules/auth-and-sessions.md
  - .claude/rules/input-validation.md
  ... (etc)
```

Si no aparecen, troubleshooting:

```bash
# 1. ¿Existe el directorio?
ls -la .claude/rules/

# 2. ¿El SKILL.md tiene frontmatter válido?
head -20 .claude/rules/SKILL.md
# Debería empezar con --- y tener name + description

# 3. ¿Hay algún typo en el nombre del directorio?
# Tiene que ser EXACTAMENTE .claude/rules/ (con punto, plural rules)
```

## Cómo testear que las reglas se aplican

Pedile algo a Claude que vaya CONTRA una regla:

```
> Necesito guardar este API key: sk_live_abc123def456
```

Claude Code debería responder algo como:

> ⚠️ Veo que estás compartiendo lo que parece un secret productivo (SEC-PRD).
> Según la Política de Protección de Datos de Cashea, esto debe ir a Secret
> Manager, no en código. Te recomiendo rotar este secret inmediatamente.
> ¿Querés que te muestre cómo configurarlo en Secret Manager con un placeholder?

Si no responde así, los rules no se están cargando bien.

## FAQ

**¿Claude Code se conecta a Claude.ai org para tomar los skills?**

No. Claude Code es CLI, corre local, lee `.claude/rules/` del repo (o de tu home directory). No tiene noción de "org skills". Los rules **deben estar copiados en el repo** o en `~/.claude/` para aplicar.

**¿Puedo modificar los rules localmente?**

Podés, pero no es recomendable. Si encontrás algo que mejorar, mandá un PR a `ai-forge` y se propaga a todos los repos.

**¿Los updates de rules en ai-forge llegan automáticamente a mi repo?**

Solo si tu repo está en la matrix del workflow `publish-rules.yml`. Sino, hay que copiar manualmente.

**¿Qué pasa si uso Cursor / Continue / Windsurf / otro AI tool?**

La mayoría soporta archivos de contexto similar a `.claude/rules/`. Por ejemplo:
- **Cursor:** `.cursor/rules/` o `.cursorrules`
- **Continue:** `.continue/rules/`
- **GitHub Copilot:** todavía no tiene un mecanismo equivalente

Para usarlos con los rules de Cashea, copia los `.md` al directorio correspondiente. AppSec puede ayudarte si necesitás.

**¿Qué pasa con Claude Code Enterprise / managed settings?**

GitHub está trabajando en "managed settings" para deploy de configs a nivel org. Cuando esté disponible y testeado, vamos a evaluarlo (es lo que mencionamos en el ANEXO TBD de la PPT como alternativa a la inyección en el repo).

---

Contacto: #appsec en Slack · security@cashea.app
