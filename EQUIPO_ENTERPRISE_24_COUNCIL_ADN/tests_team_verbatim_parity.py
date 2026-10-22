"""Paridad VERBATIM (M6): vectores de `t29` reproducidos contra nuestro codigo.

Dos fragmentos adoptados bajo la ENMIENDA PERMANENTE del operador
(`docs/security/FUSILE_SOURCE_POLICY.md`), tras el gate Tier 2 de `t29`:

  * **AG-F1** — `ag2ai/ag2@0938ebda125d77d35856059df264a30c86ad656e:ag2/events/conditions.py`
    L1-144, Apache-2.0 → condiciones componibles de parada (M2) en `engine/team_loop.py`.
  * **MG-F1** — `FoundationAgents/MetaGPT@11cdf466d042aece04fc6cfd13b28e1a70341b1f:metagpt/team.py`
    L87-100, MIT → corte por presupuesto (M5) en `engine/team_process.py`.

Este modulo hace tres cosas, en este orden:

  1. **Prueba de procedencia**: guarda el texto EXACTO de cada fragmento y comprueba su `sha256`
     contra el declarado en `docs/rea/license_audit.md` / `docs/rea/PORT_REPORT_AGILIDAD.md`
     (01647ee6… para AG-F1 y d13e885a… para MG-F1). Sin red: el texto vive aqui.
  2. **Prueba de copia**: las lineas del fuente, tras aplicar SOLO las sustituciones declaradas en
     la cabecera de cada bloque verbatim, aparecen literalmente en el modulo destino, una vez.
  3. **Prueba de comportamiento**: los casos del test del fuente
     (`test/events/test_conditions.py`, 30 casos) y los 5 vectores derivados de MG-F1 (§4.2 del
     informe) se reproducen contra nuestras clases: entrada del caso -> salida esperada.

Divergencias declaradas (fail-honest, §7 del informe): el fuente AG2 construye condiciones con
azucar de metaclase (`TestEvent.field == "1"`, `AnotherEvent | TestEvent`); aqui se expresan con
`OpCondition`/`TypeCondition` porque esa azucar vive en `ag2.events` (fuera del fragmento
adoptado). MG-F1 no trae test de `_check_balance`: sus vectores son **derivados** del predicado, y
la vista dual `get_costs().total_cost == get_total_cost()` del test de `cost_manager.py` **no** se
reproduce (pertenece a un fichero no adoptado): se declara como divergencia con motivo.

Solo biblioteca estandar; sin red, sin ficheros fuera de la lectura del propio modulo y del texto
guardado aqui.
"""
import hashlib
import unittest
from pathlib import Path

from engine import team_loop as tl
from engine import team_process as tp

SUITE_ROOT = Path(__file__).resolve().parent
LOOP_PATH = SUITE_ROOT / 'engine' / 'team_loop.py'
PROCESS_PATH = SUITE_ROOT / 'engine' / 'team_process.py'

AG_F1_SHA256 = '01647ee672e18da5a663d42aa022f0c2715c3c5bdf0f2a92316e33ecbb0b22e3'
MG_F1_SHA256 = 'd13e885a69080987ea0d5d541cecb2e1a60ce1c57165eca9a505dbc24083b192'
AG_F1_CITATION = 'ag2ai/ag2@0938ebda125d77d35856059df264a30c86ad656e'
MG_F1_CITATION = 'FoundationAgents/MetaGPT@11cdf466d042aece04fc6cfd13b28e1a70341b1f'
VERBATIM_NOTE = 'ENMIENDA PERMANENTE - codigo verbatim'
BEGIN_AG = '# BLOQUE VERBATIM AG-F1'
END_AG = '# ===== FIN BLOQUE VERBATIM AG-F1 ====='
BEGIN_MG = '# BLOQUE VERBATIM MG-F1'
END_MG = '# ===== FIN BLOQUE VERBATIM MG-F1 ====='

