# Herramientas y permisos por perfil

El catálogo aportado contiene 271 nombres únicos exactos. Se entrega completo en `engine/tool_catalog.json`, con descripciones, riesgo orientativo, roles candidatos y procedencia. Las descripciones no son instrucciones: ninguna herramienta se ejecutó para clasificarlas. Su presencia en el catálogo no demuestra que esté instalada o visible en tu sesión.

Brecha importante: este catálogo no acredita editor de archivos, terminal general, navegador E2E ni cargador de skills. Una allowlist es restrictiva sobre TODO el conjunto visible, también herramientas fuera de este catálogo; puede impedir implementar o probar un proyecto aunque el perfil tenga el nombre Backend, Frontend o BrowserE2E. Si faltan estas capacidades, BLOCKED hasta conocer los nombres registrados y el permiso real. La edición manual admite nombres externos exactos declarados por el usuario, siempre marcados como no verificados, sin inventarlos ni agregarlos automáticamente. `docs/tool_permission_guide.md` y `docs/tool_role_presets.md` detallan candidatos, riesgos y precondiciones.

## Formato DSH

El campo reconocido es `agents[].toolScope`, singular, dentro de cada agente: `allow` y/o `deny`. Recipe v1 y definitions v2 comparten los mismos agentes, prompts y toolScope. No se añaden claves inventadas de permisos al squad. El exportador respeta el límite de escritura actual: hasta 256 nombres en allow y 256 en deny, únicos después de limpiar espacios, sin solapamiento. No se aceptan arrays vacíos ni un scope vacío. 271 nombres no caben en un único allow; no se trunca la lista ni se usan nombres de skills, comodines o fragmentos como atajo.

Omitir allow significa heredar las herramientas visibles del padre sujetas a las restricciones del host. No significa denegar todo. Deny-only también hereda y puede admitir futuras herramientas. La lista exportada y el modo de cada perfil se conservan en `organizacion/PERMISOS_POR_PERFIL.json`; las recomendaciones quedan separadas del estado aplicado.

## Verificación antes de ejecutar

1. Verificar la versión DSH instalada y los nombres exactos realmente visibles en la sesión padre.
2. Revisar preview y affectedSquads antes del merge autorizado; ambos squads usan las mismas identidades globales.
3. Un nombre allow ausente de la sesión puede producir INVALID_DISPATCH. Corregir el catálogo o la asignación con decisión explícita; no borrarlo silenciosamente ni afirmar que funcionó.
4. Una allowlist filtra nombres. No limita argumentos, destinos, presupuesto, red, modo read-only, sistema de archivos o autoridad para una acción. Shell, ejecución genérica y herramientas de orquestación pueden tener efectos amplios. No se usa run_code como supuesto sandbox universal.
5. Council mantiene contrato de sólo lectura, pero el toolScope común no cambia automáticamente según el squad. No afirmar que la separación de fases impone read-only mediante ACL.

## Competencias y skills

Las competencias del perfil son objetivos evaluables. Las guías `webapp-testing` y `systematic-debugging` son archivos propuestos, no nombres de herramientas ni skills instaladas. `organizacion/MAPA_SKILLS_HERRAMIENTAS.json` relaciona por perfil sus competencias, permisos declarados y candidatos del catálogo, de manera orientativa. No afirma equivalencia funcional ni carga automática.

El cargador `skill` no aparece entre los 271 nombres aportados: queda PENDIENTE, sin añadirlo al allow. Primero comprobar que el host admite ese cargador y registra la skill. Tener permiso para llamar una herramienta, tener una skill instalada y estar autorizado para una acción son comprobaciones diferentes.

Fuentes públicas y restricciones revisadas: `engine/tool_catalog.json`, schema_constraints.source_urls. Esta revisión no identifica tu runtime instalado.

## Listas exactas exportadas

## Planner
ID: bb4f7927-7d2f-4ff7-a467-dc999ac59c2a
Modo: explicit_allow

Allow: ops_plan, ops_status, loop.boot, loop.expand, mem.store, mem.recall, ai.plan, ai.htn, meta.mutate, meta.fitness, evidence_add, research_report, ledger_query, memory_store, memory_recall, memory_stats, visual_mermaid, visual_ascii, agent_teams_status, univer_new, univer_status, univer_worktree, univer_unit, univer_import, univer_inspect, univer_execute, univer_export, univer_lint, univer_print_pdf, univer_compile_svg, univer_api, univer_resources, univer_screenshot, get_pipeline_status, get_job_status, get_phase_description, why_check, why_file, why_find, why_recall

Deny: Ninguna lista deny declarada.

Recomendación orientativa por rol: ops_plan, ops_status, loop.boot, loop.expand, mem.store, mem.recall, ai.plan, ai.htn, meta.mutate, meta.fitness, evidence_add, research_report, ledger_query, memory_store, memory_recall, memory_stats, visual_mermaid, visual_ascii, agent_teams_status, univer_new, univer_status, univer_worktree, univer_unit, univer_import, univer_inspect, univer_execute, univer_export, univer_lint, univer_print_pdf, univer_compile_svg, univer_api, univer_resources, univer_screenshot, get_pipeline_status, get_job_status, get_phase_description, why_check, why_file, why_find, why_recall

