#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Falsificacion del port P2 — engine/team_channel.py.

Transcribe como casos del destino los vectores de docs/rea/agentscope_vectors.json
que el cuaderno REA (docs/rea/agentscope_notebook.md, tabla de capacidades) asigna a
P2 "canal/asignacion tipo colega": segmento team_pipeline completo + Modos A/D del
bus -> team_pipeline (12), bus_queue (8) y bus_pubsub (3). Los segmentos bus_log /
bus_lock / bus_registry / bus_domain pertenecen a P1/P3 y NO se transcriben aca.

Cada test cita su vector y su origen_test: si la semantica del fuente se leyo mal,
el test correspondiente FALLA (los tests destino se leen como los tests del fuente).

Vectores NO PORTABLES (declarados con razon, no omitidos en silencio):

  * member_hitl_park_y_enrutamiento_por_reply_id y
    member_hitl_confirmacion_continua_al_leader (pipeline_team_test.py:271) — el
    HITL por reply_id exige stream de eventos y confirmaciones de herramientas, es
    decir EJECUCION de la delegacion (P1/P3), no enrutamiento.
  * cancel_mientras_corre_miembro (pipeline_team_test.py:932) y
    cancel_de_miembro_reanudado (pipeline_team_test.py:1018) — cancelacion de una
    ejecucion en curso; el canal no ejecuta.
  * fallo_de_miembro_joinea_siblings_y_propaga_excepcion_original
    (pipeline_team_cleanup_test.py:51) — asyncio.gather con join de siblings.
  * delegation_round_trip_eventos_intercalados (pipeline_team_test.py:149) — la
    SECUENCIA de eventos del stream; el round-trip asignacion->claim->submit si se
    transcribe (test_vector_round_trip_mencion_claim_submit).
  * delegation_round_trip_resultado_y_reset, mitad "reset del contexto del miembro"
    (pipeline_team_test.py:149) — el canal no guarda contexto de miembros.