#: Texto exacto del fragmento AG-F1 (L1-144 del fuente en el sha citado). Inyectado como literal
#: por `t30`; su sha256 se comprueba abajo, de modo que este archivo es la prueba offline del gate.
AG_F1_SOURCE = '''# Copyright (c) 2026, AG2ai, Inc., AG2ai open-source projects maintainers and core contributors
#
# SPDX-License-Identifier: Apache-2.0

import operator
from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any

from ag2.types import ClassInfo


class Condition(ABC):
    @abstractmethod
    def __call__(self, event: Any) -> bool:
        raise NotImplementedError

    def __and__(self, other: Any) -> "AndCondition":
        return self.and_(other)

    def and_(self, other: Any) -> "AndCondition":
        if not isinstance(other, Condition):
            other = TypeCondition(other)
        return AndCondition(self, other)

    def __or__(self, other: Any) -> "OrCondition":
        return self.or_(other)

    def or_(self, other: Any) -> "OrCondition":
        if not isinstance(other, Condition):
            other = TypeCondition(other)
        return OrCondition(self, other)

    def __invert__(self) -> "NotCondition":
        return self.not_()

    def not_(self) -> "NotCondition":
        return NotCondition(self)


class TypeCondition(Condition):
    def __init__(self, t: ClassInfo) -> None:
        self._expected_type = t

    def __call__(self, event: Any) -> bool:
        return isinstance(event, self._expected_type)

    def __repr__(self) -> str:
        if isinstance(self._expected_type, type):
            return f"IsType({self._expected_type.__name__})"
        elif isinstance(self._expected_type, tuple):
            names = [t.__name__ if isinstance(t, type) else str(t) for t in self._expected_type]
            return f"IsType({' | '.join(names)})"
        else:
            return f"IsType({self._expected_type})"


class AndCondition(Condition):
    def __init__(self, *conditions: Condition) -> None:
        self.conditions = conditions

    def __call__(self, event: Any) -> bool:
        return all(condition(event) for condition in self.conditions)

    def __repr__(self) -> str:
        flattened: list[Condition] = []
        for c in self.conditions:
            if isinstance(c, AndCondition):
                flattened.extend(c.conditions)
            else:
                flattened.append(c)
        parts = " & ".join(f"{c!r}" for c in flattened)
        return f"And({parts})"


class OrCondition(Condition):
    def __init__(self, *conditions: Condition) -> None:
        self.conditions = conditions

    def __call__(self, event: Any) -> bool:
        return any(condition(event) for condition in self.conditions)

    def __repr__(self) -> str:
        flattened: list[Condition] = []
        for c in self.conditions:
            if isinstance(c, OrCondition):
                flattened.extend(c.conditions)
            else:
                flattened.append(c)
        parts = " | ".join(f"{c!r}" for c in flattened)
        return f"Or({parts})"


class NotCondition(Condition):
    def __init__(self, condition: Condition) -> None:
        self.condition = condition

    def __call__(self, event: Any) -> bool:
        return not self.condition(event)

    def __repr__(self) -> str:
        return f"~{self.condition!r}"


class OpCondition(Condition):
    def __init__(
        self,
        op_func: Callable[[Any, Any], bool],
        field_name: str,
        value: Any,
        event_class: type,
    ) -> None:
        self.op_func = op_func
        self.field_name = field_name
        self.value = value
        self.event_class = event_class

    def __call__(self, event: Any) -> bool:
        if not isinstance(event, self.event_class):
            return False

        field_value = getattr(event, self.field_name, None)
        return self.op_func(field_value, self.value)

    def __repr__(self) -> str:
        op_name = op_names.get(self.op_func, "?")
        return f"Is({self.event_class.__name__}.{self.field_name} {op_name} {self.value!r})"


def check_eq(x: Any, y: Any) -> Any:
    if not isinstance(x, type(y)):
        return False
    return x == y


op_names = {
    check_eq: "==",
    operator.ne: "!=",
    operator.lt: "<",
    operator.le: "<=",
    operator.gt: ">",
    operator.ge: ">=",
    operator.is_: "is",
}'''