## Architect
ID: 2e4033f6-9f72-5c6b-9180-6e9aa1efcf9f
Modo: explicit_allow

Allow: ops_plan, ops_status, grafos.chromatic, grafos.ramsey, logica.satisfiable, logica.eval, cat.limits, cat.adjunction, tipo.check, tipo.universe, espec.dominant, espec.clustering, comp.reduce, comp.param, turing.simular, turing.halt, sem.eval, sem.fixed, alea.lll, alea.derand, sql.schema, sql.plan, idx.store, idx.sub, loop.boot, loop.expand, gn.msgpass, gn.isomorph, ai.plan, ai.htn, ledger_query, visual_mermaid, visual_ascii, dep_graph, dep_impact

Deny: Ninguna lista deny declarada.

Recomendación orientativa por rol: ops_plan, ops_status, grafos.chromatic, grafos.ramsey, logica.satisfiable, logica.eval, cat.limits, cat.adjunction, tipo.check, tipo.universe, espec.dominant, espec.clustering, comp.reduce, comp.param, turing.simular, turing.halt, sem.eval, sem.fixed, alea.lll, alea.derand, sql.schema, sql.plan, idx.store, idx.sub, loop.boot, loop.expand, gn.msgpass, gn.isomorph, ai.plan, ai.htn, ledger_query, visual_mermaid, visual_ascii, dep_graph, dep_impact

## QA
ID: d37e22a3-3427-53f5-a11b-2f741d9ee58a
Modo: explicit_allow

Allow: ops_inspect, ops_diagnose, ops_plan, ops_validate, ops_learn, ops_status, forge_pool, forge_swap, forge_tech, mem.rmw, mem.model, ker.trace, ker.page_fault, net.pkt, net.quic, micro.saga, micro.trace, ws.open, ws.metric, test.prop, test.fuzz, evidence_add, research_report, ledger_query, visual_mermaid, visual_ascii, ci_predict, ci_status, sandbox_rust, sandbox_python, sandbox_js, incremental_check_rust, incremental_check_ts, testforge_rust, testforge_ts

Deny: Ninguna lista deny declarada.

Recomendación orientativa por rol: ops_inspect, ops_diagnose, ops_plan, ops_validate, ops_learn, ops_status, forge_pool, forge_swap, forge_tech, mem.rmw, mem.model, ker.trace, ker.page_fault, net.pkt, net.quic, micro.saga, micro.trace, ws.open, ws.metric, test.prop, test.fuzz, evidence_add, research_report, ledger_query, visual_mermaid, visual_ascii, ci_predict, ci_status, sandbox_rust, sandbox_python, sandbox_js, incremental_check_rust, incremental_check_ts, testforge_rust, testforge_ts

## PersonalOps
ID: 039fa8c8-ba62-5929-837c-dd6480445976
Modo: explicit_allow

Allow: ops_plan, ops_status, mem.store, mem.recall, meta.mutate, meta.fitness, ledger_query, memory_store, memory_recall, memory_stats, visual_mermaid, visual_ascii, agent_teams_status, univer_new, univer_status, univer_worktree, univer_unit, univer_import, univer_inspect, univer_execute, univer_export, univer_lint, univer_print_pdf, univer_compile_svg, univer_api, univer_resources, univer_screenshot

Deny: Ninguna lista deny declarada.

Recomendación orientativa por rol: ops_plan, ops_status, mem.store, mem.recall, meta.mutate, meta.fitness, ledger_query, memory_store, memory_recall, memory_stats, visual_mermaid, visual_ascii, agent_teams_status, univer_new, univer_status, univer_worktree, univer_unit, univer_import, univer_inspect, univer_execute, univer_export, univer_lint, univer_print_pdf, univer_compile_svg, univer_api, univer_resources, univer_screenshot

## Implementer
ID: 8869c04c-628b-4bc3-a46c-25acb993b698
Modo: explicit_allow

Allow: ops_inspect, ops_diagnose, ops_plan, ops_validate, ops_learn, ops_status, ir.passes, ir.registers, test.prop, test.fuzz, ledger_query, visual_mermaid, visual_ascii, ci_predict, ci_status, sandbox_rust, sandbox_python, sandbox_js, incremental_check_rust, incremental_check_ts, dep_graph, dep_impact, testforge_rust, testforge_ts, why_check, why_file, why_find, why_recall

Deny: Ninguna lista deny declarada.

Recomendación orientativa por rol: ops_inspect, ops_diagnose, ops_plan, ops_validate, ops_learn, ops_status, ir.passes, ir.registers, test.prop, test.fuzz, ledger_query, visual_mermaid, visual_ascii, ci_predict, ci_status, sandbox_rust, sandbox_python, sandbox_js, incremental_check_rust, incremental_check_ts, dep_graph, dep_impact, testforge_rust, testforge_ts, why_check, why_file, why_find, why_recall

## Backend
ID: 04bb8901-fa3c-545a-878b-a3cf462e3a65
Modo: explicit_allow

