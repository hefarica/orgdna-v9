# PREFLIGHT OPERABLE — OrgDNA

**7 pasos. Cada uno con comando, criterio PASA, criterio FALLA, evidencia y qué hacer si falla.**
Todo es **de solo lectura** salvo el paso 7. Nada de aquí instala, activa ni llama a un proveedor.

```bat
preflight-step1.cmd   …   preflight-step7.cmd     un paso cada uno
python preflight_operable.py                      los 7, en orden
python preflight_operable.py --json               artefacto para máquina
```

## Códigos de salida

```
0 = PASA          2 = BLOCKED (falta verificar, no roto)          1 = FALLA
```

## La regla de oro

> **Un paso en `BLOCKED` NO es un paso en `PASA`.**
> «Falta verificar» ≠ «verificado». Nunca se eleva el veredicto por inferencia.

## Estado medido en este host (ejecutado, no supuesto)

```
[PASS   ] 1. Integridad del paquete      valid=true y sello OK (320 entradas)
[BLOCKED] 2. Compatibilidad de versiones  @deepseek-ai/dsh-tools no es resoluble desde cordis_extension
[PASS   ] 3. Capacidad nativa             maxMembers declarado: 23
[BLOCKED] 4. Ausencia de doble motor      el contrato existe; comprobarlo exige el host
[BLOCKED] 5. Bindings sesión→perfil       no hay identity-map.json
[PASS   ] 6. Ruta del Captain             una sola ruta: deepseek-flash
[BLOCKED] 7. Herramientas registradas     exige sesión vinculada y addon montado

VEREDICTO: BLOCKED(2,4,5,7)
```

**Tres PASA y cuatro BLOCKED.** Los cuatro bloqueos son reales, no pesimismo: son cosas que **no se pueden
afirmar desde aquí**, y afirmarlas sería mentir.

---

## Orden estricto, por dependencia

```
1 → 2 → 3 → 4 → 5 → 6 → 7
```

Los pasos **1–4** corren sin bindings. El **paso 5** es el más frágil: si no puedes verificar la relación
sesión→perfil, **detente** — es donde el «cerebro único» se parte. El **paso 7** sólo va **después** de la
revisión humana de permisos.

---

## Los 7 pasos

### 1 · Integridad del paquete

| | |
|---|---|
| **Comando** | `preflight-step1.cmd` |
| **PASA** | `validate_imports_portable.py` devuelve `valid=true` **y** el sello SHA-256 verifica |
| **FALLA** | el validador devuelve otro código, o no declara `valid=true`, o el sello no cuadra |
| **Evidencia** | salida del validador + número de entradas del manifiesto |
| **Si falla** | **no continuar.** Repara con `python resella_paquete.py` |

### 2 · Compatibilidad de versiones

| | |
|---|---|
| **Comando** | `preflight-step2.cmd` |
| **PASA** | la versión instalada de `@deepseek-ai/dsh-tools` está en `SUPPORTED_TOOLS_VERSIONS` (`runtime.mjs`) |
| **FALLA** | está resoluble pero **no** en la lista |
| **BLOCKED** | no es resoluble, o falta `node`, o la lista no se puede leer |
| **Evidencia** | versiones soportadas + versión instalada + versión de node |
| **Si falla** | `BLOCKED_ACTIVATION`. No se toca la instalación |

La lista soportada se **lee** de `runtime.mjs`, no se supone. Es la misma que usa `entry.mjs:19` y
`plugin.mjs:15`.

### 3 · Capacidad nativa (`maxMembers`)

| | |
|---|---|
| **Comando** | `preflight-step3.cmd` |
| **PASA** | `maxMembers` está **declarado** con un valor |
| **BLOCKED** | no aparece, o aparece sin valor: el default del plugin decide y **la capacidad no está verificada** |
| **Evidencia** | los valores declarados y en qué archivo |
| **Acción** | **compáralo con N−1 y decide tú.** Este paso **no cambia** la configuración del host |

