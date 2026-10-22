# RE-B — Auditoría de licencias leída al sha (gate Tier 2 de la adopción verbatim)

**Estado: GATE TIER 2 CERRADO.** Siete fuentes resueltas con evidencia al sha; **2 fragmentos
adoptables verbatim** (2 fuentes); 5 fuentes con veredicto explícito de *no copia*; **0 líneas de
código ajeno copiadas en esta tarea**.

- Tarea: `t29` (RE-B). Autoriza: `docs/security/FUSILE_SOURCE_POLICY.md` §«ENMIENDA PERMANENTE —
  código verbatim» (marca literal del operador, 2026-10-21), con la condición única de **no código
  malicioso** y sus 5 supuestos de exclusión. Obligaciones Tier 2 (a)–(f) siguen vigentes.
- Alcance de este documento: resolver **licencia leída en el sha**, clasificar y decidir. La copia
  es de `t30`; aquí no se escribe ni una línea de código de las fuentes.
- Prohibiciones respetadas: no se ejecutó `resella_paquete.py` ni la suite completa; no se tocó
  `engine/`, `web/`, `MANIFIESTO_SHA256.txt` ni DSH.
- Fecha de lectura: **2026-10-21/22** (hora local del host `-05:00`), sesión del harness.
- Naturaleza: registro técnico de lectura de textos de licencia. **No es asesoría legal.**

---

## 1. Método (reproducible por cualquiera)

| Paso | Cómo se hizo | Por qué es verificable |
|---|---|---|
| 1. Fijar el sha | `git ls-remote https://github.com/<owner>/<name> HEAD` | Devuelve el sha sin depender de metadatos de la API ni de la cuota |
| 2. Leer el fichero de licencia **en ese sha** | `GET https://raw.githubusercontent.com/<owner>/<name>/<sha>/LICENSE` (y `LICENSE.md`, `LICENSE.txt`, `COPYING`, `COPYING.txt`, `LICENSE-APACHE`, `LICENSE-MIT`, `NOTICE`) | HTTP 200 registrado por fichero; los ausentes dieron 404 |
| 3. Huella de la licencia | `sha256` de los **bytes exactos** descargados | Cualquiera repite la descarga y compara el hash |
| 4. SPDX | Deducido **del texto** (frases decisivas: «Apache License / Version 2.0», «Permission is hereby granted», «Attribution 4.0 International», «PolyForm Shield») | Nunca se usó `license.spdx_id` de la API como veredicto |
| 5. Blob SHA del fichero candidato | `git hash-object <fichero descargado>` | Es el id de objeto git; coincide con el campo `sha` de la API `contents` si se consulta |
| 6. Fragmento | Rango de líneas 1-based inclusive; `sha256` sobre las líneas unidas con `\n`, UTF-8 sin BOM y **sin salto final**; tamaño en bytes de esa misma cadena | El `sha256` del fragmento fija exactamente qué se copia |
| 7. Veredicto | `COMPATIBLE` (Apache-2.0 / MIT / BSD-3 / ISC) · `NO COMPATIBLE` (sin licencia, AGPL/GPL fuerte, SSPL, BUSL, o licencia **no de software** como CC-BY) · `INDETERMINADA` (no se puede probar) | `INDETERMINADA` ⇒ **no se copia** (condición de parada) |

La cuota de la API de GitHub quedó en 8/60 al empezar, así que el pin de sha y el blob SHA se
resolvieron con `git ls-remote` y `git hash-object` (equivalente y sin cuota). La API solo se usó
para una comprobación de cuota.

---

## 2. Tabla A — licencia leída al sha (7 fuentes)