Allow: ops_plan, ops_status, ir.passes, ir.registers, mem.rmw, mem.model, ker.trace, ker.page_fault, net.pkt, net.quic, sql.schema, sql.plan, micro.saga, micro.trace, ws.open, ws.metric, api.route, test.prop, test.fuzz, prof.hotspot, prof.inline, idx.store, idx.sub, tf.kvcache, ledger_query, visual_mermaid, visual_ascii, sql_tables, sandbox_rust, sandbox_python, sandbox_js, incremental_check_rust, incremental_check_ts, dep_graph, dep_impact, testforge_rust, testforge_ts

Deny: Ninguna lista deny declarada.

Recomendación orientativa por rol: ops_plan, ops_status, ir.passes, ir.registers, mem.rmw, mem.model, ker.trace, ker.page_fault, net.pkt, net.quic, sql.schema, sql.plan, micro.saga, micro.trace, ws.open, ws.metric, api.route, test.prop, test.fuzz, prof.hotspot, prof.inline, idx.store, idx.sub, tf.kvcache, ledger_query, visual_mermaid, visual_ascii, sql_tables, sandbox_rust, sandbox_python, sandbox_js, incremental_check_rust, incremental_check_ts, dep_graph, dep_impact, testforge_rust, testforge_ts

## Frontend
ID: d28d2e1d-94c6-55cf-96e3-502260dadeb1
Modo: explicit_allow

Allow: ops_plan, ops_status, ui.compile, ui.island, test.prop, test.fuzz, ledger_query, visual_mermaid, visual_ascii, sandbox_rust, sandbox_python, sandbox_js, incremental_check_rust, incremental_check_ts, testforge_rust, testforge_ts, univer_new, univer_status, univer_worktree, univer_unit, univer_import, univer_inspect, univer_execute, univer_export, univer_lint, univer_print_pdf, univer_compile_svg, univer_api, univer_resources, univer_screenshot

Deny: Ninguna lista deny declarada.

Recomendación orientativa por rol: ops_plan, ops_status, ui.compile, ui.island, test.prop, test.fuzz, ledger_query, visual_mermaid, visual_ascii, sandbox_rust, sandbox_python, sandbox_js, incremental_check_rust, incremental_check_ts, testforge_rust, testforge_ts, univer_new, univer_status, univer_worktree, univer_unit, univer_import, univer_inspect, univer_execute, univer_export, univer_lint, univer_print_pdf, univer_compile_svg, univer_api, univer_resources, univer_screenshot

## Reviewer
ID: 8453288b-95e1-456f-8bf5-07f2567c2e90
Modo: explicit_allow

Allow: ops_plan, ops_status, forge_med, lat.profile, lat.symbolic, test.prop, test.fuzz, evidence_add, research_report, ledger_query, visual_mermaid, visual_ascii, ci_predict, ci_status, sandbox_rust, sandbox_python, sandbox_js, incremental_check_rust, incremental_check_ts, get_pipeline_status, get_job_status, get_phase_description, why_check, why_file, why_find, why_recall

Deny: Ninguna lista deny declarada.

Recomendación orientativa por rol: ops_plan, ops_status, forge_med, lat.profile, lat.symbolic, test.prop, test.fuzz, evidence_add, research_report, ledger_query, visual_mermaid, visual_ascii, ci_predict, ci_status, sandbox_rust, sandbox_python, sandbox_js, incremental_check_rust, incremental_check_ts, get_pipeline_status, get_job_status, get_phase_description, why_check, why_file, why_find, why_recall

## Security
ID: 24234d32-aec2-5b8f-8aa9-3dbf492c3c3c
Modo: explicit_allow

Allow: ops_inspect, ops_diagnose, ops_plan, ops_validate, ops_learn, ops_status, forge_med, espejo.watch, espejo.clan, espejo.pred, guardian.scan, guardian.stale, guardian.gas_spike, guardian.anomalia, logica.satisfiable, logica.eval, cat.limits, cat.adjunction, tipo.check, tipo.universe, turing.simular, turing.halt, sem.eval, sem.fixed, lat.profile, lat.symbolic, api.route, yul.disasm, yul.gas, merkle.proof, accum.add, hash.state, hash.keccak, cons.vote, cons.final, curva.ecdh, curva.pair, priv.mix, priv.probe, zk.prove, zk.verify, enc.ckks, enc.boot, ledger_query, chain_call, chain_balance, chain_block, visual_mermaid, visual_ascii, sql_tables, dep_graph, dep_impact

Deny: Ninguna lista deny declarada.

Recomendación orientativa por rol: ops_inspect, ops_diagnose, ops_plan, ops_validate, ops_learn, ops_status, forge_med, espejo.watch, espejo.clan, espejo.pred, guardian.scan, guardian.stale, guardian.gas_spike, guardian.anomalia, logica.satisfiable, logica.eval, cat.limits, cat.adjunction, tipo.check, tipo.universe, turing.simular, turing.halt, sem.eval, sem.fixed, lat.profile, lat.symbolic, api.route, yul.disasm, yul.gas, merkle.proof, accum.add, hash.state, hash.keccak, cons.vote, cons.final, curva.ecdh, curva.pair, priv.mix, priv.probe, zk.prove, zk.verify, enc.ckks, enc.boot, ledger_query, chain_call, chain_balance, chain_block, visual_mermaid, visual_ascii, sql_tables, dep_graph, dep_impact