**Corrección medida:** `maxMembers` **no** es un registro público de Cordis — es un **parámetro del plugin**
AgentTeams (`ctx.plugin(AgentTeams, {maxMembers:23,…})`), y el smoke test cubre explícitamente el caso
**omitido**. Los fixtures de test declaran valores inventados (`999`) y el paso los **excluye a propósito**:
incluirlos daría un PASS falso.

### 4 · Ausencia de doble motor

| | |
|---|---|
| **Comando** | `preflight-step4.cmd` |
| **PASA** | `assertNoActiveGuiRuns()` y `assertNoExistingTeam()` devuelven ambos `true` |
| **BLOCKED** | no se puede comprobar **sin el host** (el caso de este host) |
| **FALLA** | hay GUI activa o ya existe un equipo nativo |
| **Evidencia** | recibos de ambos asserts |

La autoridad es **inyectada** (`native_orchestration.mjs`), no global. El contrato existe y la exclusión es
explícita (`entry.mjs:14`: *«Choose native review UI or a pre-reviewed manual hook, not both»*), pero
**comprobarlo exige el host**: este paso no puede pasar desde fuera.

### 5 · Bindings sesión → perfil  ← **el más frágil**

| | |
|---|---|
| **Comando** | `preflight-step5.cmd` |
| **PASA** | 1 sesión verificada por miembro |
| **FALLA** | `session_bindings` vacío o ambiguo |
| **BLOCKED** | no existe `identity-map.json`: los bindings no están producidos |
| **Si no puedes verificarlo** | **DETENTE.** Es donde el «cerebro único» se parte |

**Verificado, no supuesto:** `tests/runtime.test.mjs:94` **asserta que `session_bindings` vacío LANZA**
(mensaje que casa `/bindings/`). El fail-closed está probado en el propio árbol.

### 6 · Ruta del Captain

| | |
|---|---|
| **Comando** | `preflight-step6.cmd` |
| **PASA** | una sola ruta de modelo entre los artefactos del equipo |
| **FALLA** | más de una: el producto exige que la ruta del Captain coincida con la del perfil y falla si difieren |
| **Acción** | seleccionar una ruta revisada. **Nunca forzar** el modelo para que coincida |

### 7 · Herramientas registradas (readback)  ← **único paso que toca el host**

| | |
|---|---|
| **Comando** | `preflight-step7.cmd` |
| **PASA** | el readback del namespace devuelve `MOUNTED` con las herramientas esperadas |
| **BLOCKED** | sin sesión vinculada y addon montado, no se puede afirmar `MOUNTED` |
| **Cuándo** | **después** de la revisión humana de permisos. No antes |

El readback real es `call(agent, addonNamespace+'_state', {section:'summary'})`, visible en
`cordis_extension/tests/native_agentteams_stage_smoke.mjs:182`.

---

## Artefacto de salida

```json
{
  "preflight": {
    "host": "...", "runner": "...", "started_at": "...", "root": "...",
    "steps": [{"id": 1, "title": "...", "status": "PASS|FAIL|BLOCKED", "evidence": "..."}],
    "verdict": "READY_TO_STAGE | BLOCKED(2,4,5,7)",
    "writes_performed": false,
    "model_calls_performed": false,
    "rule": "Un paso en BLOCKED no es un paso en PASA."
  }
}
```

`python preflight_operable.py --json` lo emite.

---

## Lo que este preflight **no** hace, y no pretende

- **No escribe** en el host, **no instala**, **no activa**, **no llama a ningún proveedor**
  (`writes_performed: false`, `model_calls_performed: false` en el propio artefacto).
- **No cambia** `maxMembers`.
- **No fuerza** el modelo del Captain.
- **No convierte** un BLOCKED en PASA aunque «parezca que funciona».
- Un `READY_TO_STAGE` significaría que los 7 pasos pasan. **Hoy no ocurre**, y el veredicto lo dice.