#: Texto exacto del fragmento MG-F1 (L87-100 del fuente en el sha citado).
MG_F1_SOURCE = '''    @property
    def cost_manager(self):
        """Get cost manager"""
        return self.env.context.cost_manager

    def invest(self, investment: float):
        """Invest company. raise NoMoneyException when exceed max_budget."""
        self.investment = investment
        self.cost_manager.max_budget = investment
        logger.info(f"Investment: ${investment}.")

    def _check_balance(self):
        if self.cost_manager.total_cost >= self.cost_manager.max_budget:
            raise NoMoneyException(self.cost_manager.total_cost, f"Insufficient funds: {self.cost_manager.max_budget}")'''


def module_text(path):
    return path.read_text('utf-8')


def block_of(text, begin, end):
    start = text.index(begin)
    stop = text.index(end, start)
    return text[start:stop]


def declared_ag_f1_body():
    """Lineas 11-144 del fuente: lo unico que debe aparecer literalmente (L1-10 son la cabecera)."""
    return '\n'.join(AG_F1_SOURCE.split('\n')[10:])


def declared_mg_f1_body():
    """Aplica las sustituciones declaradas A1-A3 al fragmento (A2 elimina la linea del logger)."""
    lines = []
    for line in MG_F1_SOURCE.split('\n'):
        if 'logger.info' in line:
            continue
        lines.append(line.replace('self.env.context.cost_manager', 'self._cost')
                         .replace('NoMoneyException(', '_BudgetExhausted('))
    return '\n'.join(lines)


class ProvenanceTests(unittest.TestCase):
    """El texto guardado es el del sha autorizado por t29 (prueba offline, sin red)."""

    def test_ag_f1_source_hash_matches_the_licence_audit(self):
        digest = hashlib.sha256(AG_F1_SOURCE.encode('utf-8')).hexdigest()
        self.assertEqual(digest, AG_F1_SHA256)

    def test_mg_f1_source_hash_matches_the_licence_audit(self):
        digest = hashlib.sha256(MG_F1_SOURCE.encode('utf-8')).hexdigest()
        self.assertEqual(digest, MG_F1_SHA256)

    def test_ag_f1_has_the_144_lines_and_carries_its_spdx_header(self):
        lines = AG_F1_SOURCE.split('\n')
        self.assertEqual(len(lines), 144)
        self.assertIn('SPDX-License-Identifier: Apache-2.0', lines[2])
        self.assertIn('Copyright (c) 2026, AG2ai, Inc.', lines[0])

    def test_mg_f1_has_the_14_lines_and_the_verbatim_predicate(self):
        lines = MG_F1_SOURCE.split('\n')
        self.assertEqual(len(lines), 14)
        self.assertIn('def _check_balance(self):', AG_F1_SOURCE + MG_F1_SOURCE)
        self.assertIn('if self.cost_manager.total_cost >= self.cost_manager.max_budget:',
                      MG_F1_SOURCE)


