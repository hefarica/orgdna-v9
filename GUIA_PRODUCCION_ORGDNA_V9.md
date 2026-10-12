# GUÍA DE PUESTA EN MARCHA — OrgDNA V9 (plataforma integrada)

Escrita por el capitán el 10 de octubre de 2026, tras la verificación V1. **Léela entera antes de generar.** No es
publicidad: incluye lo que **no** está certificado y lo que puede hacerte perder dinero si lo ignoras.

---

## 1. Qué está verificado y qué no

| Verificado con evidencia ejecutada | NO verificado (`NOT_RUN`) |
|---|---|
| El paquete valida: `valid=true`, 1791 comprobaciones, 301 archivos | **Generación con un proveedor real**: nunca se ha ejecutado aquí |
| Suite de plataforma: 382/382 OK | Conectores vivos (GitHub, Drive, BD, email, CI) |
| Recibo de aprobación: 38/38, con sus 14 falsificadores | Operación continua 24/7 |
| Cero reintentos automáticos de operaciones pagadas (84/84 combinaciones) | Chromium real, Excel COM del usuario, instalación DSH |
| La app arranca con `launch.cmd` (Python 3.10+) | Facturación real de cualquier intento |

**Conclusión honesta:** puedes **ejecutar** la aplicación. No puedes declarar que está **certificada para producción**,
porque el camino pagado contra un proveedor real sigue sin medirse y los cinco puntos de la sección 6 están abiertos.

---

## 2. Arranque

```
1. Python 3.10 o posterior instalado (probado con 3.12.10).
2. launch.cmd   (desde la carpeta EQUIPO_ENTERPRISE_24_COUNCIL_ADN)
3. Introduce la credencial del proveedor en el panel local. Se guarda cifrada con DPAPI
   por usuario (%LOCALAPPDATA%\OrgDNA\keys.dpapi). No se guarda en el proyecto.
```

---

## 3. LO MÁS IMPORTANTE: evita repetir el fallo que originó todo

Tu intento original murió en `api_design` con `output_truncated` («la respuesta alcanzó su límite de salida antes de
completar el lote»). **El modo de fallo sigue existiendo en V9**: no se parcheó, porque el plan P0-A quedó como diseño y
la ola que se implementó fue la de plataforma.

**El mecanismo, con sus líneas exactas.** `engine/org_design.py:469` calcula `per_batch` a partir del tope de salida, y
`:491` fija el tope así:

```python
cap = effective_cap if profiles_per_request is not None \
      else min(effective_cap, BATCH_TOKEN_OVERHEAD + PROFILE_TOKEN_BUDGET * len(batch))
```

Es decir: **si dejas «perfiles por solicitud» en automático, el tope se consume casi exactamente** con una estimación
local que el propio motor declara no ser un tokenizer (`:509-511`). Si un perfil real cuesta más de 2400 tokens, la
respuesta se corta y el lote falla entero.

**Lo que debes hacer, y es gratis:**

| Ajuste | Por qué |
|---|---|
| **Fija «perfiles por solicitud» explícitamente** (4–6 con N=30) **en lugar de dejarlo automático** | Con valor explícito `cap = effective_cap`: cada lote usa el **tope completo del modelo** en vez del cálculo al límite. Es el margen que evita el truncamiento |
| **No aumentes N para «aprovechar» el lote** | Más perfiles por solicitud = menos margen por perfil |
| Lee la advertencia de límites antes de autorizar | Si el proveedor no reporta `max_output_tokens`, el plan lo dice (`:545-546`) y **no bloquea**: te avisa y sigue. Si aparece, baja perfiles por solicitud |
| Deja el modo JSON si tu modelo lo soporta; si el proveedor rechaza `response_format`, cambia a Texto explícitamente | `JSON_MODE_SOURCES` (`:33-37`) es un mapa estático, no una capacidad consultada |

**Antes de autorizar, el plan te muestra**: hash de la solicitud, lote, tope de salida y presupuesto. **Si algo no
cuadra, no autorices**: la autorización se consume y puede facturarse aunque no se complete ningún perfil.

---

## 4. El identificador de modelo (el otro factor del incidente)

- La app **exige** que el ID lo devuelva el catálogo del proveedor: consulta `GET /models` con tu credencial.
- Un **nombre visible** (`DeepSeek-V4.1-Flash`) o un alias de DSH **no** sirven como ID: se rechazan con un mensaje
  específico antes de preparar el envío.
- Si no hay clave, DeepSeek devuelve un catálogo documental marcado `UNVERIFIED_ACCOUNT_AVAILABILITY` y **no** habilita
  el envío: es correcto, no un fallo.

---

## 5. Exportar en Windows — esto SÍ te va a afectar

Defecto heredado de V8, **medido y no causado por la ola**:

- `engine/bridge.py:1444`: en Windows toda descarga de exportación pasa por `excel_call('Read', …)`; en POSIX usa
  `read_xlsx_snapshot(...)` y no toca Excel.
- `engine/excel_bridge.ps1:81-82`: lanza **si el libro designado no está abierto** en la instancia activa de Excel.
- El script llega con **Mark-of-the-Web**: con `LocalMachine=RemoteSigned`, PowerShell se niega a cargarlo.

**Para exportar en Windows necesitas las dos cosas:**

```powershell
# 1) Desbloquear el script (una vez)
Unblock-File .\engine\excel_bridge.ps1
# 2) Tener Excel abierto CON el libro designado cargado antes de exportar
```

Si no puedes cumplir eso, **exporta desde un host POSIX**, donde el camino es `read_xlsx_snapshot` y no requiere Excel.

---

## 6. Lo que sigue abierto (no lo tapes)

| Asunto | Estado | Qué implica para ti |
|---|---|---|
| Regresión de plazo de la ola | **Abierta** | La **suite** ve 5 fallos + 8 errores donde la base veía 1 + 8. La **app** sólo va ~0,9 s más lenta en la etapa de exportación. Localizado: `build_package_bytes`, +78 %, por los 32 archivos nuevos reempaquetados en cada generación |
| Tres requisitos de prueba | **Parciales** | Límite antes del primer perfil, corte dentro de un bloque, y fidelidad del aviso: hoy se sostienen por lectura de código, no por aserción |
| `skipped=1` | Pendiente de **tu** aceptación | Un test de enlaces simbólicos no puede ejecutarse en este Windows |
| Independencia de verificación | **Degradada** | El informe V1 lo firma el capitán: cinco intentos por miembros murieron por infraestructura |
| Bloqueo del plan | **Abierto** | `create_task` funciona; `edit_plan` no. Las cinco P2 siguen gateadas |
| O-1 paso 2, A-1, O-3, O-5, D-R0-5 | **Sin decidir** | Ninguna es aprobación implícita |

**Recomendación de secuencia si quieres producción de verdad:**

1. **Hoy puedes usar la app** con los ajustes de §3 y §5, asumiendo que el proveedor real sigue sin medir.
2. **Antes de gastar en serio**: un intento pequeño (N=4–6, no 30) con perfiles por solicitud explícito, para medir el
   camino real sin arriesgar un lote grande. Guarda el diagnóstico aunque falle.
3. **Reparar la regresión**: el foco ya está localizado; la optimización razonable es **no reempaquetar la parte
   inmutable del runtime en cada generación** (cachear la base invariable), no tocar la ventana de 12 s.
4. Cerrar los tres requisitos de prueba parciales.

**Nada de esto convierte la entrega en «verificada en producción».** El paquete está integrado y probado **offline**;
lo que falta no es código de plataforma, es medir el proveedor real y cerrar lo de arriba.
