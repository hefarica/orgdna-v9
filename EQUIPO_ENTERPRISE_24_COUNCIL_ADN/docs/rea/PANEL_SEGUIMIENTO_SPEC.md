# PANEL_SEGUIMIENTO_SPEC -- Contrato de UI del seguimiento (P3 / C4, follow-ups)

**Estado:** documento de DISENO cerrado. **No se aplico codigo.** Este archivo es el unico artefacto de `t33`:
`engine/`, `web/`, `MANIFIESTO_SHA256.txt` y el sello no se tocaron, y no se ejecuto `resella_paquete.py` ni la suite.
**Consumidores:** `t24` (implementacion: bridge + `web/`), `t26`/`t24` (guion Chromium). Objetivo: que la implementacion
sea **mecanica** -- copiar selectores, textos y formas de este documento, sin inventar nada.
**Convencion de citas:** `archivo:linea` sobre el codigo leido para este documento. Ninguna afirmacion tecnica se apoya
en memoria.
**Vocabulario:** prosa **sin acentos** (como `docs/PLATAFORMA_*.md`); el unico caracter no ASCII que se conserva es el
separador `·` de los literales de UI, porque el panel ya lo usa (`web/app.js:372`) y el arnes compara byte a byte.

---

## 0. Reglas duras de esta UI (las cinco que no se negocian)

| # | Regla | Consecuencia verificable |
|---|---|---|
| R-1 | **Todo id nuevo empieza por `followups-`.** | Las lineas de handler de `web/app.js` que empiezan por `$('#dsh...`, `$('#harness...`, `$('#cordis...` o `$('#prepare-cordis...` estan **pineadas por hash** (`qa_v7/test_dsh_preservation_independent.py:30-33`). Un id nuevo con otro prefijo no entra en ese conjunto y no rompe el pin; un id nuevo con prefijo pineado, si. |
| R-2 | **No tocar las 14 funciones pineadas de `web/app.js`** (`request`, `renderHarness`, `renderDshConnection`, `renderDshLauncher`, `renderCordis`, `updateHarnessControls`, `updateExtensionControls`, `updateDshLauncherControls`, `pollHarness`, `harnessInput`, `dshConnectionStatus`, `disconnectDsh`, `discoverDshLauncher`, `readGenerationState`). | `qa_v7/dsh_baseline.json:javascript_functions` (14 entradas) se recompone por hash de cada funcion (`...:21-28`). Se **llaman** tal cual; no se editan. |
| R-3 | **No tocar las tres ramas de despacho pineadas** de `engine/bridge.py`: `if action in HARNESS_ACTIONS`, `if action in LAUNCHER_ACTIONS`, `if action in INTEGRATION_ACTIONS`. | `qa_v7/dsh_baseline.json:bridge_dispatch_branches` fija el hash del cuerpo de cada rama (`...:35-41`). La accion nueva se despacha en una rama **nueva**. |
| R-4 | **Cero temporizadores.** El seguimiento avanza solo con `POST /api/followups-tick` disparado por una persona. | Doctrina de tick explicito: `engine/gang_supervisor.py:19-21`, citada por `docs/rea/TEAM_API_CONTRACT_v1.md:7` y por `engine/followups.py:314-316`. Nada de `setInterval`, `setTimeout` ni polling automatico en esta seccion. |
| R-5 | **La autoria de un recordatorio nunca es un miembro.** | El motor publica con **su** identidad de coordinacion (`engine/followups.py:283-287`, `:300-304`) y se salta sus propios mensajes (`:222`). La UI lo declara explicitamente (sec. 6). |

Nota de alcance de los pines: `web/app.js`, `web/index.html` y `web/style.css` **no** estan en la lista de archivos
byte-pineados (`qa_v7/dsh_baseline.json:files`, 41 entradas: solo `cordis_extension/**`, `engine/{cordis_extension,
dsh_connection,dsh_harness,dsh_launcher,integration_recommendations,integration_tools,launcher}.py`, `launch.cmd` y
`relanzador_dsh/**`). Por tanto `t24` **puede** editar `web/`; lo que no puede es alterar R-1..R-3.

---

## 1. Contrato HTTP: `followups-tick` y `followups-drain`

### 1.1 Como entra una accion hoy (comportamiento heredado, no se reinventa)

- `POST /api/<accion>` -> `LocalHandler.do_POST` -> `state.execute(<accion>, body)` -> JSON del resultado con **200**
  (`engine/bridge.py:2014-2041`).
- Antes de despachar, el handler exige: sesion (`orgdna_session`), `Origin` local, `X-CSRF-Token` valido,
  `Content-Type: application/json`, `Content-Length` en `(0, MAX_BODY]` y ausencia de `Transfer-Encoding`
  (`engine/bridge.py:1926-1950`, `:2015-2031`).
- `BridgeError`/`ValueError`/`TypeError` -> **400** `{"error": "<texto redactado>"}` (`engine/bridge.py:2042-2044`).
  Cualquier otra excepcion -> **502** `{"error": "La accion no termino: ..."}` (`:2045-2049`).
- El despacho ocurre **dentro** de `self.lock` (`engine/bridge.py:1302-1303`).
- Precedente exacto de version: `expected_state_version` se compara con `self.organization.get('state_version', 1)` y
  el error es literal `'Version obsoleta: recarga el estado antes de guardar; expected_state_version debe coincidir.'`
  (`engine/bridge.py:621-623`).

### 1.2 `POST /api/followups-tick`

**Cabeceras obligatorias** (las pone `request()` del panel, `web/app.js:67-71`):
`Content-Type: application/json`, `X-CSRF-Token: <csrf>`, `Origin: <origen local>`, cookie `orgdna_session`,
`credentials: same-origin`.

**Body -- conjunto CERRADO de claves** (una clave extra o desconocida => 400; precedente de rechazo de campos:
`engine/bridge.py:185`):

```json
{ "expected_state_version": 7 }
```

| Campo | Tipo | Obligatorio | Validacion | Error 400 literal |
|---|---|---|---|---|
| `expected_state_version` | entero (`type(x) is int`, nunca `bool`) | si | debe ser **igual** a `organization.state_version` (por defecto `1`) | `Version obsoleta: recarga el estado antes de guardar; expected_state_version debe coincidir.` |
| *(cualquier otra)* | -- | no | se **rechaza** | `Campos no admitidos: <lista ordenada>.` |

**Validaciones de estado** (ademas de las de transporte, que ya aplica el handler):

| Situacion | Codigo | `error` literal |
|---|---|---|
| Sin diseno (`state.organization is None`) o diseno obsoleto (`generation_stale === true`) | 400 | `Genera un diseño actualizado antes de registrar esta acción.` (literal de `require_version`, `engine/bridge.py:637`; es el mismo que usan las acciones del canal, a proposito) |
| `expected_state_version` ausente, no entero o distinto | 400 | `Versión obsoleta: recarga el estado antes de guardar; expected_state_version debe coincidir.` (`engine/bridge.py:639`) |
| `team_followups.available === false` (roster invalido, canal no disponible) | 400 | el **mismo** `reason` que publica `team_followups.reason` (se propaga sin reescribir) |
| Tick con exito | **200** | -- (cuerpo de exito, ver abajo) |

**Respuesta 200 -- el estado publico completo + sobre efimero de la accion.** El cuerpo es **exactamente**
`state.public()` (la misma forma que `GET /api/state`, `engine/bridge.py:871-894`) con la clave `team_followups`
(sec. 2) y **una** clave adicional, `followups_tick`, que **no** viaja en `GET /api/state`:

```json
{
  "...": "resto del estado publico, sin cambios (config, organization, team_channel, team_memory, ...)",
  "team_followups": { "...": "ver sec. 2" },
  "followups_tick": {
    "events": 2, "commitments": 1, "reminders": 1, "escalations": 0,
    "skipped": 0, "reported": 0, "at": "2026-10-10T18:00:00Z"
  }
}
```

`followups_tick` se deriva de la tupla que devuelve `FollowupsEngine.tick()` (`engine/followups.py:314-320`): se
cuentan los eventos por `event` (`commitment`, `commitment_skipped`, `reminder`, `escalated`, `reported`). Es
**efimero**: el panel lo guarda en una variable de modulo (`followupsTick`, mismo patron que `capPlan` o
`selectedCouncil`) y lo pinta en `#followups-status`; no modifica `state` persistido ni el proyecto.

**Efecto declarado:** exactamente **un** `FollowupsEngine.tick()` -- escaneo de mensajes nuevos y persecucion de
vencidas contra **un solo** `now` (`engine/followups.py:314-320`). No ejecuta agentes, no llama proveedores, no escribe
en disco, no abre red y no inicia temporizadores. Anade **un recibo**:

```
receipt('followups-tick', 'success',
        'Tick explicito de seguimiento: N evento(s), M recordatorio(s), K escalacion(es). '
        'No se ejecutaron agentes ni se llamo a ningun proveedor.')
```

(convencion de recibos: `engine/bridge.py:1041-1044`, `:1068`).

### 1.3 `POST /api/followups-drain`

**Body -- conjunto CERRADO de claves:**

```json
{ "expected_state_version": 7, "member": "a-01", "max_count": 20 }
```

| Campo | Tipo | Obligatorio | Validacion | Error 400 literal |
|---|---|---|---|---|
| `expected_state_version` | entero | si | igual a `organization.state_version` | `Version obsoleta: recarga el estado antes de guardar; expected_state_version debe coincidir.` |
| `member` | texto | si | debe resolver a un miembro del roster vigente (`TeamChannel.resolve`, `engine/team_channel.py`, lanza `unknown_member`) | `member debe ser un miembro del roster vigente.` |
| `max_count` | entero | si | `1 <= max_count <= 100` (techo de `DEFAULT_DRAIN`, `engine/team_channel.py:DEFAULT_DRAIN = 100`) | `max_count debe ser un entero entre 1 y 100.` |
| *(cualquier otra)* | -- | no | se **rechaza** | `Campos no admitidos: <lista ordenada>.` |

