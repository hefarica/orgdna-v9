"""Pruebas del panel de seguimiento (GenTeam P3) por HTTP local real.

Arnes: el mismo de `tests_bridge.py` (BridgeState + LocalServer sobre 127.0.0.1:0, cookie
de sesion, Origin local y X-CSRF-Token). No usa proveedores, red externa, DSH ni claves:
el unico efecto de las acciones es registrar en el canal EN MEMORIA y anadir un recibo.

Que fija:
  1. `team_followups` viaja en /api/state con todos sus campos y la autoria declarada
     (identidad de coordinacion = miembro raiz, reports_to externo; nunca un miembro autor).
  2. Sin diseno la vista devuelve available=False con motivo y NO lanza (HTTP 200).
  3. `followups-tick` y `followups-drain` exigen sesion, Origin/CSRF y expected_state_version
     (403 sin sesion; 400 con version obsoleta o parametros invalidos).
  4. Un tick crea UNA persecucion desde un compromiso detectado; tickear de nuevo no la
     duplica; al vencer el intervalo persigue; tras el tope escala y no vuelve a recordar.
  5. El drenaje devuelve los recordatorios con la autoridad de coordinacion y conserva los
     mensajes de otros topicos sin atribuirlos al motor.
  6. Reiniciar el motor (cambio de roster) no duplica ni deja fantasmas.
  7. La vista nunca lanza aunque el canal sea invalido.

CLI:  python -m unittest tests_team_followups_panel -v
"""
import http.client
import json
import threading
import time
import unittest

from engine.bridge import BridgeState, LocalServer, FOLLOWUPS_ACTIONS, FOLLOWUP_TOPIC
from tests_bridge import NullStore

ROOT_PATH = '/api/state'
COMMITMENT_TEXT = 'luego subo el informe'      # dispara _COMMITMENT_RE (followups.py:113-117)
REPORT_TEXT = 'ya esta entregado el informe'   # dispara _REPORT_RE (followups.py:122-134)
POSITION_NOTE = 'ningun miembro del roster es su autor'


class ClockedBridgeState(BridgeState):
    """Bridge con el SEAM de reloj sobrescrito (lo mismo que hara el fixture E2E).

    El bridge de produccion no expone control de tiempo por HTTP: esta subclase existe solo
    para que la prueba pueda vencer el intervalo real de 3600 s sin esperar una hora.
    """

    def __init__(self, *args, **kwargs):
        self.now = 1000.0
        super().__init__(*args, **kwargs)

    def _followups_clock(self):
        return self.now