class CopyTests(unittest.TestCase):
    """Lo copiado esta en el destino, una sola vez, y solo dentro de su bloque trazado."""

    def test_ag_f1_body_appears_verbatim_in_team_loop(self):
        body = declared_ag_f1_body()
        module = module_text(LOOP_PATH)
        block = block_of(module, BEGIN_AG, END_AG)
        self.assertIn(body, block, 'las lineas 11-144 de AG-F1 deben estar literales en el bloque')
        self.assertEqual(module.count(body), 1, 'el fragmento no puede estar duplicado')

    def test_mg_f1_body_appears_after_the_declared_substitutions(self):
        body = declared_mg_f1_body()
        module = module_text(PROCESS_PATH)
        block = block_of(module, BEGIN_MG, END_MG)
        self.assertIn(body, block, 'MG-F1 con A1-A3 aplicadas debe estar literal en el bloque')
        self.assertEqual(module.count(body), 1)

    def test_each_block_is_delimited_cited_and_licensed(self):
        for path, begin, end, citation, licence in (
                (LOOP_PATH, BEGIN_AG, END_AG, AG_F1_CITATION, 'Apache-2.0'),
                (PROCESS_PATH, BEGIN_MG, END_MG, MG_F1_CITATION, 'MIT')):
            with self.subTest(block=begin):
                module = module_text(path)
                self.assertEqual(module.count(begin), 1)
                self.assertEqual(module.count(end), 1)
                block = block_of(module, begin, end)
                self.assertIn(citation, block, 'falta la cita owner/name@sha')
                self.assertIn(VERBATIM_NOTE, block, 'falta la nota de la enmienda')
                self.assertIn(licence, block, 'falta la licencia SPDX')
                self.assertIn('sha256', block)
                # La cabecera del modulo tambien declara el origen (trazabilidad, no solo el bloque).
                self.assertIn(citation, module.split('"""')[1])

    def test_no_untraced_third_party_block(self):
        """Cada linea larga (>40 caracteres) del fuente aparece SOLO dentro de su bloque."""
        module = module_text(LOOP_PATH)
        block = block_of(module, BEGIN_AG, END_AG)
        outside = module.replace(block, '')
        for line in AG_F1_SOURCE.split('\n'):
            if len(line) > 40 and line.strip():
                with self.subTest(line=line[:40]):
                    self.assertNotIn(line, outside)
        process = module_text(PROCESS_PATH)
        process_block = block_of(process, BEGIN_MG, END_MG)
        process_outside = process.replace(process_block, '')
        for line in MG_F1_SOURCE.split('\n'):
            if len(line) > 40 and line.strip():
                with self.subTest(line=line[:40]):
                    self.assertNotIn(line, process_outside)

    def test_only_the_two_authorised_blocks_exist(self):
        modules = module_text(LOOP_PATH) + module_text(PROCESS_PATH)
        self.assertEqual(modules.count('BLOQUE VERBATIM'), 4)  # 2 cabeceras + 2 cierres
        # La nota aparece en cada cabecera y, ademas, en el docstring del fragmento MG-F1.
        self.assertGreaterEqual(modules.count(VERBATIM_NOTE), 2)
        for path, begin, end in ((LOOP_PATH, BEGIN_AG, END_AG), (PROCESS_PATH, BEGIN_MG, END_MG)):
            with self.subTest(block=begin):
                self.assertIn(VERBATIM_NOTE, block_of(module_text(path), begin, end))


class TestEvent:
    """Espejo minimo del `TestEvent(BaseEvent)` del fuente: campos por atributo."""

    def __init__(self, **fields):
        self.__dict__.update(fields)


class ChildEvent(TestEvent):
    pass


class AnotherEvent:
    def __init__(self, **fields):
        self.__dict__.update(fields)


def field_condition(op, value, event_class=TestEvent):
    """Azucar del fuente (`TestEvent.field <op> valor`) -> `OpCondition` del fragmento."""
    return tl.OpCondition(op, 'field', value, event_class)