## EvidenceAuditor
ID: 2afbda5b-fcb1-55de-aac1-1d3a29e2662b
Modo: explicit_allow

Allow: ops_plan, ops_status, registro.store, registro.pnl, registro.tax, registro.stats, registro.wash, mem.store, mem.recall, meta.mutate, meta.fitness, evidence_add, research_report, ledger_query, memory_store, memory_recall, memory_stats, visual_mermaid, visual_ascii, univer_new, univer_status, univer_worktree, univer_unit, univer_import, univer_inspect, univer_execute, univer_export, univer_lint, univer_print_pdf, univer_compile_svg, univer_api, univer_resources, univer_screenshot, why_check, why_file, why_find, why_recall

Deny: Ninguna lista deny declarada.

Recomendación orientativa por rol: ops_plan, ops_status, registro.store, registro.pnl, registro.tax, registro.stats, registro.wash, mem.store, mem.recall, meta.mutate, meta.fitness, evidence_add, research_report, ledger_query, memory_store, memory_recall, memory_stats, visual_mermaid, visual_ascii, univer_new, univer_status, univer_worktree, univer_unit, univer_import, univer_inspect, univer_execute, univer_export, univer_lint, univer_print_pdf, univer_compile_svg, univer_api, univer_resources, univer_screenshot, why_check, why_file, why_find, why_recall

## SRE
ID: d345c7bf-a05e-58bb-a434-412a8e018900
Modo: explicit_allow

Allow: ops_inspect, ops_diagnose, ops_plan, ops_validate, ops_learn, ops_status, mem.rmw, mem.model, ker.trace, ker.page_fault, net.pkt, net.quic, micro.saga, micro.trace, ws.open, ws.metric, prof.hotspot, prof.inline, tf.kvcache, ledger_query, visual_mermaid, visual_ascii, sql_tables, sandbox_rust, sandbox_python, sandbox_js, incremental_check_rust, incremental_check_ts

Deny: Ninguna lista deny declarada.

Recomendación orientativa por rol: ops_inspect, ops_diagnose, ops_plan, ops_validate, ops_learn, ops_status, mem.rmw, mem.model, ker.trace, ker.page_fault, net.pkt, net.quic, micro.saga, micro.trace, ws.open, ws.metric, prof.hotspot, prof.inline, tf.kvcache, ledger_query, visual_mermaid, visual_ascii, sql_tables, sandbox_rust, sandbox_python, sandbox_js, incremental_check_rust, incremental_check_ts

## Ledger
ID: 07345392-10e4-596b-8261-723199a106c2
Modo: explicit_allow

Allow: ops_plan, ops_status, defi_catalogo, defi_evaluar, defi_riesgo, forge_opt, nodo_scan, red.scan, red.best, faro.consenso, faro.source, faro.clean, registro.store, registro.pnl, registro.tax, registro.stats, registro.wash, espejo.watch, espejo.clan, espejo.pred, guardian.scan, guardian.stale, guardian.gas_spike, guardian.anomalia, puente.scan, puente.latency, bus.status, bus.pause, ora.twap, ora.dev, book.qpos, hawk.fit, mm.quote, mm.risk, vol.price, vol.greeks, int.branch, int.regime, ord.lifecycle, ord.litpool, perp.fund, perp.base, loan.liq, loan.optimal, pf.covariance, pf.turnover, evidence_add, research_report, ledger_query, chain_call, chain_balance, chain_block, visual_mermaid, visual_ascii, sql_tables, strategy_performance, strategy_detail, backtest_run, patterns_temporal, patterns_gas, patterns_tokens, ev_calculate, ev_route_history, univer_new, univer_status, univer_worktree, univer_unit, univer_import, univer_inspect, univer_execute, univer_export, univer_lint, univer_print_pdf, univer_compile_svg, univer_api, univer_resources, univer_screenshot

Deny: Ninguna lista deny declarada.

Recomendación orientativa por rol: ops_plan, ops_status, defi_catalogo, defi_evaluar, defi_riesgo, forge_opt, nodo_scan, red.scan, red.best, faro.consenso, faro.source, faro.clean, registro.store, registro.pnl, registro.tax, registro.stats, registro.wash, espejo.watch, espejo.clan, espejo.pred, guardian.scan, guardian.stale, guardian.gas_spike, guardian.anomalia, puente.scan, puente.latency, bus.status, bus.pause, ora.twap, ora.dev, book.qpos, hawk.fit, mm.quote, mm.risk, vol.price, vol.greeks, int.branch, int.regime, ord.lifecycle, ord.litpool, perp.fund, perp.base, loan.liq, loan.optimal, pf.covariance, pf.turnover, evidence_add, research_report, ledger_query, chain_call, chain_balance, chain_block, visual_mermaid, visual_ascii, sql_tables, strategy_performance, strategy_detail, backtest_run, patterns_temporal, patterns_gas, patterns_tokens, ev_calculate, ev_route_history, univer_new, univer_status, univer_worktree, univer_unit, univer_import, univer_inspect, univer_execute, univer_export, univer_lint, univer_print_pdf, univer_compile_svg, univer_api, univer_resources, univer_screenshot

