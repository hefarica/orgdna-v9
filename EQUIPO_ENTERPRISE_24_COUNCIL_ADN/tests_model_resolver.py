"""Falsificación del resolutor de notación de modelos.

El caso central es real: la configuración guardada tiene `DeepSeek-V41-Flash`, que
es el NOMBRE VISIBLE, mientras el ID de API es `deepseek-flash`. Lo que estos casos
protegen es que resolver la notación NO se convierta en elegir otro modelo.
"""
import unittest

from engine import model_resolver as mr

ROWS = [
    {'id': 'deepseek-flash', 'name': 'DeepSeek-V4.1-Flash', 'source': 'official_docs_snapshot', 'available': None},
    {'id': 'deepseek-v4-pro', 'name': 'DeepSeek-V4-Pro-0813', 'source': 'official_docs_snapshot', 'available': None},
]


class NormalizationTests(unittest.TestCase):
    def test_punctuation_is_not_identity(self):
        for value in ('DeepSeek-V41-Flash', 'DeepSeek-V4.1-Flash', 'deepseek v4.1 flash',
                      'DEEPSEEK_V41_FLASH', '  DeepSeek--V41--Flash  '):
            with self.subTest(value=value):
                self.assertEqual(mr.normalize(value), 'deepseekv41flash')

    def test_normalization_never_merges_distinct_models(self):
        self.assertNotEqual(mr.normalize('GLM-5.3-Flash'), mr.normalize('GLM-5.3-FlashX'))
        self.assertNotEqual(mr.normalize('deepseek-flash'), mr.normalize('deepseek-v4-pro'))

    def test_empty_or_non_text_is_empty(self):
        for value in ('', '   ', '---', None, 7):
            with self.subTest(value=value):
                self.assertEqual(mr.normalize(value), '')


class ResolutionTests(unittest.TestCase):
    def test_the_real_case_resolves(self):
        result = mr.resolve('DeepSeek-V41-Flash', ROWS)
        self.assertEqual(result['status'], 'resolved')
        self.assertEqual(result['model_id'], 'deepseek-flash')
        self.assertEqual(result['matched_on'], 'name')
        self.assertIn('DeepSeek-V4.1-Flash', mr.describe(result))

    def test_exact_id_stays_exact(self):
        self.assertEqual(mr.resolve('deepseek-flash', ROWS)['status'], 'exact')
        self.assertEqual(mr.resolve('deepseek-flash', ROWS)['model_id'], 'deepseek-flash')

    def test_same_notation_of_an_id_resolves_without_changing_the_model(self):
        result = mr.resolve('DEEPSEEK_FLASH', ROWS)
        self.assertEqual(result['status'], 'resolved')
        self.assertEqual(result['model_id'], 'deepseek-flash')
        self.assertEqual(result['matched_on'], 'id')

    def test_partial_or_fuzzy_never_resolves(self):
        """Ni subcadena ni parecido: si no es la forma COMPLETA, no hay resolución."""
        for value in ('DeepSeek-V41', 'DeepSeek', 'deepseek', 'flash', 'V4.1', 'gpt-4', 'INVENTED'):
            with self.subTest(value=value):
                result = mr.resolve(value, ROWS)
                self.assertEqual(result['status'], 'unknown', '%r no debe resolver' % value)
                self.assertIsNone(result['model_id'])

    def test_ambiguity_is_never_resolved_by_the_system(self):
        rows = [dict(ROWS[0]), dict(ROWS[1], name='DeepSeek-V4.1-Flash')]
        result = mr.resolve('DeepSeek-V4.1-Flash', rows)
        self.assertEqual(result['status'], 'ambiguous')
        self.assertIsNone(result['model_id'])
        self.assertEqual(len(result['candidates']), 2)
        self.assertIn('no elige por ti', mr.describe(result))

    def test_empty_rows_is_unknown_not_an_invention(self):
        self.assertEqual(mr.resolve('DeepSeek-V41-Flash', [])['status'], 'unknown')

    def test_candidates_carry_the_evidence(self):
        candidate = mr.resolve('DeepSeek-V41-Flash', ROWS)['candidates'][0]
        self.assertEqual(candidate['id'], 'deepseek-flash')
        self.assertEqual(candidate['name'], 'DeepSeek-V4.1-Flash')
        self.assertEqual(candidate['matched_on'], 'name')
        self.assertEqual(candidate['source'], 'official_docs_snapshot')

    def test_malformed_rows_are_rejected(self):
        for rows in ([{'name': 'sin id'}], ['no es dict'], [None]):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                mr.resolve('x', rows)
        with self.assertRaises(ValueError):
            mr.resolve('', ROWS)
        with self.assertRaises(ValueError):
            mr.resolve('x', 'no es lista')

    def test_resolution_is_deterministic_and_digestible(self):
        first, second = mr.resolve('DeepSeek-V41-Flash', ROWS), mr.resolve('DeepSeek-V41-Flash', ROWS)
        self.assertEqual(mr.digest(first), mr.digest(second))
        self.assertRegex(mr.digest(first), r'^[0-9a-f]{64}$')


class WiringTests(unittest.TestCase):
    """El resolutor esta cableado para DIAGNOSTICAR, no para aceptar.

    Dos tests del repositorio prohiben que un nombre visible pase por un ID:
    'test_api_display_name_or_alias_rejected_even_if_manual_preference_exists' y
    'test_provider_alias_does_not_bypass_exact_api_catalog'. Aqui se fija que la
    regla NO se mueve y que el error pasa a decir cual es el ID exacto.
    """

    def _state(self):
        from tests_generation_pipeline import GenerationPipelineTests

        class _Fixture(GenerationPipelineTests):
            def test_fixture(self):
                pass

        case = _Fixture("test_fixture")
        case.setUp()
        self.addCleanup(case.tearDown)
        return case.state

    def test_display_name_is_rejected_but_the_error_names_the_exact_id(self):
        from engine.bridge import BridgeError
        state = self._state()
        state.models = [{"provider": "deepseek-official", "model": "deepseek-flash",
                         "name": "DeepSeek-V4.1-Flash", "source": "official_docs_snapshot",
                         "available": None}]
        with self.assertRaises(BridgeError) as caught:
            state.validate_api_model_choice(dict(state.config, model="DeepSeek-V41-Flash"), manual_confirmed=True)
        message = str(caught.exception)
        self.assertIn("ID elegido para la API no está verificado", message)
        self.assertIn("deepseek-flash", message, "el error debe decir el ID exacto")
        self.assertIn("nombre visible", message)

    def test_exact_id_verification_is_unaffected(self):
        state = self._state()
        row_model = state.config["model"]
        state.models = [{"provider": "deepseek-official", "model": row_model,
                         "source": "live_api", "available": True, "catalog_scope": "provider_api"}]
        receipt = state.validate_api_model_choice(state.config)
        self.assertEqual(receipt["status"], "catalog_verified")
        self.assertEqual(receipt["model"], row_model)

    def test_unresolvable_name_is_named_as_unresolvable(self):
        from engine.bridge import BridgeError
        state = self._state()
        state.models = [{"provider": "deepseek-official", "model": "fixture-model",
                         "source": "live_api", "available": True, "catalog_scope": "provider_api"}]
        with self.assertRaises(BridgeError) as caught:
            state.validate_api_model_choice(dict(state.config, model="INVENTED"))
        self.assertIn("no corresponde a ningun ID ni nombre visible", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