**Respuesta 200 -- estado publico + sobre efimero `followups_drained`:**

```json
{
  "...": "resto del estado publico, sin cambios",
  "team_followups": { "...": "ver sec. 2" },
  "followups_drained": {
    "member": "a-01",
    "max_count": 20,
    "at": "2026-10-10T18:00:00Z",
    "reminders": [
      { "id": "m-7", "actor": "coordinacion-local", "to": "a-01", "topic": "followups",
        "text": "follow-up 1/3: a-01 tiene un compromiso pendiente de entrega: \"...\" (tarea fu-1).",
        "created_at": "2026-10-10T18:00:00Z", "provenance": "engine.followups",
        "content_verified": false, "authority": { "...": "ver sec. 6.2" } }
    ],
    "other": [ { "id": "m-8", "actor": "a-02", "to": "a-01", "topic": "coordination", "text": "...", "...": "..." } ],
    "counts": { "delivered": 2, "reminders": 1, "other": 1 }
  }
}
```

**Semantica del drenaje (decidida aqui, para que `t24` no elija):** `followups-drain` delega en la primitiva
**destructiva** ya existente `TeamChannel.inbox(member, max_count)`
(`engine/team_channel.py:def inbox`, usada hoy por la accion `channel-inbox`, `engine/bridge.py:1066-1068`) y
**clasifica** cada mensaje entregado por su `topic`:

- `topic == "followups"` (`engine/followups.py:91`, `FOLLOWUP_TOPIC`) -> `reminders[]` (con `authority` de sec. 6.2).
- cualquier otro `topic` -> `other[]`.

**Nada se descarta ni se filtra en silencio**: si el buzon del miembro tenia mensajes de otros topicos, salen en
`other[]` y el estado lo dice (`counts`). *Alternativa declarada, solo si el operador la autoriza:* anadir
`topic=None` **aditivo** a `TeamChannel.inbox` para consumir solo recordatorios; **no** es la via por defecto porque
toca `engine/team_channel.py` y obliga a su propia prueba de no-regresion.

**Efecto declarado:** una lectura destructiva del buzon de **un** miembro, y **un recibo**:

```
receipt('followups-drain', 'success',
        'Inbox de seguimiento drenado: N mensaje(s) entregados (R recordatorio(s) de seguimiento, '
        'O de otros topicos; lectura destructiva).')
```

### 1.4 Tabla completa de codigos

| Codigo | Causa | `error` literal | Origen |
|---|---|---|---|
| **200** | tick o drenaje ejecutado | -- | `engine/bridge.py:2040-2041` |
| **400** | `expected_state_version` ausente / no entero / distinto | `Version obsoleta: recarga el estado antes de guardar; expected_state_version debe coincidir.` | `engine/bridge.py:621-623` |
| **400** | claves extra | `Campos no admitidos: ...` | `engine/bridge.py:185` |
| **400** | sin diseno / diseno obsoleto | `Genera un diseño actualizado antes de registrar esta acción.` (`engine/bridge.py:637`, literal de `require_version` que comparten las acciones del canal; NO se invento un literal por accion) |
| **400** | seguimiento no disponible | el `reason` de `team_followups` | sec. 2.3 |
| **400** | `member` invalido | `member debe ser un miembro del roster vigente.` | `engine/team_channel.py:resolve` |
| **400** | `max_count` invalido | `max_count debe ser un entero entre 1 y 100.` | `engine/team_channel.py:inbox` |
| **400** | cuerpo no es objeto JSON | `El cuerpo debe ser un objeto JSON.` | `engine/bridge.py:2034-2035` |
| **403** | cliente no local / `Host` distinto | `Host local no valido.` | `engine/bridge.py:1927-1929` |
| **403** | `Sec-Fetch-Site: cross-site` | `Origen cruzado bloqueado.` | `:1930-1932` |
| **403** | mutacion sin `Origin` local | `Origin local obligatorio.` | `:1933-1935` |
| **403** | sin cookie de sesion | `Abre primero el panel local en esta sesion.` | `:1936-1946` |
| **403** | `X-CSRF-Token` invalido | `Token de sesion no valido. Recarga el panel.` | `:1947-1949` |
| **404** | ruta fuera de `/api/` | `Ruta no encontrada.` | `:2037-2038` |
| **413** | cuerpo vacio o demasiado grande | `Cuerpo vacio o demasiado grande.` | `:2026-2028` |
| **415** | `Content-Type` distinto de JSON | `Se requiere application/json.` | `:2029-2031` |
| **502** | excepcion inesperada | `La accion no termino: ...` | `:2045-2049` |

Los textos de 403/404/413/415/502 los produce el handler **heredado**: `t24` no los reescribe. Los de 400 son los
que `t24` debe lanzar como `BridgeError` con el literal exacto de esta tabla.

---

## 2. Forma exacta de `team_followups` dentro de `/api/state`

### 2.1 Origen y composicion

`team_followups` se compone **asi** (nada mas, nada menos):

```
team_followups = FollowupsEngine.ledger_view()      # engine/followups.py:353-367  (fuente unica)
               + {'available': true, 'reason': null, 'in_memory_session_only': true,
                  'reset_policy': 'session_only', 'authority': {...sec. 6.2}}
```

`ledger_view()` ya devuelve `schema_version`, `provenance`, `agent_member_id`, `supervisor_member_id`,
`reminder_interval_secs`, `max_reminders`, `processed_message_ids`, `tasks`, `archive`, `events` y `stats`. **No se
recalcula nada de eso en el bridge** (evita divergencia engine/UI).

**Dos campos OPCIONALES y aditivos** (no forman parte de los 15 obligatorios; si `t24` los omite, el contrato sigue
cumpliendose, pero el panel queda mas honesto si los trae):

| Campo | Tipo | Regla |
|---|---|---|
| `clock_source` | `"system"` \| `"injected"` | Declara con que reloj corre el motor. Se calcula **sin flags ni variables de entorno**, por introspeccion del seam de prueba: `'injected' if type(self)._followups_clock is not BridgeState._followups_clock else 'system'` (ver sec. 5.1 E-2a). Evita que la UI presente como tiempo real una simulacion del arnes. |
| `loop` | `{available, reason, state}` | Estado **de solo lectura** del bucle de equipo, si `engine/team_loop.py` llega a existir y otra tarea lo cablea. Hoy **no existe** el modulo, asi que el valor obligatorio es `{'available': false, 'reason': 'El bucle de equipo (engine/team_loop.py) no esta cableado en esta vista.', 'state': null}`. `t24` **no** cablea el bucle: solo reserva el sobre. |

### 2.2 Ejemplo completo (disponible)

```json
"team_followups": {
  "available": true,
  "reason": null,
  "in_memory_session_only": true,
  "reset_policy": "session_only",
  "clock_source": "system",
  "loop": { "available": false,
            "reason": "El bucle de equipo (engine/team_loop.py) no esta cableado en esta vista.",
            "state": null },
  "schema_version": "engine.followups/1",
  "provenance": "engine.followups",
  "agent_member_id": "coordinacion-local",
  "supervisor_member_id": "a-00",
  "reminder_interval_secs": 3600.0,
  "max_reminders": 3,
  "processed_message_ids": ["m-1", "m-2", "m-3"],
  "tasks": [
    {
      "id": "fu-1", "message_id": "m-3", "owner_member_id": "a-01",
      "snippet": "entrego el informe el viernes",
      "state": "chasing", "reminders_sent": 0,
      "next_reminder_at": 1791670800.0,
      "created_at": "2026-10-10T17:00:00Z", "updated_at": "2026-10-10T17:00:00Z",
      "escalated_at": null, "reported_message_id": null, "reported_at": null,
      "history": [
        { "event": "commitment", "at": "2026-10-10T17:00:00Z",
          "detail": "compromiso detectado en el mensaje m-3" }
      ]
    }
  ],
  "archive": [],
  "events": [
    { "event": "commitment", "at": "2026-10-10T17:00:00Z", "task_id": "fu-1",
      "owner_member_id": "a-01", "message_id": "m-3", "snippet": "entrego el informe el viernes" }
  ],
  "stats": { "chasing": 1, "escalated": 0, "reported": 0, "active": 1, "archived": 0, "total": 1 },
  "authority": {
    "kind": "coordination", "is_member_authored": false,
    "actor_member_id": "coordinacion-local", "topic": "followups",
    "provenance": "engine.followups",
    "role_label": "Coordinacion local (motor de seguimiento)",
    "identity_verified": false,
    "note": "Los recordatorios y escalaciones los emite el motor engine.followups; ningun miembro del roster es su autor."
  }
}
```

### 2.3 Los cuatro estados degradados -- **`team_followups` NUNCA lanza**

