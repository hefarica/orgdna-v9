# PLATAFORMA_APROBACION_V1 — ApprovalReceipt v1: consentimiento declarativo enlazado al hash del TaskGraph

**Reparación aditiva de auditabilidad:** `O1-APPROVAL-RECEIPT-LINK-01` (tarea `t13`, miembro `nucleo`).
**Naturaleza:** contrato, semántica y pruebas. **No es** cableado de persistencia, **no** ejecuta nada,
**no** autentica a nadie y **no** modifica ningún artefacto vigente.
**Convención de rutas:** relativas a `EQUIPO_ENTERPRISE_24_COUNCIL_ADN/`, raíz de la suite.
**Convención de citas:** `archivo:línea` sobre el código de esta entrega o sobre los contratos congelados.

---

## 1. INVARIANTE DE APROBACIÓN (bloque canónico del operador, publicado verbatim por el capitán)

**Atribución corregida.** La versión anterior de este epígrafe titulaba «(bloque literal del operador)» un
texto que en realidad procedía de la descripción de `t13` (escrita por el capitán) y no de una publicación
del operador: el capitán no había publicado su bloque en ningún artefacto accesible al equipo. El bloque
canónico se publicó después en `OBSERVACIONES_CAPITAN_PLATAFORMA.md`, sección **O-10**, que pasa a ser la
fuente de autoridad para esta alineación. El bloque siguiente es **el bloque del operador, reproducido
verbatim** (mismos saltos de línea, misma puntuación). La transcripción anterior se conserva íntegra en la
sección 1.1 por trazabilidad y por ser la que consumen las pruebas de documentación ya existentes.

```text
INVARIANTE DE APROBACIÓN

compute_graph_sha256 identifica el contenido canónico de un TaskGraph.
No acredita aprobación, identidad humana, autorización de herramientas,
presupuesto, consentimiento vigente ni permiso de ejecución.

Una aprobación solo es válida si existe un ApprovalReceipt vigente cuyo
graph_sha256, policy_hash, scope y nivel de autonomía coinciden con el
TaskGraph y la tarea que se pretende ejecutar.

En modo local/offline, approver.role es declarativo y
approver.authenticated=false. La plataforma no debe presentar esa
declaración como una identidad autenticada.
```

### 1.1 Transcripción previa desde la descripción de `t13` (conservada; no es el bloque del operador)

Bloque reproducido **literalmente** desde la autorización `O1-APPROVAL-RECEIPT-LINK-01`, tal como fue
transmitida en la descripción de `t13`. No es el bloque canónico del operador —ese está en el epígrafe 1—
y se conserva sin cambios porque las pruebas de documentación de `tests_platform_approval_receipt.py`
verifican estos fragmentos.