| # | Fuente fijada | Fichero leído (HTTP) | Bytes | `sha256` del fichero de licencia | SPDX deducido del texto | Veredicto |
|---|---|---|---|---|---|---|
| 1 | `langchain-ai/langgraph@3cd57c038ad827d05f80c6488adea9994156c58c` | `LICENSE` (200) | 1 072 | `d9bb52f2e3540d60ff50d8f0f5b6ba649b7fd346948c4c3d086c8afb120763c7` | **MIT** («MIT License», «Copyright (c) 2024 LangChain, Inc.», «Permission is hereby granted») | **COMPATIBLE** |
| 2 | `FoundationAgents/MetaGPT@11cdf466d042aece04fc6cfd13b28e1a70341b1f` | `LICENSE` (200) | 1 072 | `74945da6216c3f6498159a55cd25c0564acc684b791c169f869117a095808b00` | **MIT** («The MIT License», «Copyright (c) 2024 Chenglin Wu») | **COMPATIBLE** |
| 3 | `ag2ai/ag2@0938ebda125d77d35856059df264a30c86ad656e` | `LICENSE` (200) | 11 384 | `18415054d6b2011f92feb403e65f213dd82f83292d55dcb8071e7ebfdd087d12` | **Apache-2.0** (cuerpo íntegro; sin MIT/GPL/SSPL/BUSL en el texto) | **COMPATIBLE** |
| 4 | `agentscope-ai/agentscope@8a2aef4f1787f6aeb4b07a56bbc1d061c5aa7ef5` | `LICENSE` (200) | 20 637 | `4186bcadf358c60080060309769db6b2a352720d7353d827bb574c600fee9913` | **Apache-2.0** (cuerpo, líneas 1–189) + **apéndice de avisos de terceros** (solo ISC y Apache; sin copyleft) | **COMPATIBLE** |
| 5 | `OpenBMB/ChatDev@a2ea4a263cebe9a7abd01ee3b5b0bf95698ed328` | `LICENSE` (200) | 11 337 | `709b5ae8d3b982431831481298f5ceddc1432f98a914da3a4acc829f0615038b` | **Apache-2.0** | **COMPATIBLE** |
| 6 | `microsoft/autogen@004749e6b7102c8fd317b9b1499ce5807223c278` | `LICENSE` (200) | 18 650 | `7e7170e3cebf88a9f60c7b8421418323c09304da1af4d5e90f4da1dc1c8a2661` | **CC-BY-4.0** («Attribution 4.0 International»; es licencia de *contenido*, no de software) | **NO COMPATIBLE** |
| 7 | `Significant-Gravitas/AutoGPT@8d4a965b7bbc87b271cd7e4c163ed09d443e9199` | `LICENSE` (200) | 8 542 | `aafc62ebf01092909ae72131b66f48c89ea7eaf4bd7e916f3f05f7960611799a` | **SPLIT**: `PolyForm-Shield-1.0.0` en `autogpt_platform/**` + **MIT** en el resto (`classic/`, forge, benchmark, frontend) | **NO COMPATIBLE** para el *platform*; MIT solo fuera de esa carpeta |

**Ficheros de licencia ausentes (404, todos):** `LICENSE.md`, `LICENSE.txt`, `COPYING`,
`COPYING.txt`, `LICENSE-APACHE`, `LICENSE-MIT`, `NOTICE` en las seis fuentes que solo publican
`LICENSE`. (AutoGPT y agentscope tampoco publican `NOTICE`.)

---

## 3. Casos especiales y correcciones al supuesto previo

### 3.1 `microsoft/autogen` — CC-BY-4.0: **no copiable para código** (confirmado por texto)

El `LICENSE` al sha es el texto legal completo de *Creative Commons Attribution 4.0 International*
(`Attribution 4.0 International` → `Creative Commons Corporation ("Creative Commons") is not a law
firm…`). No es una licencia de software: no concede el conjunto de derechos que un port de código
necesita (patentes, forma de distribución de binarios) y exige atribución en términos pensados para
obras creativas. **Veredicto: NO COMPATIBLE.** Los mecanismos que t21 leyó de su documentación
(M2 parada/terminación, M5 contabilidad de uso) **se reimplementan**; no se copia código ni tests.

### 3.2 `Significant-Gravitas/AutoGPT` — **corrección**: no es «sin licencia»

El metadato de la API decía `NOASSERTION` (GitHub no sabe clasificar un repo con dos licencias). El
texto **al sha** es inequívoco (líneas 1–17 del `LICENSE`):

> «All portions of this repository are under one of two licenses. — Everything inside the
> `autogpt_platform` folder is under the Polyform Shield License. — Everything outside the
> `autogpt_platform` folder is under the MIT License.»

Consecuencias exactas:

- `autogpt_platform/**` → **PolyForm Shield License 1.0.0** (source-available, con restricción de
  competencia) → **NO COMPATIBLE** con la adopción de este repo.
- Resto (`classic/**`, Forge, benchmark, frontend) → **MIT** → compatible, *si* algún día se
  selecciona un fragmento de ahí.
- **No se seleccionó ningún fragmento** de esta fuente: t21 la usó solo como referencia y los
  mecanismos de interés viven en el *platform* (PolyForm). Se registra la corrección porque el
  supuesto «NOASSERTION ⇒ sin licencia determinable ⇒ nada copiable» era **impreciso**: sí hay
  licencia determinable, y una de sus dos mitades es MIT.

### 3.3 `agentscope-ai/agentscope` — Apache-2.0 con apéndice, y licencia idéntica en el sha ya permitido

