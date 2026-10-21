#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Falsificacion del port P4 (team_memory) contra los vectores de agentscope.

Vectores: `docs/rea/agentscope_vectors.json`, segmento "memory" (9), transcriptos de
tests/middleware_filesystem_memory_test.py de agentscope-ai/agentscope@26ec620
(Apache-2.0). Adaptaciones declaradas por vector: tokens -> bytes UTF-8 (presupuesto
del destino), mtime -> recorded_at del contrato v1, selector LLM -> solape de terminos
offline, filenames de 2+ caracteres (el patron memory_id del contrato exige 2..64).

Invariantes exigidos por la tarea: append persiste tras reload del store, el indice
respeta el presupuesto de bytes (bytes del contenido <= presupuesto) y la busqueda
recupera lo appendeado.
"""
import tempfile
import unittest
from pathlib import Path

from engine import context_compiler
from engine import team_memory as tm
from engine.memory_governance import MemoryGovernanceError
from engine.tenants import TenantBoundary, TenantRegistry

TENANT = 'acme-org'
ORG_UUID = '01234567-89ab-cdef-0123-456789abcdef'
ROLE = 'role-captain'
FIXED_NOW = '2024-05-01T10:00:00.000000Z'


def _registry():
    registry = TenantRegistry()
    registry.register(TenantBoundary.default(TENANT, ORG_UUID))
    return registry


def _tienda(tmp, member='agent-uno', **kwargs):
    return tm.TeamMemoryStore(Path(tmp), _registry(), TENANT, member, **kwargs)


class TeamMemoryTests(unittest.TestCase):
    # ------------------------------------------------ vectores del fuente (9)

    def test_v1_layout_vacio_e_inyeccion_del_prompt(self):
        # Vector: reply_crea_layout_e_inyecta_prompt_de_memoria. Adaptado: el "reply"
        # del agente upstream se reemplaza por el alta en el store; la seccion de
        # system prompt es lo que este port inyecta.
        with tempfile.TemporaryDirectory() as tmp:
            store = _tienda(tmp)
            self.assertTrue(store.index_path.exists(), 'MEMORY.md debe existir tras el layout')
            self.assertTrue(store.index_path.parent.is_dir())
            section = store.system_prompt_section()
            self.assertIn('## MEMORY.md', section)
            self.assertIn(str(store.index_path), section, 'la ruta real debe viajar')
            self.assertIn(tm.EMPTY_INDEX_TEXT, section, 'indice vacio inyecta texto de vacio')
            self.assertNotIn('{memory_dir}', section, 'el placeholder no puede filtrarse')
            self.assertFalse(store.index_snapshot()['placeholder_leak'])

    def test_v2_hint_con_contenido_y_path_elegidos(self):
        # Vector: hint_con_contenido_y_path_elegidos. Adaptado: selector LLM -> search
        # por solape de terminos.
        with tempfile.TemporaryDirectory() as tmp:
            store = _tienda(tmp)
            store.append('user-profile', 'organizational',
                         'The user prefers concise answers.', role_ref=ROLE,
                         now=FIXED_NOW)
            hint = store.search('user prefers concise answers', role_ref=ROLE)
            self.assertIsNotNone(hint)
            self.assertIn('The user prefers concise answers.', hint)
            self.assertIn('user-profile.md', hint)

    def test_v3_filtra_nombres_alucinados(self):
        # Vector: filtra_nombres_alucinados.
        with tempfile.TemporaryDirectory() as tmp:
            store = _tienda(tmp)
            store.append('real-note', 'organizational',
                         'Only this real memory should be injected.', role_ref=ROLE,
                         now=FIXED_NOW)
            hint = store.select_files(['real-note.md', 'missing.md'], role_ref=ROLE)
            self.assertIsNotNone(hint)
            self.assertIn('Only this real memory should be injected.', hint)
            self.assertNotIn('missing.md', hint)

    def test_v4_dedup_con_presupuesto_exacto(self):
        # Vector: dedup_con_presupuesto_exacto. Adaptado: filenames aa.md/bb.md
        # (memory_id del contrato exige 2..64 chars) y edad fijada con now=recorded_at
        # para que la etiqueta relativa sea 'today'.
        with tempfile.TemporaryDirectory() as tmp:
            store = _tienda(tmp)
            store.append('aa', 'project', 'Fact a.', role_ref=ROLE,
                         description='Memory a', project_id='proyecto-alpha',
                         now=FIXED_NOW)
            store.append('bb', 'project', 'Fact b.', role_ref=ROLE,
                         description='Memory b', project_id='proyecto-alpha',
                         now=FIXED_NOW)
            hint = store.select_files(['aa.md'] * 5 + ['bb.md'], role_ref=ROLE,
                                      now=FIXED_NOW)
            path_a = store.fragment_file('project', 'aa')
            path_b = store.fragment_file('project', 'bb')
            esperado = (
                'Memory (saved today): %s:\n\n'
                '---\nname: aa.md\ndescription: Memory a\ntype: project\n---\n\n'
                'Fact a.\n'
                '\n\n---\n\n'
                'Memory (saved today): %s:\n\n'
                '---\nname: bb.md\ndescription: Memory b\ntype: project\n---\n\n'
                'Fact b.\n'
            ) % (path_a, path_b)
            self.assertEqual(hint, esperado)

    def test_v5_seleccion_vacia_sin_hint(self):
        # Vector: seleccion_vacia_sin_hint.
        with tempfile.TemporaryDirectory() as tmp:
            store = _tienda(tmp)
            store.append('nota', 'organizational', 'Hecho guardado.', role_ref=ROLE,
                         now=FIXED_NOW)
            self.assertIsNone(store.select_files([], role_ref=ROLE))

    def test_v6_solo_indice_sin_topic_files_no_recupera(self):
        # Vector: solo_indice_sin_topic_files_no_llama_al_selector. Solo existe
        # MEMORY.md: la busqueda devuelve None sin recuperar nada.
        with tempfile.TemporaryDirectory() as tmp:
            store = _tienda(tmp)
            self.assertTrue(store.index_path.exists())
            self.assertIsNone(store.search('cualquier consulta', role_ref=ROLE))

    def test_v7_recordatorio_de_truncamiento_con_offset(self):
        # Vector: recordatorio_de_truncamiento_con_offset. Adaptado: indice de linea
        # larga con presupuesto 30 BYTES (el fuente usa 10 tokens).
        with tempfile.TemporaryDirectory() as tmp:
            store = _tienda(tmp)
            store.append('nota-larga', 'organizational', '0123456789' * 20,
                         role_ref=ROLE, now=FIXED_NOW)
            snapshot = store.index_snapshot(budget_bytes=30, role_ref=ROLE)
            self.assertTrue(snapshot['truncated'])
            self.assertLessEqual(snapshot['content_bytes'], 30)
            self.assertIsNotNone(snapshot['reminder'])
            self.assertIn('<<<TRUNCATED>>>', snapshot['reminder'])
            self.assertIn('Use the `Read` tool with offset', snapshot['reminder'])
            self.assertIn(str(store.index_path), snapshot['reminder'])

    def test_v8_recuperacion_deshabilitada_no_recupera(self):
        # Vector: retrieval_async_false_no_recupera. Adaptado: flag retrieval_enabled.
        with tempfile.TemporaryDirectory() as tmp:
            store = _tienda(tmp, retrieval_enabled=False)
            store.append('user-profile', 'organizational',
                         'The user prefers concise answers.', role_ref=ROLE,
                         now=FIXED_NOW)
            self.assertIsNone(store.search('user prefers', role_ref=ROLE))
            self.assertIsNone(store.select_files(['user-profile.md'], role_ref=ROLE))

    def test_v9_frontmatter_con_cierre_al_final_del_texto(self):
        # Vector: frontmatter_con_cierre_al_final_del_texto (FrontmatterParseTest).
        text = '---\nname: tea.md\ndescription: User likes tea\ntype: user\n---'
        esperado = {'name': 'tea.md', 'description': 'User likes tea', 'type': 'user'}
        self.assertEqual(tm._parse_frontmatter_fields(text), esperado)
        self.assertEqual(tm._parse_frontmatter_fields(
            text + '\n\nThey drink tea daily.\n'), esperado)

    # ------------------------------------------------ invariantes de la tarea

    def test_invariante_append_persiste_tras_reload(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = _tienda(tmp)
            store.append('decision-ruta', 'organizational',
                         'Prefer the stable route when gas spikes.', role_ref=ROLE,
                         now=FIXED_NOW)
            recargado = _tienda(tmp)  # nuevo store, mismo root/tenant/miembro
            resultado = recargado.read('decision-ruta', plane='organizational',
                                       role_ref=ROLE)
            self.assertIn('Prefer the stable route when gas spikes.',
                          resultado['record']['content_ref']['value'])
            self.assertIn('Prefer the stable route when gas spikes.',
                          resultado['markdown'])
            self.assertEqual(recargado.ignored_on_reload, ())

    def test_invariante_el_indice_respeta_el_presupuesto_de_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = _tienda(tmp)
            for i in range(5):
                store.append('fragmento-%02d' % i, 'organizational',
                             'Hecho numero %d con detalle suficiente para ocupar '
                             'indice %s' % (i, 'x' * 40), role_ref=ROLE, now=FIXED_NOW)
            for budget in (30, 100, 500, 6000):
                snapshot = store.index_snapshot(budget_bytes=budget, role_ref=ROLE)
                self.assertLessEqual(snapshot['content_bytes'], budget,
                                     'presupuesto %d violado' % budget)
                self.assertEqual(snapshot['content_bytes'],
                                 len(snapshot['content'].encode('utf-8')))
                self.assertGreater(snapshot['content_bytes'], 0)

    def test_invariante_la_busqueda_recupera_lo_appendeado(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = _tienda(tmp)
            store.append('arb-preferencias', 'organizational',
                         'Prefer the stable route when gas spikes.', role_ref=ROLE,
                         now=FIXED_NOW)
            store.append('formato-reporte', 'organizational',
                         'Reports go in Markdown with evidence links.', role_ref=ROLE,
                         now=FIXED_NOW)
            store.append('kanban-flujo', 'organizational',
                         'Follow-ups land in the team kanban board.', role_ref=ROLE,
                         now=FIXED_NOW)
            hint = store.search('gas spikes stable route', role_ref=ROLE)
            self.assertIsNotNone(hint)
            self.assertIn('Prefer the stable route when gas spikes.', hint)
            self.assertNotIn('kanban board', hint)

    # ------------------------------------------------ gobierno e integracion

    def test_el_gobierno_de_planos_sigue_mandando(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = _tienda(tmp)
            store.append('n1', 'organizational', 'Hecho organizacional.', role_ref=ROLE,
                         now=FIXED_NOW)
            with self.assertRaises(MemoryGovernanceError) as ctx:
                store.read('n1', plane='project', role_ref=ROLE)
            self.assertEqual(ctx.exception.code, 'cross_plane_denied')
            with self.assertRaises(MemoryGovernanceError) as ctx:
                store.read('n1', plane='organizational', role_ref='role-intruso')
            self.assertEqual(ctx.exception.code, 'read_not_permitted')

    def test_aislamiento_por_miembro(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = _tienda(tmp, member='agent-uno')
            store.append('n1', 'organizational', 'Solo del agente uno.', role_ref=ROLE,
                         now=FIXED_NOW)
            otro = _tienda(tmp, member='agent-dos')
            with self.assertRaises(MemoryGovernanceError) as ctx:
                otro.read('n1', plane='organizational', role_ref=ROLE)
            self.assertEqual(ctx.exception.code, 'record_not_found')
            self.assertTrue(otro.index_path.exists())
            self.assertNotIn('n1.md', str(list(otro.base_dir.rglob('*.md'))))

    def test_append_idempotente_y_rechaza_sobrescritura(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = _tienda(tmp)
            store.append('duplicado', 'organizational', 'Mismo hecho.', role_ref=ROLE,
                         now=FIXED_NOW)
            archivo = store.fragment_file('organizational', 'duplicado')
            bytes_antes = archivo.read_bytes()
            store.append('duplicado', 'organizational', 'Mismo hecho.', role_ref=ROLE,
                         now=FIXED_NOW)  # mismo registro: idempotente
            self.assertEqual(archivo.read_bytes(), bytes_antes,
                             're-apendar el mismo registro no reescribe el archivo')
            with self.assertRaises(MemoryGovernanceError) as ctx:
                store.append('duplicado', 'organizational', 'Otro contenido.',
                             role_ref=ROLE, now=FIXED_NOW)
            self.assertEqual(ctx.exception.code, 'record_exists')

    def test_items_entran_al_tier_memory_del_context_compiler(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = _tienda(tmp)
            store.append('regla-entrega', 'organizational',
                         'Toda entrega cita su artefacto verificable.', role_ref=ROLE,
                         now=FIXED_NOW)
            items = store.memory_context_items(role_ref=ROLE)
            package = context_compiler.compile_context({
                'agent': {'name': 'agent-uno', 'role': 'researcher'},
                'task': {'task_id': 't-1', 'title': 'responder con memoria de equipo'},
                'memory': items})
            self.assertTrue(context_compiler.verify_context(package))
            kinds = [section['kind'] for section in package['sections']]
            self.assertIn('memory', kinds)
            self.assertLessEqual(package['budget']['used_bytes'],
                                 package['budget']['limit_bytes'])

    def test_member_invalido_se_rechaza(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(MemoryGovernanceError) as ctx:
                _tienda(tmp, member='Malo Con espacios')
            self.assertEqual(ctx.exception.code, 'invalid_request')


if __name__ == '__main__':
    unittest.main()