class AgF1SourceCaseParityTests(unittest.TestCase):
    """Los 30 casos de `test/events/test_conditions.py` (AG-F1), uno a uno."""

    def test_case_01_equality_condition_string(self):
        condition = field_condition(tl.check_eq, '1')
        self.assertTrue(condition(TestEvent(field='1')))
        self.assertFalse(condition(TestEvent(field='2')))
        self.assertFalse(condition(TestEvent(field=2)))

    def test_case_02_equality_condition_integer(self):
        condition = field_condition(tl.check_eq, 42)
        self.assertTrue(condition(TestEvent(field=42)))
        self.assertFalse(condition(TestEvent(field=41)))
        self.assertFalse(condition(TestEvent(field='42')))

    def test_case_03_inequality_condition(self):
        condition = field_condition(tl.operator.ne, '1')
        self.assertFalse(condition(TestEvent(field='1')))
        self.assertTrue(condition(TestEvent(field='2')))
        self.assertTrue(condition(TestEvent(field=2)))

    def test_case_04_less_than_condition(self):
        condition = field_condition(tl.operator.lt, 10)
        self.assertTrue(condition(TestEvent(field=5)))
        self.assertTrue(condition(TestEvent(field=9)))
        self.assertFalse(condition(TestEvent(field=10)))
        self.assertFalse(condition(TestEvent(field=15)))

    def test_case_05_less_than_or_equal_condition(self):
        condition = field_condition(tl.operator.le, 10)
        self.assertTrue(condition(TestEvent(field=5)))
        self.assertTrue(condition(TestEvent(field=10)))
        self.assertFalse(condition(TestEvent(field=11)))

    def test_case_06_greater_than_condition(self):
        condition = field_condition(tl.operator.gt, 10)
        self.assertFalse(condition(TestEvent(field=10)))
        self.assertTrue(condition(TestEvent(field=11)))
        self.assertTrue(condition(TestEvent(field=20)))

    def test_case_07_greater_than_or_equal_condition(self):
        condition = field_condition(tl.operator.ge, 10)
        self.assertFalse(condition(TestEvent(field=9)))
        self.assertTrue(condition(TestEvent(field=10)))
        self.assertTrue(condition(TestEvent(field=20)))

    def test_case_08_and_condition(self):
        condition = field_condition(tl.operator.gt, 0) & field_condition(tl.operator.lt, 10)
        for value in (5, 1, 9):
            self.assertTrue(condition(TestEvent(field=value)), value)
        for value in (0, 10, -5, 15):
            self.assertFalse(condition(TestEvent(field=value)), value)

    def test_case_09_or_condition(self):
        condition = field_condition(tl.operator.lt, 0) | field_condition(tl.operator.gt, 10)
        self.assertTrue(condition(TestEvent(field=-5)))
        self.assertTrue(condition(TestEvent(field=15)))
        for value in (0, 5, 10):
            self.assertFalse(condition(TestEvent(field=value)), value)

    def test_case_10_or_condition_with_class(self):
        condition = (field_condition(tl.operator.gt, 10) | tl.TypeCondition(AnotherEvent)
                     | field_condition(tl.operator.lt, 0))
        self.assertTrue(condition(TestEvent(field=15)))
        self.assertTrue(condition(AnotherEvent(field='')))
        self.assertTrue(condition(TestEvent(field=-5)))
        self.assertFalse(condition(TestEvent(field=0)))

    def test_case_11_or_condition_with_class_first(self):
        condition = tl.TypeCondition(AnotherEvent) | field_condition(tl.operator.gt, 10)
        self.assertTrue(condition(TestEvent(field=15)))
        self.assertTrue(condition(AnotherEvent(field='')))
        self.assertFalse(condition(TestEvent(field=0)))

    def test_case_12_or_condition_with_class_or_method(self):
        condition = tl.TypeCondition(AnotherEvent).or_(field_condition(tl.operator.gt, 10))
        self.assertTrue(condition(TestEvent(field=15)))
        self.assertTrue(condition(AnotherEvent(field='')))
        self.assertFalse(condition(TestEvent(field=0)))

    def test_case_13_or_condition_with_union_classes(self):
        condition = tl.TypeCondition(AnotherEvent) | tl.TypeCondition(TestEvent)
        self.assertTrue(condition(TestEvent(field=15)))
        self.assertTrue(condition(AnotherEvent(field='')))

    def test_case_14_and_method(self):
        condition = field_condition(tl.operator.gt, 0).and_(field_condition(tl.operator.lt, 10))
        for value in (5, 1, 9):
            self.assertTrue(condition(TestEvent(field=value)), value)
        for value in (0, 10, -5, 15):
            self.assertFalse(condition(TestEvent(field=value)), value)

    def test_case_15_or_method(self):
        condition = field_condition(tl.operator.lt, 0).or_(field_condition(tl.operator.gt, 10))
        self.assertTrue(condition(TestEvent(field=-5)))
        self.assertTrue(condition(TestEvent(field=15)))
        for value in (0, 5, 10):
            self.assertFalse(condition(TestEvent(field=value)), value)

    def test_case_16_not_condition(self):
        condition = ~field_condition(tl.check_eq, '1')
        self.assertFalse(condition(TestEvent(field='1')))
        self.assertTrue(condition(TestEvent(field='2')))
        self.assertTrue(condition(TestEvent(field=2)))

    def test_case_17_not_method(self):
        condition = field_condition(tl.check_eq, '1').not_()
        self.assertFalse(condition(TestEvent(field='1')))
        self.assertTrue(condition(TestEvent(field='2')))
        self.assertTrue(condition(TestEvent(field=2)))

    def test_case_18_complex_condition(self):
        condition = ((field_condition(tl.operator.ge, 0) & field_condition(tl.operator.le, 10))
                     | field_condition(tl.check_eq, 100))
        for value in (0, 5, 10, 100):
            self.assertTrue(condition(TestEvent(field=value)), value)
        for value in (-1, 11, 99):
            self.assertFalse(condition(TestEvent(field=value)), value)

    def test_case_19_event_with_multiple_fields(self):
        event = TestEvent(field='test', value=42, name='example')
        self.assertEqual(event.field, 'test')
        self.assertEqual(event.value, 42)
        self.assertEqual(event.name, 'example')
        self.assertTrue(field_condition(tl.check_eq, 'test')(event))

    def test_case_20_condition_with_none_value(self):
        condition = field_condition(tl.check_eq, None)
        self.assertTrue(condition(TestEvent(field=None)))
        self.assertFalse(condition(TestEvent(field='test')))
        self.assertFalse(condition(TestEvent(field=0)))

    def test_case_21_condition_with_is_none_value(self):
        condition = field_condition(tl.operator.is_, None)
        self.assertTrue(condition(TestEvent(field=None)))
        self.assertFalse(condition(TestEvent(field='test')))
        self.assertFalse(condition(TestEvent(field=0)))

    def test_case_22_condition_with_boolean(self):
        condition = field_condition(tl.check_eq, True)
        self.assertTrue(condition(TestEvent(field=True)))
        self.assertFalse(condition(TestEvent(field=False)))
        self.assertFalse(condition(TestEvent(field=1)))

    def test_case_23_chained_conditions(self):
        condition = (field_condition(tl.operator.gt, 0) & field_condition(tl.operator.lt, 100)
                     & field_condition(tl.operator.ne, 50))
        self.assertTrue(condition(TestEvent(field=25)))
        self.assertTrue(condition(TestEvent(field=75)))
        for value in (0, 100, 50):
            self.assertFalse(condition(TestEvent(field=value)), value)

    def test_case_24_condition_matches_subclass(self):
        condition = field_condition(tl.check_eq, '1', TestEvent)
        self.assertTrue(condition(TestEvent(field='1')))
        self.assertTrue(condition(ChildEvent(field='1')))

    def test_case_25_child_condition_does_not_match_parent(self):
        condition = field_condition(tl.check_eq, '1', ChildEvent)
        self.assertTrue(condition(ChildEvent(field='1')))
        self.assertFalse(condition(TestEvent(field='1')))

    def test_case_26_reading_an_inherited_field_elsewhere_does_not_retarget(self):
        condition = field_condition(tl.check_eq, '1', TestEvent)
        self.assertTrue(condition(TestEvent(field='1')))

    def test_case_27_invert_event_class(self):
        condition = ~tl.TypeCondition(TestEvent)
        self.assertFalse(condition(TestEvent(field='1')))
        self.assertFalse(condition(ChildEvent(field='1')))
        self.assertTrue(condition(AnotherEvent(field='test')))

    def test_case_28_invert_event_class_composition(self):
        condition = ~tl.TypeCondition(TestEvent) & field_condition(tl.check_eq, 'ok', AnotherEvent)
        self.assertFalse(condition(TestEvent(field='1')))
        self.assertTrue(condition(AnotherEvent(field='ok')))
        self.assertFalse(condition(AnotherEvent(field='nope')))

    def test_case_29_not_method_on_event_class(self):
        condition = tl.TypeCondition(TestEvent).not_()
        self.assertFalse(condition(TestEvent(field='1')))
        self.assertTrue(condition(AnotherEvent(field='test')))

    def test_case_30_different_event_with_condition(self):
        condition = field_condition(tl.check_eq, '1', TestEvent)
        self.assertTrue(condition(TestEvent(field='1')))
        self.assertFalse(condition(AnotherEvent(field='1')))

    def test_check_eq_is_type_strict_and_supports_bool_and_none(self):
        self.assertFalse(tl.check_eq(2, '1'))
        self.assertTrue(tl.check_eq('1', '1'))
        self.assertFalse(tl.check_eq(1, True))
        self.assertTrue(tl.check_eq(True, True))
        self.assertTrue(tl.check_eq(None, None))
        self.assertFalse(tl.check_eq('None', None))

    def test_repr_uses_the_verbatim_op_names_map(self):
        self.assertEqual(repr(field_condition(tl.check_eq, 1)), 'Is(TestEvent.field == 1)')
        self.assertEqual(repr(field_condition(tl.operator.ne, 1)), 'Is(TestEvent.field != 1)')
        self.assertEqual(repr(field_condition(tl.operator.lt, 10)), 'Is(TestEvent.field < 10)')
        self.assertEqual(repr(field_condition(tl.operator.le, 10)), 'Is(TestEvent.field <= 10)')
        self.assertEqual(repr(field_condition(tl.operator.gt, 10)), 'Is(TestEvent.field > 10)')
        self.assertEqual(repr(field_condition(tl.operator.ge, 10)), 'Is(TestEvent.field >= 10)')
        self.assertEqual(repr(field_condition(tl.operator.is_, None)), 'Is(TestEvent.field is None)')
        self.assertEqual(repr(tl.TypeCondition(TestEvent)), 'IsType(TestEvent)')
        flattened = (field_condition(tl.operator.gt, 0) & field_condition(tl.operator.lt, 10)
                     & field_condition(tl.operator.ne, 5))
        self.assertEqual(repr(flattened),
                         'And(Is(TestEvent.field > 0) & Is(TestEvent.field < 10)'
                         ' & Is(TestEvent.field != 5))')
        self.assertTrue(repr(~field_condition(tl.check_eq, '1')).startswith('~Is('))