## Release
ID: 671a9d2a-3d9b-59c7-a72d-d2bb53363c01
Modo: explicit_allow

Allow: ops_inspect, ops_diagnose, ops_plan, ops_validate, ops_learn, ops_status, ledger_query, visual_mermaid, visual_ascii, ci_predict, ci_status, sandbox_rust, sandbox_python, sandbox_js, incremental_check_rust, incremental_check_ts, dep_graph, dep_impact

Deny: Ninguna lista deny declarada.

Recomendación orientativa por rol: ops_inspect, ops_diagnose, ops_plan, ops_validate, ops_learn, ops_status, ledger_query, visual_mermaid, visual_ascii, ci_predict, ci_status, sandbox_rust, sandbox_python, sandbox_js, incremental_check_rust, incremental_check_ts, dep_graph, dep_impact

## Data
ID: fecfbc1e-c2cd-54a1-a338-63717e2da523
Modo: explicit_allow

Allow: ops_plan, ops_status, registro.store, registro.pnl, registro.tax, registro.stats, registro.wash, medida.stop, medida.girsanov, info.capacity, info.code, ecc.encode, ecc.decode, sql.schema, sql.plan, idx.store, idx.sub, nn.init, nn.backward, opt.adamw, opt.mixed, caus.do, caus.counterfactual, caus.instrumental, dream.rollout, dream.plan, rl.train, rl.policy, tf.attn, ledger_query, visual_mermaid, visual_ascii, sql_tables, strategy_performance, strategy_detail, backtest_run, patterns_temporal, patterns_gas, patterns_tokens, ev_route_history

Deny: Ninguna lista deny declarada.

Recomendación orientativa por rol: ops_plan, ops_status, registro.store, registro.pnl, registro.tax, registro.stats, registro.wash, medida.stop, medida.girsanov, info.capacity, info.code, ecc.encode, ecc.decode, sql.schema, sql.plan, idx.store, idx.sub, nn.init, nn.backward, opt.adamw, opt.mixed, caus.do, caus.counterfactual, caus.instrumental, dream.rollout, dream.plan, rl.train, rl.policy, tf.attn, ledger_query, visual_mermaid, visual_ascii, sql_tables, strategy_performance, strategy_detail, backtest_run, patterns_temporal, patterns_gas, patterns_tokens, ev_route_history

## Integration
ID: 1379d506-d159-59a8-9f7b-7e017d2f464d
Modo: explicit_allow

Allow: ops_plan, ops_status, api.route, loop.boot, loop.expand, ai.plan, ai.htn, ledger_query, visual_mermaid, visual_ascii, sandbox_rust, sandbox_python, sandbox_js, incremental_check_rust, incremental_check_ts

Deny: Ninguna lista deny declarada.

Recomendación orientativa por rol: ops_plan, ops_status, api.route, loop.boot, loop.expand, ai.plan, ai.htn, ledger_query, visual_mermaid, visual_ascii, sandbox_rust, sandbox_python, sandbox_js, incremental_check_rust, incremental_check_ts

## Contracts
ID: 3de093dc-2587-582d-9d90-d593478fc65a
Modo: explicit_allow

Allow: ops_plan, ops_status, forge_pool, forge_swap, forge_tech, forge_med, espejo.watch, espejo.clan, espejo.pred, guardian.scan, guardian.stale, guardian.gas_spike, guardian.anomalia, logica.satisfiable, logica.eval, cat.limits, cat.adjunction, tipo.check, tipo.universe, turing.simular, turing.halt, sem.eval, sem.fixed, lat.profile, lat.symbolic, test.prop, test.fuzz, yul.disasm, yul.gas, merkle.proof, accum.add, hash.state, hash.keccak, cons.vote, cons.final, curva.ecdh, curva.pair, priv.mix, priv.probe, zk.prove, zk.verify, enc.ckks, enc.boot, ledger_query, chain_call, chain_balance, chain_block, visual_mermaid, visual_ascii

Deny: Ninguna lista deny declarada.

Recomendación orientativa por rol: ops_plan, ops_status, forge_pool, forge_swap, forge_tech, forge_med, espejo.watch, espejo.clan, espejo.pred, guardian.scan, guardian.stale, guardian.gas_spike, guardian.anomalia, logica.satisfiable, logica.eval, cat.limits, cat.adjunction, tipo.check, tipo.universe, turing.simular, turing.halt, sem.eval, sem.fixed, lat.profile, lat.symbolic, test.prop, test.fuzz, yul.disasm, yul.gas, merkle.proof, accum.add, hash.state, hash.keccak, cons.vote, cons.final, curva.ecdh, curva.pair, priv.mix, priv.probe, zk.prove, zk.verify, enc.ckks, enc.boot, ledger_query, chain_call, chain_balance, chain_block, visual_mermaid, visual_ascii

## Quant
ID: 3c77aa48-d378-5352-b961-686581792862
Modo: explicit_allow

