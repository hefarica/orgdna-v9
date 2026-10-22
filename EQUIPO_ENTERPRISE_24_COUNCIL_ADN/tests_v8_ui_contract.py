"""V8 static UI contracts. Offline checks, not browser or provider verification."""
from pathlib import Path
from html.parser import HTMLParser
import re
import unittest

ROOT = Path(__file__).resolve().parent

class Markup(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags = []
    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))

class V8UIContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.js = (ROOT / 'web/app.js').read_text(encoding='utf-8')
        cls.html = (ROOT / 'web/index.html').read_text(encoding='utf-8')
        cls.css = (ROOT / 'web/style.css').read_text(encoding='utf-8')
        parser = Markup(); parser.feed(cls.html)
        cls.fields = {a['id']: (tag, a) for tag, a in parser.tags if 'id' in a}

    def test_version_and_exact_catalog_identity_controls(self):
        self.assertIn('V8 · Exactamente N perfiles', self.html)
        for field in ('generation-model-select', 'generation-model-status', 'generation-model-identity', 'generation-discover-models'):
            self.assertIn(field, self.fields)
        self.assertIn("row.source==='live_api'||row.status==='VERIFIED_INFERENCE'", self.js)
        self.assertIn("m.catalog_scope!=='dsh_runtime'", self.js)
        self.assertIn('ID exacto que recibirá la API', self.js)
        self.assertIn('Rutas del diseño DSH conservado', self.js)

    def test_manual_reference_is_explicit_not_configuration_export(self):
        tag, attrs = self.fields['generation-manual-model']
        self.assertEqual(tag, 'input')
        self.assertEqual(attrs['type'], 'checkbox')
        self.assertNotIn('name', attrs)
        self.assertIn('manual_model_confirmed:true', self.js)
        self.assertIn("generationModelFingerprint!==fingerprint", self.js)

    def test_zero_reference_is_not_a_price_or_guaranteed_cap(self):
        self.assertIn('Vacío o 0 significa sin referencia', self.html)
        self.assertIn('Sin referencia definida · vacío o 0 no significa gratuito', self.js)
        self.assertIn('No calculado · no hay una tarifa verificada', self.js)
        self.assertNotIn("String(state.config.llm_budget_usd??0)+' USD", self.js)

    def test_tokens_have_separate_meanings(self):
        for label in ('Entrada estimada · suma de solicitudes', 'Tope solicitado de salida por solicitud', 'Tope nominal efectivo de salida', 'Límites de salida realmente enviados por lote', 'Máximo total de salida · suma de lotes', 'Tokens reales totales'):
            self.assertIn(label, self.js)
        self.assertIn('generation-batch-list', self.fields)

    def test_receipts_have_allowlisted_fields_and_pending_polling(self):
        self.assertIn('generationSafeReceipts', self.js)
        self.assertIn('generationSafeUsage', self.js)
        self.assertIn("schema:'orgdna-generation-diagnostic-ui-v2'", self.js)
        self.assertIn('response_received_not_yet_validated', self.js)
        self.assertIn('generationNeedsPolling()', self.js)
        self.assertIn("state?.generation_job?.receipts_pending===true", self.js)
        self.assertIn('renderCompletedGenerationDiagnostic(result,job)', self.js)
        self.assertIn('No informado no significa 0 ni gratis', self.js)

    def test_exact_authorization_and_download_identity_retained(self):
        preview = self.html.split('id="generation-preview"', 1)[1].split('id="generation-usage"', 1)[0]
        self.assertEqual(preview.count('type="checkbox"'), 1)
        for contract in ('payload_sha256:pending.payload_sha256', 'coverage_sha256:pending.coverage_sha256', 'config_version:pending.config_version??job.config_version', 'data_reviewed:true,budget_acknowledged:true', "'/download/generation-diagnostic.json?job_id='+encodeURIComponent(jobId)"):
            self.assertIn(contract, self.js)
        self.assertIn('No se reintenta automáticamente', self.js)

    def test_evidence_is_path_specific_and_never_claims_semantic_completeness(self):
        for field in ('pending_subtree_paths', 'evidence_distribution', 'common_paths', 'targeted_paths', 'omitted_read_paths', 'content_sha256', 'read_source'):
            self.assertIn(field, self.js)
        self.assertIn('La selección es heurística', self.js)
        self.assertIn('No demuestra comprensión completa', self.js)

    def test_new_css_is_generation_scoped(self):
        """Todo CSS anadido despues del marcador V8 cuelga de un contenedor de pagina.

        El contrato original exigia el prefijo literal `#configuration ` porque hasta V8
        el unico bloque nuevo era el estudio de generacion. GenTeam P2 agrega estilos a
        OTRA pagina (el canal de equipo vive en #council), asi que la regla se enuncia
        por su intencion: ningun selector nuevo puede ser global; debe estar acotado a
        un contenedor de pagina declarado en el propio HTML (seccion .page o el estudio
        de generacion). Un selector global o fuera de esos contenedores sigue fallando.
        """
        added = self.css.split('/* V8:', 1)[1]
        body = re.sub(r'/\*.*?\*/', '', added.split('*/', 1)[1], flags=re.S)
        selectors = re.findall(r'(?:^|\})\s*([^{}]+)\{', body)
        roots = {'#%s' % field for field, (tag, attrs) in self.fields.items()
                 if tag == 'section' and attrs.get('class') == 'page'}
        roots.add('#configuration')
        self.assertGreaterEqual(len(roots), 2, 'debe haber contenedores de pagina declarados')
        for group in selectors:
            if group.strip().startswith('@media'):
                continue
            for selector in group.split(','):
                parts = selector.strip().split(' ', 1)
                self.assertIn(parts[0], roots,
                              'selector fuera de un contenedor de pagina: %s' % selector)
                self.assertEqual(len(parts), 2,
                                 'el selector debe acotarse a un descendiente: %s' % selector)

if __name__ == '__main__':
    unittest.main()