- `LICENSE` = cuerpo Apache-2.0 (líneas 1–189) + **APPENDIX de avisos de terceros** desde ~línea
  190 (`Copyright 2024 Alibaba` y componentes embebidos, p. ej. `socket.io.js` MIT). Los términos
  presentes en el apéndice son **ISC y Apache**: ningún copyleft. El código del repo es Apache-2.0.
- **Verificación de la entrada ya permitida por la política**: el sha declarado en
  `docs/security/FUSILE_SOURCE_POLICY.md` es `26ec620`; su `LICENSE` es **byte a byte idéntico** al
  del sha auditado `8a2aef4` (mismos 20 637 B y mismo `sha256`). Es decir, la licencia declarada en
  la allowlist coincide con la que se lee hoy: **no hubo deriva de licencia**.
- `pyproject.toml` al sha (7 857 B, `sha256 5b766c3eff08b9c3c6ca1d36535914a51dc43f0350b468486c8af97355e8085f`)
  se leyó **solo como soporte**; el veredicto sale del texto de `LICENSE`.

### 3.4 `OpenBMB/ChatDev` — Apache-2.0 y **sha auditado == sha declarado**

El sha auditado (`a2ea4a263cebe9a7abd01ee3b5b0bf95698ed328`) es el mismo que la política declara
(`a2ea4a2`). `LICENSE` = Apache-2.0 (11 337 B). Soporte: `pyproject.toml` al sha (1 455 B,
`sha256 8bad7cc79f4f863a74ea625c1cc6c4f99dcabb9e02ae0cecc0d895be29c16e90`) declara
`license = { text = "Apache-2.0" }`. El `package.json` (57 B) solo lista `devDependencies`.

### 3.5 Evidencia de licencia **por fichero**, no solo por repo

`ag2/events/conditions.py` (fragmento adoptado, §Tabla B) lleva cabecera propia:

```
# Copyright (c) 2026, AG2ai, Inc., AG2ai open-source projects maintainers and core contributors
#
# SPDX-License-Identifier: Apache-2.0
```

Es la evidencia más fuerte posible para un fragmento: licencia declarada **en el propio fichero**
además de en el repo. `metagpt/team.py` y `langgraph/checkpoint/base/__init__.py` no llevan SPDX por
fichero; su cobertura es la del `LICENSE` del repo al sha (MIT en ambos).

Nota de precisión sobre «0 líneas de código copiadas»: en este documento la cabecera de AG2 se cita
**literalmente** (3 líneas de comentario: copyright, `SPDX-License-Identifier` y la misma cabecera que
encabeza el fichero de pruebas) porque es la prueba de licencia. No hay ninguna otra línea de código de
las fuentes en `license_audit.md` ni en `PORT_REPORT_AGILIDAD.md`; lo verifiqué con un control
automático (ninguna línea de más de 40 caracteres de los ficheros fuente aparece en los dos documentos,
salvo esa cabecera, que aparece por estar idéntica en `conditions.py` y en su test).

---

## 4. Condición de parada aplicada (fuentes sin copia)

| Fuente | Veredicto | Qué se hace |
|---|---|---|
| `microsoft/autogen` | NO COMPATIBLE (CC-BY-4.0) | Se **reimplementan** los mecanismos M2 (parada/terminación) y M5 (corte por presupuesto) desde el comportamiento documentado, sin código ni tests del fuente |
| `Significant-Gravitas/AutoGPT` | NO COMPATIBLE en `autogpt_platform/**` (PolyForm Shield); MIT solo fuera | **Nada se copia**: no se seleccionó fragmento; queda como referencia |
| `agentscope-ai/agentscope` | COMPATIBLE | **No requiere verbatim**: el port ya existe y está vectorizado (`engine/team_channel.py`, `engine/team_memory.py`; `docs/rea/PORT_REPORT.md:25-26`). No se duplica |
| `OpenBMB/ChatDev` | COMPATIBLE | **No requiere verbatim**: port existente bajo puertas (`engine/sandbox_executor.py`; `PORT_REPORT.md:27`). Además su fragmento natural (ejecutor por subproceso) roza la exclusión 4 de la enmienda: se conserva la reimplementación gobernada |
| `langchain-ai/langgraph` | COMPATIBLE (MIT) | Los fragmentos de **checkpoint** están completos y verificados (Tabla B) pero **no se copian**: M1 ya está congelado por `TEAM_API_CONTRACT_v1` (C-2) e implementado en `engine/team_process.py`. Los de **almacén en memoria** y **uuid6** se rechazan por razón técnica (pickle / `random`), y se reimplementan con sus vectores |
| `ag2ai/ag2` | COMPATIBLE (Apache-2.0) | **Se adopta verbatim** un fragmento (condiciones de parada) |
| `FoundationAgents/MetaGPT` | COMPATIBLE (MIT) | **Se adopta verbatim** un fragmento (corte por presupuesto) |