Allow: ops_plan, ops_status, defi_catalogo, defi_evaluar, defi_riesgo, forge_scan, forge_pool, forge_swap, forge_tech, forge_opt, nodo_scan, red.scan, red.best, faro.consenso, faro.source, faro.clean, registro.store, registro.pnl, registro.tax, registro.stats, registro.wash, catalizador.mutate, catalizador.deploy, catalizador.history, simulacro.run, simulacro.walk, puente.scan, puente.latency, bus.status, bus.pause, plano.res, plano.contour, topo.h1, topo.euler, lie.bracket, lie.killing, grafos.chromatic, grafos.ramsey, medida.stop, medida.girsanov, info.capacity, info.code, ecc.encode, ecc.decode, fn.op, fn.spectrum, pde.eigen, pde.green, opt.solve, opt.dual, juego.nash, juego.vickrey, caos.lyap, caos.bifur, geom.gb, geom.curvatura, espec.dominant, espec.clustering, frac.dim, frac.spec, onda.dft, onda.wavelet, campo.beta, campo.anomaly, qc.surface, qc.vqe, opt.squeeze, opt.vis, topo.quantum, topo.boundary, dirac.solucion, majorana.parity, comp.reduce, comp.param, alea.lll, alea.derand, syn.place, syn.timing, gpu.kernel, gpu.roofline, lin.solve, lin.svd, yul.disasm, yul.gas, merkle.proof, accum.add, hash.state, hash.keccak, cons.vote, cons.final, curva.ecdh, curva.pair, ora.twap, ora.dev, book.qpos, hawk.fit, mm.quote, mm.risk, vol.price, vol.greeks, int.branch, int.regime, ord.lifecycle, ord.litpool, perp.fund, perp.base, loan.liq, loan.optimal, pf.covariance, pf.turnover, nn.init, nn.backward, opt.adamw, opt.mixed, gn.msgpass, gn.isomorph, mo.front, mo.knee, caus.do, caus.counterfactual, caus.instrumental, dream.rollout, dream.plan, evo.evolve, swarm.trace, rl.train, rl.policy, priv.mix, priv.probe, bayes.sample, bayes.bandit, tf.attn, zk.prove, zk.verify, enc.ckks, enc.boot, ledger_query, visual_mermaid, visual_ascii, sandbox_rust, sandbox_python, sandbox_js, incremental_check_rust, incremental_check_ts, strategy_performance, strategy_detail, backtest_run, patterns_temporal, patterns_gas, patterns_tokens, ev_calculate, ev_route_history, get_pipeline_status, get_job_status, get_phase_description

Deny: Ninguna lista deny declarada.

Recomendación orientativa por rol: ops_plan, ops_status, defi_catalogo, defi_evaluar, defi_riesgo, forge_scan, forge_pool, forge_swap, forge_tech, forge_opt, nodo_scan, red.scan, red.best, faro.consenso, faro.source, faro.clean, registro.store, registro.pnl, registro.tax, registro.stats, registro.wash, catalizador.mutate, catalizador.deploy, catalizador.history, simulacro.run, simulacro.walk, puente.scan, puente.latency, bus.status, bus.pause, plano.res, plano.contour, topo.h1, topo.euler, lie.bracket, lie.killing, grafos.chromatic, grafos.ramsey, medida.stop, medida.girsanov, info.capacity, info.code, ecc.encode, ecc.decode, fn.op, fn.spectrum, pde.eigen, pde.green, opt.solve, opt.dual, juego.nash, juego.vickrey, caos.lyap, caos.bifur, geom.gb, geom.curvatura, espec.dominant, espec.clustering, frac.dim, frac.spec, onda.dft, onda.wavelet, campo.beta, campo.anomaly, qc.surface, qc.vqe, opt.squeeze, opt.vis, topo.quantum, topo.boundary, dirac.solucion, majorana.parity, comp.reduce, comp.param, alea.lll, alea.derand, syn.place, syn.timing, gpu.kernel, gpu.roofline, lin.solve, lin.svd, yul.disasm, yul.gas, merkle.proof, accum.add, hash.state, hash.keccak, cons.vote, cons.final, curva.ecdh, curva.pair, ora.twap, ora.dev, book.qpos, hawk.fit, mm.quote, mm.risk, vol.price, vol.greeks, int.branch, int.regime, ord.lifecycle, ord.litpool, perp.fund, perp.base, loan.liq, loan.optimal, pf.covariance, pf.turnover, nn.init, nn.backward, opt.adamw, opt.mixed, gn.msgpass, gn.isomorph, mo.front, mo.knee, caus.do, caus.counterfactual, caus.instrumental, dream.rollout, dream.plan, evo.evolve, swarm.trace, rl.train, rl.policy, priv.mix, priv.probe, bayes.sample, bayes.bandit, tf.attn, zk.prove, zk.verify, enc.ckks, enc.boot, ledger_query, visual_mermaid, visual_ascii, sandbox_rust, sandbox_python, sandbox_js, incremental_check_rust, incremental_check_ts, strategy_performance, strategy_detail, backtest_run, patterns_temporal, patterns_gas, patterns_tokens, ev_calculate, ev_route_history, get_pipeline_status, get_job_status, get_phase_description

