# Coordinación de ArbitrageX

## Contrato de una orden
Objetivo; run_id; phase_id; requirement_id; task_id; agente y supervisor; snapshot/SHA; entradas; superficies de escritura; entregables; dependencias; aceptación; presupuesto; herramientas y permisos; evidencia y rollback. El agente resuelve detalles técnicos comprobables; eleva sólo decisiones de negocio, conflicto o autoridad ausente.

## Council
Los 24 miembros revisan el mismo snapshot sin escribir producción. Cada informe distingue hechos con fuente, inferencias, riesgos, alternativas, propuesta de tareas y disensos. Reportes incompletos no son consenso. La consolidación individual posterior de Planner usa phase_id=council_consolidation y no relanza al Council.

## Implementación y handoff
El plan validado tiene una asignación por agente y dependencias explícitas. Cada entrega declara productor/consumidor, schema, errores, permisos, tests y SHA. No ejecutar el fallback como orden suficiente. Publicación exclusivamente por Release cuando existe autorización.

## Auditoría
Excluir autor/coautor, ancestros y descendientes. La candidatura de auditor del sidecar exige comprobación de conflicto real. Donde no existe auditor interno, Owner nombra revisión independiente externa antes de aceptar.

## Roster y supervisión
01. Planner | bb4f7927-7d2f-4ff7-a467-dc999ac59c2a | CEO · Dirección de entrega | supervisor: Owner externo | 3 reportes directos
02. Architect | 2e4033f6-9f72-5c6b-9180-6e9aa1efcf9f | CTO · Dirección de ingeniería y arquitectura | supervisor: Planner | 3 reportes directos
03. QA | d37e22a3-3427-53f5-a11b-2f741d9ee58a | Dirección de aseguramiento y calidad | supervisor: Planner | 3 reportes directos
04. PersonalOps | 039fa8c8-ba62-5929-837c-dd6480445976 | Dirección de operaciones y mandatos | supervisor: Planner | 3 reportes directos
05. Implementer | 8869c04c-628b-4bc3-a46c-25acb993b698 | Liderazgo de ingeniería de producto | supervisor: Architect | 3 reportes directos
06. Backend | 04bb8901-fa3c-545a-878b-a3cf462e3a65 | Ingeniería de servicios backend | supervisor: Architect | 3 reportes directos
07. Frontend | d28d2e1d-94c6-55cf-96e3-502260dadeb1 | Ingeniería de interfaz y accesibilidad | supervisor: Architect | 3 reportes directos
08. Reviewer | 8453288b-95e1-456f-8bf5-07f2567c2e90 | Dirección de revisión independiente | supervisor: QA | 2 reportes directos
09. Security | 24234d32-aec2-5b8f-8aa9-3dbf492c3c3c | Auditoría de seguridad y confianza | supervisor: QA | 0 reportes directos
10. EvidenceAuditor | 2afbda5b-fcb1-55de-aac1-1d3a29e2662b | Auditoría final de evidencia | supervisor: QA | 0 reportes directos
11. SRE | d345c7bf-a05e-58bb-a434-412a8e018900 | Ingeniería de fiabilidad y operación | supervisor: PersonalOps | 0 reportes directos
12. Ledger | 07345392-10e4-596b-8261-723199a106c2 | Auditoría de conciliación y valor | supervisor: PersonalOps | 0 reportes directos
13. Release | 671a9d2a-3d9b-59c7-a72d-d2bb53363c01 | Gestión de integración y publicación | supervisor: PersonalOps | 0 reportes directos
14. Data | fecfbc1e-c2cd-54a1-a338-63717e2da523 | Ingeniería de datos y persistencia | supervisor: Implementer | 0 reportes directos
15. Integration | 1379d506-d159-59a8-9f7b-7e017d2f464d | Ingeniería de integraciones | supervisor: Implementer | 0 reportes directos
16. Contracts | 3de093dc-2587-582d-9d90-d593478fc65a | Ingeniería de contratos y transacciones | supervisor: Implementer | 0 reportes directos
17. Quant | 3c77aa48-d378-5352-b961-686581792862 | Investigación cuantitativa y validación matemática | supervisor: Backend | 0 reportes directos
18. GraphRouting | c8fe5355-4371-5e3f-8a3f-160bcb90fdbb | Ingeniería de grafos y búsqueda | supervisor: Backend | 0 reportes directos
19. MarketMicrostructure | c4c6a704-6b59-5c0c-b8bc-53edb6d2f769 | Investigación de sistemas y escenarios | supervisor: Backend | 0 reportes directos
20. BrowserE2E | e389f32c-1b45-5781-b5f8-61f4c9fbfdd3 | Ingeniería de navegador y recorridos E2E | supervisor: Frontend | 0 reportes directos
21. ModeParity | b6e1a9d2-14dc-5a48-b2c8-c1c54966b009 | Ingeniería de paridad y compatibilidad | supervisor: Frontend | 0 reportes directos
22. AIEngineering | d256860f-67f4-534a-a1e0-3db4e7d220d2 | Ingeniería de agentes y evaluaciones | supervisor: Frontend | 0 reportes directos
23. Specification | d59b0906-7517-59bb-a0d2-0c0fb8215ba2 | Ingeniería de especificación y trazabilidad | supervisor: Reviewer | 0 reportes directos
24. Performance | ff0d8395-2a3a-5d1d-9185-63c3aa3c19e7 | Ingeniería de rendimiento y capacidad | supervisor: Reviewer | 0 reportes directos