`public()` se llama en cada `/api/state` y en casi todas las acciones: un fallo aqui convierte el panel entero en un
500. Se replica la disciplina ya escrita para el canal (`engine/bridge.py:964-976`: "nunca revienta `public()` del
bridge").

| Estado | `available` | `reason` literal | Resto de campos |
|---|---|---|---|
| Sin diseno (`state.organization is None`) | `false` | `Genera un diseno para abrir el seguimiento del equipo.` | ausentes salvo `authority` (siempre presente) |
| Sin canal (`_ensure_team_channel()` devuelve `None`) | `false` | `Genera un diseno para abrir el seguimiento del equipo.` | idem |
| Roster invalido (`ChannelError`) | `false` | `Roster invalido para el seguimiento: <mensaje del ChannelError>` | idem |
| Motor no construible (`FollowupsError`: agente/supervisor fuera del roster) | `false` | `El motor de seguimiento no esta disponible: <mensaje del FollowupsError>` | idem |

Reglas de implementacion (obligatorias):

1. `team_followups_public()` envuelve **todo** en `try/except (ChannelError, FollowupsError, Exception)` y, ante
   cualquier fallo, devuelve `{'available': False, 'reason': '...', 'authority': {...}}`. **Prohibido** propagar.
2. Con `available: true`, `reason` es **`null` explicito** (no ausente): "nada desconocido se convierte en cero" y la
   UI distingue `null` de `undefined`.
3. Cuando no hay diseno, la clave existe igualmente: el panel muestra el motivo, nunca un hueco ni un error.
4. `processed_message_ids` **no se pinta** (es traza de deduplicacion, `engine/followups.py:191-192`); se expone para
   auditoria y para la prueba de que un mensaje se procesa **una sola vez**.
5. `agent_member_id` es la **identidad de coordinacion** con la que firma el motor; **no** es el autor humano de ningun
   mensaje (sec. 6).

### 2.4 Campos, uno por uno

| Campo | Tipo | Origen | Uso en UI |
|---|---|---|---|
| `available` | `bool` | bridge | Habilita/deshabilita los controles; `false` => solo motivo |
| `reason` | `string \| null` | bridge | Texto de estado degradado |
| `in_memory_session_only` | `bool` (siempre `true`) | bridge | Aviso "se reinicia con cada rediseno" |
| `reset_policy` | `"session_only"` | bridge | Idem |
| `schema_version` | `"engine.followups/1"` | engine (`engine/followups.py:89`) | Se muestra en el bloque de motor |
| `provenance` | `"engine.followups"` | engine (`:90`) | Idem + `authority.provenance` |
| `agent_member_id` | `string` | engine | Se muestra **como identidad de coordinacion**, nunca como autor de un miembro |
| `supervisor_member_id` | `string` | engine | Destino de la escalacion; se muestra como "dirigido a" |
| `reminder_interval_secs` | `number` (def. `3600.0`, `:105`) | engine | Se muestra formateado; **no** editable desde la UI |
| `max_reminders` | `int` 1..10 (def. `3`, `:106-107`) | engine | Denominador de "recordatorios N/M" |
| `processed_message_ids` | `string[]` | engine | No se pinta (auditoria) |
| `tasks[]` | `object[]` | engine (`:246-257`) | Lista de compromisos (`#followups-task-list`) |
| `archive[]` | `object[]` | engine (`:328-330`) | Historial (`#followups-archive-list`) |
| `events[]` | `object[]` | engine (`:201-204`, `:349-351`) | Registro append-only (`#followups-events`) |
| `stats` | `object` | engine (`:338-347`) | Contadores (`#followups-metrics`) |
| `authority` | `object` | bridge (constante) | Declaracion de autoria (sec. 6) |
| `clock_source` | `"system"` \| `"injected"` (OPCIONAL) | bridge, por introspeccion del seam (sec. 5.1 E-2a) | Se muestra junto al motor: si es `injected`, la UI dice `reloj inyectado por el arnes` y **no** presenta la simulacion como tiempo real |
| `loop` | `{available, reason, state}` (OPCIONAL) | bridge (sobre reservado) | `available:false` hoy; `state` se rellena **solo** si otra tarea cablea `engine/team_loop.py` (esta tarea no lo cablea) |

**`tasks[]` / `archive[]` -- campos exactos** (`_create`, `:246-257`; `_close`, `:259-267`):

| Campo | Tipo | Nota |
|---|---|---|
| `id` | `"fu-<n>"` | correlativo del motor |
| `message_id` | `string` | mensaje que abrio el compromiso |
| `owner_member_id` | `string` | **destinatario** del recordatorio (no autor) |
| `snippet` | `string` <= 200 (`MAX_SNIPPET`, `:109`) | cita del compromiso |
| `state` | `"chasing" \| "escalated" \| "reported"` (`:94-97`) | estados del vocabulario del motor |
| `reminders_sent` | `int` | numerador de "recordatorios N/M" |
| `next_reminder_at` | `number (epoch) \| null` | `null` en `escalated` y `reported` |
| `created_at`, `updated_at` | ISO-8601 Z | `_stamp`, `:198-199` |
| `escalated_at` | ISO `\| null` | solo tras escalar |
| `reported_message_id`, `reported_at` | `string \| null`, ISO `\| null` | solo tras reportar |
| `history[]` | `{event, at, detail}[]` | `commitment`/`reminder`/`escalated`/`reported` (`:206-207`) |

**`events[]` -- clases exactas** (`:230-243`, `:292-309`): `commitment`, `commitment_skipped`, `reminder`,
`escalated`, `reported`. Cada fila lleva `event`, `at` y, segun clase, `task_id`, `owner_member_id`, `message_id`,
`snippet`, `count`/`max` o `reminders_sent`/`reason`.

**`stats`** (`:338-347`): `{chasing, escalated, reported, active, archived, total}`.

**Doctrina que la UI debe respetar:** `tick()` es **explicito** (`:314-316`); `escalated` y `reported` son
**terminales** (`next_reminder_at = null`, `:299`); no hay reintento automatico tras escalar.

---

## 3. Mapa de DOM

### 3.1 Ubicacion

Dentro de `<section id="council" class="page" ...>` (`web/index.html:102`), **despues** del bloque
`<details class="panel coordination-panel" id="team-memory-panel">...</details>` (termina en `web/index.html:105`) y
antes del `</section>` de cierre. Es un `<details>` como sus hermanos `#team-channel-panel` y `#team-memory-panel`,
con `<summary>` operable por teclado.

### 3.2 Tabla de ids (todos con prefijo `followups-`; ninguno existente se renombra)

| Id | Elemento | Rol / aria | Texto o contenido | Quien lo escribe |
|---|---|---|---|---|
| `followups-panel` | `details.panel.coordination-panel` | `<summary>` nativo (teclado) | `Seguimiento (C4): recordatorios y escalaciones del canal` | estatico (HTML) |
| `followups-count` | `span.tag` | dentro del `summary` | `"{n} activos · {m} archivados"` | `renderFollowups` |
| `followups-status` | `p.helper` | `role="status" aria-live="polite"` | ver sec. 3.4 | `renderFollowups`, `tickFollowups`, `drainFollowups` |
| `followups-authority` | `p.helper` | `id` referenciado por `aria-describedby` de `#followups-tick` | ver sec. 6.4 | `renderFollowups` (constante) |
| `followups-error` | `div.notice.error` | `role="alert"`, arranca `hidden` | el `error` del 400 | `tickFollowups` / `drainFollowups` |
| `followups-metrics` | `div.followups-metrics` | `aria-live="polite"`, `aria-label="Contadores de seguimiento"` | 4 celdas | `renderFollowups` |
| `followups-stat-active` | `strong` | dentro de la celda `Activos` | entero | `renderFollowups` |
| `followups-stat-chasing` | `strong` | celda `En persecucion` | entero | `renderFollowups` |
| `followups-stat-escalated` | `strong` | celda `Escalados` | entero | `renderFollowups` |
| `followups-stat-reported` | `strong` | celda `Reportados` | entero | `renderFollowups` |
| `followups-tick` | `button.secondary` | `type="button"`, `aria-describedby="followups-authority"` | `Ejecutar tick explicito` | estatico |
| `followups-drain-member` | `select` | `aria-label="Miembro cuyo inbox de seguimiento se drena"` | opciones `"{name} · {member_id}"` | `renderFollowups` |
| `followups-drain-max` | `input type="number"` | dentro de `<label>` visible | `min="1" max="100" value="20"` | estatico |
| `followups-drain` | `button.textbutton` | `type="button"` | `Drenar recordatorios del miembro` | estatico |
| `followups-task-list` | `div.record-list` | `aria-label="Compromisos en seguimiento"` | `article.record[data-followup-task]` | `renderFollowups` |
| `followups-empty-tasks` | `p.empty` | -- | `Sin compromisos en seguimiento: ninguna mencion con promesa detectada en el canal.` | `renderFollowups` |
| `followups-archive-list` | `div.record-list` | `aria-label="Historial de seguimientos cerrados"` | `article.record[data-followup-task]` | `renderFollowups` |
| `followups-empty-archive` | `p.empty` | -- | `Sin seguimientos archivados: un reporte cierra y archiva el compromiso.` | `renderFollowups` |
| `followups-drained` | `div.record-list` | `aria-label="Mensajes drenados"` | filas de `followups_drained` | `drainFollowups` |
| `followups-drained-status` | `p.helper` | `role="status" aria-live="polite"` | ver sec. 3.4 | `drainFollowups` |
| `followups-events` | `pre.preformatted` | dentro de `<details class="inspector-section">` con `<summary>Registro de eventos (append-only)</summary>` | una linea JSON por evento | `renderFollowups` |
| `followups-engine-details` | `details.inspector-section` | `<summary>Motor de seguimiento (identidad y limites)</summary>` | `schema_version`, `provenance`, `agent_member_id`, `supervisor_member_id`, `reminder_interval_secs`, `max_reminders` | `renderFollowups` |
| `followups-engine-summary` | `p.helper` | dentro de `#followups-engine-details` | cadena `schema_version=... · provenance=... · identidad de coordinacion=... · supervision=... · intervalo=... s · maximo=... recordatorios` | `renderFollowups` |

**Prohibido**: `followups-*` como *prefijo de linea de handler pineada*. Las lineas de asignacion nuevas deben
empezar por `$('#followups-` (nunca `$('#dsh`, `$('#harness`, `$('#cordis`, `$('#prepare-cordis`), que es
exactamente el conjunto que fija `qa_v7/dsh_baseline.json:javascript_handler_lines_sha256`
(`qa_v7/test_dsh_preservation_independent.py:30-33`).

### 3.3 Marcado de fila (identico en lista e historial)

```html
<article class="record" data-followup-task="fu-1" data-followup-state="chasing">
  <strong>fu-1 · en persecucion · Ana (a-01) · recordatorios 0/3</strong>
  <p class="helper">Compromiso del mensaje m-3: "entrego el informe el viernes"</p>
  <p class="helper">Proximo recordatorio: 10/10/2026, 18:00 · Emite: Coordinacion local (no es un mensaje de un
    miembro)</p>
  <p class="helper">Dirigido a: Ana (a-01)</p>
</article>
```

Reglas de fila:

- `data-followup-task` = `id` del motor; `data-followup-state` = `chasing` / `escalated` / `reported`.
- Etiquetas de estado (texto visible, literal): `chasing` -> `en persecucion`; `escalated` -> `escalado a supervision`;
  `reported` -> `reportado y archivado`. Un `escalated` lleva ademas `class="tag amber"` con el texto `escalado`.
- `recordatorios {reminders_sent}/{max_reminders}` es el unico sitio donde se usa el denominador.
- **Autoria**: la linea `Emite:` es **siempre** `Coordinacion local (no es un mensaje de un miembro)` (sec. 6.4). La linea
  `Dirigido a:` es el unico lugar donde aparece el nombre del miembro destinatario.
- Ni avatar ni `channelLabel(owner_member_id)` en la posicion de autor.

### 3.4 Textos exactos (para que el arnes los compare)

| Id | Situacion | Literal |
|---|---|---|
| `followups-status` | reposo | `Seguimiento del equipo: tick explicito, sin temporizadores.` |
| `followups-status` | tras tick | `Tick ejecutado: {n} evento(s), {r} recordatorio(s), {k} escalacion(es).` |
| `followups-status` | sin eventos | `Tick ejecutado: 0 evento(s). Nada nuevo en el canal.` |
| `followups-status` | no disponible | el `reason` de `team_followups` (sin prefijo) |
| `followups-drained-status` | tras drenar | `Drenados {n} mensaje(s): {r} recordatorio(s) de seguimiento y {o} de otros topicos.` |
| `followups-drained-status` | drenaje vacio | `Drenados 0 mensaje(s): el buzon del miembro no tenia mensajes.` |
| `followups-error` | error 400 | el texto de `error` tal cual lo devuelve el motor |
| `followups-count` | siempre | `{active} activos · {archived} archivados` |

### 3.5 Cambios minimos en `web/app.js` (dos lineas + cuatro funciones nuevas)

1. En `render()` (`web/app.js:97-119`), junto a las demas llamadas de la linea `:117`, anadir `renderFollowups()` --
   **despues** de `renderTeamMemory();` para que el canal ya este poblado (el panel usa el roster del canal).
2. En `setBusy()` (`web/app.js:36-65`), junto a la linea `:53`, anadir:

   ```js
   const followups=state?.team_followups;
   $('#followups-tick').disabled=noDesign||!followups?.available;
   $('#followups-drain').disabled=noDesign||!followups?.available||!$('#followups-drain-member').value;
   ```

   Las variables `state` y `noDesign` ya existen en ese ambito (`:47`).
3. Funciones nuevas (fuera de las 14 pineadas): `renderFollowups()`, `updateFollowupsControls()`,
   `tickFollowups()`, `drainFollowups()`. Implementacion de referencia en **Anexo B**.
4. Estado de UI de modulo: `let followupsTick=null, followupsDrained=null;` (mismo patron que `capPlan`,
   `selectedCouncil`, `pluginCompared`).

---

## 4. CSS acotado a `#council` y accesibilidad

### 4.1 Regla de acotacion

Todo selector nuevo empieza por `#council` (precedente exacto en `web/style.css:30`: `#council .mention{...}`). No se
redefinen clases globales existentes: `.record`, `.record-list`, `.tag`, `.tag.amber`, `.helper`, `.notice.error`,
`.empty`, `.preformatted`, `.actions`, `.panel`, `.coordination-panel`, `.inspector-section`, `.sr-only`, `.metric-strip`
ya existen y se usan **tal cual** (`web/style.css:1-2`).

### 4.2 Bloque CSS nuevo (literal, 6 reglas)

```css
#council .followups-metrics{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin:16px 0}
#council .followups-metrics>div{border:1px solid var(--border);border-radius:8px;padding:12px 14px}
#council .followups-metrics strong{display:block;font-size:20px;font-weight:550;letter-spacing:-.5px}
#council .followups-metrics span{display:block;font-size:10px;color:#859382}
#council .followups-drain-row{display:flex;flex-wrap:wrap;gap:10px;align-items:flex-end;margin-top:14px}
#council .followups-drain-row select{min-width:200px}
@media(max-width:540px){#council .followups-metrics{grid-template-columns:repeat(2,minmax(0,1fr))}}
```

Se anade al final de `web/style.css` (no se reescribe ninguna linea existente; el archivo no esta pineado).

### 4.3 Accesibilidad (lo que el panel ya usa, aplicado aqui)

| Elemento | Regla | Precedente en el panel |
|---|---|---|
| `#followups-status`, `#followups-drained-status` | `role="status" aria-live="polite"` | `#resource-status`, `#cap-status`, `#cap-ai-status` (`web/index.html:114,119,120`) |
| `#followups-error` | `role="alert"` + `hidden` hasta que hay error | `#coordination-error` (`web/index.html:102`) |
| `#followups-metrics` | `aria-live="polite"` (anuncia cambio de contadores, no de la lista) | `#harness-lights` (`web/index.html:127`) |
| `#followups-drain-member` | `aria-label` (el `<select>` no lleva `<label>` visible) | `#channel-inbox-member` (`web/index.html:103`) |
| `#followups-drain-max` | `<label>` visible envolviendo el `input` | convencion `label` del panel |
| `#followups-tick` | `aria-describedby="followups-authority"` | -- (nuevo; obliga a leer la autoria) |
| `#followups-task-list`, `#followups-archive-list`, `#followups-drained` | `aria-label` descriptivo | `#channel-message-list`/`#channel-task-list` (sin rol, con `h3` previo) |
| `details > summary` | teclado nativo; `openDetailsFor` del arnes los abre por puntero | `#team-channel-panel`, `#team-memory-panel` |
| Botones | `<button type="button">` con texto visible; sin `tabindex` manual | panel completo |
| Foco | `:focus-visible` global ya definido (`web/style.css:1`) | -- |
| `aria-busy` | lo pone `setBusy` en `document.body` (`web/app.js:37`) | -- |

Prohibiciones de accesibilidad: **no** usar `aria-live="assertive"`, **no** poner `aria-live` en las listas (un tick
puede anadir N filas y saturaria al lector), **no** usar `title=` como unica etiqueta, **no** ocultar texto de estado
con `display:none` (usar `hidden` solo para el bloque de error antes de existir).

---

## 5. Guion E2E reutilizable por Chromium

### 5.1 Prerrequisitos que `t24`/`t26` deben dejar listos (fuera de `web/`)

**Reparto de propiedad, fijado por instruccion del capitan (enmienda E1 del final del documento):** `t24` toca
`engine/bridge.py`, `web/` y `tests_team_followups_panel.py`; **no** toca `tests/e2e/`. El arnes (`tests/e2e/**`,
incluido `fixture_server.py`, `build_matrix.py` y `authored-cases.json`) es de `t26`.

| # | Requisito | Archivo y dueno | Detalle |
|---|---|---|---|
| E-1 | Las dos acciones superan el guardia del fixture | `tests/e2e/fixture_server.py` (**t26**) | anadir `'followups-tick', 'followups-drain'` a `SAFE_ACTIONS`; si no, el fixture las bloquea y `blocked_actions` deja de estar vacio (`tests/e2e/fixtures.cjs:137`) |
| E-2a | **Seam de reloj en el bridge (sin superficie HTTP)** | `engine/bridge.py` (**t24**) | el motor usa `time.time` (`engine/followups.py:186`) y el intervalo por defecto es **3600 s** (`:105`), asi que con reloj real **no se puede** observar un recordatorio dentro de una prueba. `t24` construye el motor con `clock=self._followups_clock` y declara `def _followups_clock(self): return time.time()` como **metodo sobrescribible de prueba**. Reglas: **no** se anade ningun endpoint a `bridge.py`, **no** se usa ninguna variable de entorno de produccion, **no** se toca `time.time` global ni el reloj de ningun otro motor, y el metodo **no** aparece en `/api/state` (solo se declara `clock_source`, sec. 2.1). `tests_team_followups_panel.py` (t24) prueba el seam **sobrescribiendolo en una subclase de prueba** y comprobando que el tick ve el reloj inyectado |
| E-2b | Operacion de control del reloj en el fixture | `tests/e2e/fixture_server.py` (**t26**) | `FixtureState` sobrescribe `_followups_clock` devolviendo `time.time() + offset`, y `FixtureHandler.do_POST` gana una rama `path == '/__e2e__/followups-clock'` que fija `offset` desde `{"offset_secs": <int>}` (acumulativo: cada llamada suma al anterior), con el mismo patron que `mode`/`release`/`reset` (`tests/e2e/fixture_server.py:165-178`) y respondiendo `state.public()` como las demas (`:179`). `offset` arranca en 0 en cada `FixtureState` nuevo; **`POST /__e2e__/reset` ya lo reinicia** al reconstruir el estado (`:169-177`), por lo que no hace falta una operacion de reset propia del reloj |
| E-3 | Registro de casos de la matriz | `tests/e2e/build_matrix.py` (**t26**) | las listas de `:53-60` (archivo -> ids) y de `:89-99` (page, selector, accion, esperado, spec) son **literales**: hay que anadir `followups.spec.cjs` con sus ids y sus filas, y regenerar `control-matrix.json` (`python tests/e2e/build_matrix.py`, `docs/CHROMIUM_E2E.md:104`) |
| E-4 | Declaracion de autoria en la matriz | `tests/e2e/authored-cases.json` (**t26**) | anadir el caso con `expected` que mencione `Coordinacion local` y `no es un mensaje de un miembro` |

`app.navigate('council')` ya existe y funciona: `tests/e2e/fixtures.cjs:108-112` pulsa
`nav a[data-page="council"]`, `'council'` esta en `PAGES` (`:8`) y la seccion es `#council` (`web/index.html:102`).

### 5.2 Guion (paso -> selector -> texto esperado)

| # | Paso | Selector | Accion | Texto / asercion esperada |
|---|---|---|---|---|
| 1 | Ir al Council | `#council` | `await app.navigate('council')` | `#council` visible; `.page:not([hidden])` cuenta 1 (lo hace el propio helper) |
| 2 | Abrir el panel | `#followups-tick` | `await openDetailsFor(page, '#followups-tick')` | `#followups-panel` queda con `open`; `#followups-status` = `Seguimiento del equipo: tick explicito, sin temporizadores.` |
| 3 | Estado inicial con diseno sembrado | `#followups-count`, `#followups-stat-active` | -- | `#followups-count` = `0 activos · 0 archivados`; `#followups-stat-active` = `0`; `#followups-authority` contiene `Coordinacion local` y `no es un mensaje de un miembro`; `#followups-empty-tasks` visible |
| 4 | Sembrar un compromiso | `#channel-publish-form` (`#channel-sender`, `#channel-to`, `#channel-text`) | publicar, **con `#channel-sender` = el miembro que sera perseguido**, el texto `luego subo el informe` | `#notice` contiene `Mensaje publicado en el canal dirigido.` (texto heredado, `engine/bridge.py:1041`) |
| 5 | Tick explicito | `#followups-tick` | click | `#followups-status` empieza por `Tick ejecutado: 1 evento(s)`; `#followups-task-list article[data-followup-task="fu-1"]` visible con `data-followup-state="chasing"`; su texto contiene `en persecucion` y `recordatorios 0/3`; `#followups-stat-chasing` = `1`; `#followups-events` contiene `"event":"commitment"` |
| 6 | Un recordatorio vence | `#followups-tick` | `await app.control('followups-clock', { offset_secs: 3601 })` y click | el texto de la fila contiene `recordatorios 1/3`; `#followups-events` contiene `"event":"reminder"`; `#followups-stat-chasing` sigue `1` |
| 7 | Drenar los recordatorios | `#followups-drain-member`, `#followups-drain-max`, `#followups-drain` | seleccionar el **miembro perseguido**, poner `50`, click | `#followups-drained-status` = `Drenados 1 mensaje(s): 1 recordatorio(s) de seguimiento y 0 de otros topicos.`; en `#followups-drained` aparece `follow-up 1/3` y `Coordinacion local`; **no** aparece el nombre del miembro como autor |
| 8 | Agotar y escalar | `#followups-tick` | **tres** pares `{offset_secs: 3601}` + click | 1er par: `recordatorios 2/3`; 2do par: `recordatorios 3/3`; **3er par**: la fila pasa a `data-followup-state="escalated"`, texto `escalado a supervision` y `tag amber`; `#followups-stat-escalated` = `1`; `#followups-events` contiene `"event":"escalated"` |
| 9 | Cerrar y archivar | `#channel-publish-form` + `#followups-tick` | publicar **con `#channel-sender` = el miembro perseguido** el texto `ya esta entregado el informe` y tick | `#followups-archive-list article[data-followup-state="reported"]` visible; `#followups-stat-active` = `0`; `#followups-stat-reported` = `1`; `#followups-count` = `0 activos · 1 archivados`; `#followups-empty-tasks` visible |
| 10 | Error 400 visible | `#followups-drain-max` = `0` + `#followups-drain` | dentro de `app.expectActionError('/api/followups-drain', cb, /entre 1 y 100/)` | respuesta **400** con `error` que casa `/entre 1 y 100/`; `#notice` contiene ese texto; `#followups-error` visible con ese texto (`role="alert"`) |

**Nota de disparadores: los textos se eligen por las expresiones del motor, no por gusto.** El motor reconoce el
**compromiso** con `_COMMITMENT_RE` (`engine/followups.py:113-117`): una marca de
`haras|hare|hareis|pendiente(s)|cuando|luego|despues|voy a|me encargo` seguida de **una palabra**; reconocer el
**reporte** es `_REPORT_RE` (`:122-134`): `ya esta`, `entregado|entregada|entregue`, `subido|subida|subi`, `hecho`
(sin `de ` delante), `completado|completada|complete`, `finalizado`, `listo:` o una marca de artefacto
(`_ARTIFACT_RE`, `:135-141`: sha256, URL o ruta con extension). Por eso el guion usa **`luego subo el informe`**
(compromiso: `luego` + `subo`; y `subo` **no** es reporte, `:119-121`) y **`ya esta entregado el informe`** (reporte).
Ningun otro texto del guion contiene esas marcas: no se abren compromisos accidentales. El **reporte lo firma el
miembro perseguido** porque `_scan` cruza `owner_member_id == actor` (`:226-231`): un reporte de otro actor no cierra
la persecucion.

**Nota del reloj del arnes (par de llamadas exacto).** El arnes arranca cada caso con `control('reset')` y recarga
(`tests/e2e/fixtures.cjs:105-106`), lo que reconstruye el `FixtureState` (`tests/e2e/fixture_server.py:169-177`) y deja
el `offset` del reloj en **0**. A partir de ahi, cada vencimiento se provoca con **dos** llamadas en este orden:

1. `await app.control('followups-clock', { offset_secs: 3601 })` -> `POST /__e2e__/followups-clock` (fixture, solo
   pruebas) que suma 3601 s al `offset` del reloj inyectado y responde `state.public()` como las demas operaciones de
   control (`fixture_server.py:179`).
2. `await page.locator('#followups-tick').click()` -> `POST /api/followups-tick` con el estado ya avanzado.

El `offset` es **acumulativo**: tres llamadas de 3601 s producen los vencimientos 2, 3 y 4 (recordatorios `2/3`, `3/3`
y escalacion), que es exactamente la secuencia del paso 8. **No hay endpoint de reloj en `bridge.py`**: si en el futuro
alguien lo anade ahi, F-8 falla.

### 5.3 Esqueleto del spec (Anexo D lo trae completo)

```js
'use strict';
const { test, expect, openDetailsFor } = require('./fixtures.cjs');
test('seguimiento: tick, recordatorio, drenaje con autoria de coordinacion y archivo', async ({ app }) => {
  const { page } = app;
  await app.navigate('council');
  await openDetailsFor(page, '#followups-tick');
  await expect(page.locator('#followups-count')).toHaveText('0 activos · 0 archivados');
  ...
});
```

Reglas del guion: **una sola** asercion por texto esperado de sec. 5.2; nada de `waitForTimeout` (el tick es sincrono y la
respuesta 200 ya trae el estado); si se necesita esperar, `expect.poll(async () => (await app.state()).team_followups...)`
-- patron del arnes (`tests/e2e/fixtures.cjs:157`); consola limpia y `blocked_actions == []` al final (lo comprueba el
propio fixture, `:132-139`).

---

## 6. Autoria de los recordatorios (identidad de coordinacion)

### 6.1 Hecho medido, no supuesto

El motor publica **con su propia identidad** de coordinacion y **nunca** en nombre de un miembro:

- `self._channel.publish(self._agent_id, to=task['owner_member_id'], topic=FOLLOWUP_TOPIC, text='follow-up ...')` --
  recordatorio (`engine/followups.py:283-287`).
- `self._channel.publish(self._agent_id, to=self._supervisor_id, topic=FOLLOWUP_TOPIC, text='follow-up escalado ...')`
  -- escalacion (`:300-304`).
- El escaneo **descarta** los mensajes cuyo `actor` es el propio motor (`if actor == self._agent_id: continue`,
  `:222`): el motor no se persigue a si mismo.

Por tanto, en el ledger del canal (`TeamChannel.publish` fija `row['actor'] = actor.member_id`,
`engine/team_channel.py:def publish`) el autor de un recordatorio es `agent_member_id` (la identidad de coordinacion),
y `owner_member_id` es el **destinatario**. La UI no debe confundir ambos: el panel **no** usa `channelLabel(row.actor)`
para el recordatorio (esa funcion resolveria el id del motor al nombre de un miembro del roster,
`web/app.js:channelLabel`), sino la etiqueta fija de `authority.role_label`.

### 6.2 Bloque `authority` (forma congelada por este documento)

```json
"authority": {
  "kind": "coordination",
  "is_member_authored": false,
  "actor_member_id": "coordinacion-local",
  "topic": "followups",
  "provenance": "engine.followups",
  "role_label": "Coordinacion local (motor de seguimiento)",
  "identity_verified": false,
  "note": "Los recordatorios y escalaciones los emite el motor engine.followups; ningun miembro del roster es su autor."
}
```

| Campo | Tipo | Regla |
|---|---|---|
| `kind` | `"coordination"` | constante; **no** existe `kind: "member"` en esta version |
| `is_member_authored` | `false` | constante y **verificable**: es el test que impide atribuir a un miembro |
| `actor_member_id` | `string` | = `agent_member_id` del motor (identidad de coordinacion) |
| `topic` | `"followups"` | = `FOLLOWUP_TOPIC` (`engine/followups.py:91`) |
| `provenance` | `"engine.followups"` | = `PROVENANCE` (`:90`) |
| `role_label` | `string` | etiqueta que la UI pinta como autor |
| `identity_verified` | `false` | coherente con `capabilities.reviewer_identity_verified: false` (`engine/bridge.py:893`): un proceso local no acredita identidad |
| `note` | `string` | frase de responsabilidad que la UI muestra junto al bloque |

### 6.3 Reglas de atribucion (las que el test fija)

1. Un recordatorio (`topic == "followups"`) **siempre** se pinta con `authority.role_label` como autor.
2. El miembro destinatario se pinta **solo** en la linea `Dirigido a:`; nunca en la posicion de autor, ni con avatar,
   ni con `channelLabel()`, ni con `owner_member_id` en el sitio del autor.
3. En `#followups-events` los eventos `reminder`/`escalated` no muestran "autor": muestran `owner_member_id` como
   destinatario y la etiqueta de coordinacion como emisor.
4. El bloque `#followups-authority` es **visible sin abrir ningun desplegable**: la declaracion de autoria no se
   esconde tras un `<details>`.
5. Cualquier mensaje de otro topico que aparezca en `followups_drained.other[]` se pinta con su autor real
   (`channelLabel(actor)`) y **sin** `authority`, para no mezclar procedencias.
6. Prohibido el texto "recordatorio de <nombre de miembro>" o cualquier formula que sugiera que el miembro escribio el
   recordatorio.

### 6.4 Texto literal del bloque visible

```
#followups-authority =
Recordatorios y escalaciones los emite la coordinacion local (motor engine.followups) con la identidad
"<agent_member_id>". Ningun miembro del roster es su autor; identity_verified=false.
```

---

## 7. Prerrequisitos de implementacion para `t24` (mecanica, sin decisiones abiertas)

| # | Pieza | Donde | Estado |
|---|---|---|---|
| P-1 | `FollowupsEngine` | `engine/followups.py` (367 lineas) | **YA EXISTE.** API congelada: `__init__(channel, agent, supervisor, *, clock=None, reminder_interval=..., max_reminders=...)`, `tick()`, `tasks()`, `archive()`, `find()`, `stats()`, `events_log()`, `ledger_view()` (`:166-367`) |
| P-2 | `team_followups_public()` | `engine/bridge.py` (junto a `team_channel_public`, `:964`) | Crear: compone `ledger_view()` + sec. 2.1; **nunca lanza** (sec. 2.3) |
| P-3 | Accion `followups-tick` | `engine/bridge.py:execute` (rama nueva) | Crear `if action in FOLLOWUPS_ACTIONS:` (rama **nueva**, R-3) con validacion de sec. 1.2 y recibo |
| P-4 | Accion `followups-drain` | idem | Idem con sec. 1.3; delega en `TeamChannel.inbox` y clasifica por `topic` |
| P-5 | Clave en `/api/state` | `engine/bridge.py:874-894` | Anadir `'team_followups': self.team_followups_public()` a la expresion de `public()` |
| P-6 | HTML | `web/index.html` (dentro de `#council`, antes de su `</section>`) | Copiar **Anexo A** |
| P-7 | CSS | `web/style.css` (final) | Copiar **Anexo C** |
| P-8 | JS | `web/app.js` | `render()` +`renderFollowups()`; `setBusy()` +2 lineas; 4 funciones nuevas (**Anexo B**) |
| P-9 | Seam de reloj (solo prueba, sin HTTP) | `engine/bridge.py` | `def _followups_clock(self): return time.time()` **sobrescribible**, y el motor se construye con `clock=self._followups_clock` (E-2a). **No** se anade ningun endpoint ni variable de entorno a `bridge.py` |
| P-10 | Prueba del flujo del panel | `tests_team_followups_panel.py` (nuevo, raiz de la suite) | Casos: las dos acciones (200/400/403 sin sesion, version obsoleta, member/max_count invalidos), los 15 campos de `team_followups` y `authority` congelado, `available:false` sin diseno sin lanzar, el tick con reloj inyectado por subclase de prueba (E-2a), y los 25 ids presentes en `web/index.html` con las 6 reglas CSS acotadas |
| P-11 | Fixture, spec y matriz E2E | `tests/e2e/**` | **NO es de `t24`**: `t26` lo hace (E-1, E-2b, E-3, E-4). `t24` solo entrega el seam de P-9 y el guion de sec. 5.2/Anexo D como insumo |

**Reparto fijado por el capitan (enmienda E1).** `t24` = `engine/bridge.py` + `web/` + `tests_team_followups_panel.py`.
`tests/e2e/**` = `t26`. Ninguna tarea anade a `bridge.py` una superficie de control de tiempo: el reloj del arnes vive
solo en el fixture de pruebas.

**Lo que `t24` NO debe tocar:** las 14 funciones pineadas de `web/app.js`, las tres ramas de despacho pineadas de
`engine/bridge.py`, `request()`, `engine/followups.py` (salvo la alternativa declarada de sec. 1.3, que exige autorizacion),
`engine/team_channel.py`, `tests/e2e/**`, `MANIFIESTO_SHA256.txt` y el sello.

---

## 8. Limites de este documento y falsificadores

**Limites declarados**

1. Este documento **no aplica codigo**: describe contrato, forma, ids, CSS, accesibilidad y guion.
2. **Chromium NOT_RUN** en esta entrega (`docs/CHROMIUM_E2E.md:3`): el guion de sec. 5 esta **autorizado, no ejecutado**.
   Ninguna asercion de este documento implica que el navegador se haya lanzado.
3. El estado de seguimiento vive **en memoria de la sesion del motor** (como el canal, `engine/team_channel.py` y
   `engine/bridge.py:928-930`): se reinicia con cada rediseno. El panel lo dice (`in_memory_session_only`,
   `reset_policy`) y no promete persistencia.
4. `reminder_interval_secs` **no** es editable desde la UI: se muestra. Cambiarlo es una decision del motor.
5. La matriz E2E pasa de 92 a 92+N casos declarados; ese numero **no** es una medida de calidad y hay que regenerar
   `control-matrix.json` (E-3).

**Falsificadores (cada uno debe fallar si la implementacion se desvia)**

| # | Falsificador | Como se detecta |
|---|---|---|
| F-1 | Un id nuevo no empieza por `followups-` | `qa_v7/test_dsh_preservation_independent.py:30-33` (digest de lineas de handler) o lint de prefijos en `tests_v8_ui_contract.py` (patron de ids) |
| F-2 | `team_followups` lanza sin diseno | `GET /api/state` con el bridge sin organizacion devuelve **no** 500 y `team_followups.available === false` con `reason` no vacio |
| F-3 | Un recordatorio se atribuye a un miembro | asercion E2E de sec. 5.2 paso 7 sobre `#followups-drained` + prueba unitaria `authority.is_member_authored === false` e `is not` el nombre del miembro |
| F-4 | El drenaje se come mensajes de otros topicos sin declararlo | prueba con un mensaje `topic != followups` en el buzon: aparece en `followups_drained.other[]` y `counts.other == 1` |
| F-5 | Hay un temporizador | busqueda de `setInterval|setTimeout` en `renderFollowups`/`tickFollowups`/`drainFollowups` y de nuevas claves `followups_*` en el estado: 0 resultados |
| F-6 | Se edito una funcion pineada | `qa_v7/test_dsh_preservation_independent.py` (4 pruebas) en verde |
| F-7 | El error 400 no llega a la UI | asercion de sec. 5.2 paso 10: 400 + `body.error` + `#notice` + `#followups-error` |
| F-8 | El bridge de produccion gana control de tiempo | `grep '/__e2e__'` en `engine/**`: 0 resultados; `bridge.py` no lee `ORGDNA_E2E` ni ninguna variable de tiempo; `GET /api/state` no expone reloj escribible (`clock_source` es solo lectura) |
| F-9 | El tick no ve el reloj inyectado | en la prueba de `tests_team_followups_panel.py` con el seam sobrescrito: un `tick()` con `now` avanzado 3601 s produce `"event":"reminder"`; con el reloj del sistema, 0 recordatorios |
| F-10 | La UI presenta como real un tiempo simulado | con `clock_source === 'injected'` el bloque del motor dice `reloj inyectado por el arnes`; nunca "hora real" |

---

## Anexo A -- HTML literal a insertar en `web/index.html` (dentro de `#council`)

```html
<details class="panel coordination-panel" id="followups-panel">
  <summary>Seguimiento (C4): recordatorios y escalaciones del canal <span id="followups-count" class="tag">0 activos · 0 archivados</span></summary>
  <p class="helper">Persecucion explicita de compromisos detectados en el canal (motor <code>engine.followups</code>).
    Un <strong>tick</strong> escanea mensajes nuevos y persigue los vencidos; no hay temporizadores, no se ejecutan
    agentes y no se llama a ningun proveedor. Registro en memoria de esta sesion del motor: se reinicia con cada
    rediseno.</p>
  <p id="followups-authority" class="helper">Recordatorios y escalaciones los emite la coordinacion local (motor
    engine.followups). Ningun miembro del roster es su autor.</p>
  <p id="followups-status" class="helper" role="status" aria-live="polite">Seguimiento del equipo: tick explicito, sin temporizadores.</p>
  <div id="followups-error" class="notice error" role="alert" hidden></div>
  <div id="followups-metrics" class="followups-metrics" aria-live="polite" aria-label="Contadores de seguimiento">
    <div><strong id="followups-stat-active">0</strong><span>Activos</span></div>
    <div><strong id="followups-stat-chasing">0</strong><span>En persecucion</span></div>
    <div><strong id="followups-stat-escalated">0</strong><span>Escalados</span></div>
    <div><strong id="followups-stat-reported">0</strong><span>Reportados</span></div>
  </div>
  <div class="actions">
    <button id="followups-tick" class="secondary" type="button" aria-describedby="followups-authority">Ejecutar tick explicito</button>
  </div>
  <div class="followups-drain-row">
    <label>Miembro cuyo inbox se drena<select id="followups-drain-member" aria-label="Miembro cuyo inbox de seguimiento se drena"></select></label>
    <label>Maximo de mensajes<input id="followups-drain-max" type="number" min="1" max="100" value="20"></label>
    <button id="followups-drain" class="textbutton" type="button">Drenar recordatorios del miembro</button>
  </div>
  <p id="followups-drained-status" class="helper" role="status" aria-live="polite"></p>
  <div id="followups-drained" class="record-list" aria-label="Mensajes drenados"></div>
  <h3>Compromisos en seguimiento</h3>
  <div id="followups-task-list" class="record-list" aria-label="Compromisos en seguimiento"></div>
  <p id="followups-empty-tasks" class="empty" hidden>Sin compromisos en seguimiento: ninguna mencion con promesa detectada en el canal.</p>
  <h3>Historial de seguimientos cerrados</h3>
  <div id="followups-archive-list" class="record-list" aria-label="Historial de seguimientos cerrados"></div>
  <p id="followups-empty-archive" class="empty" hidden>Sin seguimientos archivados: un reporte cierra y archiva el compromiso.</p>
  <details class="inspector-section">
    <summary>Registro de eventos (append-only)</summary>
    <pre id="followups-events" class="preformatted"></pre>
  </details>
  <details class="inspector-section" id="followups-engine-details">
    <summary>Motor de seguimiento (identidad y limites)</summary>
    <p class="helper" id="followups-engine-summary"></p>
  </details>
</details>
```

## Anexo B -- Implementacion de referencia de `web/app.js` (nueva; no aplicada)

```js
let followupsTick=null,followupsDrained=null;
function followupsState(){return state.team_followups||{available:false,reason:'Genera un diseno para abrir el seguimiento del equipo.'};}
function followupsLabel(id){const members=channelMembers();const m=members.find(x=>x.member_id===id);return m?m.name+' ('+m.member_id+')':String(id||'');}
function followupsRow(task,max,archived){
  const row=node('article',undefined,'record');
  row.dataset.followupTask=task.id;row.dataset.followupState=task.state;
  const stateLabel={chasing:'en persecucion',escalated:'escalado a supervision',reported:'reportado y archivado'}[task.state]||task.state;
  const head=node('strong',task.id+' · '+stateLabel+' · '+followupsLabel(task.owner_member_id)+
    (archived?'':' · recordatorios '+String(task.reminders_sent||0)+'/'+String(max)));
  row.append(head,node('p','Compromiso del mensaje '+task.message_id+': "'+String(task.snippet||'')+'"','helper'));
  if(!archived&&task.next_reminder_at)row.append(node('p','Proximo recordatorio: '+localDate(new Date(task.next_reminder_at*1000).toISOString()),'helper'));
  if(task.state==='escalated')row.append(node('span','escalado','tag amber'));
  // Autoria: SIEMPRE la identidad de coordinacion, nunca el miembro destinatario.
  row.append(node('p','Emite: '+(followupsState().authority?.role_label||'Coordinacion local (motor de seguimiento)')+
    ' (no es un mensaje de un miembro)','helper'));
  row.append(node('p','Dirigido a: '+followupsLabel(task.owner_member_id),'helper'));
  return row;
}
function renderFollowups(){
  if(!$('#followups-panel'))return;
  const data=followupsState(),stats=data.stats||{active:0,archived:0,chasing:0,escalated:0,reported:0};
  // Mismos valores que el resto del canal: member_id del roster del canal (no del ADN).
  const select=$('#followups-drain-member'),previous=select.value;select.replaceChildren();
  channelMembers().forEach(m=>select.append(option(m.member_id,m.name+(m.role?' · '+m.role:''))));
  if(channelMembers().some(m=>m.member_id===previous))select.value=previous;
  $('#followups-count').textContent=String(stats.active||0)+' activos · '+String(stats.archived||0)+' archivados';
  $('#followups-stat-active').textContent=String(stats.active||0);
  $('#followups-stat-chasing').textContent=String(stats.chasing||0);
  $('#followups-stat-escalated').textContent=String(stats.escalated||0);
  $('#followups-stat-reported').textContent=String(stats.reported||0);
  const tasks=$('#followups-task-list'),archive=$('#followups-archive-list');
  tasks.replaceChildren();archive.replaceChildren();
  if(!data.available){
    $('#followups-status').textContent=data.reason||'Genera un diseno para abrir el seguimiento del equipo.';
    $('#followups-empty-tasks').hidden=false;$('#followups-empty-archive').hidden=false;
    $('#followups-events').textContent='';return;
  }
  $('#followups-status').textContent=followupsTick
    ? 'Tick ejecutado: '+followupsTick.events+' evento(s), '+followupsTick.reminders+' recordatorio(s), '+followupsTick.escalations+' escalacion(es).'
    : 'Seguimiento del equipo: tick explicito, sin temporizadores.';
  (data.tasks||[]).forEach(task=>tasks.append(followupsRow(task,data.max_reminders,false)));
  (data.archive||[]).forEach(task=>archive.append(followupsRow(task,data.max_reminders,true)));
  $('#followups-empty-tasks').hidden=Boolean((data.tasks||[]).length);
  $('#followups-empty-archive').hidden=Boolean((data.archive||[]).length);
  $('#followups-events').textContent=(data.events||[]).map(row=>JSON.stringify(row)).join('\n');
  $('#followups-engine-summary').textContent='schema_version='+data.schema_version+' · provenance='+data.provenance+
    ' · identidad de coordinacion='+data.agent_member_id+' · supervision='+data.supervisor_member_id+
    ' · intervalo='+String(data.reminder_interval_secs)+' s · maximo='+String(data.max_reminders)+' recordatorios';
  updateFollowupsControls();
}
function updateFollowupsControls(){
  const available=Boolean(state&&state.team_followups&&state.team_followups.available);
  if($('#followups-drain'))$('#followups-drain').disabled=!available||!$('#followups-drain-member').value;
}
async function tickFollowups(){
  const version=(state.organization||{}).state_version||1;
  return run('Ejecutando un tick explicito de seguimiento...',async()=>{
    const payload=await request('followups-tick',{expected_state_version:version});
    followupsTick=payload.followups_tick||null;
    $('#followups-error').hidden=true;
  },'Tick de seguimiento ejecutado.');
}
async function drainFollowups(){
  const version=(state.organization||{}).state_version||1;
  const member=$('#followups-drain-member').value,max=Number($('#followups-drain-max').value);
  return run('Drenando el inbox de seguimiento...',async()=>{
    const payload=await request('followups-drain',{expected_state_version:version,member:member,max_count:max});
    followupsDrained=payload.followups_drained||null;
    const box=$('#followups-drained');box.replaceChildren();
    const counts=(followupsDrained&&followupsDrained.counts)||{delivered:0,reminders:0,other:0};
    $('#followups-drained-status').textContent='Drenados '+counts.delivered+' mensaje(s): '+counts.reminders+
      ' recordatorio(s) de seguimiento y '+counts.other+' de otros topicos.';
    (followupsDrained?.reminders||[]).forEach(row=>{const article=node('article',undefined,'record');
      article.append(node('strong','Recordatorio · dirigido a '+followupsLabel(row.to)),
        node('p',row.text,'helper'),
        node('p','Emite: '+row.authority.role_label+' (no es un mensaje de un miembro)','helper'));
      box.append(article);});
    (followupsDrained?.other||[]).forEach(row=>{const article=node('article',undefined,'record');
      article.append(node('strong','Mensaje de otro topico · '+String(row.topic||'')+ ' · autor '+channelLabel(row.actor)),
        node('p',row.text,'helper'));box.append(article);});
    if(!counts.delivered)box.append(node('p','Drenados 0 mensaje(s): el buzon del miembro no tenia mensajes.','empty'));
    $('#followups-error').hidden=true;
  },'Inbox de seguimiento drenado (lectura destructiva).');
}
```

Requisitos de estilo del bloque: `run()`, `request()`, `node()`, `localDate()`, `populateAgentSelect()`,
`channelMembers()` y `channelLabel()` ya existen y **no se modifican**; el error 400 lo pinta `run()` por el canal
heredado (`#notice`) y ademas se copia a `#followups-error` (anadir en el `catch` de `run` un gancho
`#followups-error` **no** es aceptable: se hace en estas dos funciones con un `try/catch` propio si `run` no expone el
error -- decision de `t24` **limitada a estas dos funciones nuevas**, nunca a `run` ni a `request`).

## Anexo C -- CSS literal (ver sec. 4.2)

```css
/* Seguimiento (C4) -- todo acotado a #council */
#council .followups-metrics{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin:16px 0}
#council .followups-metrics>div{border:1px solid var(--border);border-radius:8px;padding:12px 14px}
#council .followups-metrics strong{display:block;font-size:20px;font-weight:550;letter-spacing:-.5px}
#council .followups-metrics span{display:block;font-size:10px;color:#859382}
#council .followups-drain-row{display:flex;flex-wrap:wrap;gap:10px;align-items:flex-end;margin-top:14px}
#council .followups-drain-row select{min-width:200px}
@media(max-width:540px){#council .followups-metrics{grid-template-columns:repeat(2,minmax(0,1fr))}}
```

## Anexo D -- Esqueleto de `tests/e2e/followups.spec.cjs`

```js
'use strict';
const { test, expect, openDetailsFor } = require('./fixtures.cjs');

test('seguimiento: tick, recordatorio, drenaje con autoria de coordinacion y archivo', async ({ app }) => {
  const { page } = app;
  await app.navigate('council');
  await openDetailsFor(page, '#followups-tick');
  await expect(page.locator('#followups-count')).toHaveText('0 activos · 0 archivados');
  await expect(page.locator('#followups-authority')).toContainText('Coordinacion local');
  await expect(page.locator('#followups-authority')).toContainText('no es un mensaje de un miembro');

  // 1) sembrar un compromiso por el canal existente (texto que dispara _COMMITMENT_RE)
  const current = await app.state();
  const owner = current.team_channel.members.at(-1);
  await page.locator('#channel-sender').selectOption(owner.member_id);
  await page.locator('#channel-to').selectOption(owner.member_id);
  await page.locator('#channel-text').fill('luego subo el informe');
  await page.locator('#channel-publish-form button[type="submit"]').click();
  await expect(page.locator('#notice')).toContainText('Mensaje publicado en el canal dirigido.');

  // 2) tick explicito -> compromiso en persecucion
  await page.locator('#followups-tick').click();
  const row = page.locator('#followups-task-list article[data-followup-task]').first();
  await expect(row).toHaveAttribute('data-followup-state', 'chasing');
  await expect(row).toContainText('en persecucion');
  await expect(row).toContainText('recordatorios 0/3');
  await expect(page.locator('#followups-stat-chasing')).toHaveText('1');
  await expect(page.locator('#followups-events')).toContainText('"event":"commitment"');

  // 3) reloj del fixture + tick -> recordatorio 1/3
  await app.control('followups-clock', { offset_secs: 3601 });
  await page.locator('#followups-tick').click();
  await expect(row).toContainText('recordatorios 1/3');
  await expect(page.locator('#followups-events')).toContainText('"event":"reminder"');

  // 4) drenaje: el autor es la coordinacion, nunca el miembro
  await page.locator('#followups-drain-member').selectOption(owner.member_id);
  await page.locator('#followups-drain-max').fill('50');
  await page.locator('#followups-drain').click();
  await expect(page.locator('#followups-drained-status')).toContainText('1 recordatorio(s)');
  const drained = page.locator('#followups-drained article').first();
  await expect(drained).toContainText('follow-up 1/3');
  await expect(drained).toContainText('Emite: Coordinacion local');
  await expect(drained).not.toContainText('autor ' + owner.name);

  // 5) agotar recordatorios 2/3 y 3/3, y escalar en el cuarto vencimiento
  for (const expected of ['recordatorios 2/3', 'recordatorios 3/3']) {
    await app.control('followups-clock', { offset_secs: 3601 });
    await page.locator('#followups-tick').click();
    await expect(row).toContainText(expected);
  }
  await app.control('followups-clock', { offset_secs: 3601 });
  await page.locator('#followups-tick').click();
  await expect(row).toHaveAttribute('data-followup-state', 'escalated');
  await expect(row).toContainText('escalado a supervision');
  await expect(page.locator('#followups-stat-escalated')).toHaveText('1');
  await expect(page.locator('#followups-events')).toContainText('"event":"escalated"');

  // 6) reporte del miembro perseguido (texto que dispara _REPORT_RE) -> archivo
  await page.locator('#channel-sender').selectOption(owner.member_id);
  await page.locator('#channel-to').selectOption(owner.member_id);
  await page.locator('#channel-text').fill('ya esta entregado el informe');
  await page.locator('#channel-publish-form button[type="submit"]').click();
  await page.locator('#followups-tick').click();
  await expect(page.locator('#followups-archive-list article[data-followup-state="reported"]')).toBeVisible();
  await expect(page.locator('#followups-stat-active')).toHaveText('0');
  await expect(page.locator('#followups-stat-reported')).toHaveText('1');
  await expect(page.locator('#followups-count')).toHaveText('0 activos · 1 archivados');

  // 7) error 400 visible en el panel
  await page.locator('#followups-drain-max').fill('0');
  await app.expectActionError('/api/followups-drain', async () => {
    await page.locator('#followups-drain').click();
  }, /entre 1 y 100/);
  await expect(page.locator('#followups-error')).toBeVisible();
});
```

## Anexo E -- Ejemplos de respuesta de los dos estados degradados

```json
"team_followups": {
  "available": false,
  "reason": "Genera un diseno para abrir el seguimiento del equipo.",
  "authority": { "kind": "coordination", "is_member_authored": false, "actor_member_id": null,
                 "topic": "followups", "provenance": "engine.followups",
                 "role_label": "Coordinacion local (motor de seguimiento)",
                 "identity_verified": false,
                 "note": "Los recordatorios y escalaciones los emite el motor engine.followups; ningun miembro del roster es su autor." }
}
```

```json
"team_followups": {
  "available": false,
  "reason": "Roster invalido para el seguimiento: unknown_member: 'a-09' no esta en el roster (target outside roster).",
  "authority": { "...": "igual, con actor_member_id: null" }
}
```

---

## Registro de verificacion de ESTE documento (cierre de `t33`)

**Cambio aplicado:** un unico archivo nuevo, `docs/rea/PANEL_SEGUIMIENTO_SPEC.md`. `engine/`, `web/`,
`MANIFIESTO_SHA256.txt` y el sello **no** se tocaron; no se ejecuto `resella_paquete.py` ni la suite completa.

| Comprobacion | Comando / criterio | Resultado |
|---|---|---|
| El documento no altera el paquete | `docs/rea/PANEL_SEGUIMIENTO_SPEC.md` **no** figura en `bundle.RUNTIME_ALLOWLIST` (literal, `engine/bundle.py:238` cierra la tupla) ni en `MANIFIESTO_SHA256.txt` (360 entradas comprobadas) | **no figura en ninguno** -> `_expected_package_paths` no cambia y no hay que resellar |
| Pines intactos | `python -m unittest discover -s EQUIPO_ENTERPRISE_24_COUNCIL_ADN -t EQUIPO_ENTERPRISE_24_COUNCIL_ADN -p 'test_dsh_preservation_independent.py'` | `Ran 4 tests -- OK` |
| Fallos NO atribuibles a este documento | `... -p 'tests_platform_integration.py'` | `Ran 34 tests -- 2 fallos AJENOS`: (1) `engine/team_process.py` existe en el arbol y aun no esta en la allowlist (trabajo de `t24` en curso); (2) `docs/security/FUSILE_SOURCE_POLICY.md` fue modificado **despues** de regenerarse el manifiesto (21:29 vs 21:08). Ninguno menciona este archivo |
| Codificacion del documento | solo el separador `·` es no ASCII (25 veces); el resto es ASCII sin acentos | apto para cualquier lector, incluido cp1252 |

**Lo que este registro NO afirma:** que el panel exista (no se implemento), que Chromium se haya ejecutado (sigue
`NOT_RUN`, `docs/CHROMIUM_E2E.md:3`) ni que la matriz E2E este regenerada (lo hace `t26`/`t24` con
`python tests/e2e/build_matrix.py`).

---

## Enmienda E1 -- el reloj del arnes NO va en `bridge.py` (correccion del capitan, aplicada)

**Origen.** Dos mensajes vinculantes del capitan. El primero pedia un endpoint de reloj en `bridge.py` protegido por
`ORGDNA_E2E=1`; **el segundo lo corrige** y es el que manda: *"hice mal la asignacion del reloj controlable. No va en
`bridge.py`. Va en el fixture de pruebas. [...] NO se anade ningun endpoint nuevo a `bridge.py`: el bridge de
produccion no debe ganar una superficie de control de tiempo que hoy no tiene. Retiro mi instruccion anterior en ese
punto; el `ORGDNA_E2E=1` deja de hacer falta en produccion."*

**Contrato vigente (sustituye a cualquier lectura del primer mensaje).**

| Aspecto | Decision vigente |
|---|---|
| Donde vive la operacion de control | `tests/e2e/fixture_server.py` (**t26**), junto a `mode`/`release`/`reset` (`:165-178`) |
| Forma de la operacion | `POST /__e2e__/followups-clock` con `{"offset_secs": <int>}` **acumulativo**; responde `state.public()` como las demas (`:179`) |
| Reset | **No** se crea `followups-reset`: `POST /__e2e__/reset` ya reconstruye el `FixtureState` y deja el `offset` en 0 (`:169-177`) |
| Inyeccion | `FixtureState` sobrescribe el seam `BridgeState._followups_clock()` (declarado por **t24** en `bridge.py`, E-2a) |
| `bridge.py` | **Cero** endpoints `/__e2e__`, **cero** variables de entorno de produccion, **cero** control de tiempo en `/api/state`; solo el seam sobrescribible y el campo de solo lectura `clock_source` |
| `ORGDNA_E2E` | **Retirado.** No hace falta en produccion ni en el arnes |
| Propiedad | `t24` = `engine/bridge.py` + `web/` + `tests_team_followups_panel.py`; `t26` = `tests/e2e/**` (fixture, spec, `build_matrix.py`, `authored-cases.json`) |

**Cambios aplicados a este documento por la enmienda.** (a) sec. 2.1/2.2/2.4: campos **opcionales aditivos**
`clock_source` (`system`|`injected`, por introspeccion del seam) y `loop` (`available:false` mientras
`engine/team_loop.py` no exista y otra tarea no lo cablee); los 15 campos obligatorios **no cambian**. (b) sec. 5.1:
E-1/E-2a/E-2b/E-3/E-4 reescritos con dueno explicito y sin endpoint en el bridge. (c) sec. 5.2: nota del **par de
llamadas exacto** (control del reloj + click de tick) y caracter acumulativo del `offset`. (d) sec. 7: P-9 (seam),
P-10 (`tests_team_followups_panel.py`), P-11 (fixture/spec/matriz = t26) y reparto de propiedad. (e) sec. 8:
falsificadores F-8 (el bridge no gana control de tiempo), F-9 (el tick ve el reloj inyectado) y F-10 (la UI no presenta
como real un tiempo simulado).

**Estado del arbol al aplicar la enmienda (verificado, no supuesto).** `engine/team_loop.py` **no existe** todavia
(solo `engine/team_process.py`, 47 401 B): por eso `loop.available` queda en `false` y `state` en `null`, y `t24` **no**
cablea el bucle. `tests/e2e/fixture_server.py` sigue con las tres operaciones de control originales. Chromium sigue
`NOT_RUN`: la enmienda no ejecuta nada, solo fija el contrato.