CLI:  python -m unittest tests_team_channel -v
"""
import re
import unittest

from engine import team_channel as tc

# Roster tipo cordis (engine/cordis_extension.py:161): member_id/name/role/reports_to.
# coder reporta a ana: permite probar revision independiente en las dos direcciones.
MIEMBROS = [
    {'member_id': 'id-ceo', 'name': 'ceo', 'role': 'CEO', 'reports_to': None},
    {'member_id': 'id-ana', 'name': 'ana', 'role': 'Investigacion', 'reports_to': 'id-ceo'},
    {'member_id': 'id-bob', 'name': 'bob', 'role': 'Revision', 'reports_to': 'id-ceo'},
    {'member_id': 'id-researcher', 'name': 'researcher', 'role': 'Research', 'reports_to': 'id-ceo'},
    {'member_id': 'id-coder', 'name': 'coder', 'role': 'Code', 'reports_to': 'id-ana'},
]
SHA64 = 'a' * 64


def canal(reloj=None):
    if reloj is None:
        reloj = {'t': 1000.0}
    return tc.TeamChannel(MIEMBROS, clock=lambda: reloj['t'])


def entregar(ch, miembro, tarea):
    """claim + evidencia + submit con salida (round-trip minimo del miembro)."""
    ch.claim(miembro, tarea['id'])
    evidencia = ch.record_evidence(miembro, 'docs/prueba.md', SHA64, 'evidencia')
    return ch.submit(miembro, tarea['id'], [evidencia['id']], output='resultado')


class RosterTests(unittest.TestCase):
    """Invariante de construccion portada de TeamPipeline (_team_pipeline.py:152)."""

    def test_nombres_duplicados_rechazan_la_construccion(self):
        duplicados = MIEMBROS + [{'member_id': 'id-x', 'name': 'ana', 'role': 'X'}]
        with self.assertRaises(tc.ChannelError) as ctx:
            tc.TeamChannel(duplicados)
        self.assertIn('duplicate_member', str(ctx.exception))

    def test_destinos_reservados_y_tokens_invalidos_rechazados(self):
        with self.assertRaises(tc.ChannelError):
            tc.TeamChannel(MIEMBROS + [{'member_id': 'id-x', 'name': 'all'}])
        with self.assertRaises(tc.ChannelError):
            tc.TeamChannel(MIEMBROS + [{'member_id': 'id-x', 'name': 'dos palabras'}])
        with self.assertRaises(tc.ChannelError):
            tc.TeamChannel(MIEMBROS + [{'member_id': 'id-x', 'name': 'x@y'}])
        with self.assertRaises(tc.ChannelError):
            tc.TeamChannel([{'member_id': 'id-a', 'name': 'a', 'reports_to': 'id-fantasma'}])

    def test_resolve_por_id_por_nombre_y_desconocido(self):
        ch = canal()
        self.assertEqual(ch.resolve('id-ana').name, 'ana')
        self.assertEqual(ch.resolve('ana').member_id, 'id-ana')
        with self.assertRaises(tc.ChannelError):
            ch.resolve('fantasma')


class InboxTests(unittest.TestCase):
    """Vectores bus_queue (Mode A): inbox por miembro, orden preservado."""

    def test_vector_push_drain_fifo(self):
        # bus_queue push_drain_fifo — tests/in_memory_message_bus_test.py:32
        ch = canal()
        ch.publish('ana', to='bob', text='hola')
        ch.publish('ana', to='bob', text='chau')
        self.assertEqual([fila['text'] for fila in ch.inbox('bob')], ['hola', 'chau'])

    def test_vector_drain_destructivo(self):
        # bus_queue drain_destructivo — :39
        ch = canal()
        ch.publish('ana', to='bob', text='hola')
        self.assertTrue(ch.inbox('bob'))
        self.assertEqual(ch.inbox('bob'), [])

    def test_vector_drain_respeta_max_count_y_el_resto_persiste(self):
        # bus_queue drain_respeta_max_count — :45
        ch = canal()
        for i in range(5):
            ch.publish('ana', to='bob', text=str(i))
        self.assertEqual([fila['text'] for fila in ch.inbox('bob', 3)], ['0', '1', '2'])
        self.assertEqual([fila['text'] for fila in ch.inbox('bob', 10)], ['3', '4'])

    def test_vector_drain_de_inbox_vacia(self):
        # bus_queue drain_de_clave_inexistente -> [] — :54. Divergencia declarada: el
        # bus usa claves opacas; aqui el miembro fuera del roster se rechaza.
        ch = canal()
        self.assertEqual(ch.inbox('ana'), [])
        with self.assertRaises(tc.ChannelError):
            ch.inbox('fantasma')

    def test_vector_push_devuelve_ids_unicos_no_ordenables_lexicograficamente(self):
        # bus_queue push_devuelve_ids_unicos — :58; ids "<seq>-0" no comparables como
        # string (notebook: seq > 9 rompe el orden lexicografico).
        ch = canal()
        ids = [ch.publish('ana', to='bob', text=str(i))['message']['id'] for i in range(12)]
        patron = re.compile(r'^\d+-0$')
        self.assertTrue(all(patron.match(ident) for ident in ids))
        self.assertEqual(len(set(ids)), 12)
        self.assertEqual([tc.entry_seq(ident) for ident in ids], list(range(1, 13)))
        # ordenar por string MIENTE: '10-0' < '9-0' lexicograficamente
        self.assertNotEqual(sorted(['9-0', '10-0']), ['9-0', '10-0'])

    def test_vector_delete_vacia_y_es_idempotente(self):
        # bus_queue queue_delete_vacia_y_es_idempotente — :64,71
        ch = canal()
        ch.publish('ana', to='bob', text='hola')
        ch.publish('ana', to='bob', text='chau')
        ch.inbox_delete('bob')
        self.assertEqual(ch.inbox('bob'), [])
        ch.inbox_delete('bob')       # re-delete: no lanza
        ch.inbox_delete('ceo')       # miembro del roster sin inbox: no-op, no lanza

    def test_vector_aislamiento_entre_miembros(self):
        # bus_queue aislamiento_entre_claves — :75
        ch = canal()
        ch.publish('ana', to='bob', text='para bob')
        ch.publish('ana', to='ceo', text='para ceo')
        self.assertEqual([fila['text'] for fila in ch.inbox('bob')], ['para bob'])
        self.assertEqual([fila['text'] for fila in ch.inbox('ceo')], ['para ceo'])

    def test_vector_ttl_cero_expira_inmediatamente(self):
        # bus_queue ttl_cero_expira_inmediatamente — :84 (ttl=0 EXPIRA, no desactiva)
        ch = canal()
        ch.publish('ana', to='bob', text='efimera', ttl_secs=0)
        self.assertEqual(ch.inbox('bob'), [])

    def test_purga_de_expirados_antes_del_append(self):
        # Invariante de bounded-memory del bus (:158): la purga corre en el push, no
        # solo en el drain. Observable en la cola interna del inbox.
        reloj = {'t': 1000.0}
        ch = canal(reloj)
        ch.publish('ana', to='bob', text='vieja', ttl_secs=5)
        reloj['t'] = 2000.0
        ch.publish('ana', to='bob', text='nueva')
        # el check interno va ANTES del drain (destructivo) para observar la purga
        self.assertEqual(len(ch._queues._queues['id-bob']), 1,
                         'el push debio purgar la entrada expirada (bus :158)')
        self.assertEqual([fila['text'] for fila in ch.inbox('bob')], ['nueva'])

    def test_broadcast_all_entrega_a_todos_los_miembros(self):
        # Doctrina _base.py:33-40: fan-out = una entrada de inbox POR destinatario.
        ch = canal()
        ch.publish('ana', to='all', text='aviso')
        for nombre in ch.names:
            fila = ch.inbox(nombre)
            self.assertEqual([f['text'] for f in fila], ['aviso'], nombre)


class MentionAssignTests(unittest.TestCase):
    """Vectores team_pipeline: @mencion (_TeamAssign), orden de llamada, parqueo."""

    def test_vector_round_trip_mencion_claim_submit(self):
        # team_pipeline delegation_round_trip ( nucleo asignacion->resultado ) —
        # tests/pipeline_team_test.py:149
        ch = canal()
        publicado = ch.publish('ana', to='all', text='@researcher Find A')
        tarea = publicado['task']
        self.assertIsNotNone(tarea)
        self.assertEqual(tarea['owner_member_id'], 'id-researcher')
        self.assertEqual(tarea['status'], 'open')
        self.assertEqual(tarea['prompt'], 'Find A')
        self.assertEqual(tarea['title'], 'Find A')
        self.assertEqual(publicado['message']['text'], '@researcher Find A')
        # el mensaje broadcast llego al inbox del destinatario de la tarea
        self.assertEqual([f['text'] for f in ch.inbox('researcher')], ['@researcher Find A'])
        entregado = entregar(ch, 'researcher', tarea)
        self.assertEqual(entregado['status'], 'submitted')
        self.assertEqual(entregado['history'][-1]['note'], 'resultado')

    def test_vector_mencion_desconocido_rechaza_la_publicacion_entera(self):
        # Semantica _TeamAssign: member es enum de nombres del roster
        # (_team_pipeline.py:51-99) — target fuera del roster no enruta nada.
        ch = canal()
        with self.assertRaises(tc.ChannelError) as ctx:
            ch.publish('ana', to='all', text='@fantasma haz algo')
        self.assertIn('unknown_member', str(ctx.exception))
        vista = ch.ledger_view()      # fail-closed: nada quedo mutado
        self.assertEqual(vista['version'], 0)
        self.assertEqual(vista['messages'], [])
        self.assertEqual(vista['tasks'], [])

    def test_mencion_sin_prompt_sin_titulo_rechaza(self):
        ch = canal()
        with self.assertRaises(tc.ChannelError):
            ch.publish('ana', to='all', text='@researcher')

    def test_vector_input_reparable_sigue_enrutando_y_el_texto_queda_crudo(self):
        # team_pipeline input_reparable_sigue_enrutandose — pipeline_team_test.py:550:
        # un input que solo parsea tras reparar igualmente se enruta y el crudo se
        # CONSERVA sin normalizar.
        ch = canal()
        publicado = ch.publish('ana', to='all', text='  @researcher   Find A  ')
        self.assertEqual(publicado['task']['prompt'], 'Find A',
                         'el parse tolerante debia rutear con prompt normalizado')
        self.assertEqual(publicado['task']['owner_member_id'], 'id-researcher')
        self.assertEqual(publicado['message']['text'], '@researcher   Find A',
                         'la fila conserva el texto crudo (solo extremos recortados)')

    def test_vector_resultado_sin_respuesta(self):
        # team_pipeline: output = "The member finished without a reply." cuando el
        # miembro termina sin respuesta (_team_pipeline.py:332).
        ch = canal()
        tarea = ch.assign('ana', 'researcher', 'Find A')
        ch.claim('researcher', tarea['id'])
        evidencia = ch.record_evidence('researcher', 'docs/x.md', SHA64, 'sin salida')
        entregado = ch.submit('researcher', tarea['id'], [evidencia['id']], output='')
        self.assertEqual(entregado['history'][-1]['note'],
                         'The member finished without a reply.')

    def test_vector_delegaciones_concurrentes_resultados_en_orden_de_llamada(self):
        # team_pipeline delegaciones_concurrentes — pipeline_team_test.py:445: dos
        # miembros corren juntos (sin orden entre ellos) y los resultados aterrizan
        # en ORDEN DE LLAMADA aunque terminen al reves.
        ch = canal()
        t1 = ch.assign('ana', 'researcher', 'Find A')   # call-1
        t2 = ch.assign('ana', 'coder', 'Write A')       # call-2
        # coder (call-2) termina PRIMERO: entre miembros no hay orden de espera
        ch.claim('coder', t2['id'])
        evidencia = ch.record_evidence('coder', 'docs/a.py', SHA64, 'wrote')
        ch.submit('coder', t2['id'], [evidencia['id']], output='Wrote a.py')
        # researcher (call-1) puede reclamar MIENTRAS el otro avanza: concurrentes
        entregar(ch, 'researcher', t1)
        vista = ch.ledger_view()
        self.assertEqual([tarea['id'] for tarea in vista['tasks']],
                         [t1['id'], t2['id']],
                         'las filas de tarea quedan en orden de llamada, no de finalizacion')
        self.assertLess(tc.entry_seq(t1['id']), tc.entry_seq(t2['id']))

    def test_vector_mismo_miembro_encola_asignaciones(self):
        # team_pipeline mismo_miembro_encola_asignaciones — pipeline_team_test.py:768:
        # la 2da asignacion al MISMO miembro no avanza antes que la 1ra.
        ch = canal()
        t1 = ch.assign('ana', 'researcher', 'Find A')
        t2 = ch.assign('ana', 'researcher', 'Find B')
        with self.assertRaises(tc.ChannelError) as ctx:
            ch.claim('researcher', t2['id'])
        self.assertIn('orden de llamada', str(ctx.exception))
        entregar(ch, 'researcher', t1)
        segunda = ch.claim('researcher', t2['id'])   # ahora si
        self.assertEqual(segunda['status'], 'claimed')

    def test_vector_uno_parquea_el_otro_alimenta_y_el_orden_se_conserva(self):
        # team_pipeline un_miembro_parquea_el_otro_alimenta — pipeline_team_test.py:620
        # (+ bloqueo/re-claim del parqueo, mitad portable de :507): coder alimenta,
        # researcher parquea (block), reanuda y entrega; el orden final es el de llamada.
        ch = canal()
        t1 = ch.assign('ana', 'researcher', 'Find A')
        t2 = ch.assign('ana', 'coder', 'Write A')
        self.assertEqual(t2['status'], 'open')
        entregar(ch, 'coder', t2)                     # el otro alimenta primero
        vista_parcial = ch.ledger_view()
        estados = {t['id']: t['status'] for t in vista_parcial['tasks']}
        self.assertEqual(estados[t1['id']], 'open')       # researcher sigue pendiente
        self.assertEqual(estados[t2['id']], 'submitted')  # coder ya alimento
        ch.claim('researcher', t1['id'])
        ch.block('researcher', t1['id'], note='parqueado')
        reanudada = ch.claim('researcher', t1['id'], note='reanudo')
        self.assertEqual(reanudada['status'], 'claimed')
        evidencia = ch.record_evidence('researcher', 'docs/a.md', SHA64, 'found')
        final = ch.submit('researcher', t1['id'], [evidencia['id']], output='Found: A = 42')
        self.assertEqual([paso['action'] for paso in final['history']],
                         ['claim', 'block', 'claim', 'submit'])
        self.assertEqual([t['id'] for t in ch.ledger_view()['tasks']],
                         [t1['id'], t2['id']])

    def test_assign_valida_miembro_y_rechaza_desconocidos(self):
        # Semantica TeamMember (_team_pipeline.py:37-48): el destinatario debe ser un
        # miembro del roster existente; el desconocido se rechaza.
        ch = canal()
        tarea = ch.assign('ana', 'coder', 'Escribe el modulo')
        self.assertEqual(tarea['owner_member_id'], 'id-coder')
        self.assertEqual(tarea['status'], 'open')
        self.assertEqual(tarea['actor'], 'id-ana')
        with self.assertRaises(tc.ChannelError):
            ch.assign('ana', 'fantasma', 'nada')
        with self.assertRaises(tc.ChannelError):
            ch.publish('fantasma', to='all', text='hola')   # emisor tambien es roster


class PubSubTests(unittest.TestCase):
    """Vectores bus_pubsub (Mode D): entrega transitoria con on_ready."""

    def test_vector_suscriptor_recibe_publicados_tras_ready(self):
        # bus_pubsub suscriptor_recibe_publicados_tras_ready — :189: on_ready corre
        # UNA vez despues del registro y ANTES de cualquier entrega.
        ch = canal()
        eventos = []
        ch.subscribe('bob', lambda fila: eventos.append(('handler', fila['text'])),
                     on_ready=lambda: eventos.append(('ready',)))
        self.assertEqual(eventos, [('ready',)])
        ch.publish('ana', to='bob', text='uno')
        ch.publish('ana', to='bob', text='dos')
        self.assertEqual(eventos, [('ready',), ('handler', 'uno'), ('handler', 'dos')])

    def test_vector_publish_sin_suscriptores_es_noop(self):
        # bus_pubsub publish_sin_suscriptores_es_noop — :214
        ch = canal()
        ch.publish('ana', to='bob', text='al vacio')   # no lanza
        self.assertEqual([f['text'] for f in ch.inbox('bob')], ['al vacio'])

    def test_vector_varios_suscriptores_reciben_cada_uno(self):
        # bus_pubsub varios_suscriptores_reciben_cada_uno — :218
        ch = canal()
        recibido = []
        ch.subscribe('ana', lambda fila: recibido.append(('uno', fila['text'])))
        ch.subscribe('ana', lambda fila: recibido.append(('dos', fila['text'])))
        ch.publish('bob', to='ana', text='x=42')
        self.assertEqual(recibido, [('uno', 'x=42'), ('dos', 'x=42')])


class LedgerCompatTests(unittest.TestCase):
    """Compatibilidad de campos con cordis_extension/runtime.mjs:175-215."""

    def test_campos_de_fila_de_mensaje(self):
        # runtime.mjs:177 — {base..., to, text, topic}
        ch = canal()
        fila = ch.publish('ana', to='bob', text='hola')['message']
        self.assertTrue({'id', 'actor', 'created_at', 'provenance', 'content_verified',
                         'to', 'text', 'topic'} <= set(fila))
        self.assertEqual(fila['to'], 'id-bob')
        self.assertEqual(fila['topic'], 'coordination')  # default runtime.mjs:177
        difusion = ch.publish('ana', to='all', text='todos')['message']
        self.assertEqual(difusion['to'], 'all')

    def test_campos_de_tarea_y_history_de_claim_submit(self):
        # runtime.mjs:195 create y :201-214 transiciones: claim/submit con history.
        ch = canal()
        tarea = ch.assign('ana', 'researcher', 'Find A')
        self.assertTrue({'id', 'actor', 'created_at', 'provenance', 'content_verified',
                         'title', 'owner_member_id', 'depends_on', 'status',
                         'evidence_ids', 'history'} <= set(tarea))
        self.assertEqual(tarea['history'], [])            # create no agrega history
        ch.claim('researcher', tarea['id'])
        evidencia = ch.record_evidence('researcher', 'docs/x.md', SHA64, 'r')
        entregada = ch.submit('researcher', tarea['id'], [evidencia['id']],
                              output='Found: A = 42')
        self.assertEqual([paso['action'] for paso in entregada['history']],
                         ['claim', 'submit'])
        for paso in entregada['history']:
            self.assertTrue({'actor', 'action', 'at', 'note', 'evidence_ids'} <= set(paso))
        self.assertEqual(entregada['evidence_ids'], [evidencia['id']])
        self.assertIn('updated_at', entregada)

    def test_solo_el_dueno_asignado_puede_actuar(self):
        # runtime.mjs:201 "Only assigned owner may act"
        ch = canal()
        tarea = ch.assign('ana', 'researcher', 'Find A')
        with self.assertRaises(tc.ChannelError) as ctx:
            ch.claim('coder', tarea['id'])
        self.assertIn('not_task_owner', str(ctx.exception))

    def test_claim_requiere_dependencias_aceptadas(self):
        # runtime.mjs:203 "Dependencies not accepted"
        ch = canal()
        base = ch.assign('ana', 'coder', 'Base')
        encima = ch.assign('ana', 'coder', 'Encima', depends_on=[base['id']])
        with self.assertRaises(tc.ChannelError) as ctx:
            ch.claim('coder', encima['id'])
        self.assertIn('dependencies_not_accepted', str(ctx.exception))
        entregar(ch, 'coder', base)
        evidencia = ch.ledger_view()['evidence'][0]['id']
        revision = ch.accept('bob', base['id'], note='ok', evidence_ids=[evidencia])
        self.assertEqual(revision['status'], 'accepted')
        self.assertEqual(ch.claim('coder', encima['id'])['status'], 'claimed')

    def test_revision_independiente_por_cadena_de_mando(self):
        # runtime.mjs:240-251: el revisor no puede ser el autor ni ancestro/descendiente.
        ch = canal()
        tarea = ch.assign('ceo', 'ana', 'Informe')
        entregar(ch, 'ana', tarea)
        evidencia = ch.ledger_view()['evidence'][0]['id']
        with self.assertRaises(tc.ChannelError):
            ch.accept('ana', tarea['id'], note='self', evidence_ids=[evidencia])
        with self.assertRaises(tc.ChannelError):
            ch.accept('ceo', tarea['id'], note='jefe', evidence_ids=[evidencia])
        with self.assertRaises(tc.ChannelError):
            ch.accept('coder', tarea['id'], note='reporta a ana', evidence_ids=[evidencia])
        aceptada = ch.accept('bob', tarea['id'], note='par', evidence_ids=[evidencia])
        self.assertEqual(aceptada['status'], 'accepted')
        self.assertEqual(aceptada['reviewer_member_id'], 'id-bob')

    def test_visible_messages_filtro_del_ledger(self):
        # runtime.mjs:151: to == 'all' || to == actor || actor == actor, en orden.
        ch = canal()
        ch.publish('ana', to='bob', text='1-directa')
        ch.publish('ana', to='ceo', text='2-ajena')
        ch.publish('bob', to='all', text='3-propia')
        self.assertEqual([f['text'] for f in ch.visible_messages('bob')], ['1-directa', '3-propia'])
        self.assertEqual([f['text'] for f in ch.visible_messages('ana')],
                         ['1-directa', '2-ajena', '3-propia'])
        self.assertEqual([f['text'] for f in ch.visible_messages('ceo')], ['2-ajena', '3-propia'])

    def test_ledger_view_devuelve_copias(self):
        # Disciplina registry_getall (bus :509): mutar la salida no toca el estado.
        ch = canal()
        tarea = ch.assign('ana', 'researcher', 'Find A')
        vista = ch.ledger_view()
        vista['tasks'][0]['status'] = 'accepted'
        vista['messages'].append({'inyectado': True})
        vista['members'][0]['name'] = 'hackeado'
        self.assertEqual(ch.ledger_view()['tasks'][0]['status'], tarea['status'])
        self.assertEqual(ch.ledger_view()['messages'], [])
        self.assertEqual(ch.ledger_view()['members'][0]['name'], 'ceo')

    def test_version_y_audit_por_operacion(self):
        # runtime.mjs:230-232: version += 1 por operacion y audit con seq/actor/...
        ch = canal()
        self.assertEqual(ch.ledger_view()['version'], 0)
        ch.publish('ana', to='bob', text='hola')
        tarea = ch.assign('ana', 'researcher', 'Find A')
        ch.claim('researcher', tarea['id'])
        vista = ch.ledger_view()
        self.assertEqual(vista['version'], 3)
        self.assertEqual([fila['seq'] for fila in vista['audit']], [1, 2, 3])
        self.assertEqual([fila['operation'] for fila in vista['audit']],
                         ['message', 'task', 'task'])
        for fila in vista['audit']:
            self.assertTrue({'seq', 'actor', 'operation', 'record_id', 'at',
                             'request_digest'} <= set(fila))

    def test_evidencia_exige_sha256_hexadecimal(self):
        # runtime.mjs:181: sha256 hex64 obligatorio; submit exige evidencia existente.
        ch = canal()
        with self.assertRaises(tc.ChannelError):
            ch.record_evidence('ana', 'docs/x.md', 'no-hex', 'resumen')
        tarea = ch.assign('ana', 'researcher', 'Find A')
        ch.claim('researcher', tarea['id'])
        with self.assertRaises(tc.ChannelError):
            ch.submit('researcher', tarea['id'], ['99-0'], output='sin evidencia real')


if __name__ == '__main__':
    unittest.main(verbosity=2)