**Ninguna fuente quedó en `INDETERMINADA`**: las siete resolvieron con texto al sha. La condición de
parada no tuvo que aplicarse a la ligera, y donde se aplicó fue por licencia (autogen, AutoGPT) o por
razón técnica declarada (langgraph almacén/uuid6), no por comodidad.

---

## 5. Inventario de evidencia (lo que se descargó, con su huella)

Rutas locales de trabajo: `%TEMP%\t29\` (efímeras; **la prueba portable es el `sha256`**). URL de
cada licencia: `https://raw.githubusercontent.com/<fuente-sin-sha>/<sha>/LICENSE`. `blob` = id de
objeto git (`git hash-object`), equivalente al `sha` de la API `contents`.

| Fichero | Fuente@sha | Bytes | `sha256` del fichero | `blob` git |
|---|---|---|---|---|
| `LICENSE` | `langchain-ai/langgraph@3cd57c0` | 1 072 | `d9bb52f2e3540d60ff50d8f0f5b6ba649b7fd346948c4c3d086c8afb120763c7` | `fc0602feecdd6748623c852ab534e1ca612673c7` |
| `LICENSE` | `FoundationAgents/MetaGPT@11cdf46` | 1 072 | `74945da6216c3f6498159a55cd25c0564acc684b791c169f869117a095808b00` | `00d36a832e74e0a131ed5e698896206cb3724323` |
| `LICENSE` | `ag2ai/ag2@0938ebd` | 11 384 | `18415054d6b2011f92feb403e65f213dd82f83292d55dcb8071e7ebfdd087d12` | `a40e7d03d70e094a54bcc34f67f4243b0c8a382d` |
| `LICENSE` | `agentscope-ai/agentscope@8a2aef4` | 20 637 | `4186bcadf358c60080060309769db6b2a352720d7353d827bb574c600fee9913` | `2f2f2f25ea6019e5a51213c4e8a4df0c67a6ea2a` |
| `LICENSE` | `agentscope-ai/agentscope@26ec620` (sha de la política) | 20 637 | `4186bcad…` (**idéntico byte a byte**) | `2f2f2f25…` (**idéntico**) |
| `LICENSE` | `OpenBMB/ChatDev@a2ea4a2` | 11 337 | `709b5ae8d3b982431831481298f5ceddc1432f98a914da3a4acc829f0615038b` | `88fc36e7ec8691d3523648568474f0cccd3c2592` |
| `LICENSE` | `microsoft/autogen@004749e` | 18 650 | `7e7170e3cebf88a9f60c7b8421418323c09304da1af4d5e90f4da1dc1c8a2661` | `2f244ac814036ecd9ba9f69782e89ce6b1dca9eb` |
| `LICENSE` | `Significant-Gravitas/AutoGPT@8d4a965` | 8 542 | `aafc62ebf01092909ae72131b66f48c89ea7eaf4bd7e916f3f05f7960611799a` | `b75444a0b0ab429be2e070d104208b507c2294ac` |
| `pyproject.toml` | `agentscope-ai/agentscope@8a2aef4` | 7 857 | `5b766c3eff08b9c3c6ca1d36535914a51dc43f0350b468486c8af97355e8085f` | `51704ace9865f2f0b7bf67a417ba09ecea2e7bae` |
| `pyproject.toml` | `OpenBMB/ChatDev@a2ea4a2` | 1 455 | `8bad7cc79f4f863a74ea625c1cc6c4f99dcabb9e02ae0cecc0d895be29c16e90` | `e1e9cebe207ebd32cd359956101f813622c773ca` |
| `package.json` | `OpenBMB/ChatDev@a2ea4a2` | 57 | `f3949fe3dfbc571ddeec8b31c60cbfa465c12115197b5ec2149af298202db2e6` | `619710d8fc532952c404c88ec93d718e7cbb2e94` |
| `ag2/events/conditions.py` | `ag2ai/ag2@0938ebd` | 4 152 | `217db4aed771bb1ad23f16b7a077ec51c760333544cb4704d0cc3a7e20c4ecba` | `67b72fc7fd84ad43394df75e515ac05bc73287fc` |
| `test/events/test_conditions.py` | `ag2ai/ag2@0938ebd` | 8 741 | `8f2f783d8acf6a3e32cc3cb20c92bcc3a3b8deb167d76ce07f61fc81caeb5bf4` | `d7108a3f8d8d2336144ee2f1310b2e2ac4a392e6` |
| `metagpt/team.py` | `FoundationAgents/MetaGPT@11cdf46` | 4 844 | `af0398fce4109cadf8a0ac8e479d261ef0cb6347c60d0c3343ff7d6e22180bcc` | `5a9838885070add38a7cdd3ddf034ea40768d4b2` |
| `metagpt/utils/cost_manager.py` | `FoundationAgents/MetaGPT@11cdf46` | 5 272 | `9097f63062186b7dc388b4bd78ec3c21e1c52563193c812299b292a4c333bc1a` | `05df1e09a0aeeb977e7abe4d182dcb93e724914b` |
| `tests/metagpt/utils/test_cost_manager.py` | `FoundationAgents/MetaGPT@11cdf46` | 1 038 | `907977cae46ae8b57b015c8d38fa36597f2b0f6d4862fd2593d1939b14a4461a` | `9508c778f45191c035d4ef018c69d8a7cffc3e2a` |
| `tests/metagpt/test_team.py` | `FoundationAgents/MetaGPT@11cdf46` | 280 | `c8d07c0b2ac07246af3afde878585db9ced70881d216f82cecc4db0be287e84f` | `a97fc78bf6aa6fc423d66bd38cfe8c6444f4d5d5` |
| `tests/metagpt/serialize_deserialize/test_team.py` | `FoundationAgents/MetaGPT@11cdf46` | 4 820 | `70f520b6c658d7f2c6dd469fbd646291c0a573610bf7c93777d43f9f758ebba2` | `6312e1fde453056a1af7df04e4cf86ca06b080e0` |
| `libs/checkpoint/langgraph/checkpoint/base/__init__.py` | `langchain-ai/langgraph@3cd57c0` | 32 051 | `e1b412fb541b47cf9ab0657f5c160c955c71ce929d8ac786f0bcc94d356481e9` | `c7cacc7bfd703f298427e870bd6d07b4aa395812` |
| `libs/checkpoint/langgraph/checkpoint/memory/__init__.py` | `langchain-ai/langgraph@3cd57c0` | 26 460 | `9e81ce01b41fc1bf591e930e350629282fb4ac86d667e211899bae9b5b573a84` | `ff6f7b1caaab88f01363dc8d6b249d5ad0c338e8` |
| `libs/checkpoint/langgraph/checkpoint/base/id.py` | `langchain-ai/langgraph@3cd57c0` | 3 647 | `f4635d8f5f1e713c0f55eb111ad32a323121b318e1b2456eb5d61b305c25785b` | `30abc48a509601216fe7ddee3be55ceaa6cd93bd` |
| `libs/checkpoint/tests/test_memory.py` | `langchain-ai/langgraph@3cd57c0` | 26 868 | `e00afff74d5f26dd8549fcc68f5028e30dba4d162076eb61b180f06646b5c66d` | `7c350ab96209706e4540f3887afdd0097d766629` |