```text
REGLA DE ORO: TaskGraphHash != ProofOfApproval, pero ApprovalReceipt.graph_sha256 == compute_graph_sha256(TaskGraph).
El hash sigue identificando SÓLO el contenido determinista; el recibo prueba que un rol declarativo aprobó ese contenido exacto, en un momento dado, bajo una política y un alcance concretos.

SEMÁNTICA DE LAS CINCO PREGUNTAS que el sistema debe diferenciar:
(1) ¿el grafo es íntegro? sólo si compute_graph_sha256 coincide;
(2) ¿fue aprobado? sólo si existe ApprovalReceipt con graph_sha256 coincidente;
(3) ¿sigue vigente? sólo si no está expirado ni revocado;
(4) ¿el alcance de la tarea cabe en la aprobación? sólo si task_id, autonomía, herramientas y presupuesto están cubiertos;
(5) ¿quién aprobó? en local/offline únicamente un rol declarativo — NO se afirma identidad autenticada.

FLUJO: construir el TaskGraph determinista -> compute_graph_sha256 -> mostrar al operador hash, tareas, autonomía máxima, herramientas, conectores, presupuesto y expiración -> denegar emite ApprovalReceipt(decision='denied'); aprobar emite recibo inmutable -> antes de ejecutar cada tarea recalcular el hash, localizar el recibo vigente y comprobar scope, autonomía, presupuesto y policy_hash: si falla una condición se bloquea la ejecución, y si todo coincide se permite SÓLO la acción aprobada.

PERSISTENCIA (semántica en esta tarea, sin cableado físico): el recibo debe poder sobrevivir dentro de proyecto guardado, bundle exportado, diagnóstico descargado, resultado de generación y artefacto de aprobación; el modelo mínimo previsto es project/task_graph.json, project/approval_receipts.jsonl, project/generation_diagnostics.json y project/artifacts/, con DOS REGLAS: la persistencia local es opcional y explícita, y la AUSENCIA de archivo de recibo NO se interpreta como aprobación. NO abras ninguna base de datos nueva en data/.

BLINDAJE: el primer allOf del contrato de política rechaza campos con forma de credencial; reutiliza esa lógica en lectura, sin modificar policy_engine.py.

NO MODIFICA: compute_graph_sha256(), TaskGraph serializado, MANIFIESTO_SHA256.txt, permisos efectivos, defaults de autonomía, política de persistencia efímera, ni identidad/autenticación de usuario.
SI AÑADE: schema, emisión, enlace, verificador, pruebas positivas y negativas, documentación.
Restricciones: sólo biblioteca estándar; sin red, sin claves, sin proveedores, sin dependencias nuevas, sin tocar DSH, sin escribir fuera de inScope.
```

Y la regla que gobierna toda lectura de este documento:

> **TaskGraphHash != ProofOfApproval.** Un hash válido prueba que el contenido determinista es el
> mismo; **no** prueba que alguien lo haya aprobado, ni quién, ni cuándo, ni bajo qué política. Solo un
> `ApprovalReceipt` cuyo `graph_sha256` coincida con `compute_graph_sha256(TaskGraph)` aporta esa
> evidencia, y en local/offline esa evidencia es **declarativa**: un rol, no una identidad autenticada.

---

## 2. Las cinco preguntas, respondidas por separado

`answer_security_questions(graph, task, receipt, ...)` devuelve las cinco respuestas por separado, de
modo que ninguna se confunda con otra. Ninguna respuesta se aproxima: si no se puede afirmar, es `False`.

| # | Pregunta | Respuesta del sistema | Clave del veredicto |
| --- | --- | --- | --- |
| 1 | ¿el grafo es íntegro? | `compute_graph_sha256(graph.tasks)` coincide con el enlace del recibo (y, sin recibo, el `TaskGraph` se autoverificó al construirse) | `graph_intact` |
| 2 | ¿fue aprobado? | existe un `ApprovalReceipt` con `graph_sha256` coincidente **y** `decision == "approved"` | `approved` |
| 3 | ¿sigue vigente? | `decision` activa, sin revocación efectiva y `now <= expires_at` | `active` |
| 4 | ¿el alcance de la tarea cabe? | `task_id`, autonomía, alcances de escritura, conectores, peticiones, tokens y coste dentro de `approval_scope` | `scope_covers` |
| 5 | ¿quién aprobó? | **solo** un rol declarativo: `approver.mode == "declarative_role"`, `approver.authenticated is False`, `identity_verified is False` | `approver` |

La pregunta 5 se responde con lo que el sistema puede sostener: `approver.role` es una declaración y
`APPROVER_AUTHENTICATION` reutiliza el vocabulario del Policy Engine (`not_verified`). No hay firma, ni
clave, ni certificado, ni atestación: cualquier recibo que los declare se rechaza.

---

## 3. Regla de oro y enlace exigido

```text
ApprovalReceipt.graph_sha256 == compute_graph_sha256(TaskGraph)
```

- El hash se **recalcula**; no se copia de un campo de conveniencia: `graph_hash_of(graph)` llama a
  `task_graph.compute_graph_sha256(graph.tasks)` (`engine/approval_receipt.py`).
- `graph_schema_of(graph)` deriva el esquema del propio contrato de I1: `orgdna-task-graph-v1`
  (prefijo `orgdna-task-graph-v` + `graph_version`). Un `graph_schema` distinto se rechaza
  (`GraphSchemaMismatchError`).