class MgF1VectorParityTests(unittest.TestCase):
    """Los 5 vectores derivados de MG-F1 (§4.2 del informe) + la forma de acumulacion."""

    def test_vector_1_invest_sets_the_ceiling(self):
        balance = tp._BudgetBalance()
        balance.invest(3.0)
        self.assertEqual(balance.cost_manager.max_budget, 3.0)

    def test_vector_2_below_the_ceiling_does_not_cut(self):
        balance = tp._BudgetBalance(max_budget=3.0, total_cost=2.999)
        balance._check_balance()  # no lanza
        self.assertFalse(balance.is_exhausted())

    def test_vector_3_exact_boundary_cuts(self):
        balance = tp._BudgetBalance(max_budget=3.0, total_cost=3.0)
        with self.assertRaises(tp._BudgetExhausted) as caught:
            balance._check_balance()
        self.assertEqual(caught.exception.code, 'budget_exhausted')
        self.assertEqual(str(caught.exception), 'budget_exhausted: Insufficient funds: 3.0')
        self.assertTrue(balance.is_exhausted())

    def test_vector_4_above_the_ceiling_cuts(self):
        balance = tp._BudgetBalance(max_budget=3.0, total_cost=3.001)
        with self.assertRaises(tp._BudgetExhausted):
            balance._check_balance()

    def test_vector_5_no_prior_invest_uses_the_injected_ceiling(self):
        balance = tp._BudgetBalance(max_budget=12, total_cost=12)
        self.assertIsNone(balance.investment)
        self.assertTrue(balance.is_exhausted())
        self.assertEqual(balance.cost_manager.max_budget, 12)

    def test_vector_6_accumulation_shape_is_monotonic(self):
        balance = tp._BudgetBalance(max_budget=10.0)
        first = balance.cost_manager.update_cost(0.25)
        second = balance.cost_manager.update_cost(0.5)
        self.assertLessEqual(first, second)
        self.assertEqual(second, 0.75)
        self.assertFalse(balance.is_exhausted())
        # DIVERGENCIA DECLARADA: la vista dual del fuente
        # (`get_costs().total_cost == get_total_cost()`) pertenece a
        # `metagpt/utils/cost_manager.py`, que NO se adopta; aqui solo se reproduce la
        # monotonia no decreciente, que es la forma de la asercion del test del fuente.
        self.assertFalse(hasattr(balance.cost_manager, 'get_total_cost'))

    def test_undeclared_ceiling_never_cuts(self):
        balance = tp._BudgetBalance(total_cost=10 ** 9)
        self.assertFalse(balance.is_exhausted())

    def test_the_process_uses_the_adopted_predicate_at_the_boundary(self):
        """El predicado no es decorativo: el corte del borde exacto sale de `_check_balance`."""
        clock = _FakeClock()
        process = tp.TeamProcess([{'slot': index, 'member_id': 'm%d' % index, 'role': 'r'}
                                   for index in (1, 2, 3)],
                                  worker=lambda request: {request['slots'][0]: {'state': 'success',
                                                                                'result': 'ok'}},
                                  clock=clock, budget={'steps': 2})
        report = process.run()
        self.assertEqual(report['cycle_state'], 'budget_exhausted')
        self.assertEqual(report['exhausted'], {'reason': 'steps'})
        self.assertEqual(report['steps_advanced'], 2)
        self.assertEqual(report['budget_consumed']['steps'], 2)