Los hashes de los **fragmentos** (rango de líneas, `sha256` sobre el texto del rango y tamaño) están en
`docs/rea/PORT_REPORT_AGILIDAD.md` §3 (Tabla B), que es el documento operativo para `t30`; un
fragmento tiene hash distinto del fichero porque el rango se normaliza a `\n` sin salto final.

---

## 6. Lo que esta auditoría **no** acredita (fail-honest)

1. **No es asesoría legal.** Es lectura de textos de licencia en un sha concreto, con huellas.
2. **No barre cabeceras de todos los ficheros** de cada repo: cubre el `LICENSE` del repo al sha y,
   cuando existe, la cabecera SPDX de los ficheros citados. Un fichero concreto de un repo compatible
   podría tener cabecera distinta: eso se comprueba **fichero a fichero** al copiar (obligación de
   `t30`).
3. **No audita dependencias transitivas** de los fragmentos. Los dos adoptados no importan terceros:
   `ag2/events/conditions.py` usa solo stdlib (`operator`, `abc`, `collections.abc`, `typing`) más un
   alias interno (`ag2.types.ClassInfo`) que se sustituye en la adaptación; el fragmento de MetaGPT
   (líneas 87–100) **no tiene ni un import**.
4. **Los blob SHA se calcularon localmente** con `git hash-object` (id de objeto git; equivalente al
   `sha` de la API `contents`). No se consultó la API por cuota disponible (8/60), no porque falte
   método de verificación.
5. **El registro en `docs/rea/PORT_REPORT.md`** (obligación Tier 2 (f)) corresponde a `t30`, que es
   quien copia; está fuera de mi inScope. El contenido listo para ese registro está en
   `docs/rea/PORT_REPORT_AGILIDAD.md`.