- `issue_receipt(...)` **se niega a construir** el recibo si el `graph_sha256` o el `graph_schema`
  declarados no coinciden con el grafo aprobado.
- El hash de contenido **no** cambia: no se añade ningún campo al `TaskSpec` ni al `TaskGraph`, y
  `compute_graph_sha256()` no se modifica. El fixture dorado de I1 sigue siendo
  `c0690c65c91bc5b55be60136f3f4f9b7453eb04708794286e0a54027998d8b53`.

---

## 4. Flujo: construir → mostrar → aprobar / denegar → comprobar antes de ejecutar

| Paso | Acción | Artefacto |
| --- | --- | --- |
| 1 | Construir el `TaskGraph` determinista (I1) | `TaskGraph` con `topological_order` y `graph_sha256` |
| 2 | Recalcular el hash con `graph_hash_of(graph)` | hash de contenido, no prueba de aprobación |
| 3 | Mostrar al operador hash, tareas, autonomía máxima, herramientas, conectores, presupuesto y expiración | `graph.to_dict()`, `to_dict()` de la política |
| 4a | **Denegar** emite `ApprovalReceipt(decision='denied')` | recibo de denegación con su propio `receipt_id` y sello |
| 4b | **Aprobar** emite recibo inmutable | `ApprovalReceipt` (dataclass `frozen`) enlazado al hash exacto |
| 5 | Antes de cada tarea: recalcular el hash, localizar el recibo vigente (`active_receipt`) y comprobar alcance, autonomía, presupuesto y `policy_hash` | `evaluate_execution()` → `blockers` |
| 6 | Si falla una condición se bloquea; si todo coincide se permite **sólo** la acción aprobada | `can_execute(task, graph, receipt, ...)` → `True`/`False` |

`can_execute()` es estricto por diseño: devuelve `False` ante cualquier duda (ausencia de recibo, recibo
inválido, grafo que no es un `TaskGraph`, política en vigor no aportada, marca de tiempo inválida,
excepción inesperada). **El fallo nunca autoriza**; `evaluate_execution()` explica *por qué* con códigos
exhaustivos.

### 4.1 Vocabulario de bloqueo (`BLOCKER_CODES`)

`receipt_missing`, `receipt_invalid`, `graph_invalid`, `graph_hash_mismatch`, `graph_schema_mismatch`,
`receipt_not_approved`, `receipt_expired`, `receipt_revoked`, `task_unknown`, `task_out_of_scope`,
`autonomy_not_covered`, `write_scope_not_covered`, `connector_not_covered`, `requests_exceeded`,
`tokens_exceeded`, `cost_exceeded`, `policy_hash_not_supplied`, `policy_hash_mismatch`.

`policy_hash_not_supplied` es deliberado: sin la política en vigor no se puede afirmar que la aprobación
siga respaldada por la misma política, así que la ejecución se bloquea en vez de suponerla.

### 4.2 Verificador de consistencia (`verify_receipt`)

`receipt_invalid`, `receipt_hash_mismatch`, `graph_invalid`, `graph_hash_mismatch`,
`graph_schema_mismatch`, `receipt_not_approved`, `receipt_expired`, `receipt_revoked`,
`policy_hash_mismatch`. `valid` es `True` **solo** si la lista de problemas está vacía.

---

## 5. Forma del recibo (`orgdna-approval-receipt-v1`)

Campos obligatorios, todos presentes y validados:

| Campo | Contenido |
| --- | --- |
| `receipt_id` | identificador derivado del contenido (`rcpt-…`) o explícito; patrón `^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$` |
| `kind` | `task_graph_approval` |
| `graph_sha256` | SHA-256 hexadecimal minúscula del `TaskGraph` aprobado |
| `graph_schema` | `orgdna-task-graph-v1` |
| `approval_scope` | `task_ids`, `max_autonomy`, `allowed_write_scopes`, `allowed_connectors`, `max_requests`, `max_output_tokens`, `max_estimated_cost_usd` |
| `approver` | `mode = declarative_role`, `role`, `authenticated = false` |
| `policy` | `policy_version`, `policy_hash` (64 hex), `approval_required` |
| `decision` | `approved` \| `denied` \| `revoked` \| `expired` |
| `created_at` | marca UTC `…Z` |
| `expires_at` | marca UTC `…Z` o `null` (sin caducidad declarada, nunca 0) |
| `revocation` | `null` o `{revoked_at, revoked_by_role, reason, supersedes}` |
| `notes` | texto declarativo (hasta 1000 caracteres) |

