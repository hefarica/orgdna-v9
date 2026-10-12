# Capacitación remedial verificable

Este contrato acompaña ambas skills. No es una clave nativa del recipe DSH ni
un proceso de fine-tuning. El CV y los cargos del paquete son perfiles sintéticos;
no acreditan empleo, títulos, experiencia real o capacidades ya demostradas.

1. **Fallo observado.** Registra failure ID, requisito/caso, entorno, candidato,
   evidence IDs y el resultado esperado/real. Separa fallo del producto de gap
   del agente. Una prueba bloqueada por acceso no demuestra incompetencia.
2. **Gap específico.** Identifica decisión o técnica insuficiente y su alcance.
   El supervisor documenta hipótesis alternativas: requisito ambiguo, herramienta
   ausente o fixture defectuoso. No alteres todo el rol por un único caso.
3. **Skill candidata.** Crea una nueva versión propuesta con entrada/salida,
   triggers/exclusiones, procedimiento, negativos, baseline y criterio medible.
   Conserva la versión vigente y un diff. No cambies el ID estable del agente.
4. **Ensayo aislado.** El aprendiz ejecuta una tarea representativa sin datos
   sensibles ni efectos externos no autorizados. Registra errores y resultados
   reales. Ensayar leyendo la solución no prueba transferencia de habilidad.
5. **Retest independiente.** Un supervisor evaluador distinto del autor de la
   solución y del aprendiz usa casos reservados, al menos un positivo y un negativo relevante,
   su propio oráculo, y la versión exacta. No recibe la respuesta esperada como
   parte del prompt del aprendiz. Registra IDs de autor, aprendiz y evaluador,
   conflictos de interés, decisión y evidencia. Si no hay evaluador independiente
   o evidencia accesible, estado BLOCKED; nunca «aprobado por consenso».
6. **Promoción de versión.** Promueve sólo dentro de la autoridad delegada cuando
   los criterios predefinidos pasan y no hay regresiones obligatorias abiertas.
   Registra versión previa/nueva, hashes, aprobador, fecha y resultados. Si el
   cambio modifica definiciones compartidas en DSH, revisa preview/affectedSquads
   y autorización antes de merge; no lo apliques como parte del ensayo.
7. **Seguimiento y rollback.** Un fallo posterior conserva el historial, revoca
   la afirmación afectada y abre una nueva iteración. Vuelve a la versión previa
   cuando el cambio es la causa y esa reversión esté autorizada.

Estados recomendados del registro local: PROPOSED → PRACTICING → AWAITING_RETEST
→ PROMOTED, con FAILED/BLOCKED/RETIRED según evidencia. Ningún estado equivale
a una certificación profesional ni garantiza desempeño fuera del conjunto probado.

Campos mínimos: training_id, failure_id, skill_name, from_version, to_version,
learner_id, author_id, evaluator_id, acceptance_criteria, practice_evidence_ids,
retest_evidence_ids, decision, approved_by, timestamp_utc. Guarda datos reales
o null cuando estén pendientes; no rellenes resultados ficticios como ejecutados.

El schema de evidencia sólo valida estructura. Para un gate obligatorio, revisa
que existan los artefactos y que coincidan sus hashes, que todos los requisitos
estén cubiertos por el mismo candidato/configuración, que el método observado
cubra la capacidad pedida, y que autor, aprendiz y evaluador cumplan independencia.
Un PASS aislado o un JSON válido no autorizan promoción. Las aprobaciones y la
versión anterior/nueva deben enlazarse al registro completo y a sus hashes.
