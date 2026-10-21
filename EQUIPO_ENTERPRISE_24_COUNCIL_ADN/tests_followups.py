#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Falsificacion de la brecha P3 — engine/followups.py (composicional propio).

Sin vectores externos: el modulo bajo prueba NO es un port (el barrido REA no
encontro candidato con este mecanismo; declarado en su docstring), asi que estos
tests derivan DIRECTO de la semantica prescrita para P3:

  1. compromiso detectado (heuristica determinista, sin LLM)  -> tarea 'chasing'
     dirigida al emisor comprometido;
  2. tick sin respuesta                                       -> UN recordatorio al
     inbox del destinatario por tick vencido, con cuenta EXACTA;
  3. 3 recordatorios                                          -> 'escalated' al
     supervisor y NUNCA mas recordatorios (reintento infinito prohibido);
  4. mensaje con artefacto/resultado                          -> 'reported' y
     archivada.

Ademas fija la composicion declarada: vocabulario DISJUNTO del scheduler (solo
lectura), tick explicito (doctrina gang_supervisor.py:19-21), salto de los
mensajes propios del motor, backoff fijo con reloj inyectable, dedup por mensaje
y techo visible de capacidad.

CLI:  python -m unittest tests_followups -v
"""
import unittest

from engine import followups as fu
from engine import scheduler
from engine import team_channel as tc

# Roster tipo cordis. 'fu' es la identidad del motor en el canal; 'ceo' supervisa.
MIEMBROS = [
    {'member_id': 'id-ceo', 'name': 'ceo', 'role': 'CEO', 'reports_to': None},
    {'member_id': 'id-ana', 'name': 'ana', 'role': 'Investigacion', 'reports_to': 'id-ceo'},
    {'member_id': 'id-bob', 'name': 'bob', 'role': 'Revision', 'reports_to': 'id-ceo'},
    {'member_id': 'id-fu', 'name': 'fu', 'role': 'Followups', 'reports_to': 'id-ceo'},
]
SHA64 = 'a' * 64


def par(reloj=None, intervalo=0.0, maximo=3):
    """Canal + motor compartiendo reloj falso. intervalo=0: todo tick esta vencido."""
    if reloj is None:
        reloj = {'t': 1000.0}
    ch = tc.TeamChannel(MIEMBROS, clock=lambda: reloj['t'])
    motor = fu.FollowupsEngine(ch, agent='id-fu', supervisor='id-ceo',
                               clock=lambda: reloj['t'],
                               reminder_interval=intervalo, max_reminders=maximo)
    return ch, motor, reloj


def comprometer(ch, emisor, texto):
    return ch.publish(emisor, to='all', text=texto)['message']


def kinds(eventos):
    return [evento['event'] for evento in eventos]


class DeteccionTests(unittest.TestCase):
    """(1) Deteccion: compromiso textual -> tarea 'chasing' dirigida al emisor."""

    def test_compromiso_detectado_genera_tarea_chasing(self):
        ch, motor, _ = par(intervalo=60.0)          # gracia: el 1er tick no recuerda
        fila = comprometer(ch, 'bob', 'luego subo el informe final')
        eventos = motor.tick()
        self.assertEqual(kinds(eventos), ['commitment'])
        tareas = motor.tasks()
        self.assertEqual(len(tareas), 1)
        tarea = tareas[0]
        self.assertEqual(tarea['state'], fu.CHASING)
        self.assertEqual(tarea['owner_member_id'], 'id-bob')   # dirigida al emisor
        self.assertEqual(tarea['message_id'], fila['id'])      # trazable al mensaje
        self.assertEqual(tarea['snippet'], 'luego subo')
        self.assertEqual(tarea['reminders_sent'], 0)           # ventana de gracia

    def test_mensaje_sin_compromiso_no_genera_tarea(self):
        ch, motor, _ = par()
        comprometer(ch, 'ana', 'hola equipo, buen dia a todos')
        self.assertEqual(motor.tick(), ())
        self.assertEqual(motor.tasks(), ())

    def test_marcador_huerfano_no_cuenta(self):
        # El marcador exige palabra siguiente: verbo/sustantivo aproximado.
        ch, motor, _ = par()
        comprometer(ch, 'ana', 'lo hago luego.')
        comprometer(ch, 'bob', 'cuando?')
        motor.tick()
        self.assertEqual(motor.tasks(), ())

    def test_una_tarea_por_mensaje_primer_match(self):
        ch, motor, _ = par()
        comprometer(ch, 'bob', 'luego subo el X y quedo pendiente de Y')
        motor.tick()
        tareas = motor.tasks()
        self.assertEqual(len(tareas), 1)
        self.assertTrue(tareas[0]['snippet'].startswith('luego subo'))

    def test_dedup_un_mensaje_se_procesa_una_vez(self):
        ch, motor, _ = par()
        comprometer(ch, 'bob', 'luego subo el informe')
        motor.tick()
        motor.tick()
        motor.tick()
        self.assertEqual(motor.stats()['total'], 1)
        self.assertEqual(len([e for e in motor.events_log() if e['event'] == 'commitment']), 1)


class RecordatorioTests(unittest.TestCase):
    """(2) Persecucion: un recordatorio por tick vencido, cuenta exacta al inbox."""

    def test_tick_sin_respuesta_recordatorio_exacto_al_inbox(self):
        ch, motor, _ = par(intervalo=0.0)
        comprometer(ch, 'bob', 'luego subo el informe')
        ch.inbox('bob')                             # baseline: limpiar el broadcast
        for _ in range(3):                          # tres ticks SIN drenar
            motor.tick()
        inbox = ch.inbox('bob')                     # cuenta exacta acumulada: 3
        self.assertEqual(len(inbox), 3)
        for esperado, fila in zip((1, 2, 3), inbox):
            self.assertEqual(fila['topic'], fu.FOLLOWUP_TOPIC)
            self.assertEqual(fila['to'], 'id-bob')
            self.assertEqual(fila['actor'], 'id-fu')
            self.assertTrue(fila['text'].startswith('follow-up %d/3' % esperado), fila['text'])
        tarea = motor.tasks()[0]
        self.assertEqual(tarea['state'], fu.CHASING)
        self.assertEqual(tarea['reminders_sent'], 3)

    def test_backoff_fijo_con_reloj(self):
        ch, motor, reloj = par(intervalo=60.0)
        comprometer(ch, 'bob', 'luego subo el informe')
        ch.inbox('bob')
        secuencia = []
        for t in (1000.0, 1030.0, 1060.0, 1119.0, 1120.0, 1180.0, 1240.0):
            reloj['t'] = t
            secuencia.append(kinds(motor.tick()))
        self.assertEqual(secuencia, [['commitment'], [], ['reminder'], [],
                                     ['reminder'], ['reminder'], ['escalated']])

    def test_el_escaneo_cierra_antes_de_que_el_tick_recuerde(self):
        # Reporte entregado en el mismo tick: la tarea se cierra SIN nuevo recordatorio.
        ch, motor, _ = par(intervalo=0.0)
        comprometer(ch, 'bob', 'luego subo el informe')
        motor.tick()
        ch.inbox('bob')
        ch.publish('bob', to='id-fu', text='ya esta listo: subi el informe docs/i.md')
        ch.inbox('bob')
        self.assertEqual(kinds(motor.tick()), ['reported'])
        self.assertEqual(ch.inbox('bob'), [])


class EscalacionTests(unittest.TestCase):
    """(3) Tope: 3 recordatorios -> escalated al supervisor, sin reintento infinito."""

    def test_tres_recordatorios_escalada_y_no_mas_recordatorios(self):
        ch, motor, _ = par(intervalo=0.0)
        comprometer(ch, 'bob', 'luego subo el informe')
        ch.inbox('bob')
        ch.inbox('id-ceo')
        for _ in range(3):
            motor.tick()
            ch.inbox('bob')
        self.assertEqual(motor.tasks()[0]['state'], fu.CHASING)   # aun persiguiendo
        cuarto = motor.tick()
        self.assertIn('escalated', kinds(cuarto))
        tarea = motor.tasks()[0]
        self.assertEqual(tarea['state'], fu.ESCALATED)
        self.assertIsNone(tarea['next_reminder_at'])
        self.assertEqual(ch.inbox('bob'), [])                     # cero recordatorios mas
        escalaciones = ch.inbox('id-ceo')
        self.assertEqual(len(escalaciones), 1)                    # UNA sola al supervisor
        self.assertIn('escalado', escalaciones[0]['text'])
        for _ in range(3):                                        # nunca reintento infinito
            self.assertEqual(motor.tick(), ())
            self.assertEqual(ch.inbox('bob'), [])
        self.assertEqual(ch.inbox('id-ceo'), [])
        self.assertEqual(motor.stats()[fu.ESCALATED], 1)

    def test_escalada_es_terminal_ante_reporte_tardio(self):
        # La escalacion no se reescribe: el supervisor ve el incumplimiento.
        ch, motor, _ = par(intervalo=0.0)
        comprometer(ch, 'bob', 'luego subo el informe')
        for _ in range(4):
            motor.tick()
        ch.publish('bob', to='id-fu', text='ya esta listo, subi todo: %s' % SHA64)
        motor.tick()
        tarea = motor.tasks()[0]
        self.assertEqual(tarea['state'], fu.ESCALATED)
        self.assertEqual(motor.archive(), ())

    def test_max_reminders_configurable(self):
        ch, motor, _ = par(maximo=1)
        comprometer(ch, 'bob', 'luego subo el informe')
        ch.inbox('bob')
        ch.inbox('id-ceo')
        motor.tick()
        self.assertTrue(ch.inbox('bob')[0]['text'].startswith('follow-up 1/1'))
        self.assertEqual(kinds(motor.tick()), ['escalated'])
        self.assertEqual(motor.tasks()[0]['state'], fu.ESCALATED)


class ReporteTests(unittest.TestCase):
    """(4) Reporte: mensaje con artefacto/resultado -> 'reported' y archivada."""

    def test_mensaje_con_resultado_reporta_y_archiva(self):
        ch, motor, _ = par(intervalo=0.0)
        comprometer(ch, 'bob', 'luego subo el informe')
        motor.tick()
        reporte = ch.publish('bob', to='id-fu',
                             text='ya esta listo: subi el informe docs/informe.md sha256 %s' % SHA64)['message']
        eventos = motor.tick()
        self.assertIn('reported', kinds(eventos))
        self.assertEqual(motor.tasks(), ())                       # fuera de activas
        archivadas = motor.archive()
        self.assertEqual(len(archivadas), 1)
        self.assertEqual(archivadas[0]['state'], fu.REPORTED)
        self.assertEqual(archivadas[0]['reported_message_id'], reporte['id'])
        self.assertEqual(motor.stats()[fu.REPORTED], 1)
        self.assertEqual(motor.tick(), ())                        # archivada: sin eco

    def test_reporte_cierra_todas_las_chases_del_reportero(self):
        ch, motor, _ = par(intervalo=0.0)
        comprometer(ch, 'bob', 'luego subo el informe')
        comprometer(ch, 'bob', 'quedo pendiente de validar el anexo')
        comprometer(ch, 'ana', 'hare el resumen')
        motor.tick()
        self.assertEqual(motor.stats()[fu.CHASING], 3)
        ch.publish('bob', to='id-fu', text='entregado: informe y anexo revisados')
        motor.tick()
        stats = motor.stats()
        self.assertEqual(stats[fu.REPORTED], 2)                   # las 2 de bob
        self.assertEqual(stats[fu.CHASING], 1)                    # ana sigue
        self.assertEqual(motor.tasks()[0]['owner_member_id'], 'id-ana')

    def test_reporte_sin_chase_es_noop(self):
        ch, motor, _ = par()
        ch.publish('bob', to='id-fu', text='ya esta todo subido: %s' % SHA64)
        self.assertEqual(motor.tick(), ())
        self.assertEqual(motor.tasks(), ())

    def test_reporte_y_nuevo_compromiso_en_el_mismo_mensaje(self):
        ch, motor, _ = par(intervalo=0.0)
        comprometer(ch, 'bob', 'luego subo el informe')
        motor.tick()
        motor.tick()
        ch.publish('bob', to='id-fu',
                   text='ya esta listo, subi el informe; luego preparo el anexo')
        motor.tick()
        stats = motor.stats()
        self.assertEqual(stats[fu.REPORTED], 1)                   # cerro la vieja
        self.assertEqual(stats[fu.CHASING], 1)                    # abrio la nueva
        nueva = motor.tasks()[0]
        self.assertEqual(nueva['owner_member_id'], 'id-bob')
        self.assertEqual(nueva['snippet'], 'luego preparo')


class MotorTests(unittest.TestCase):
    """Bordes del motor: auto-skip, capacidad, validacion, vistas copia."""

    def test_el_motor_ignora_sus_propios_mensajes(self):
        # El texto del recordatorio lleva 'pendiente' a proposito: si el motor no
        # se saltara sus propios mensajes, se perseguiria a si mismo.
        ch, motor, _ = par(intervalo=0.0)
        comprometer(ch, 'bob', 'luego subo el informe')
        ch.inbox('id-fu')
        for _ in range(4):
            motor.tick()
        self.assertTrue(any('pendiente' in fila['text'] for fila in ch.ledger_view()['messages']
                            if fila['actor'] == 'id-fu'))
        self.assertEqual([t for t in motor.tasks() if t['owner_member_id'] == 'id-fu'], [])
        stats = motor.stats()
        self.assertEqual(stats[fu.ESCALATED], 1)                  # solo la de bob
        self.assertEqual(stats['total'], 1)

    def test_capacidad_activa_con_skip_visible(self):
        ch, motor, _ = par(intervalo=0.0)
        for n in range(fu.MAX_ACTIVE_TASKS + 2):
            ch.publish('ana', to='all', text='luego entrego el parte %d' % n)
        motor.tick()
        self.assertEqual(len(motor.tasks()), fu.MAX_ACTIVE_TASKS)
        saltados = [e for e in motor.events_log() if e['event'] == 'commitment_skipped']
        self.assertEqual(len(saltados), 2)                        # nunca silencioso
        self.assertEqual(saltados[0]['reason'], 'capacity')

    def test_errores_de_construccion(self):
        ch, _, _ = par()
        with self.assertRaises(fu.FollowupsError):
            fu.FollowupsEngine('canal-falso', agent='id-fu', supervisor='id-ceo')
        with self.assertRaises(fu.FollowupsError):
            fu.FollowupsEngine(ch, agent='fantasma', supervisor='id-ceo')
        with self.assertRaises(fu.FollowupsError):
            fu.FollowupsEngine(ch, agent='id-fu', supervisor='fantasma')
        for intervalo in (-1, True, '60'):
            with self.assertRaises(fu.FollowupsError):
                fu.FollowupsEngine(ch, agent='id-fu', supervisor='id-ceo',
                                   reminder_interval=intervalo)
        for maximo in (0, True, 11):
            with self.assertRaises(fu.FollowupsError):
                fu.FollowupsEngine(ch, agent='id-fu', supervisor='id-ceo',
                                   max_reminders=maximo)

    def test_find_copia_y_unknown(self):
        ch, motor, _ = par(intervalo=60.0)
        comprometer(ch, 'bob', 'luego subo el informe')
        motor.tick()
        tarea = motor.find('fu-1')
        self.assertEqual(tarea['state'], fu.CHASING)
        with self.assertRaises(fu.FollowupsError):
            motor.find('fu-999')

    def test_ledger_view_serializable_y_de_copia(self):
        ch, motor, _ = par(intervalo=60.0)
        comprometer(ch, 'bob', 'luego subo el informe')
        motor.tick()
        vista = motor.ledger_view()
        self.assertEqual(vista['schema_version'], fu.SCHEMA_VERSION)
        self.assertEqual(vista['agent_member_id'], 'id-fu')
        self.assertEqual(vista['supervisor_member_id'], 'id-ceo')
        self.assertEqual(vista['max_reminders'], 3)
        self.assertEqual(len(vista['tasks']), 1)
        vista['tasks'][0]['state'] = 'falsificado'
        self.assertEqual(motor.tasks()[0]['state'], fu.CHASING)   # copia profunda


class ComposicionTests(unittest.TestCase):
    """Composicion declarada: vocabulario disjunto del scheduler, detectores puros."""

    def test_vocabulario_disjunto_del_scheduler(self):
        # scheduler.py se consume SOLO LECTURA: sus estados no cambian ni se mezclan.
        self.assertEqual(fu.VOCABULARY_OVERLAP, frozenset())
        self.assertEqual(set(fu.FOLLOWUP_STATES) & set(scheduler.RUN_STATES), set())
        self.assertNotIn(fu.CHASING, scheduler.RUN_STATES)
        self.assertEqual(len(scheduler.RUN_STATES), 6)
        self.assertEqual(scheduler.TERMINAL_STATES, ('passed', 'failed', 'blocked'))

    def test_detectores_puros_positivos(self):
        for texto, snippet in [
            ('luego subo el informe', 'luego subo'),
            ('haré el informe', 'haré el'),
            ('hare el informe', 'hare el'),
            ('quedo pendiente de enviar el dato', 'pendiente de'),
            ('cuando termine lo reviso', 'cuando termine'),
            ('despues reviso todo', 'despues reviso'),
            ('voy a enviar el anexo', 'voy a enviar'),
            ('me encargo del resumen', 'me encargo del'),
        ]:
            self.assertEqual(fu.detect_commitment(texto), snippet, texto)
        for texto in ['ya esta listo', 'entregado', 'subí el archivo docs/x.md',
                      'completé todo', 'listo!', SHA64, 'https://x.dev/a.py']:
            self.assertTrue(fu.detect_report(texto), texto)

    def test_detectores_puros_negativos(self):
        for texto in ['hola equipo', 'lo hago luego.', 'cuando?', 'ok', '']:
            self.assertIsNone(fu.detect_commitment(texto), texto)
        for texto in ['lo subo cuando termine',          # promesa presente, no reporte
                      'de hecho, luego lo hago',         # marcador de discurso
                      'estoy pendiente todavia',
                      'cuando llegue lo veo']:
            self.assertFalse(fu.detect_report(texto), texto)
        self.assertIsNone(fu.detect_commitment(None))
        self.assertFalse(fu.detect_report(None))


if __name__ == '__main__':
    unittest.main()