Campos adicionales declarados por O1 (el contrato exige *todos* los obligatorios y no prohíbe que el
recibo identifique su esquema y selle su contenido): `receipt_schema`, `receipt_version`, `receipt_sha256`.

**Inmutabilidad.** `ApprovalReceipt`, `ApprovalScope`, `Approver`, `PolicyReference` y `Revocation` son
`dataclass(frozen=True)`: no se pueden modificar después de emitirse. `to_dict()` devuelve copias.

**Sello y sus límites honestos.** `receipt_sha256` es el SHA-256 del JSON canónico del recibo sin el
sello; cubre exactamente el contenido. Detecta alteración **no recalculada**. No es una firma: quien
puede recalcular el sello puede producir un recibo coherente consigo mismo (y probado en
`test_falsifier_13`), por eso la ejecución se bloquea además con el enlace al grafo y con la política en
vigor. Aquí no se inventa autenticación.

---

## 6. Contrato de incrustación: los cinco canales

El recibo debe **poder sobrevivir** dentro de proyecto guardado, bundle exportado, diagnóstico
descargado, resultado de generación y artefacto de aprobación. Esta tarea entrega el payload canónico y
su contrato; **no** cablea la persistencia física.

| Canal (`CHANNELS`) | Clave del payload | Modelo mínimo previsto |
| --- | --- | --- |
| `saved_project` | `approval_receipts` | `project/approval_receipts.jsonl` |
| `exported_bundle` | `approval_receipts` | `bundle/approval_receipts.jsonl` |
| `downloaded_diagnostic` | `approval_receipts` | `project/generation_diagnostics.json` |
| `generation_result` | `approval_receipt` | `project/task_graph.json` |
| `approval_artifact` | `approval_receipt` | `project/artifacts/` |

- `embed_receipt(receipt, channel)` devuelve `{channel, receipt_schema, receipt_version, key, payload,
  receipt_sha256}`; un canal fuera de los cinco se rechaza (`channel_unknown`).
- `canonical_receipt_json(receipt)` y `parse_receipt(...)` dan **round-trip sin pérdida** (verificado
  también sobre el payload incrustado).
- **Dos reglas:** (1) la persistencia local es **opcional y explícita**; (2) la **AUSENCIA de archivo de
  recibo NO se interpreta como aprobación** — se interpreta como `receipt_missing` y bloquea.
- **No se abre ningún almacén nuevo**: el módulo no escribe nada (verificado con `builtins.open`
  parcheado) y **no** se crea ninguna base de datos nueva en `data/`.

---

## 7. Blindaje en lectura (sin modificar el Policy Engine)

- **Credenciales:** `policy_engine.find_prohibited_fields(payload)` (lista literal de
  `engine/project_store.py:19`) → `ProhibitedFieldError`.
- **Autenticación:** `policy_engine.find_authentication_claims(payload)` → `AuthenticationClaimError`.
  La **única** exención declarada es `approver.authenticated` con valor `False` (`AUTHENTICATION_EXEMPT_FIELDS`):
  el campo lo exige el contrato y `False` es la forma de declarar que **no** hay autenticación. Un valor
  distinto de `False` no se exime y se rechaza.
- El blindaje se aplica **antes** de la comprobación de campos desconocidos, de modo que un nombre con
  forma de credencial produce su propio código y no un genérico `invalid_field`.
- `engine/policy_engine.py` **no se modifica**: se importa en modo lectura.

---

## 8. Los 14 falsificadores (todos BLOQUEAN)

