"""tests_agent_factory.py - la fabrica declara lo que existe y rechaza lo que no."""
import json
import os
import unittest

from universal_agent_factory import (CAPABILITIES, FactoryError, OperatorParams,
                                     absent, available, build, driver_para,
                                     fetch_file, fetch_huggingface, plan)
from engine.limits import MAX_AGENTS

AQUI = os.path.dirname(os.path.abspath(__file__))


def llm_que_cita(prompt):
    d = json.loads(prompt)
    rutas = d.get("RUTAS_VALIDAS") or d.get("RUTAS_DEL_ADN") or []
    if "core_claim" in (d.get("salida") or {}):
        return json.dumps({
            "core_claim": {"text": "espina", "evidence": rutas[:1]},
            "primitives": [{"text": "modulo", "evidence": rutas[1:2] or rutas[:1]}]})
    return json.dumps({
        "name": "Espina", "competency": "mantener",
        "capabilities": [{"text": "verificar", "evidence": rutas[:2]}],
        "blind_spots": ["no cubre on-chain"]})


class RegistroTests(unittest.TestCase):
    def test_catorce_declaradas(self):
        self.assertEqual(len(CAPABILITIES), 14)

    def test_solo_cuatro_implementadas(self):
        self.assertEqual(set(available()), {"REA", "FUSILAR", "SCRAPE", "MICROSERVICE"})

    def test_nueve_ausentes_con_bloqueo(self):
        self.assertEqual(len(absent()), 9)
        for n in absent():
            self.assertTrue(CAPABILITIES[n]["blocker"], n)

    def test_schedule_declarado_ausente_no_vendido(self):
        # el producto ya declara "el llamador no existe": no se puede vender activo
        self.assertEqual(CAPABILITIES["SCHEDULE"]["status"], "declared_absent")

    def test_excel_parcial_por_com_no_ejercitado(self):
        self.assertEqual(CAPABILITIES["EXCEL"]["status"], "partial")
        self.assertIn("NO ejercitado", CAPABILITIES["EXCEL"]["blocker"])

    def test_no_hay_metricas_inventadas_en_el_registro(self):
        blob = json.dumps(CAPABILITIES, ensure_ascii=False)
        self.assertNotIn("2000", blob)
        self.assertNotIn("20x", blob)


class PlanTests(unittest.TestCase):
    def test_plan_sin_gasto(self):
        p = plan(OperatorParams(domains=(AQUI,), max_agents=12))
        self.assertEqual(p["max_agents"], 12)
        self.assertIn("sin gasto", p["nota"])

    def test_limite_max_agents(self):
        with self.assertRaises(FactoryError):
            OperatorParams(domains=(AQUI,), max_agents=MAX_AGENTS + 1)

    def test_sin_dominios(self):
        with self.assertRaises(FactoryError):
            OperatorParams(domains=())

    def test_blockchain_declarado(self):
        with self.assertRaises(FactoryError) as ctx:
            driver_para("ethereum:0x1234")
        self.assertIn("allowlist", str(ctx.exception))

    def test_git_y_web_reconocidos(self):
        self.assertEqual(driver_para("https://github.com/o/r")[1], "git")
        self.assertEqual(driver_para("https://example.com")[1], "web")
        self.assertEqual(driver_para(AQUI)[1], "git")


class BuildTests(unittest.TestCase):
    def test_adn_y_especialista_desde_arbol_local(self):
        r = build(OperatorParams(domains=(AQUI,), max_agents=12), llm_que_cita)
        self.assertEqual(r["adns"], 1)
        self.assertGreater(r["citas_adn"], 0)
        self.assertGreaterEqual(r["cobertura_verificada"], 1)
        self.assertTrue(r["capacidades_ausentes"])

    def test_sin_llm_no_inventa(self):
        with self.assertRaises(FactoryError):
            build(OperatorParams(domains=(AQUI,), max_agents=4), None)

    def test_no_excede_max_agents(self):
        r = build(OperatorParams(domains=(AQUI,), max_agents=3), llm_que_cita)
        self.assertLessEqual(r["especialistas_usados"], 3)


class FuentesRealesTests(unittest.TestCase):
    def test_hf_se_detecta_ANTES_que_web(self):
        # si el orden se invierte, huggingface.co cae en 'web' y se scrappea la
        # pagina en vez de usar su API. Este test fija ese orden.
        self.assertEqual(driver_para("https://huggingface.co/microsoft/DialoGPT-medium")[1],
                         "huggingface")
        self.assertEqual(driver_para("hf:microsoft/DialoGPT-medium")[1], "huggingface")
        self.assertEqual(driver_para("https://example.com")[1], "web")

    def test_archivo_se_detecta_antes_que_git(self):
        self.assertEqual(driver_para(os.path.join(AQUI, "universal_agent_factory.py"))[1], "file")

    def test_fetch_file_devuelve_ruta_real(self):
        ruta = os.path.join(AQUI, "universal_agent_factory.py")
        sid, tipo, rutas, texto = fetch_file(ruta)
        self.assertEqual(tipo, "file")
        self.assertEqual(rutas, (os.path.abspath(ruta),))
        self.assertIn("CAPABILITIES", texto)

    def test_fetch_file_rechaza_inexistente(self):
        with self.assertRaises(FactoryError):
            fetch_file(os.path.join(AQUI, "no_existe_jamas.txt"))

    def test_fetch_hf_rechaza_vacio(self):
        with self.assertRaises(FactoryError):
            fetch_huggingface("")

    def test_build_desde_archivo_local(self):
        r = build(OperatorParams(domains=(os.path.join(AQUI, "universal_agent_factory.py"),),
                                 max_agents=4), llm_que_cita)
        self.assertEqual(r["adns"], 1)
        self.assertGreaterEqual(r["cobertura_verificada"], 1)


if __name__ == "__main__":
    unittest.main()
