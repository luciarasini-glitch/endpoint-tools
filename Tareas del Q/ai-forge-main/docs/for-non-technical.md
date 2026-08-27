# Guía para no-técnicos

> Si no sabés qué es Docker, Kubernetes, o por qué importa, esta guía es para vos.

## ¿Qué es ai-forge?

Es la **forja** donde se crean las aplicaciones internas de Cashea de manera segura.

Pensalo así:

> *Antes:* "necesito un dashboard para revisar pagos pendientes" → mandás un mail a ingeniería → 2 semanas de back-and-forth → quizás te lo hacen, quizás no.
>
> *Ahora:* abrís un Issue acá, AppSec lo revisa, y en 30 segundos tenés un repo con todo armado y seguro listo para que vos o un dev empiecen a desarrollar.

## Los 3 tipos de proyecto

Toda app interna en Cashea se construye desde uno de estos 3 templates. Nadie arranca de cero.

| Tipo | Cuándo usarlo | Ejemplo |
|---|---|---|
| 🖥️ **Backoffice** | Querés una **pantalla** (dashboard, herramienta interna con UI) que usan empleados de Cashea | "Quiero ver todos los pedidos del día y poder aprobarlos manualmente" |
| ⚙️ **Microservicio** | Querés un **servicio** que hace algo sin UI (procesa datos, expone API, integra con BigQuery) | "Quiero que cada vez que llegue un pago, se valide contra mi modelo de fraude" |
| 🎨 **Paquete frontend** | Querés un **componente reutilizable** que se usa en varios backoffices | "Quiero una tabla con filtros y paginación que sirva para varios dashboards" |

Si no sabés cuál te corresponde, abrí un Issue y describí lo que querés hacer. AppSec te ayuda a clasificarlo.

## ¿Cómo creo un proyecto nuevo?

### Paso 1: Abrir Issue

1. Andá a la página principal del repo `ai-forge`
2. Click en **"Issues"** (arriba)
3. Click en **"New Issue"** (verde, arriba a la derecha)
4. Elegí el template que te corresponde

### Paso 2: Llenar el formulario

El formulario te va a preguntar:

- **Nombre del proyecto** (corto, en inglés, con guiones — ej: `risk-review-bo`)
- **Para qué sirve** (descripción de 2-3 oraciones)
- **Tu equipo** (engineering, platform, finance, etc.)
- **Qué tipo de datos va a manejar** (público, interno, confidencial, restringido)
- **Otras preguntas específicas** según el tipo

> 💡 **Tip:** si vas a manejar datos sensibles (números de tarjeta, datos personales, secrets), marcalo aunque no estés 100% seguro. AppSec ajusta si hace falta.

### Paso 3: Esperar aprobación

AppSec + CloudSec revisan tu Issue. Posibles resultados:

- ✅ **Aprobado:** te ponen el label `approved` y la mágica empieza
- 🔄 **Necesita info:** te comentan pidiendo más detalle
- ❌ **Rechazado:** te explican por qué y proponen alternativas

Tiempo típico: 1-2 días hábiles.

### Paso 4: Recibir tu repo

Cuando se aprueba, automáticamente:

1. Se crea un repo nuevo en `github.com/cashea-bnpl/<tu-proyecto>`
2. El repo viene con todos los archivos base (código de ejemplo, configs, Dockerfile, etc.)
3. Tiene los rules de seguridad inyectados — Claude Code y Claude.ai los van a usar
4. Tu equipo tiene permisos automáticamente
5. AppSec tiene admin para revisar cambios críticos

Recibís un comentario en tu Issue con el link. Listo, podés empezar.

## ¿Y ahora qué hago con el repo?

Depende de cuánto sepas:

### Opción A: Tenés ayuda de un dev

Pasale el link al dev. Ellos saben qué hacer.

### Opción B: Querés desarrollar vos mismo con Claude

1. Cloná el repo (Slack #appsec si no sabés cómo)
2. Instalá [Claude Code](https://docs.anthropic.com/claude/docs/claude-code) en tu máquina
3. Abrí Claude Code en la carpeta del repo
4. Pedile cosas: *"agregame un endpoint que liste pedidos del día"*

Claude Code va a:
- Leer los rules de seguridad del repo (`.claude/rules/`)
- Generar código que cumple esos rules (auth, validación, logging, etc.)
- Avisarte si pedís algo que viola los rules

### Opción C: Querés usar Claude.ai (web) en vez de CLI

Misma lógica. El skill `secure-coding` ya está activo en tu cuenta de Claude.ai de Cashea. Pedile lo que necesites en el chat web, copiá el código y pegalo en tu repo.

> ⚠️ **OJO:** No pegues datos reales de clientes en el chat. Si tenés que mostrarle un ejemplo a Claude, usá datos fake (`user@example.com`, `00000000`, etc.). Más info: [Política de Uso de IA](https://www.notion.so/cashea/Politica-Uso-IA-Codigo).

## Lo que el sistema hace por vos automáticamente

No hace falta que sepas de seguridad. Estos controles aplican aunque no los pidas:

- ✅ Tu código no puede tener secrets hardcodeados (CI lo bloquea)
- ✅ Tus endpoints requieren autenticación por default
- ✅ Tus queries a la base de datos están protegidas contra SQL injection
- ✅ Tu app corre en un container que no puede salir a internet libremente
- ✅ Si usás un paquete con vulnerabilidades, te avisa
- ✅ Si pegás un secret en el código, te lo borra antes de subir

## Preguntas frecuentes

**¿Tengo que saber programar para usar esto?**

Idealmente sí, aunque sea un poco. Pero con Claude Code o Claude.ai podés llegar lejos sin saber demasiado. Si te trabás, AppSec te ayuda.

**¿Cuánto cuesta hacer un proyecto nuevo?**

Cero. El costo está en el tiempo que vos invertís desarrollándolo. La infra la paga Cashea via GCP.

**¿Y si necesito ayuda de un dev en algún punto?**

Mandá un mensaje en Slack al equipo que corresponda. Si no sabés a quién, preguntá en #appsec y te re-dirigimos.

**¿Mi proyecto va a estar disponible para clientes externos?**

**No.** Estos proyectos son **internos** — solo accesibles con cuenta de Cashea via JumpCloud. Si necesitás algo público, abrí un Issue y conversamos.

**¿Qué pasa si rompo algo?**

Nada grave. El código siempre se revisa antes de mergear a producción. Y si igual algo se rompe, hay rollback automático.

**¿Cuándo voy a tener un dashboard listo?**

Depende de lo que pidas. Un dashboard simple con Claude puede estar en 1-2 días. Uno complejo con muchas integraciones, 1-2 semanas.

## Contacto

- 💬 Slack: #appsec
- 📧 Email: security@cashea.app
- 📖 Notion: AI Security workspace
