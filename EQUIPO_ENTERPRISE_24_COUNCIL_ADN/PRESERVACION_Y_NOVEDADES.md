# Preservación y novedades

Se conserva la función documental de los 42 miembros del ZIP anterior y se regenera el contenido para 24 agentes. El archivo original no se modifica. No se reclama igualdad literal de prompts ni vigencia de defectos históricos.

## Cambios explícitos
- 24 identidades actuales, jerarquía con máximo 3 reportes directos; Owner externo y CEO único.
- Dos formatos principales: recipe v1 y definitions v2; definitions incluye ambos squads con una sola lista global de agentes.
- Nombres nativos basados en fecha UTC y UUID, con hashes de bytes finales en un manifiesto separado; no se duplican aliases históricos como otros JSON principales.
- Tarea Plan Preview específica del repositorio en PLAN_PREVIEW_TAREA.txt; preset y límites reales visibles en IMPORTAR_LEEME.txt, con contexto esencial embebido en prompts y collabNote legales.
- Council de todos los miembros, separado de implementación y de consolidación individual del CEO.
- Prompts bifásicos idénticos para evitar sobrescritura semántica al importar squads que comparten agentes.
- CV ficticios aspiracionales, responsabilidades, journeys, competencias y supervisión por persona.
- Aprendizaje correctivo exige fallo demostrado, retest y doble revisión. Esto reemplaza la promoción automática de skills correctivas del protocolo histórico.
- Modelo por agente y preferencias explícitas; ninguna capacidad se deduce como verificada por el nombre del modelo.
- Catálogo histórico privado sustituido por índice de entregables actuales. No se reutilizan cifras anteriores de pruebas como pruebas actuales.
- Validador Python nuevo, visor offline con DOM textContent, plantilla Excel, motor local y dos guías de skills propuestas.

## Mapeo exacto
- 00_DIRECTRIZ_COMUN.txt → 00_DIRECTRIZ_COMUN.txt (regenerated_for_current_organization)
- 01_PROTOCOLO_DE_COORDINACION.md → 01_PROTOCOLO_DE_COORDINACION.md (regenerated_for_current_organization)
- 02_FUENTES_Y_ALCANCE.md → 02_FUENTES_Y_ALCANCE.md (regenerated_for_current_organization)
- 03_CATALOGO_DOCUMENTAL.json → 03_CATALOGO_DOCUMENTAL.json (regenerated_for_current_organization)
- 04_CONTROL_DE_LONGITUD.txt → 04_CONTROL_DE_LONGITUD.txt (regenerated_for_current_organization)
- 05_ROLES_Y_MISIONES.md → 05_ROLES_Y_MISIONES.md (regenerated_for_current_organization)
- 06_VERIFICACION_DEL_PAQUETE.txt → 06_VERIFICACION_DEL_PAQUETE.txt (regenerated_for_current_organization)
- 07_APRENDIZAJE_Y_HABILIDADES.txt → 07_APRENDIZAJE_Y_HABILIDADES.txt (regenerated_for_current_organization)
- AGENT_TEAM_DEFINITIONS_21.json → agent-team-backup-2026-10-21.json (native_filename_definitions_v2_regenerated_current_organization)
- AGENT_TEAM_RECIPE_21.json → agent-team-recipe-6cfad98c-7b40-43b8-92d7-faf33fb4a3fd.json (native_filename_recipe_v1_regenerated_current_organization)
- COLLAB_NOTE_EQUIPO_21.txt → COLLAB_NOTE_EQUIPO_24.txt (regenerated_for_current_organization)
- DIRECTRIZ_COLABORACION_21.txt → DIRECTRIZ_COLABORACION_24.txt (regenerated_for_current_organization)
- EQUIPO_ENTERPRISE_21_PROMPTS_COMPLETOS.md → EQUIPO_ENTERPRISE_24_PROMPTS_COMPLETOS.md (regenerated_for_current_organization)
- IMPORTAR_LEEME.txt → IMPORTAR_LEEME.txt (regenerated_for_current_organization)
- MANIFIESTO_SHA256.txt → MANIFIESTO_SHA256.txt (regenerated_for_current_organization)
- PRESERVACION_Y_NOVEDADES.md → PRESERVACION_Y_NOVEDADES.md (regenerated_for_current_organization)
- PROMPT_MAESTRO_21.txt → PROMPT_MAESTRO_24.txt (regenerated_for_current_organization)
- RESUMEN_EQUIPO_ENTERPRISE_21.txt → RESUMEN_EQUIPO_ENTERPRISE_24.txt (regenerated_for_current_organization)
- VISOR_DE_PERFILES.html → VISOR_DE_PERFILES.html (regenerated_for_current_organization)
- final_schema_validation_public.json → final_schema_validation_public.json (regenerated_for_current_organization)
- prompts/01_Planner.txt → prompts/01_Planner.txt (regenerated_current_profile)
- prompts/02_Implementer.txt → prompts/05_Implementer.txt (regenerated_current_profile)
- prompts/03_Reviewer.txt → prompts/08_Reviewer.txt (regenerated_current_profile)
- prompts/04_Architect.txt → prompts/02_Architect.txt (regenerated_current_profile)
- prompts/05_Backend.txt → prompts/06_Backend.txt (regenerated_current_profile)
- prompts/06_Frontend.txt → prompts/07_Frontend.txt (regenerated_current_profile)
- prompts/07_Data.txt → prompts/14_Data.txt (regenerated_current_profile)
- prompts/08_Integration.txt → prompts/15_Integration.txt (regenerated_current_profile)
- prompts/09_Quant.txt → prompts/17_Quant.txt (regenerated_current_profile)
- prompts/10_Contracts.txt → prompts/16_Contracts.txt (regenerated_current_profile)
- prompts/11_Security.txt → prompts/09_Security.txt (regenerated_current_profile)
- prompts/12_QA.txt → prompts/03_QA.txt (regenerated_current_profile)
- prompts/13_Performance.txt → prompts/24_Performance.txt (regenerated_current_profile)
- prompts/14_SRE.txt → prompts/11_SRE.txt (regenerated_current_profile)
- prompts/15_Release.txt → prompts/13_Release.txt (regenerated_current_profile)
- prompts/16_Ledger.txt → prompts/12_Ledger.txt (regenerated_current_profile)
- prompts/17_GraphRouting.txt → prompts/18_GraphRouting.txt (regenerated_current_profile)
- prompts/18_MarketMicrostructure.txt → prompts/19_MarketMicrostructure.txt (regenerated_current_profile)
- prompts/19_AIEngineering.txt → prompts/22_AIEngineering.txt (regenerated_current_profile)
- prompts/20_Specification.txt → prompts/23_Specification.txt (regenerated_current_profile)
- prompts/21_PersonalOps.txt → prompts/04_PersonalOps.txt (regenerated_current_profile)
- validate_imports_portable.cjs → validate_imports_portable.py (new_standard_library_validator_old_script_not_executed)
