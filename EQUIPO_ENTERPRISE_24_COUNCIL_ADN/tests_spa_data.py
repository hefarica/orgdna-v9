#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Canales de datos de SPA sin JavaScript: contrato de t16/t17 hecho codigo.

Se prueban los tres canales MEDIDOS (Nuxt /_payload.json, Next con la cabecera
RSC: 1, endpoints citados por los bundles del propio sitio) y las dos trampas que
t16 midio: un HTTP 200 con el cuerpo del shell no es dato (T1) y filtrar solo por
application/json pierde el canal RSC, que llega como text/x-component (T2).

Sin red: transporte de fixture. Sin navegador: el render se desactiva en setUp.
"""
import hashlib
import unittest
from unittest.mock import patch

from engine import providers
from engine import web_sources as w

BASE = 'https://spa.example'
ROBOTS = b'User-agent: *\nAllow: /'

# Cuerpos de mas de 1 KB: el contrato exige tamano minimo para aceptar un payload.
def nuxt_payload(marca='a'):
    datos = [{'data': 1, 'prerenderedAt': -1}, ['ShallowReactive', 2],
             {'navigation': {'docs': marca * 40, 'sponsors': [marca * 60] * 8}}]
    texto = repr(datos).replace("'", '"')
    return (texto + ' ' * 1100).encode('utf-8')


def flight_payload(marca='b'):
    lineas = ['%d:["$","html",null,{"lang":"en","data":"%s"}]' % (n, marca * 50) for n in range(12)]
    return ('\n'.join(lineas) + '\n').encode('utf-8')


SHELL = (b'<!DOCTYPE html><html><head><title>App</title></head><body><div id="root"></div>'
         b'<script src="/_next/static/chunks/a.js"></script></body></html>')
NEXT_MARKS = (b'<html><head><title>App</title><script>self.__next_f=[]</script>'
              b'<script src="/_next/static/chunks/a.js"></script></head><body><div id="root"></div></body></html>')
NUXT_MARKS = (b'<html><head><title>App</title><script>window.__NUXT__={}</script></head>'
              b'<body><div id="__nuxt"></div></body></html>')
PLAIN = b'<html><head><title>Doc</title></head><body><h1>Contenido real y suficiente para pasar el umbral.</h1></body></html>'


class Fixture:
    """Transporte offline: rutas exactas + respuesta que puede depender de cabeceras."""

    def __init__(self, rutas, robots=ROBOTS):
        self.rutas = dict(rutas)
        self.rutas.setdefault(BASE + '/robots.txt', (200, {'Content-Type': 'text/plain'}, robots))
        self.calls = []

    def __call__(self, method, url, headers, body, timeout, max_bytes):
        self.calls.append((url, {str(k): str(v) for k, v in (headers or {}).items()}))
        entrada = self.rutas.get(url, (404, {}, b''))
        if callable(entrada):
            entrada = entrada(headers or {})
        if len(entrada[2]) > max_bytes:
            raise providers.ResponseTooLarge('response_byte_limit')
        return entrada

    def urls(self):
        return [u for u, _ in self.calls]

    def pedidos_a(self, fragmento):
        return [u for u in self.urls() if fragmento in u]


class Base(unittest.TestCase):
    def setUp(self):
        self.previo = w.RENDER_JS
        w.RENDER_JS = False              # sin navegador: se prueba el canal, no el render
        self.guard = patch('socket.create_connection', side_effect=AssertionError('Offline fixtures only'))
        self.guard.start()
        self.addCleanup(self.guard.stop)
        self.addCleanup(setattr, w, 'RENDER_JS', self.previo)
        w.clear_cache()

    def analizar(self, fixture, **kwargs):
        return w.analyze_website(BASE, transport=fixture, **kwargs)


class CanalNuxtTests(Base):
    def test_payload_json_es_canal_y_la_evidencia_lo_declara(self):
        cuerpo = nuxt_payload()
        fixture = Fixture({BASE + '/': (200, {'Content-Type': 'text/html'}, NUXT_MARKS),
                           BASE + '/_payload.json': (200, {'Content-Type': 'application/json'}, cuerpo)})
        r = self.analizar(fixture)
        self.assertEqual(r['spa_data']['channel'], 'nuxt_payload')
        self.assertFalse(r['spa_data']['js_rendered'])
        self.assertIn('_payload.json', r['spa_data']['mechanism'])
        self.assertTrue(r['spa_data']['determinism']['stable'])
        # P9: dos lecturas para probar determinismo
        self.assertEqual(len(fixture.pedidos_a('/_payload.json')), 2)
        dato = r['spa_data']['payloads'][0]
        self.assertEqual(dato['sha256'], hashlib.sha256(cuerpo).hexdigest())
        self.assertEqual(dato['content_type'], 'application/json')
        ev = [e for e in r['evidence'] if e.get('channel') == 'nuxt_payload']
        self.assertEqual(len(ev), 1)
        self.assertEqual(ev[0]['sha256'], hashlib.sha256(cuerpo).hexdigest())
        self.assertFalse(ev[0]['js_rendered'])
        self.assertTrue(r['evidence'])


class CanalNextRscTests(Base):
    def _fixture(self, cuerpo=None, ctype='text/x-component'):
        cuerpo = flight_payload() if cuerpo is None else cuerpo
        def raiz(headers):
            if str(headers.get('RSC', '')) == '1':
                return (200, {'Content-Type': ctype}, cuerpo)
            return (200, {'Content-Type': 'text/html'}, NEXT_MARKS)
        return Fixture({BASE + '/': raiz})

    def test_rsc_usa_la_cabecera_y_declara_el_canal(self):
        fixture = self._fixture()
        r = self.analizar(fixture)
        self.assertEqual(r['spa_data']['channel'], 'next_rsc')
        self.assertIn('RSC: 1', r['spa_data']['mechanism'])
        # la cabecera se envia de verdad (dos lecturas)
        con_rsc = [h for u, h in fixture.calls if u == BASE + '/' and h.get('RSC') == '1']
        self.assertEqual(len(con_rsc), 2)
        # el parametro ?_rsc=1 NO se usa: no sirve (devuelve el shell)
        self.assertEqual([u for u in fixture.urls() if '_rsc' in u], [])
        self.assertEqual(r['spa_data']['payloads'][0]['content_type'], 'text/x-component')
        self.assertTrue(r['evidence'])

    def test_t2_no_se_pierde_el_canal_por_filtrar_solo_json(self):
        r = self.analizar(self._fixture())
        dato = r['spa_data']['payloads'][0]
        self.assertNotEqual(dato['content_type'], 'application/json')
        self.assertGreater(dato['byte_count'], 1024)
        self.assertEqual(dato['sha256'], hashlib.sha256(flight_payload()).hexdigest())

    def test_t1_200_con_el_shell_no_es_dato(self):
        """La trampa medida: HTTP 200 con text/html y el cuerpo del shell."""
        def raiz(headers):
            return (200, {'Content-Type': 'text/html'}, SHELL)
        fixture = Fixture({BASE + '/': raiz})
        r = self.analizar(fixture)
        self.assertIsNone(r['spa_data']['channel'])
        self.assertEqual(r['spa_data']['payloads'], [])
        motivos = [a['reason'] for a in r['spa_data']['attempts']]
        self.assertTrue(any(m.startswith('content_type_no_permitido') for m in motivos), motivos)
        self.assertEqual(r['evidence'], [])

    def test_no_se_pide_la_ruta_muerta_next_data(self):
        r = self.analizar(self._fixture())
        self.assertNotIn('/_next/data', ' '.join(a['url'] for a in r['spa_data']['attempts']))
        self.assertTrue(r['evidence'])

    def test_cuerpo_que_empieza_por_menor_que_se_descarta_con_cualquier_mime(self):
        r = self.analizar(self._fixture(cuerpo=SHELL, ctype='text/x-component'))
        self.assertEqual(r['spa_data']['payloads'], [])
        motivos = [a['reason'] for a in r['spa_data']['attempts']]
        self.assertIn('shell_body', motivos)
        self.assertEqual(r['evidence'], [])

    def test_dos_lecturas_distintas_no_fijan_la_fuente(self):
        contador = {'n': 0}
        def raiz(headers):
            if str(headers.get('RSC', '')) != '1':
                return (200, {'Content-Type': 'text/html'}, NEXT_MARKS)
            contador['n'] += 1
            cuerpo = flight_payload('b') if contador['n'] % 2 else flight_payload('c')
            return (200, {'Content-Type': 'text/x-component'}, cuerpo)
        r = self.analizar(Fixture({BASE + '/': raiz}))
        self.assertFalse(r['spa_data']['determinism']['stable'])
        self.assertEqual(r['spa_data']['payloads'], [])
        self.assertIn('no_determinista', [a['reason'] for a in r['spa_data']['attempts']])


class DerivadosTests(Base):
    BUNDLE = (b'const a="https://datos.spa.example/ondo/status";'
              b'const b="/api/local-status.json";const c="/_next/static/chunks/b.js";' + b'x' * 1200)

    def _fixture(self):
        return Fixture({BASE + '/': (200, {'Content-Type': 'text/html'}, NEXT_MARKS),
                        BASE + '/_next/static/chunks/a.js': (200, {'Content-Type': 'text/javascript'}, self.BUNDLE),
                        BASE + '/api/local-status.json': (200, {'Content-Type': 'application/json'}, nuxt_payload('c'))})

    def test_deriva_endpoints_same_origin_con_su_fuente(self):
        fixture = self._fixture()
        r = self.analizar(fixture)
        self.assertEqual(r['spa_data']['channel'], 'derived_endpoints')
        self.assertEqual(len(r['spa_data']['bundles_read']), 1)
        sha_bundle = hashlib.sha256(self.BUNDLE).hexdigest()
        self.assertEqual(r['spa_data']['bundles_read'][0]['sha256'], sha_bundle)
        dato = r['spa_data']['payloads'][0]
        self.assertEqual(dato['url'], BASE + '/api/local-status.json')
        self.assertEqual(dato['derived_from'], sha_bundle)
        # X4: cada URL pedida traza a un sha; los .js no se piden como datos
        self.assertEqual(fixture.pedidos_a('/_next/static/chunks/b.js'), [])

    def test_cross_origin_nace_cerrado_y_se_registra(self):
        # La firma esta activa por defecto (commit 0878b06), asi que el camino
        # cerrado se prueba pidiendolo EXPLICITAMENTE: sin firma no se pide nada.
        fixture = self._fixture()
        r = self.analizar(fixture, allow_derived_cross_origin=False)
        self.assertEqual(fixture.pedidos_a('datos.spa.example'), [])
        self.assertEqual([c['host'] for c in r['spa_data']['cross_origin_candidates']], ['datos.spa.example'])
        motivos = [(a['reason'], a.get('host')) for a in r['spa_data']['attempts']]
        self.assertIn(('cross_origin_sin_firma', 'datos.spa.example'), motivos)

    def test_cross_origin_con_firma_pide_robots_del_host_antes(self):
        fixture = self._fixture()
        fixture.rutas['https://datos.spa.example/robots.txt'] = (200, {'Content-Type': 'text/plain'}, ROBOTS)
        fixture.rutas['https://datos.spa.example/ondo/status'] = (200, {'Content-Type': 'application/json'},
                                                                     nuxt_payload('d'))
        r = self.analizar(fixture, allow_derived_cross_origin=True)
        urls = fixture.urls()
        self.assertIn('https://datos.spa.example/robots.txt', urls)
        self.assertIn('https://datos.spa.example/ondo/status', urls)
        self.assertLess(urls.index('https://datos.spa.example/robots.txt'),
                        urls.index('https://datos.spa.example/ondo/status'))
        self.assertTrue(any(p['url'] == 'https://datos.spa.example/ondo/status'
                            for p in r['spa_data']['payloads']))
        self.assertTrue(r['spa_data']['allow_derived_cross_origin'])

    def test_endpoint_que_devuelve_el_shell_no_entra(self):
        fixture = self._fixture()
        fixture.rutas[BASE + '/api/local-status.json'] = (200, {'Content-Type': 'application/json'}, SHELL)
        r = self.analizar(fixture)
        self.assertEqual(r['spa_data']['payloads'], [])
        self.assertIn('shell_body', [a['reason'] for a in r['spa_data']['attempts']])


class SinCanalTests(Base):
    def test_sin_marcadores_no_hay_peticiones_extra(self):
        fixture = Fixture({BASE + '/': (200, {'Content-Type': 'text/html'}, PLAIN)})
        r = self.analizar(fixture)
        self.assertEqual(fixture.urls(), [BASE + '/robots.txt', BASE + '/'])
        self.assertIsNone(r['spa_data']['channel'])
        self.assertIn('sin_marcadores_de_spa', r['spa_data']['limitations'])

    def test_presupuesto_agotado_no_revienta_y_declara_el_motivo(self):
        fixture = Fixture({BASE + '/': (200, {'Content-Type': 'text/html'}, NEXT_MARKS)})
        r = self.analizar(fixture, max_requests=2)
        self.assertEqual(r['spa_data']['payloads'], [])
        motivos = [a['reason'] for a in r['spa_data']['attempts']]
        self.assertTrue(motivos and ('request_budget' in motivos[0] or 'spa_request_budget' in motivos[0]), motivos)

    def test_robots_que_deniega_no_abre_canales(self):
        fixture = Fixture({BASE + '/': (200, {'Content-Type': 'text/html'}, NEXT_MARKS)},
                          robots=b'User-agent: *\nDisallow: /')
        r = self.analizar(fixture)
        self.assertEqual(r['spa_data']['payloads'], [])
        self.assertIn('root_html_no_disponible', r['spa_data']['limitations'])
        self.assertEqual(fixture.urls(), [BASE + '/robots.txt'])

    def test_robots_ok_pero_raiz_ilegible_no_inventa_canales(self):
        fixture = Fixture({BASE + '/': (500, {'Content-Type': 'text/html'}, b'')})
        r = self.analizar(fixture)
        self.assertEqual(r['spa_data']['payloads'], [])
        self.assertIn('root_html_no_disponible', r['spa_data']['limitations'])


class ResumenTests(Base):
    def _resumen_con_payload(self):
        fixture = Fixture({BASE + '/': (200, {'Content-Type': 'text/html'}, NUXT_MARKS),
                           BASE + '/_payload.json': (200, {'Content-Type': 'application/json'}, nuxt_payload())})
        return self.analizar(fixture)

    def test_el_payload_da_evidencia_aunque_el_html_sea_solo_el_cascaron(self):
        r = self._resumen_con_payload()
        self.assertEqual(r['snapshots'][0]['content_status'], 'javascript_shell')
        self.assertTrue(r['evidence'], 'el dato del canal debe contar como evidencia')
        self.assertEqual(r['coverage']['status'], 'partial')
        self.assertIn('spa_data_via_static_channels_without_javascript', r['coverage']['limitations'])
        seguro = w.prepare_website_summary(r)          # no lanza: hay evidencia
        canal = [e for e in seguro['evidence'] if e.get('channel') == 'nuxt_payload']
        self.assertTrue(canal)
        self.assertIs(canal[0]['js_rendered'], False)

    def test_prepare_conserva_el_canal_y_es_idempotente(self):
        r = self._resumen_con_payload()
        seguro = w.prepare_website_summary(r)
        self.assertEqual(seguro['spa_data']['channel'], 'nuxt_payload')
        self.assertFalse(seguro['spa_data']['js_rendered'])
        payloads = [e for e in seguro['evidence'] if e.get('channel') == 'nuxt_payload']
        self.assertEqual(len(payloads), 1)
        self.assertFalse(payloads[0]['js_rendered'])
        self.assertEqual(seguro, w.prepare_website_summary(seguro))

    def test_prepare_rechaza_payload_de_otro_origen_sin_firma(self):
        r = self._resumen_con_payload()
        r['spa_data']['payloads'][0]['url'] = 'https://otro.example/datos.json'
        with self.assertRaises(providers.ProviderError):
            w.prepare_website_summary(r)

    def test_prepare_rechaza_huella_invalida(self):
        r = self._resumen_con_payload()
        r['spa_data']['payloads'][0]['sha256'] = 'no-es-un-sha'
        with self.assertRaises(providers.ProviderError):
            w.prepare_website_summary(r)

    def test_prepare_rechaza_js_rendered_mentiroso(self):
        r = self._resumen_con_payload()
        r['spa_data']['js_rendered'] = True
        with self.assertRaises(providers.ProviderError):
            w.prepare_website_summary(r)


class FalsosPositivosTests(Base):
    """t20: los candidatos de comentarios/cabeceras y las URLs rotas no gastan nada."""

    def _fixture(self, bundle):
        return Fixture({BASE + '/': (200, {'Content-Type': 'text/html'}, NEXT_MARKS),
                        BASE + '/_next/static/chunks/a.js': (200, {'Content-Type': 'text/javascript'}, bundle)})

    def test_host_de_documentacion_no_gasta_peticiones(self):
        bundle = (b'// vendored from https://github.com/zloirock/core-js/blob/v3.38.1/LICENSE\n'
                  b'// see https://nextjs.org/docs/messages/client-side-exception-occurred and https://w3.org/TR/x\n'
                  + b'x' * 1200)
        fixture = self._fixture(bundle)
        r = self.analizar(fixture)
        urls = fixture.urls()
        self.assertEqual([u for u in urls if 'github.com' in u], [])
        self.assertEqual([u for u in urls if 'nextjs.org' in u], [])
        self.assertEqual([u for u in urls if 'w3.org' in u], [])
        rechazos = r['spa_data']['candidates_rejected']
        self.assertGreaterEqual(rechazos.get('host_documentacion', 0), 3)
        self.assertEqual(r['spa_data']['payloads'], [])

    def test_url_malformada_no_llega_a_robots_ni_a_fetch(self):
        # host de un caracter, localhost e IP: el extractor ni siquiera los produce
        # (el patron exige >=2 etiquetas y TLD alfabetico) y el filtro los rechaza.
        bundle = (b'const a="https://a/robots.txt";const b="https://localhost/x.json";'
                  b'const c="https://192.168.1.1/datos.json";' + b'x' * 1200)
        fixture = self._fixture(bundle)
        r = self.analizar(fixture)
        urls = fixture.urls()
        self.assertEqual([u for u in urls if '/robots.txt' in u and 'spa.example' not in u], [])
        self.assertEqual([u for u in urls if 'localhost' in u or '192.168' in u or u.startswith('https://a/')], [])
        self.assertEqual(r['spa_data']['payloads'], [])
        for valor in ('https://a/robots.txt', 'https://localhost/x.json',
                      'https://192.168.1.1/datos.json', 'https://spa.example/',
                      'https://spa.example', 'https://spa.example/a.json#frag'):
            familia, normalizado, motivo = w._spa_candidato_ok(valor, 'spa.example')
            self.assertIsNone(familia, valor)
            self.assertIsNone(normalizado, valor)
            self.assertEqual(motivo, 'url_malformada', valor)

    def test_prioridad_json_y_subdominio_antes_que_el_resto(self):
        bundle = (b'const a="https://cdn.tercero.example/lib.js.map";'
                  b'const b="https://phantom.app/dapp";'
                  b'const c="https://raw-api.spa.example/ondo/status";'
                  b'const d="https://tokens.spa.example/pancakeswap-extended.json";' + b'x' * 1200)
        fixture = self._fixture(bundle)
        fixture.rutas['https://tokens.spa.example/pancakeswap-extended.json'] = (
            200, {'Content-Type': 'application/json'}, nuxt_payload('e'))
        fixture.rutas['https://raw-api.spa.example/ondo/status'] = (
            200, {'Content-Type': 'application/json'}, nuxt_payload('f'))
        fixture.rutas['https://tokens.spa.example/robots.txt'] = (200, {'Content-Type': 'text/plain'}, ROBOTS)
        fixture.rutas['https://raw-api.spa.example/robots.txt'] = (200, {'Content-Type': 'text/plain'}, ROBOTS)
        r = self.analizar(fixture)
        urls = fixture.urls()
        # el host ajeno ni se toca
        self.assertEqual([u for u in urls if 'phantom.app' in u or 'tercero.example' in u], [])
        # el .json del subdominio se pide ANTES que el endpoint sin .json
        self.assertLess(urls.index('https://tokens.spa.example/pancakeswap-extended.json'),
                        urls.index('https://raw-api.spa.example/ondo/status'))
        self.assertEqual(r['spa_data']['payloads'][0]['url'],
                         'https://tokens.spa.example/pancakeswap-extended.json')
        self.assertGreaterEqual(r['spa_data']['candidates_rejected'].get('host_ajeno', 0), 1)

    def test_prepare_normaliza_los_rechazos_y_rechaza_motivos_inventados(self):
        # Con evidencia real (payload Nuxt): el canal 3 no corre si ya hay canal,
        # asi que aqui se comprueba la FORMA normalizada del contador de rechazos.
        fixture = Fixture({BASE + '/': (200, {'Content-Type': 'text/html'}, NUXT_MARKS),
                           BASE + '/_payload.json': (200, {'Content-Type': 'application/json'},
                                                     nuxt_payload('g'))})
        r = self.analizar(fixture)
        self.assertTrue(r['evidence'])
        self.assertEqual(r['spa_data']['candidates_rejected'], {})
        seguro = w.prepare_website_summary(r)
        self.assertIn('candidates_rejected', seguro['spa_data'])
        self.assertEqual(seguro, w.prepare_website_summary(seguro))
        r['spa_data']['candidates_rejected']['inventado'] = 1
        with self.assertRaises(providers.ProviderError):
            w.prepare_website_summary(r)


if __name__ == '__main__':
    unittest.main()