## GraphRouting
ID: c8fe5355-4371-5e3f-8a3f-160bcb90fdbb
Modo: explicit_allow

Allow: ops_plan, ops_status, forge_scan, grafos.chromatic, grafos.ramsey, opt.solve, opt.dual, juego.nash, juego.vickrey, espec.dominant, espec.clustering, comp.reduce, comp.param, alea.lll, alea.derand, gn.msgpass, gn.isomorph, mo.front, mo.knee, evo.evolve, swarm.trace, bayes.sample, bayes.bandit, ledger_query, visual_mermaid, visual_ascii, sandbox_rust, sandbox_python, sandbox_js, incremental_check_rust, incremental_check_ts

Deny: Ninguna lista deny declarada.

Recomendación orientativa por rol: ops_plan, ops_status, forge_scan, grafos.chromatic, grafos.ramsey, opt.solve, opt.dual, juego.nash, juego.vickrey, espec.dominant, espec.clustering, comp.reduce, comp.param, alea.lll, alea.derand, gn.msgpass, gn.isomorph, mo.front, mo.knee, evo.evolve, swarm.trace, bayes.sample, bayes.bandit, ledger_query, visual_mermaid, visual_ascii, sandbox_rust, sandbox_python, sandbox_js, incremental_check_rust, incremental_check_ts

## MarketMicrostructure
ID: c4c6a704-6b59-5c0c-b8bc-53edb6d2f769
Modo: explicit_allow

Allow: ops_plan, ops_status, defi_catalogo, defi_evaluar, defi_riesgo, forge_scan, forge_opt, nodo_scan, red.scan, red.best, faro.consenso, faro.source, faro.clean, espejo.watch, espejo.clan, espejo.pred, catalizador.mutate, catalizador.deploy, catalizador.history, guardian.scan, guardian.stale, guardian.gas_spike, guardian.anomalia, simulacro.run, simulacro.walk, puente.scan, puente.latency, bus.status, bus.pause, ora.twap, ora.dev, book.qpos, hawk.fit, mm.quote, mm.risk, vol.price, vol.greeks, int.branch, int.regime, ord.lifecycle, ord.litpool, perp.fund, perp.base, loan.liq, loan.optimal, pf.covariance, pf.turnover, ledger_query, chain_call, chain_balance, chain_block, visual_mermaid, visual_ascii, strategy_performance, strategy_detail, backtest_run, patterns_temporal, patterns_gas, patterns_tokens, ev_calculate, ev_route_history

Deny: Ninguna lista deny declarada.

Recomendación orientativa por rol: ops_plan, ops_status, defi_catalogo, defi_evaluar, defi_riesgo, forge_scan, forge_opt, nodo_scan, red.scan, red.best, faro.consenso, faro.source, faro.clean, espejo.watch, espejo.clan, espejo.pred, catalizador.mutate, catalizador.deploy, catalizador.history, guardian.scan, guardian.stale, guardian.gas_spike, guardian.anomalia, simulacro.run, simulacro.walk, puente.scan, puente.latency, bus.status, bus.pause, ora.twap, ora.dev, book.qpos, hawk.fit, mm.quote, mm.risk, vol.price, vol.greeks, int.branch, int.regime, ord.lifecycle, ord.litpool, perp.fund, perp.base, loan.liq, loan.optimal, pf.covariance, pf.turnover, ledger_query, chain_call, chain_balance, chain_block, visual_mermaid, visual_ascii, strategy_performance, strategy_detail, backtest_run, patterns_temporal, patterns_gas, patterns_tokens, ev_calculate, ev_route_history

## BrowserE2E
ID: e389f32c-1b45-5781-b5f8-61f4c9fbfdd3
Modo: explicit_allow

Allow: ops_plan, ops_status, ui.compile, ui.island, test.prop, test.fuzz, ledger_query, visual_mermaid, visual_ascii, sandbox_rust, sandbox_python, sandbox_js, incremental_check_rust, incremental_check_ts, testforge_rust, testforge_ts

Deny: Ninguna lista deny declarada.

Recomendación orientativa por rol: ops_plan, ops_status, ui.compile, ui.island, test.prop, test.fuzz, ledger_query, visual_mermaid, visual_ascii, sandbox_rust, sandbox_python, sandbox_js, incremental_check_rust, incremental_check_ts, testforge_rust, testforge_ts

## ModeParity
ID: b6e1a9d2-14dc-5a48-b2c8-c1c54966b009
Modo: explicit_allow

Allow: ops_plan, ops_status, forge_pool, forge_swap, forge_tech, mem.rmw, mem.model, ker.trace, ker.page_fault, net.pkt, net.quic, micro.saga, micro.trace, ws.open, ws.metric, ui.compile, ui.island, test.prop, test.fuzz, ledger_query, visual_mermaid, visual_ascii, sandbox_rust, sandbox_python, sandbox_js, incremental_check_rust, incremental_check_ts, testforge_rust, testforge_ts

Deny: Ninguna lista deny declarada.