class ExclusionTests(unittest.TestCase):
    """Los fragmentos no caen en ninguno de los 5 supuestos de exclusion de la enmienda."""

    FORBIDDEN = ('socket', 'urllib', 'requests', 'http', 'subprocess', 'os.system', 'eval(',
                 'exec(', '__import__', 'open(', 'pickle', 'random', 'time.', 'getenv', 'environ',
                 'dsh', 'DSH', '.dsh-vscode')

    def _blocks(self):
        loop = module_text(LOOP_PATH)
        process = module_text(PROCESS_PATH)
        return {'AG-F1': block_of(loop, BEGIN_AG, END_AG),
                'MG-F1': block_of(process, BEGIN_MG, END_MG)}

    def test_no_network_process_or_file_tokens_in_the_blocks(self):
        for label, block in self._blocks().items():
            for token in self.FORBIDDEN:
                with self.subTest(block=label, token=token):
                    self.assertNotIn(token, block)

    def test_no_policy_gate_or_sandbox_evasion(self):
        for label, block in self._blocks().items():
            for token in ('policy_engine', 'approval', 'sandbox', 'can_execute', 'gate'):
                with self.subTest(block=label, token=token):
                    self.assertNotIn(token.lower(), block.lower())

    def test_fragments_are_pure_logic_without_side_effects(self):
        source = declared_ag_f1_body() + '\n' + declared_mg_f1_body()
        for token in ('import ', 'open(', 'print(', 'global ', 'nonlocal '):
            with self.subTest(token=token):
                self.assertNotIn(token, source)


class _FakeClock:
    def __init__(self, moment=1000.0):
        self.moment = float(moment)

    def __call__(self):
        return self.moment


if __name__ == '__main__':
    unittest.main(verbosity=2)
