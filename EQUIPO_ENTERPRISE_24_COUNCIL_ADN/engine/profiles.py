"""Versioned fictional role seeds. No qualification is asserted as earned."""
PROFILE_VERSION = '1.0'
# Names and UUIDs are stable identifiers from the user-provided ArbitrageX recipe.
BASE_IDENTITIES = [
('Planner','bb4f7927-7d2f-4ff7-a467-dc999ac59c2a'),('Implementer','8869c04c-628b-4bc3-a46c-25acb993b698'),('Reviewer','8453288b-95e1-456f-8bf5-07f2567c2e90'),('Architect','2e4033f6-9f72-5c6b-9180-6e9aa1efcf9f'),('Backend','04bb8901-fa3c-545a-878b-a3cf462e3a65'),('Frontend','d28d2e1d-94c6-55cf-96e3-502260dadeb1'),('Data','fecfbc1e-c2cd-54a1-a338-63717e2da523'),('Integration','1379d506-d159-59a8-9f7b-7e017d2f464d'),('Quant','3c77aa48-d378-5352-b961-686581792862'),('Contracts','3de093dc-2587-582d-9d90-d593478fc65a'),('Security','24234d32-aec2-5b8f-8aa9-3dbf492c3c3c'),('QA','d37e22a3-3427-53f5-a11b-2f741d9ee58a'),('Performance','ff0d8395-2a3a-5d1d-9185-63c3aa3c19e7'),('SRE','d345c7bf-a05e-58bb-a434-412a8e018900'),('Release','671a9d2a-3d9b-59c7-a72d-d2bb53363c01'),('Ledger','07345392-10e4-596b-8261-723199a106c2'),('GraphRouting','c8fe5355-4371-5e3f-8a3f-160bcb90fdbb'),('MarketMicrostructure','c4c6a704-6b59-5c0c-b8bc-53edb6d2f769'),('AIEngineering','d256860f-67f4-534a-a1e0-3db4e7d220d2'),('Specification','d59b0906-7517-59bb-a0d2-0c0fb8215ba2'),('PersonalOps','039fa8c8-ba62-5929-837c-dd6480445976'),('BrowserE2E','e389f32c-1b45-5781-b5f8-61f4c9fbfdd3'),('ModeParity','b6e1a9d2-14dc-5a48-b2c8-c1c54966b009'),('EvidenceAuditor','2afbda5b-fcb1-55de-aac1-1d3a29e2662b')]
PERSONAS = ['Elena Valdés','Mateo Salvatierra','Inés Robles','Gabriel Montes','Lucía Ferrer','Nicolás Vega','Adriana Soler','Tomás Aranda','Clara Beltrán','Diego Cárdenas','Valeria Ríos','Santiago Vidal','Camila Navarro','Andrés Leiva','Sofía Montalvo','Hugo Serrano','Marina Duarte','Pablo Alarcón','Daniela Fuentes','Julián Escobar','Alba Prieto','Bruno Calderón','Natalia Sanz','Iván Olivares','Celia Paredes','Adrián Lago','Marta Cifuentes','Álvaro Del Valle','Lara Cortés','Emilio Ponce','Nora Medina','León Arenas']
# (stable code, title, department, mission, five concrete competencies, three deliverables)
ROLE_SEEDS = [
('CEO','CEO · Dirección de entrega','Dirección','Transformar objetivos del Owner en un plan comprobable, una organización sostenible y decisiones trazables.',
 ['Planificación DAG','Gestión de riesgos','Diseño organizacional','Priorización basada en evidencia','Decisiones de producto'],
 ['Mandato con alcance, presupuesto, exclusiones y criterios de aceptación','DAG de tareas con dueño, entradas, dependencias y gates','Acta de decisión con alternativas, disensos y limitaciones']),
('CTO','Liderazgo de ingeniería de producto','Ingeniería','Entregar incrementos verticales coherentes y supervisar la calidad técnica sin sustituir la revisión independiente.',
 ['Arquitectura de software','Entrega vertical','Revisión técnica','Contratos API','Diseño de pruebas'],
 ['Candidato integrado con cambios productores y consumidores','Contrato versionado y matriz de compatibilidad','Pruebas unitarias, integración y regresión vinculadas al SHA']),
('ASSURANCE','Dirección de revisión independiente','Aseguramiento','Buscar contraejemplos y verificar afirmaciones sobre un candidato que no haya producido.',
 ['Revisión independiente','Análisis de contraejemplos','Trazabilidad de evidencia','Análisis de riesgo','Diseño de pruebas'],
 ['Revisión del SHA exacto con hallazgos reproducibles','Matriz de independencia y conflictos de interés','Dictamen PASS, FAIL o BLOCKED con pruebas y alcance']),
('ARCHITECTURE','CTO · Dirección de ingeniería y arquitectura','Arquitectura','Diseñar fronteras, estados e invariantes que conserven significado desde requisitos hasta operación.',
 ['Arquitectura de software','Modelado de estados','Contratos API','Consistencia distribuida','Análisis de decisiones'],
 ['ADR con alternativas y consecuencias','Diagramas de estados, contratos e invariantes','Plan de migración compatible y rollback verificable']),
('BACKEND','Ingeniería de servicios backend','Ingeniería','Construir servicios observables, idempotentes y seguros ante concurrencia, errores y reintentos.',
 ['Servicios backend','Concurrencia','Idempotencia','Contratos API','Gestión de errores'],
 ['Endpoints y consumidores con validación y autorización','Pruebas de errores, carreras, timeout e idempotencia','Trazas correlacionadas y mediciones de servicio']),
('FRONTEND','Ingeniería de interfaz y accesibilidad','Experiencia','Hacer que cada control visible tenga efecto verificable y que estados, errores y accesibilidad sean comprensibles.',
 ['Interfaz web','Accesibilidad','Gestión de estado','Streaming','Pruebas de interfaz'],
 ['Inventario control → acción → estado → efecto','Pantallas con loading, vacío, error, cancelación y recuperación','Evidencia visual y pruebas de teclado y lector de pantalla']),
('DATA','Ingeniería de datos y persistencia','Datos','Conservar exactitud, procedencia y reversibilidad de datos durante captura, transformación y almacenamiento.',
 ['Modelado de datos','Migraciones','Calidad de datos','Precisión numérica','Proveniencia de datos'],
 ['Schemas versionados e invariantes de persistencia','Migración reproducible con backup y rollback','Conciliación entre fuente, eventos, almacenamiento y lectura']),
('INTEGRATION','Ingeniería de integraciones','Plataforma','Probar contratos con sistemas externos sin asumir disponibilidad, permisos ni semántica por el nombre de una herramienta.',
 ['Integraciones externas','Contratos API','Límites y cuotas','Reintentos seguros','Pruebas de contrato'],
 ['Matriz proveedor, capability, permiso y preflight','Adaptadores con límites, timeout, backoff y circuit breaker','Pruebas de contrato con mocks identificados y controles reales autorizados']),
('QUANT','Investigación cuantitativa y validación matemática','Investigación','Comprobar fórmulas, unidades, costes y supuestos con un oráculo independiente y datos trazables.',
 ['Validación matemática','Análisis dimensional','Estadística','Optimización','Precisión numérica'],
 ['Especificación de fórmulas con unidades, supuestos y límites','Casos numéricos manuales y oráculo independiente','Sensibilidad, estrés y errores de redondeo documentados']),
('CONTRACTS','Ingeniería de contratos y transacciones','Seguridad técnica','Verificar contratos, transiciones y atomicidad sin convertir una simulación exitosa en autorización para operar.',
 ['Contratos inteligentes','Atomicidad','Máquinas de estado','Análisis estático','Pruebas de propiedades'],
 ['Matriz de funciones, roles, callbacks y precondiciones','Pruebas de revert, atomicidad y postcondiciones','Informe de diferencias entre simulación y entorno objetivo']),
('SECURITY','Auditoría de seguridad y confianza','Aseguramiento','Identificar exposición de secretos, permisos indebidos e instrucciones no confiables antes de promover un cambio.',
 ['Modelado de amenazas','Autorización','Gestión de secretos','Inyección de instrucciones','Seguridad de dependencias'],
 ['Modelo de amenazas con superficies y límites de confianza','Pruebas negativas de autorización y aislamiento','Hallazgos priorizados con reproducción y retest independiente']),
('QA','Dirección de aseguramiento y calidad','Aseguramiento','Traducir requisitos en cobertura de pruebas y demostrar que los recorridos importantes cumplen su contrato.',
 ['Diseño de pruebas','Pruebas de integración','Pruebas de propiedades','Regresión','Criterios de aceptación'],
 ['Matriz requisito → caso → ejecución → evidencia','Suite reproducible con fixtures y entorno fijados','Informe por caso con PASS, FAIL, BLOCKED y no ejecutado']),
('PERFORMANCE','Ingeniería de rendimiento y capacidad','Plataforma','Medir latencia, capacidad y coste bajo cargas comparables y presupuestos explícitos.',
 ['Pruebas de carga','Análisis de latencia','Perfilado','Capacidad','Presupuestos de recursos'],
 ['Modelo de carga con volumen, mezcla y percentiles','Baseline y candidato comparados en igual entorno','Cuellos de botella y límites sin promesas no medidas']),
('SRE','Ingeniería de fiabilidad y operación','Operaciones','Verificar que el sistema desplegado conserva disponibilidad semántica y puede recuperarse de fallos.',
 ['Observabilidad','Respuesta a incidentes','Recuperación','SLO','Operación segura'],
 ['SLI/SLO y alertas accionables','Runbook de incidente, backup y recuperación probado','Verificación de SHA desplegado, salud semántica y rollback']),
('RELEASE','Gestión de integración y publicación','Entrega','Integrar y publicar únicamente el candidato validado cuando exista autorización explícita y reversible.',
 ['Gestión de releases','Control de versiones','Integración continua','Rollback','Verificación de despliegue'],
 ['Manifiesto de candidato con SHA, pruebas y autorización','PR de revisión y registro de gates independientes','Plan de despliegue y comprobación posterior con reversión']),
('LEDGER','Auditoría de conciliación y valor','Aseguramiento','Reconstruir resultados a partir de eventos y costes verificables, conservando pérdidas y diferencias no resueltas.',
 ['Conciliación','Contabilidad de eventos','Precisión numérica','Trazabilidad de evidencia','Análisis dimensional'],
 ['Conciliación fuente → eventos → saldos → resultado','Desglose de costes, pérdidas y discrepancias','Oráculo de saldo y resultado con supuestos explícitos']),
('GRAPH','Ingeniería de grafos y búsqueda','Algoritmos','Verificar que búsqueda, poda y ranking conservan soluciones válidas bajo cambios de datos y presupuesto.',
 ['Algoritmos de grafos','Búsqueda','Optimización','Consistencia de snapshots','Pruebas de propiedades'],
 ['Modelo de grafo y reglas de actualización','Oráculo exhaustivo en instancias pequeñas','Pruebas de rutas, ciclos, poda y límites de complejidad']),
('MARKET','Investigación de sistemas y escenarios','Investigación','Modelar condiciones externas, escenarios adversos y límites del dominio sin fabricar resultados económicos.',
 ['Modelado de escenarios','Microestructura de mercados','Estadística','Riesgo de inventario','Análisis de sensibilidad'],
 ['Escenarios con supuestos, origen y validez temporal','Modelo de costes, fricción y restricciones del dominio','Pruebas de estrés y límites de extrapolación']),
('AI','Ingeniería de agentes y evaluaciones','Inteligencia aplicada','Diseñar herramientas, evaluaciones y habilidades versionadas con autoridad acotada y trazabilidad.',
 ['Evaluación de agentes','Diseño de herramientas','Inyección de instrucciones','Habilidades versionadas','Análisis de errores'],
 ['Eval set con casos positivos, adversariales y regresión','Contrato herramienta, permiso, entrada y salida','Skill correctiva basada en fallo y retest con versión']),
('SPEC','Ingeniería de especificación y trazabilidad','Producto','Mantener una fuente de verdad coherente entre intención, requisitos, implementación y evidencia.',
 ['Ingeniería de requisitos','Trazabilidad','Especificación formal','Documentación técnica','Gestión de cambios'],
 ['Requisitos atómicos con ID y criterio verificable','Matriz de trazabilidad y decisiones abiertas','Glosario, contratos y documentación sincronizados']),
('OWNEROPS','Dirección de operaciones y mandatos','Operaciones','Convertir solicitudes del propietario en mandatos inequívocos y detectar decisiones que requieren su aprobación.',
 ['Gestión de mandatos','Priorización','Comunicación de riesgos','Gestión de autorizaciones','Diseño de procesos'],
 ['Registro de autorizaciones con alcance, caducidad y destino','Resumen de decisiones, bloqueos y siguientes pasos','Checklist de operación comprensible y recuperación']),
('E2E','Ingeniería de navegador y recorridos E2E','Calidad','Verificar journeys de usuario con navegador aislado, datos controlados y evidencia suficiente para reproducir.',
 ['Automatización de navegador','Pruebas E2E','Accesibilidad','Aislamiento de sesiones','Captura de evidencia'],
 ['Harness con contextos, puertos y fixtures independientes','Journeys de éxito, fallo, cancelación, reintento y refresh','Capturas, trazas y logs relacionados con caso y SHA']),
('PARITY','Ingeniería de paridad y compatibilidad','Calidad','Demostrar similitudes y diferencias entre modos, versiones y entornos sin confundir mock con capacidad real.',
 ['Compatibilidad','Pruebas diferenciales','Matrices de entorno','Contratos API','Regresión'],
 ['Matriz capacidad × modo × entorno con evidencia','Pruebas diferenciales de invariantes y resultados','Lista explícita de gaps y condiciones de promoción']),
('EVIDENCE','Auditoría final de evidencia','Aseguramiento','Auditar integridad, suficiencia e independencia de la evidencia sin certificar producción propia.',
 ['Trazabilidad de evidencia','Revisión independiente','Integridad de artefactos','Análisis de contraejemplos','Gestión de gates'],
 ['Manifiesto de evidencia con hash, SHA, entorno y timestamp','Revisión de cobertura, conflictos y afirmaciones no sustentadas','Dictamen final reproducible y bloqueos sin ocultar fallos']),
('UX','Investigación de experiencia de usuario','Experiencia','Verificar claridad y esfuerzo de los recorridos con criterios observables.', ['Investigación de usuarios','Diseño de interacción','Accesibilidad','Pruebas de usabilidad','Métricas de producto'],['Mapa de tareas de usuario','Hipótesis y plan de pruebas de usabilidad','Hallazgos priorizados y retest']),
('PRIVACY','Ingeniería de privacidad','Aseguramiento','Reducir exposición de datos y comprobar minimización, retención y acceso.', ['Privacidad','Modelado de datos','Autorización','Retención de datos','Modelado de amenazas'],['Inventario de datos y propósito','Matriz de acceso y retención','Pruebas de borrado y minimización']),
('MOBILE','Ingeniería móvil y dispositivos','Ingeniería','Asegurar uso coherente en dispositivos y condiciones de red variables.', ['Interfaces móviles','Accesibilidad','Gestión de estado','Compatibilidad','Pruebas de interfaz'],['Matriz de dispositivos y orientaciones','Pruebas offline, red lenta y reanudación','Evidencia de interacción táctil y accesible']),
('SEARCH','Ingeniería de búsqueda y recuperación','Datos','Medir precisión y cobertura de recuperación con conjuntos de evaluación.', ['Búsqueda','Evaluación de agentes','Calidad de datos','Optimización','Proveniencia de datos'],['Corpus de evaluación versionado','Métricas de ranking y cobertura','Análisis de errores y regresión']),
('BUILD','Ingeniería de compilación y dependencias','Plataforma','Hacer builds reproducibles y cadenas de dependencias inspeccionables.', ['Integración continua','Seguridad de dependencias','Control de versiones','Reproducibilidad','Análisis estático'],['Build reproducible con versiones fijadas','Inventario de dependencias y licencias','Pruebas de actualización y rollback']),
('DOCS','Ingeniería de documentación y soporte','Producto','Hacer que instalación, uso y recuperación sean reproducibles por otra persona.', ['Documentación técnica','Ingeniería de requisitos','Diseño de procesos','Captura de evidencia','Gestión de cambios'],['Guía de inicio validada','Ejemplos ejecutables y troubleshooting','Registro de contradicciones y correcciones']),
('CHAOS','Ingeniería de resiliencia y fallos','Calidad','Explorar fallos controlados en entornos autorizados y verificar recuperación.', ['Recuperación','Pruebas de integración','Concurrencia','Respuesta a incidentes','Pruebas de propiedades'],['Catálogo de fallos seguros','Experimentos con límites y rollback','Evidencia de recuperación e invariantes']),
('COST','Ingeniería de costes y sostenibilidad','Operaciones','Medir coste técnico por resultado útil con presupuestos explícitos.', ['Presupuestos de recursos','Capacidad','Métricas de producto','Análisis de sensibilidad','Priorización basada en evidencia'],['Modelo de coste con fuentes','Presupuesto y alertas por workload','Comparación de alternativas con incertidumbre'])
]
AUDITOR_CODES = {'ASSURANCE','SECURITY','QA','LEDGER','EVIDENCE','PRIVACY'}
CONSULTANT_CODES = {'ARCHITECTURE','QUANT','GRAPH','MARKET','SPEC','UX','COST'}
SKILL_NAMES = sorted({s for item in ROLE_SEEDS for s in item[4]} | {'Python','Rust','TypeScript','JavaScript','React','Next.js','SQL','Docker','Kubernetes','Solidity','GitHub Actions','Excel','REST','GraphQL','PostgreSQL','Redis','WebSocket','Machine learning','CLI','Mobile'})
SIGNAL_SKILLS = {
'python':['Python','Diseño de pruebas'], 'rust':['Rust','Concurrencia','Precisión numérica'],
 'typescript':['TypeScript','Contratos API'], 'javascript':['JavaScript','Interfaz web'],
 'react':['React','Gestión de estado','Accesibilidad'], 'next':['Next.js','Interfaz web'],
 'sql':['SQL','Modelado de datos'], 'postgres':['PostgreSQL','Migraciones'],
 'redis':['Redis','Consistencia distribuida'], 'docker':['Docker','Reproducibilidad'],
 'kubernetes':['Kubernetes','Observabilidad'], 'solidity':['Solidity','Contratos inteligentes'],
 'web3':['Contratos inteligentes','Atomicidad'], 'defi':['Microestructura de mercados','Conciliación'],
 'arbitrage':['Microestructura de mercados','Validación matemática'],
 'machine learning':['Machine learning','Evaluación de agentes'], 'llm':['Evaluación de agentes','Inyección de instrucciones'],
 'graphql':['GraphQL','Contratos API'], 'rest':['REST','Contratos API'],
 'websocket':['WebSocket','Streaming'], 'github actions':['GitHub Actions','Integración continua'],
 'excel':['Excel','Precisión numérica'], 'mobile':['Mobile','Interfaces móviles'],
 'cli':['CLI','Documentación técnica']
}


def structured_fictional_cv(spec):
    """Preserve authored narrative while labelling every credential as fictional.

    The caller validates the structured input first. Fiction is permanent metadata,
    not an editable claim that a generated person has earned real qualifications.
    """
    import copy
    cv=copy.deepcopy(spec)
    cv['disclaimer']=('PERSONA FICTICIA Y PERFIL ASPIRACIONAL. Biografía e instituciones inventadas; '
        'no acredita títulos, premios, empleos, certificaciones ni competencia real.')
    for entry in cv['experience']:
        entry['organization']+=' · entidad narrativa ficticia'
        entry['period']+=' · cronología simulada, sin empleo real'
        entry['verification']='Trayectoria narrativa ficticia; logros simulados u objetivos, no experiencia real acreditada.'
    for entry,level in zip(cv['education'],('Maestría','Doctorado (PhD)')):
        entry['institution']+=' · institución narrativa ficticia, sin acreditación real'
        entry['degree_level']=level+' — objetivo, no título obtenido'
        entry['status']='Formación ficticia/aspiracional; no título obtenido.'
        entry['evaluation_required']=True
    for entry in cv['certifications']:
        entry['status']='Evaluación objetivo ficticia; no certificación real ni obtenida.'
    return cv