Ejecutados en `tests_platform_approval_receipt.py` como aserciones de bloqueo sobre `can_execute()` /
`evaluate_execution()`, no como comprobaciones de serialización.

| Id | Falsificador | Comportamiento exigido | Código observado |
| --- | --- | --- | --- |
| F1 | grafo sin recibo | bloquea `execute-approved` | `receipt_missing` |
| F2 | recibo con hash correcto | aprueba **sólo** dentro del alcance | `()` dentro; `task_out_of_scope` fuera |
| F3 | recibo con hash de otro grafo | bloquea | `graph_hash_mismatch` |
| F4 | grafo modificado tras la aprobación | hash distinto y bloquea | `graph_hash_mismatch` |
| F5 | `task_id` fuera de `approval_scope.task_ids` | bloquea | `task_out_of_scope` |
| F6 | tarea `execute-approved` con recibo sólo `prepare` | bloquea | `autonomy_not_covered` |
| F7 | herramienta/conector no incluido | bloquea | `connector_not_covered`, `write_scope_not_covered` |
| F8 | presupuesto solicitado que excede el recibo | bloquea | `requests_exceeded`, `tokens_exceeded`, `cost_exceeded` |
| F9 | recibo expirado | bloquea | `receipt_expired` |
| F10 | recibo revocado | bloquea | `receipt_not_approved`, `receipt_revoked` |
| F11 | `authenticated:false` presentado como identidad verificada | se rechaza la construcción/lectura | `authentication_claim` |
| F12 | la misma aprobación enviada dos veces | no duplica efecto y declara el duplicado | `appended=False`, `duplicate_of` |
| F13 | recibo alterado | falla la verificación | `receipt_hash_mismatch` |
| F14 | el manifiesto permanece intacto | integridad entrada a archivo + huella de R0 al cierre | `mismatched == []` |

---

## 9. Lo que esta entrega NO hace (declarado, no asumido)

1. **No cablea la persistencia.** Tocaría `engine/export_artifacts.py`, `engine/bundle.py` y
   `engine/bridge.py`, cambiaría el conjunto exacto de archivos del formato de exportación congelado y
   colisionaría con `t9`; queda como paso 2, no autorizado, registrado en
   `OBSERVACIONES_CAPITAN_PLATAFORMA.md:34`.
2. **No autentica.** No hay claves, ni firmas, ni certificados, ni atestaciones; `authenticated` es
   siempre `False` y la identidad verificada es siempre `False`.
3. **No concede permisos.** Un recibo aprobado no habilita nada por sí mismo: la ejecución exige además
   la política en vigor (`policy_hash` coincidente) y, aguas arriba, el Policy Engine (`I3`).
4. **No es una firma.** El sello detecta alteración no recalculada; no aporta autenticidad de tercero.
5. **No modifica I1.** `compute_graph_sha256()`, el `TaskGraph` serializado, el manifiesto, los permisos
   efectivos, los defaults de autonomía y la política de persistencia efímera quedan intactos.

---

## 10. Verificación reproducible

```text
python -m unittest discover -s EQUIPO_ENTERPRISE_24_COUNCIL_ADN -t EQUIPO_ENTERPRISE_24_COUNCIL_ADN -p "tests_platform_approval_receipt.py" -v
python -m unittest discover -s EQUIPO_ENTERPRISE_24_COUNCIL_ADN -t EQUIPO_ENTERPRISE_24_COUNCIL_ADN -p "tests_platform_task_graph.py" -v
python EQUIPO_ENTERPRISE_24_COUNCIL_ADN/validate_imports_portable.py
```

La suite del recibo contiene **38 casos** (mínimo exigido: 18) e incluye los **14 falsificadores** como
aserciones de bloqueo. La suite de I1 sigue en verde con el fixture dorado `c0690c65…` intacto, y
`validate_imports_portable.py` conserva `valid=true`.

**Pendiente de integración (`t9`):** añadir `engine/approval_receipt.py`, `tests_platform_approval_receipt.py`
y este documento a `RUNTIME_ALLOWLIST` y regenerar `MANIFIESTO_SHA256.txt` (decisión D-R0-2).
