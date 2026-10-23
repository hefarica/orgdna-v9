"""seeds_reconciled.py - roster reconciliado P4-A: 32 existentes + 10 gaps.

GENERADO por tools/generate_seeds_reconciled.py a partir de engine/dna.py.
Los 32 existentes conservan su nombre y rol; su destino se infiere de su
propio texto; los que no tienen codigo quedan con destino administrativo .md
(Opcion A). NO se edita a mano: se regenera.
"""
from __future__ import annotations

from typing import Tuple

if __package__:
    from .seeds_gaps import GAPS, Seed
else:
    from seeds_gaps import GAPS, Seed


EXISTING: Tuple[Seed, ...] = (
    Seed('CEO', 'CEO · Dirección de entrega', 'Transformar objetivos del Owner en un plan comprobable, una organización sostenible y decisiones trazables.',
         ('.css', '.htm', '.html', '.ico', '.jpeg', '.jpg'), 'design_systems_pack', ('destino_declarado', 'cubre:design_systems', 'cubre:security_auditor')),
    Seed('CTO', 'Liderazgo de ingeniería de producto', 'Entregar incrementos verticales coherentes y supervisar la calidad técnica sin sustituir la revisión independiente.',
         ('.20260517t144000z', '.backup', '.bak', '.base', '.cfg', '.conf'), 'config_engineer_pack', ('destino_declarado', 'cubre:config_engineer', 'cubre:design_systems')),
    Seed('ASSURANCE', 'Dirección de revisión independiente', 'Buscar contraejemplos y verificar afirmaciones sobre un candidato que no haya producido.',
         ('.css', '.htm', '.html', '.ico', '.jpeg', '.jpg'), 'design_systems_pack', ('destino_declarado', 'cubre:design_systems', 'cubre:risk_sizing_engineer')),
    Seed('ARCHITECTURE', 'CTO · Dirección de ingeniería y arquitectura', 'Diseñar fronteras, estados e invariantes que conserven significado desde requisitos hasta operación.',
         ('.20260517t144000z', '.backup', '.bak', '.base', '.cfg', '.conf'), 'config_engineer_pack', ('destino_declarado', 'cubre:config_engineer', 'cubre:typescript_engineer')),
    Seed('BACKEND', 'Ingeniería de servicios backend', 'Construir servicios observables, idempotentes y seguros ante concurrencia, errores y reintentos.',
         ('.ts', '.tsx'), 'typescript_engineer_pack', ('destino_declarado', 'cubre:typescript_engineer')),
    Seed('FRONTEND', 'Ingeniería de interfaz y accesibilidad', 'Hacer que cada control visible tenga efecto verificable y que estados, errores y accesibilidad sean comprensibles.',
         ('.css', '.htm', '.html', '.ico', '.jpeg', '.jpg'), 'design_systems_pack', ('destino_declarado', 'cubre:design_systems')),
    Seed('DATA', 'Ingeniería de datos y persistencia', 'Conservar exactitud, procedencia y reversibilidad de datos durante captura, transformación y almacenamiento.',
         ('.csv', '.ddl', '.dml', '.jsonl', '.log', '.sql'), 'data_engineer_pack', ('destino_declarado', 'cubre:data_engineer')),
    Seed('INTEGRATION', 'Ingeniería de integraciones', 'Probar contratos con sistemas externos sin asumir disponibilidad, permisos ni semántica por el nombre de una herramienta.',
         ('.rs', '.sol', '.ts', '.tsx'), 'rust_engineer_pack', ('destino_declarado', 'cubre:rust_engineer', 'cubre:solidity_engineer')),
    Seed('QUANT', 'Investigación cuantitativa y validación matemática', 'Comprobar fórmulas, unidades, costes y supuestos con un oráculo independiente y datos trazables.',
         ('.csv', '.ddl', '.dml', '.jsonl', '.log', '.sql'), 'data_engineer_pack', ('destino_declarado', 'cubre:data_engineer', 'cubre:mev_engineer')),
    Seed('CONTRACTS', 'Ingeniería de contratos y transacciones', 'Verificar contratos, transiciones y atomicidad sin convertir una simulación exitosa en autorización para operar.',
         ('.sha256',), 'security_auditor_pack', ('destino_declarado', 'cubre:security_auditor')),
    Seed('SECURITY', 'Auditoría de seguridad y confianza', 'Identificar exposición de secretos, permisos indebidos e instrucciones no confiables antes de promover un cambio.',
         ('.sha256',), 'security_auditor_pack', ('destino_declarado', 'cubre:security_auditor')),
    Seed('QA', 'Dirección de aseguramiento y calidad', 'Traducir requisitos en cobertura de pruebas y demostrar que los recorridos importantes cumplen su contrato.',
         ('.css', '.htm', '.html', '.ico', '.jpeg', '.jpg'), 'design_systems_pack', ('destino_declarado', 'cubre:design_systems', 'cubre:qa_test_engineer')),
    Seed('PERFORMANCE', 'Ingeniería de rendimiento y capacidad', 'Medir latencia, capacidad y coste bajo cargas comparables y presupuestos explícitos.',
         ('.yaml', '.yml'), 'ci_engineer_pack', ('destino_declarado', 'cubre:ci_engineer', 'cubre:risk_sizing_engineer')),
    Seed('SRE', 'Ingeniería de fiabilidad y operación', 'Verificar que el sistema desplegado conserva disponibilidad semántica y puede recuperarse de fallos.',
         ('.yaml', '.yml'), 'ci_engineer_pack', ('destino_declarado', 'cubre:ci_engineer')),
    Seed('RELEASE', 'Gestión de integración y publicación', 'Integrar y publicar únicamente el candidato validado cuando exista autorización explícita y reversible.',
         ('.yaml', '.yml'), 'ci_engineer_pack', ('destino_declarado', 'cubre:ci_engineer')),
    Seed('LEDGER', 'Auditoría de conciliación y valor', 'Reconstruir resultados a partir de eventos y costes verificables, conservando pérdidas y diferencias no resueltas.',
         ('.sha256',), 'risk_sizing_engineer_pack', ('destino_declarado', 'cubre:risk_sizing_engineer', 'cubre:security_auditor')),
    Seed('GRAPH', 'Ingeniería de grafos y búsqueda', 'Verificar que búsqueda, poda y ranking conservan soluciones válidas bajo cambios de datos y presupuesto.',
         ('.20260517t144000z', '.backup', '.bak', '.base', '.cfg', '.conf'), 'config_engineer_pack', ('destino_declarado', 'cubre:config_engineer', 'cubre:data_engineer')),
    Seed('MARKET', 'Investigación de sistemas y escenarios', 'Modelar condiciones externas, escenarios adversos y límites del dominio sin fabricar resultados económicos.',
         ('.rs',), 'risk_sizing_engineer_pack', ('destino_declarado', 'cubre:risk_sizing_engineer', 'cubre:rust_engineer')),
    Seed('AI', 'Ingeniería de agentes y evaluaciones', 'Diseñar herramientas, evaluaciones y habilidades versionadas con autoridad acotada y trazabilidad.',
         ('.css', '.htm', '.html', '.ico', '.jpeg', '.jpg'), 'design_systems_pack', ('destino_declarado', 'cubre:design_systems')),
    Seed('SPEC', 'Ingeniería de especificación y trazabilidad', 'Mantener una fuente de verdad coherente entre intención, requisitos, implementación y evidencia.',
         ('.md', '.mdx', '.pdf', '.rst', '.sha256', '.txt'), 'docs_engineer_pack', ('destino_declarado', 'cubre:docs_engineer', 'cubre:security_auditor')),
    Seed('OWNEROPS', 'Dirección de operaciones y mandatos', 'Convertir solicitudes del propietario en mandatos inequívocos y detectar decisiones que requieren su aprobación.',
         ('.css', '.htm', '.html', '.ico', '.jpeg', '.jpg'), 'design_systems_pack', ('destino_declarado', 'cubre:design_systems')),
    Seed('E2E', 'Ingeniería de navegador y recorridos E2E', 'Verificar journeys de usuario con navegador aislado, datos controlados y evidencia suficiente para reproducir.',
         ('.css', '.csv', '.ddl', '.dml', '.htm', '.html'), 'data_engineer_pack', ('destino_declarado', 'cubre:data_engineer', 'cubre:design_systems')),
    Seed('PARITY', 'Ingeniería de paridad y compatibilidad', 'Demostrar similitudes y diferencias entre modos, versiones y entornos sin confundir mock con capacidad real.',
         ('.ts', '.tsx'), 'qa_test_engineer_pack', ('destino_declarado', 'cubre:qa_test_engineer', 'cubre:typescript_engineer')),
    Seed('EVIDENCE', 'Auditoría final de evidencia', 'Auditar integridad, suficiencia e independencia de la evidencia sin certificar producción propia.',
         ('.sha256',), 'security_auditor_pack', ('destino_declarado', 'cubre:security_auditor')),
    Seed('UX', 'Investigación de experiencia de usuario', 'Verificar claridad y esfuerzo de los recorridos con criterios observables.',
         ('.css', '.htm', '.html', '.ico', '.jpeg', '.jpg'), 'design_systems_pack', ('destino_declarado', 'cubre:design_systems')),
    Seed('PRIVACY', 'Ingeniería de privacidad', 'Reducir exposición de datos y comprobar minimización, retención y acceso.',
         ('.csv', '.ddl', '.dml', '.jsonl', '.log', '.sha256'), 'data_engineer_pack', ('destino_declarado', 'cubre:data_engineer', 'cubre:security_auditor')),
    Seed('MOBILE', 'Ingeniería móvil y dispositivos', 'Asegurar uso coherente en dispositivos y condiciones de red variables.',
         ('.css', '.htm', '.html', '.ico', '.jpeg', '.jpg'), 'design_systems_pack', ('destino_declarado', 'cubre:design_systems')),
    Seed('SEARCH', 'Ingeniería de búsqueda y recuperación', 'Medir precisión y cobertura de recuperación con conjuntos de evaluación.',
         ('.csv', '.ddl', '.dml', '.jsonl', '.log', '.sql'), 'data_engineer_pack', ('destino_declarado', 'cubre:data_engineer', 'cubre:qa_test_engineer')),
    Seed('BUILD', 'Ingeniería de compilación y dependencias', 'Hacer builds reproducibles y cadenas de dependencias inspeccionables.',
         ('.sha256',), 'security_auditor_pack', ('destino_declarado', 'cubre:security_auditor')),
    Seed('DOCS', 'Ingeniería de documentación y soporte', 'Hacer que instalación, uso y recuperación sean reproducibles por otra persona.',
         ('.css', '.htm', '.html', '.ico', '.jpeg', '.jpg'), 'design_systems_pack', ('destino_declarado', 'cubre:design_systems', 'cubre:docs_engineer')),
    Seed('CHAOS', 'Ingeniería de resiliencia y fallos', 'Explorar fallos controlados en entornos autorizados y verificar recuperación.',
         ('.md',), 'qa_test_engineer_pack', ('destino_declarado', 'cubre:qa_test_engineer')),
    Seed('COST', 'Ingeniería de costes y sostenibilidad', 'Medir coste técnico por resultado útil con presupuestos explícitos.',
         ('.sha256',), 'risk_sizing_engineer_pack', ('destino_declarado', 'cubre:risk_sizing_engineer', 'cubre:security_auditor')),
)


ROLE_SEEDS_RECONCILED: Tuple[Seed, ...] = EXISTING + GAPS

assert len(ROLE_SEEDS_RECONCILED) == 42, len(ROLE_SEEDS_RECONCILED)
assert len({s.name for s in ROLE_SEEDS_RECONCILED}) == 42, "duplicados"

if __name__ == "__main__":
    sin_destino = [s.name for s in ROLE_SEEDS_RECONCILED if not s.destination]
    print("OK seeds_reconciled: %d seeds, %d sin destino"
          % (len(ROLE_SEEDS_RECONCILED), len(sin_destino)))
