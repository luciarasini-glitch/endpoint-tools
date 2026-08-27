# Text Cashea

Extensión de navegador (Chrome/Edge, Manifest V3) para definir snippets de texto con un atajo (ej. `/firma`) y expandirlos automáticamente en cualquier campo editable de cualquier sitio — como Text Blaze.

Por ahora es 100% local: cada persona guarda sus propios snippets en el `chrome.storage.local` de su navegador. No hay login, no hay backend, no hay sincronización entre máquinas.

## Cómo cargarla

1. Abrir `chrome://extensions` (o `edge://extensions` en Edge).
2. Activar **"Modo de desarrollador"** (arriba a la derecha).
3. Click en **"Cargar sin empaquetar"** ("Load unpacked").
4. Seleccionar esta carpeta (`Text Cashea`).

Para abrir el gestor de snippets: en `chrome://extensions`, click en **"Detalles"** de la tarjeta de Text Cashea → **"Opciones de la extensión"**. (La extensión no tiene ícono en la barra de herramientas del navegador, así que no hay un acceso vía click derecho ahí.)

### ID fijo de la extensión

El `manifest.json` incluye un campo `"key"` (clave pública) generado con `text-cashea-key.pem` (queda en esta carpeta, no se sube a git — ver `.gitignore`). Esto hace que el ID de la extensión sea siempre el mismo sin importar desde qué ruta se cargue:

```
gmefljmfcamjmkjgenhnbfhgbljodpmf
```

Si tu organización bloquea la instalación de extensiones por política (`ExtensionInstallBlocklist`), este es el ID que hay que agregar a `ExtensionInstallAllowlist` (Google Admin Console o el MDM que uses) para poder cargarla en modo desarrollador.

## Después de cada cambio de código

- Volver a `chrome://extensions` y click en el ícono de recarga (🔄) de la tarjeta de la extensión.
- Si el cambio fue en `content-script.js`, además hay que recargar cualquier pestaña donde se quiera probar (el content script no se actualiza solo en pestañas ya abiertas).

## Plan de prueba manual

1. Crear una carpeta y un snippet de prueba (ej. atajo `/test`, texto "Hola desde Text Cashea") desde la página de opciones.
2. Probar el reemplazo en una página real servida por http/https con un `<textarea>` simple (`test.html` en esta carpeta sirve para esto — abrirlo vía un servidor local, nunca como `data:` URL: las páginas `data:` están excluidas de los content scripts por diseño de Chrome, sin importar el `matches` del manifest).
3. Probar lo mismo en el campo `contenteditable` de `test.html`, y en el compositor de Gmail.
4. Confirmar que no se puede crear un segundo snippet con el mismo atajo (debería mostrar un error en rojo).
5. Confirmar que al borrar una carpeta se avisa cuántos snippets se van a borrar con ella.

## Compatibilidad por sitio

### Confirmado funcionando

- Campos `<input>` / `<textarea>` estándar y `contenteditable` simple (formularios web, CRMs, etc.).
- **Gmail** (compositor de correo). Requiere `match_about_blank: true` en el manifest, porque el editor de Gmail vive en un iframe `about:blank`.
- **WhatsApp Web** y **Slack, usado desde el navegador** (`slack.com`, no la app de escritorio). Ambos están construidos con **Lexical** (el framework de edición de texto enriquecido de Meta), que mantiene su propio modelo interno y no reacciona a una edición externa hecha de la forma "obvia" (`execCommand('insertText')` sobre un Range armado a mano). La solución que terminó funcionando: extender la selección hacia atrás sobre el atajo con `selection.modify('extend', 'backward', 'character')` (el mismo mecanismo que Shift+flecha) y simular un evento nativo de `paste` para reemplazarla — esperando primero un tick a que el editor termine de procesar la última tecla antes de tocar nada.
- **Google Docs**. Docs no usa un `contenteditable` normal para el documento — captura las teclas mediante un `<iframe src="about:blank">` oculto (`docs-texteventtarget-iframe`) con un `div[contenteditable][role="textbox"]` adentro, que Docs mantiene casi vacío todo el tiempo y nunca dispara un evento `input` real (lee la tecla directamente vía `keydown` y actualiza su propio modelo). Por eso tiene su propio content script separado (`src/content/google-docs.js`): arma un buffer propio de lo tecleado a partir de eventos `keydown`, y al detectar un atajo simula Backspace (`KeyboardEvent` de verdad, no `execCommand`) + un evento de `paste` para reemplazarlo. Ese mismo iframe se recrea en algún momento después de cargar la página, así que el script escucha a nivel de documento del iframe en vez de atarse a un elemento puntual.

### No funciona

- **Apps de escritorio nativas** (Slack de escritorio, WhatsApp de escritorio, etc.): una extensión de Chrome solo puede actuar dentro del navegador — esto es un límite estructural, no algo arreglable desde el código.
- Editores que renderizan sobre canvas/WebGL sin un mecanismo de captura de teclado real en el DOM (ej. Figma). Google Sheets y Slides no están probados todavía — pueden tener un mecanismo similar al de Docs, pero no se confirmó.

### Sin probar todavía

- Notion, Jira, y formularios/CRMs genéricos no listados arriba.

## Otras limitaciones

- Los atajos son únicos globalmente (no se puede repetir el mismo atajo en dos carpetas distintas).
- Solo texto plano por ahora: sin variables dinámicas, sin posicionamiento de cursor tipo `/cursor`, sin formato enriquecido.
- El "sync en vivo" de snippets nuevos hacia pestañas ya abiertas no siempre es instantáneo — si un snippet recién creado no se detecta, recargar la pestaña primero.