Recomendación orientativa por rol: ops_plan, ops_status, forge_pool, forge_swap, forge_tech, mem.rmw, mem.model, ker.trace, ker.page_fault, net.pkt, net.quic, micro.saga, micro.trace, ws.open, ws.metric, ui.compile, ui.island, test.prop, test.fuzz, ledger_query, visual_mermaid, visual_ascii, sandbox_rust, sandbox_python, sandbox_js, incremental_check_rust, incremental_check_ts, testforge_rust, testforge_ts

## AIEngineering
ID: d256860f-67f4-534a-a1e0-3db4e7d220d2
Modo: explicit_allow

Allow: ops_plan, ops_status, catalizador.mutate, catalizador.deploy, catalizador.history, simulacro.run, simulacro.walk, medida.stop, medida.girsanov, info.capacity, info.code, ecc.encode, ecc.decode, nn.init, nn.backward, opt.adamw, opt.mixed, loop.boot, loop.expand, caus.do, caus.counterfactual, caus.instrumental, dream.rollout, dream.plan, mem.store, mem.recall, ai.plan, ai.htn, rl.train, rl.policy, meta.mutate, meta.fitness, tf.attn, ledger_query, memory_store, memory_recall, memory_stats, visual_mermaid, visual_ascii, sandbox_rust, sandbox_python, sandbox_js, incremental_check_rust, incremental_check_ts, get_pipeline_status, get_job_status, get_phase_description

Deny: Ninguna lista deny declarada.

Recomendación orientativa por rol: ops_plan, ops_status, catalizador.mutate, catalizador.deploy, catalizador.history, simulacro.run, simulacro.walk, medida.stop, medida.girsanov, info.capacity, info.code, ecc.encode, ecc.decode, nn.init, nn.backward, opt.adamw, opt.mixed, loop.boot, loop.expand, caus.do, caus.counterfactual, caus.instrumental, dream.rollout, dream.plan, mem.store, mem.recall, ai.plan, ai.htn, rl.train, rl.policy, meta.mutate, meta.fitness, tf.attn, ledger_query, memory_store, memory_recall, memory_stats, visual_mermaid, visual_ascii, sandbox_rust, sandbox_python, sandbox_js, incremental_check_rust, incremental_check_ts, get_pipeline_status, get_job_status, get_phase_description

## Specification
ID: d59b0906-7517-59bb-a0d2-0c0fb8215ba2
Modo: explicit_allow

Allow: ops_plan, ops_status, logica.satisfiable, logica.eval, cat.limits, cat.adjunction, tipo.check, tipo.universe, turing.simular, turing.halt, sem.eval, sem.fixed, evidence_add, research_report, ledger_query, visual_mermaid, visual_ascii, univer_new, univer_status, univer_worktree, univer_unit, univer_import, univer_inspect, univer_execute, univer_export, univer_lint, univer_print_pdf, univer_compile_svg, univer_api, univer_resources, univer_screenshot, get_pipeline_status, get_job_status, get_phase_description, why_check, why_file, why_find, why_recall

Deny: Ninguna lista deny declarada.

Recomendación orientativa por rol: ops_plan, ops_status, logica.satisfiable, logica.eval, cat.limits, cat.adjunction, tipo.check, tipo.universe, turing.simular, turing.halt, sem.eval, sem.fixed, evidence_add, research_report, ledger_query, visual_mermaid, visual_ascii, univer_new, univer_status, univer_worktree, univer_unit, univer_import, univer_inspect, univer_execute, univer_export, univer_lint, univer_print_pdf, univer_compile_svg, univer_api, univer_resources, univer_screenshot, get_pipeline_status, get_job_status, get_phase_description, why_check, why_file, why_find, why_recall

## Performance
ID: ff0d8395-2a3a-5d1d-9185-63c3aa3c19e7
Modo: explicit_allow

Allow: ops_inspect, ops_diagnose, ops_plan, ops_validate, ops_learn, ops_status, opt.solve, opt.dual, juego.nash, juego.vickrey, ir.passes, ir.registers, mem.rmw, mem.model, ker.trace, ker.page_fault, net.pkt, net.quic, syn.place, syn.timing, gpu.kernel, gpu.roofline, micro.saga, micro.trace, ws.open, ws.metric, prof.hotspot, prof.inline, mo.front, mo.knee, evo.evolve, swarm.trace, bayes.sample, bayes.bandit, tf.kvcache, ledger_query, visual_mermaid, visual_ascii, sandbox_rust, sandbox_python, sandbox_js, incremental_check_rust, incremental_check_ts

Deny: Ninguna lista deny declarada.

Recomendación orientativa por rol: ops_inspect, ops_diagnose, ops_plan, ops_validate, ops_learn, ops_status, opt.solve, opt.dual, juego.nash, juego.vickrey, ir.passes, ir.registers, mem.rmw, mem.model, ker.trace, ker.page_fault, net.pkt, net.quic, syn.place, syn.timing, gpu.kernel, gpu.roofline, micro.saga, micro.trace, ws.open, ws.metric, prof.hotspot, prof.inline, mo.front, mo.knee, evo.evolve, swarm.trace, bayes.sample, bayes.bandit, tf.kvcache, ledger_query, visual_mermaid, visual_ascii, sandbox_rust, sandbox_python, sandbox_js, incremental_check_rust, incremental_check_ts