class FollowupsPanelTests(unittest.TestCase):
    """HTTP real contra el servidor local del bridge. Sin red externa ni proveedores."""

    def setUp(self):
        self.state = ClockedBridgeState(credential_store=NullStore())
        self.server = LocalServer(('127.0.0.1', 0), self.state)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.host = '127.0.0.1:%d' % self.server.server_port
        status, headers, _ = self.request('GET', '/')
        self.assertEqual(status, 200)
        self.cookie = headers['Set-Cookie'].split(';')[0]
        self.state.execute('generate', {})
        self.version = self.state.organization.get('state_version', 1)
        roster = self.state._team_roster()
        self.root = next(member for member in roster if member.get('reports_to') is None)
        self.member = next(member for member in roster if member.get('reports_to') is not None)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    # ------------------------------------------------------------------ utilidades

    def request(self, method, path, body=None, headers=None):
        """Peticion HTTP real contra el servidor local, con reintento de transporte.

        El host de esta suite es compartido y puede quedar sin sockets efimeros o con
        conexiones de loopback rechazadas de forma transitoria (WinError 10055/10054 bajo
        carga): se reintenta el TRANSPORTE hasta 3 veces. Ningun fallo logico se reintenta:
        un 4xx/5xx o un cuerpo inesperado se devuelve tal cual para que la prueba falle.
        """
        last = None
        for attempt in range(3):
            try:
                connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=15)
                connection.request(method, path, body=body, headers=headers or {})
                response = connection.getresponse()
                payload = response.read()
                result = (response.status, dict(response.getheaders()), payload)
                connection.close()
                return result
            except (OSError, http.client.HTTPException) as error:
                last = error
                time.sleep(0.2 * (attempt + 1))
        raise AssertionError('transporte HTTP local no disponible tras 3 intentos: %r' % (last,))

    def post_headers(self, **overrides):
        headers = {'Host': self.host, 'Origin': 'http://' + self.host, 'Cookie': self.cookie,
                   'Content-Type': 'application/json', 'X-CSRF-Token': self.state.csrf}
        headers.update(overrides)
        return headers

    def post(self, action, body, **headers):
        status, _, payload = self.request('POST', '/api/' + action, json.dumps(body),
                                          self.post_headers(**headers))
        return status, json.loads(payload)

    def state_view(self):
        status, _, payload = self.request('GET', ROOT_PATH, headers={'Cookie': self.cookie})
        self.assertEqual(status, 200)
        return json.loads(payload)

    def publish(self, sender, text, to=None, topic=None):
        body = {'expected_state_version': self.version, 'sender': sender['member_id'],
                'to': (to or sender)['member_id'], 'text': text}
        if topic:
            body['topic'] = topic
        status, payload = self.post('channel-publish', body)
        self.assertEqual(status, 200, payload)
        return payload

    def commit(self):
        return self.publish(self.member, COMMITMENT_TEXT)

    def tick(self, expect=200):
        status, payload = self.post('followups-tick', {'expected_state_version': self.version})
        self.assertEqual(status, expect, payload)
        return payload

    def advance(self, seconds=3601.0):
        self.state.now += seconds

    def tasks(self, payload):
        return payload['team_followups']['tasks']

    # ------------------------------------------------------------------ la vista

    def test_state_view_exposes_every_followups_field_and_declares_authority(self):
        view = self.state_view()['team_followups']
        for field in ('available', 'reason', 'in_memory_session_only', 'reset_policy',
                      'schema_version', 'provenance', 'agent_member_id', 'supervisor_member_id',
                      'reminder_interval_secs', 'max_reminders', 'processed_message_ids',
                      'tasks', 'archive', 'events', 'stats', 'authority', 'clock_source', 'loop'):
            with self.subTest(field=field):
                self.assertIn(field, view)
        self.assertIs(view['available'], True)
        self.assertIsNone(view['reason'])
        self.assertIs(view['in_memory_session_only'], True)
        self.assertEqual(view['schema_version'], 'engine.followups/1')
        self.assertEqual(view['provenance'], 'engine.followups')
        self.assertEqual(view['reminder_interval_secs'], 3600.0)
        self.assertEqual(view['max_reminders'], 3)
        # Identidad de coordinacion = miembro raiz (reports_to externo), declarada.
        self.assertEqual(view['agent_member_id'], self.root['member_id'])
        self.assertEqual(view['clock_source'], 'injected')       # seam de esta prueba
        authority = view['authority']
        self.assertEqual(authority['kind'], 'coordination')
        self.assertIs(authority['is_member_authored'], False)
        self.assertEqual(authority['actor_member_id'], self.root['member_id'])
        self.assertEqual(authority['topic'], FOLLOWUP_TOPIC)
        self.assertEqual(authority['provenance'], 'engine.followups')
        self.assertIs(authority['identity_verified'], False)
        self.assertIn(POSITION_NOTE, authority['note'])
        self.assertIn(self.root['name'], authority['note'])
        self.assertEqual(authority['role_label'], 'Coordinacion local (motor de seguimiento)')
        self.assertIs(view['loop']['available'], False)

    def test_view_without_design_is_unavailable_with_reason_and_never_raises(self):
        self.state.organization = None
        status, _, payload = self.request('GET', ROOT_PATH, headers={'Cookie': self.cookie})
        self.assertEqual(status, 200)
        view = json.loads(payload)['team_followups']
        self.assertIs(view['available'], False)
        self.assertIn('Genera un diseno para abrir el seguimiento del equipo.', view['reason'])
        self.assertIsNone(view['authority']['actor_member_id'])

    def test_view_never_raises_when_the_channel_roster_is_invalid(self):
        agents = self.state.organization['agents']
        agents[1]['id'] = agents[0]['id']           # roster duplicado: TeamChannel rechaza
        status, _, payload = self.request('GET', ROOT_PATH, headers={'Cookie': self.cookie})
        self.assertEqual(status, 200)
        view = json.loads(payload)['team_followups']
        self.assertIs(view['available'], False)
        self.assertTrue(view['reason'])
        self.assertIn('authority', view)

    # ------------------------------------------------------------------ el contrato HTTP

    def test_actions_require_session_and_version(self):
        body = json.dumps({'expected_state_version': self.version})
        status, _, _ = self.request('POST', '/api/followups-tick', body,
                                    self.post_headers(Cookie=''))
        self.assertEqual(status, 403)
        status, payload = self.post('followups-tick', {'expected_state_version': 999})
        self.assertEqual(status, 400)
        self.assertEqual(payload['error'],
                         'Versión obsoleta: recarga el estado antes de guardar; expected_state_version debe coincidir.')
        status, payload = self.post('followups-tick', {})
        self.assertEqual(status, 400)
        self.assertIn('expected_state_version debe coincidir', payload['error'])
        status, payload = self.post('followups-drain', {'expected_state_version': self.version,
                                                        'member': self.member['member_id']})
        self.assertEqual(status, 400)
        self.assertIn('max_count debe ser un entero entre 1 y 100.', payload['error'])
        self.assertEqual(set(FOLLOWUPS_ACTIONS), {'followups-tick', 'followups-drain'})

    def test_drain_validates_member_and_max_count(self):
        cases = (
            ({'member': 'fantasma', 'max_count': 5}, 'member debe ser un miembro del roster vigente.'),
            ({'member': self.member['member_id'], 'max_count': 0}, 'max_count debe ser un entero entre 1 y 100.'),
            ({'member': self.member['member_id'], 'max_count': 101}, 'max_count debe ser un entero entre 1 y 100.'),
            ({'member': self.member['member_id'], 'max_count': '5'}, 'max_count debe ser un entero entre 1 y 100.'),
            ({'member': None, 'max_count': 5}, 'member debe ser un miembro del roster vigente.'),
        )
        for extra, expected in cases:
            with self.subTest(case=extra):
                status, payload = self.post('followups-drain',
                                            dict(extra, expected_state_version=self.version))
                self.assertEqual(status, 400, payload)
                self.assertEqual(payload['error'], expected)

    def test_tick_returns_public_state_plus_ephemeral_envelope_only(self):
        self.commit()
        payload = self.tick()
        self.assertIn('followups_tick', payload)
        for key in ('organization', 'config', 'team_followups', 'team_channel'):
            self.assertIn(key, payload)
        self.assertEqual(payload['followups_tick']['commitments'], 1)
        self.assertEqual(payload['followups_tick']['reminders'], 0)
        view = self.state_view()
        self.assertNotIn('followups_tick', view)
        self.assertNotIn('followups_drained', view)

    # ------------------------------------------------------------------ el ciclo perseguido

    def test_tick_creates_one_chase_from_a_commitment(self):
        self.commit()
        payload = self.tick()
        tasks = self.tasks(payload)
        self.assertEqual(len(tasks), 1)
        task = tasks[0]
        self.assertEqual(task['id'], 'fu-1')
        self.assertEqual(task['state'], 'chasing')
        self.assertEqual(task['owner_member_id'], self.member['member_id'])
        self.assertEqual(task['reminders_sent'], 0)
        self.assertIn('luego subo', task['snippet'])
        self.assertEqual(payload['team_followups']['stats']['active'], 1)
        self.assertEqual([event['event'] for event in payload['team_followups']['events']], ['commitment'])

    def test_second_tick_does_not_duplicate_the_chase(self):
        self.commit()
        self.tick()
        payload = self.tick()
        self.assertEqual(len(self.tasks(payload)), 1)
        self.assertEqual(payload['followups_tick']['events'], 0)
        self.assertEqual(payload['team_followups']['stats']['total'], 1)

    def test_overdue_tick_reminds_then_escalates_after_the_cap(self):
        self.commit()
        self.tick()
        self.advance()
        payload = self.tick()
        self.assertEqual(payload['followups_tick']['reminders'], 1)
        self.assertEqual(self.tasks(payload)[0]['reminders_sent'], 1)
        reminders = [row for row in payload['team_channel']['messages']
                     if row['topic'] == FOLLOWUP_TOPIC]
        self.assertEqual(len(reminders), 1)
        published = reminders[0]
        self.assertEqual(published['actor'], self.root['member_id'])          # identidad de coordinacion
        self.assertEqual(published['to'], self.member['member_id'])           # destinatario, no autor
        self.assertIn('follow-up 1/3', published['text'])
        for expected in (2, 3):
            self.advance()
            payload = self.tick()
            self.assertEqual(payload['followups_tick']['reminders'], 1)
            self.assertEqual(self.tasks(payload)[0]['reminders_sent'], expected)
        self.advance()
        payload = self.tick()
        self.assertEqual(payload['followups_tick']['escalations'], 1)
        task = self.tasks(payload)[0]
        self.assertEqual(task['state'], 'escalated')
        self.assertIsNone(task['next_reminder_at'])
        self.assertEqual(payload['team_followups']['stats']['chasing'], 0)
        self.assertEqual(payload['team_followups']['stats']['escalated'], 1)
        escalations = [row for row in payload['team_channel']['messages']
                       if row['topic'] == FOLLOWUP_TOPIC and 'escalado' in row['text']]
        self.assertEqual(len(escalations), 1)
        self.assertEqual(escalations[0]['actor'], self.root['member_id'])
        self.advance()
        payload = self.tick()
        self.assertEqual(payload['followups_tick']['reminders'], 0)   # terminal: no reintenta
        self.assertEqual(payload['followups_tick']['escalations'], 0)

    def test_report_archives_the_chase_and_is_never_reopened(self):
        self.commit()
        self.tick()
        self.publish(self.member, REPORT_TEXT, to=self.member)
        payload = self.tick()
        self.assertEqual([event['event'] for event in payload['team_followups']['events']],
                         ['commitment', 'reported'])
        self.assertEqual(payload['team_followups']['tasks'], [])
        archive = payload['team_followups']['archive']
        self.assertEqual(len(archive), 1)
        self.assertEqual(archive[0]['state'], 'reported')
        self.assertEqual(payload['team_followups']['stats']['archived'], 1)
        self.advance()
        payload = self.tick()
        self.assertEqual(payload['followups_tick']['reminders'], 0)

    # ------------------------------------------------------------------ drenaje

    def test_drain_returns_reminders_with_coordination_authority_and_keeps_other_topics(self):
        self.commit()
        self.tick()
        self.advance()
        self.tick()
        self.publish(self.member, 'nota de coordinacion sin promesa', to=self.member,
                     topic='coordination')
        status, payload = self.post('followups-drain', {'expected_state_version': self.version,
                                                        'member': self.member['member_id'],
                                                        'max_count': 20})
        self.assertEqual(status, 200, payload)
        envelope = payload['followups_drained']
        self.assertEqual(envelope['member'], self.member['member_id'])
        counts = envelope['counts']
        self.assertEqual(counts['reminders'], 1)
        self.assertEqual(counts['delivered'], counts['reminders'] + counts['other'])
        self.assertEqual(len(envelope['reminders']) + len(envelope['other']), counts['delivered'])
        reminder = envelope['reminders'][0]
        self.assertIn('follow-up 1/3', reminder['text'])
        self.assertEqual(reminder['authority']['kind'], 'coordination')
        self.assertIs(reminder['authority']['is_member_authored'], False)
        self.assertEqual(reminder['authority']['role_label'],
                         'Coordinacion local (motor de seguimiento)')
        self.assertTrue(all('authority' not in row for row in envelope['other']))  # otro topico: autor real
        self.assertTrue(any(row.get('topic') == 'coordination' and 'sin promesa' in row['text']
                            for row in envelope['other']))
        status, payload = self.post('followups-drain', {'expected_state_version': self.version,
                                                        'member': self.member['member_id'],
                                                        'max_count': 20})
        self.assertEqual(status, 200)
        self.assertEqual(payload['followups_drained']['counts']['delivered'], 0)   # destructivo

    # ------------------------------------------------------------------ reinicio del motor

    def test_engine_restart_after_roster_change_does_not_duplicate_tasks(self):
        self.commit()
        self.tick()
        self.assertEqual(len(self.tasks(self.tick())), 1)
        agents = self.state.organization['agents']
        added = dict(agents[-1])
        added['id'] = 'agente-nuevo-p3'
        added['slot'] = max(int(agent.get('slot') or 0) for agent in agents) + 1
        added['name'] = 'Nuevo Rol P3'
        added['reports_to'] = self.root['member_id']
        agents.append(added)
        view = self.state_view()['team_followups']
        self.assertEqual(view['tasks'], [])          # motor y canal reconstruidos: sin fantasmas
        self.assertEqual(view['stats']['total'], 0)
        self.assertEqual(view['processed_message_ids'], [])
        self.version = self.state.organization.get('state_version', 1)
        self.commit()
        payload = self.tick()
        self.assertEqual(len(self.tasks(payload)), 1)   # una sola, no dos
        self.assertEqual(payload['followups_tick']['commitments'], 1)   # el ledger nuevo no se duplica

    # ------------------------------------------------------------------ sin efectos externos

    def test_actions_only_record_in_the_in_memory_channel(self):
        self.commit()
        payload = self.tick()
        receipts = [row for row in payload['receipts'] if row['action'] == 'followups-tick']
        self.assertEqual(len(receipts), 1)
        self.assertEqual(receipts[0]['status'], 'success')
        self.assertIn('No se ejecutaron agentes ni se llamo a ningun proveedor', receipts[0]['message'])
        self.assertIsNone(self.state.provider_module)
        self.assertIs(payload['team_followups']['in_memory_session_only'], True)
        self.assertIs(payload['capabilities']['agents_runtime'], False)
        self.assertIs(payload['capabilities']['network_on_start'], False)


if __name__ == '__main__':
    unittest.main(verbosity=2)
