# Jerarquía, mando y méritos

## Mando explícito

El Owner está fuera de los 24 agentes. Cada perfil conoce a su superior, la cadena hasta Owner y sus reportes directos por ID y nombre. El mando organiza trabajo dentro del alcance autorizado; no crea credenciales, permisos DSH o autoridad ilimitada. Los vínculos de auditoría/consultoría no forman una segunda cadena de mando.

Un agente debe seguir la instrucción válida de su superior y puede refutarla con evidencia, un contraejemplo, impacto y alternativa. Registra el disenso y solicita decisión. Después de una resolución válida ejecuta dentro del mandato. Una orden que exija inventar evidencia, exceda permisos o deje un riesgo crítico sin resolver se marca BLOCKED y escala hasta Owner. No hay obediencia ciega ni desobediencia arbitraria.

Los contratos exactos por perfil están en `organizacion/GOBERNANZA_Y_MANDO.json`, en el visor y en los prompts. IDs y árbol tienen prioridad sobre títulos descriptivos; una recomendación de ascenso no cambia ninguno de ellos automáticamente.

## Puntuación reproducible

Cada dimensión se normaliza a 0–100. Score = 0.3 × calidad + 0.2 × cumplimiento + 0.15 × eficiencia + 0.15 × colaboración + 0.2 × evidencia. Para calidad, cumplimiento, colaboración y evidencia se utiliza 100 × numerador / denominador, con denominador positivo. Eficiencia = mínimo(100, 100 × presupuesto / coste real), en unidades comparables y con ambos valores positivos. El presupuesto se acuerda antes de revisar; velocidad, tokens o volumen por sí solos no prueban calidad.

La calidad mantiene todos los criterios de aceptación acordados en el denominador, incluidos los fallidos. Cada entregable tiene task_id único, SHA, autores, grupo comparable, criterios, presupuesto y referencias de evidencia. La revisión independiente incluye resultados negativos, justificación y ausencia de conflicto; no se permite que autor, coautor, superior o subordinado directo/indirecto puntúe ese entregable. Si falta revisor interno independiente, Owner designa uno externo identificado y registra su nombramiento.

El ranking agrega por media entregables únicos dentro del mismo grupo comparable; no suma actividad ni mezcla funciones/dificultad no comparables. Los empates de score conservan la misma posición. Las correcciones conservan revisiones anteriores y el SHA revisado; datos guardados no sustituyen las comprobaciones de integridad. La app calcula sobre registros manuales: no ejecuta las pruebas ni verifica automáticamente identidad, existencia o suficiencia de los artefactos referenciados.

Sin datos: score=null, rank=null y estado sin_evaluar, nunca cero ni una clasificación inventada. Confianza descriptiva, no probabilística: baja con menos de 3 muestras; media de 3 a 9; alta con al menos 10 muestras y 2 revisores independientes. Una muestra pequeña no acredita superioridad.

## Promociones y recompensas recomendadas

Una promoción o sucesión exige al menos 5 muestras, score ≥85, calidad ≥80, cumplimiento ≥90 y evidencia ≥90, sin revisiones pendientes. Reconocimiento, promoción y sucesión son propuestas trazables: supervisor revisa y Owner aprueba, con evidencia actual. No se conceden dinero, permisos, presupuesto, herramientas, nuevos modelos ni puestos por alcanzar un número. Aplicar un cambio de jerarquía es una acción administrativa separada, con límites, ciclos e independencia nuevamente verificados.

No se premia ocultar fallos, manipular denominadores, duplicar tareas o castigarse por reportar honestamente un error. Los CV, nombres, títulos ficticios y modelos no son evidencia de desempeño.

## Aprendizaje y privacidad

Feedback, checklists y skills correctivas versionadas pueden mejorar el proceso mediante fallo demostrado, causa raíz, retest, supervisor y revisión independiente. Registrar una propuesta o aprobarla manualmente no instala skills, entrena pesos ni acredita mejora ejecutada.

Este ZIP contiene la metodología y estados iniciales SIN EVALUAR; no distribuye actas, evaluaciones personales, historial de promociones ni reservas activas. Los registros permanecen en los proyectos guardados localmente. Exportar no borra ese historial y no presenta el estado inicial del visor como un score actual del proyecto.

## Política exacta

```json
{
  "version": "1.0",
  "weights": {
    "quality": 30,
    "compliance": 20,
    "efficiency": 15,
    "collaboration": 15,
    "evidence": 20
  },
  "range": [
    0,
    100
  ],
  "dimensions": {
    "quality": "Criterios de aceptación y regresión satisfechos / criterios acordados; los fallos permanecen en el denominador.",
    "compliance": "Obligaciones del mandato y límites de autoridad respetados / obligaciones evaluadas.",
    "efficiency": "Presupuesto acordado / coste real comparable, limitado a 100; nunca tokens, velocidad o volumen sin calidad.",
    "collaboration": "Handoffs, dependencias y compromisos útiles cumplidos / compromisos acordados.",
    "evidence": "Afirmaciones comprobadas por revisión independiente / afirmaciones y resultados exigidos, incluidos negativos."
  },
  "aggregation": "Media de entregables únicos dentro de un grupo comparable; no suma de actividad.",
  "missing_data": "Sin evaluar: score=null y rank=null; ausencia de datos no equivale a cero.",
  "confidence": "Descriptiva, no probabilidad: baja <3 muestras; media 3–9; alta ≥10 con ≥2 revisores independientes.",
  "comparison": "Ranking sólo dentro del mismo comparison_group; funciones y dificultad no comparables no se ordenan juntas.",
  "anti_gaming": [
    "Criterios, presupuesto y grupo fijados antes de revisar; no autoevaluación ni revisión por cadena de mando.",
    "No premiar volumen, ocultar fallos, omitir criterios, manipular denominadores ni castigar reportes honestos de errores.",
    "No se infiere calidad desde persona, CV, títulos, modelo, coste o nombre de agente.",
    "Las revisiones incluyen resultados negativos y conflictos; evidencia registrada no implica ejecución verificada por la app."
  ],
  "promotion": {
    "minimum_samples": 5,
    "minimum_score": 85,
    "quality_floor": 80,
    "compliance_floor": 90,
    "evidence_floor": 90,
    "approval": "Supervisor revisa y Owner aprueba; independencia adicional ante conflicto.",
    "types": [
      "recognition",
      "promotion",
      "succession"
    ],
    "automatic": false,
    "permissions_changed": false,
    "runtime_changed": false
  },
  "learning": "Aprendizaje operativo: feedback y skills/checklists versionados con fallo demostrado y retest; sin entrenamiento de pesos.",
  "runtime_enforced": false
}
```
