#!/usr/bin/env python3
"""OrgDNA local bridge. Python >=3.10; standard library only.

Provider requests require exact, bounded local consent. Windows Excel writes
use the separate COM adapter, only after an explicit apply action. No macros,
VBOM access, security-policy changes, shell commands from a request, or Git jobs.
"""
from __future__ import annotations

if __package__:
    from .limits import MAX_AGENTS
    from . import model_resolver
    from . import gang_assembly, gang_journal, gang_services, gang_supervisor
    from . import gang_registry as _gang_registry_module
else:
    from limits import MAX_AGENTS
    import model_resolver
    import gang_assembly, gang_journal, gang_services, gang_supervisor
    import gang_registry as _gang_registry_module

import argparse
import ctypes
import copy
import hashlib
import hmac
import http.cookies
import io
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit, parse_qs
import webbrowser
import zipfile
import xml.etree.ElementTree as ET

try:
    from .launcher import instance_identity
    from .dsh_launcher import DSHLauncher, ACTIONS as LAUNCHER_ACTIONS
    from .dsh_harness import DSHHarness, ACTIONS as HARNESS_ACTIONS
    from .resource_workflows_adapter import ResourceWorkflows, ACTIONS as RESOURCE_ACTIONS
    from .project_store import ProjectStore
    from .generation_pipeline import GenerationPipeline, ACTIONS as GENERATION_ACTIONS
    from .evaluation_runs import EvaluationRuns
    from .autonomy import normalize_autonomy_config, build_autonomy
    from .integration_recommendations import IntegrationRecommendations, ACTIONS as CAPABILITY_AI_ACTIONS
    from .capability_hub import CapabilityHub, ACTIONS as CAPABILITY_ACTIONS
    from .integration_tools import IntegrationTools, ACTIONS as INTEGRATION_ACTIONS
    from .local_records import ACTIONS as RECORD_ACTIONS, apply_record_action
    from .coordination import CoordinationStore, ACTIONS as COORDINATION_ACTIONS
    from .team_channel import TeamChannel, ChannelError
    from .team_memory import TeamMemoryStore
    from .followups import (FollowupsEngine, FollowupsError, FOLLOWUP_TOPIC,
                            PROVENANCE as FOLLOWUPS_PROVENANCE)
    from .memory_governance import MemoryGovernanceError, MEMORY_ID_PATTERN
    from .tenants import TenantBoundary, TenantRegistry
    from . import policy_engine as platform_policy
    from . import sandbox_executor as sandbox_runtime
    from .governance import ACTIONS as GOVERNANCE_ACTIONS, ensure_governance, build_scoreboard, apply_governance_action
except ImportError:
    from launcher import instance_identity
    from dsh_launcher import DSHLauncher, ACTIONS as LAUNCHER_ACTIONS
    from dsh_harness import DSHHarness, ACTIONS as HARNESS_ACTIONS
    from resource_workflows_adapter import ResourceWorkflows, ACTIONS as RESOURCE_ACTIONS
    from project_store import ProjectStore
    from generation_pipeline import GenerationPipeline, ACTIONS as GENERATION_ACTIONS
    from evaluation_runs import EvaluationRuns
    from autonomy import normalize_autonomy_config, build_autonomy
    from integration_recommendations import IntegrationRecommendations, ACTIONS as CAPABILITY_AI_ACTIONS
    from capability_hub import CapabilityHub, ACTIONS as CAPABILITY_ACTIONS
    from integration_tools import IntegrationTools, ACTIONS as INTEGRATION_ACTIONS
    from local_records import ACTIONS as RECORD_ACTIONS, apply_record_action
    from coordination import CoordinationStore, ACTIONS as COORDINATION_ACTIONS
    from team_channel import TeamChannel, ChannelError
    from team_memory import TeamMemoryStore
    from followups import (FollowupsEngine, FollowupsError, FOLLOWUP_TOPIC,
                           PROVENANCE as FOLLOWUPS_PROVENANCE)
    from memory_governance import MemoryGovernanceError, MEMORY_ID_PATTERN
    from tenants import TenantBoundary, TenantRegistry
    import policy_engine as platform_policy
    import sandbox_executor as sandbox_runtime
    from governance import ACTIONS as GOVERNANCE_ACTIONS, ensure_governance, build_scoreboard, apply_governance_action

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / 'web'
MAX_BODY = 128 * 1024
MAX_XLSX = 30 * 1024 * 1024
#: GenTeam P2/P4 (canal dirigido + memoria de equipo). Los módulos portados son
#: engine/team_channel.py y engine/team_memory.py (port REA de
#: agentscope-ai/agentscope@26ec620). El canal es un registro EN MEMORIA de la sesión
#: del motor (por diseño del port: no persiste); la memoria de equipo persiste en
#: data/projects/_team_memory/<tenant>/equipo/ con fragmentos .md + índice MEMORY.md.
#: Ninguna acción ejecuta agentes ni llama proveedores; son registros locales.
TEAM_CHANNEL_ACTIONS = frozenset({
    'channel-publish', 'channel-assign', 'channel-evidence', 'channel-claim',
    'channel-submit', 'channel-accept', 'channel-reject', 'channel-inbox',
})
TEAM_MEMORY_ACTIONS = frozenset({'memory-append'})
TEAM_ACTIONS = TEAM_CHANNEL_ACTIONS | TEAM_MEMORY_ACTIONS
#: GenTeam P3 (follow-ups): persecucion explicita de compromisos detectados en el canal.
#: Dos acciones locales y versionadas: un tick (escanea y persigue) y un drenaje del
#: inbox de UN miembro (lectura destructiva, igual que channel-inbox). Ninguna ejecuta
#: agentes, llama proveedores, abre red ni escribe fuera del proyecto local.
FOLLOWUPS_ACTIONS = frozenset({'followups-tick', 'followups-drain'})
FOLLOWUPS_MAX_DRAIN = 100
#: GenTeam P1/M4 (sandbox con aprobacion en DOS pasos). `sandbox-request` valida y
#: consulta la politica SIN ejecutar; `sandbox-approve` registra una aprobacion de un solo
#: uso ligada a (request_id, scope_hash); `sandbox-exec` es el unico camino que ejecuta,
#: vuelve a evaluar la politica (deny gana) y consume la aprobacion pase lo que pase.
#: Deny by default: sin las tres piezas no se ejecuta nada. Usa engine/policy_engine.py
#: TAL CUAL (las ocho puertas no se relajan ni se duplican) y engine/sandbox_executor.py
#: sin modificarlo (su doctrina: ninguna ejecucion sin puerta aprobada, workspace por run,
#: subprocess acotado y artefacto firmado entregado al canal).
SANDBOX_ACTIONS = frozenset({'sandbox-request', 'sandbox-approve', 'sandbox-exec'})
SANDBOX_MAX_REQUESTS = 24
SANDBOX_MAX_CODE_CHARS = 20000
SANDBOX_CODE_VIEW_CHARS = 1200
SANDBOX_APPROVAL_TTL_SECONDS = 900
SANDBOX_MAX_RUNS = 32
SANDBOX_APPROVER_ROLE = 'operador-panel'
SANDBOX_PROVENANCE = 'panel:sandbox-p1'
PROVIDER_ROUTES = {'openai': 'openai', 'deepseek': 'deepseek', 'deepseek-official': 'deepseek', 'zai': 'zai', 'zai-official': 'zai'}
ALLOWED_PROVIDERS = set(PROVIDER_ROUTES)
DEFAULT_CONFIG = {
    'source_kind': 'github_repository', 'repo_url': '', 'repo_name': 'Mi organización', 'agent_count': 24,
    'max_direct_reports': 3, 'template': 'arbitragex', 'provider': 'deepseek-official',
    'model': 'deepseek-flash', 'implementation_concurrency': 3, 'analysis_model': '',
    'llm_budget_usd': 0, 'council_concurrency': 24, 'repo_ref': '', 'autonomy_preset': 'autonomous', 'objective': '',
}
AUTONOMY_KEYS = {'planning_context', 'response_mode', 'planner_max_tokens', 'member_timeout_ms',
                 'handoff_summary_max_chars', 'runtime_token_budget', 'quality_gate_rounds', 'orchestration_backend'}
CONFIG_KEYS = set(DEFAULT_CONFIG) | AUTONOMY_KEYS
NS = {'s': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
#: Capa de plataforma V9 (Agent OS). Estado DECLARATIVO de los planos: rutas de modulo
#: y de contrato, sin importar ni ejecutar esos modulos. Lo consume la unica accion
#: nueva de solo lectura ('platform-planes-status'), cubierta por
#: tests_platform_integration.py. Anadir una ruta aqui no la ejecuta ni la autoriza.
PLATFORM_PLANES = (
    ('G1', 'I1', 'Task Graph Engine', ('engine/task_graph.py',),
     ('docs/plataforma/taskspec.schema.json',)),
    ('G2', 'I2', 'Agent Registry y Evidence Graph',
     ('engine/agent_registry.py', 'engine/evidence_graph.py'),
     ('docs/plataforma/evidence-node.schema.json',)),
    ('G3', 'I3', 'Policy Engine y puertas de aprobacion humana', ('engine/policy_engine.py',),
     ('docs/plataforma/policy.schema.json', 'docs/plataforma/policy.v2.schema.json')),
    ('G4', 'I4', 'Memory Governance y Tenant Isolation',
     ('engine/memory_governance.py', 'engine/tenants.py'),
     ('docs/plataforma/memory-record.schema.json', 'docs/plataforma/tenant-boundary.schema.json')),
    ('G5', 'I5', 'Evaluation Harness y Artifact Factory',
     ('engine/evaluation_harness.py', 'engine/artifact_factory.py'),
     ('docs/plataforma/receipt-extension.schema.json',)),
    ('G6', 'I6', 'Reliability Plane y Connector Gateway',
     ('engine/reliability.py', 'engine/connector_gateway.py'),
     ('docs/plataforma/receipt-extension.schema.json',)),
    ('O1', 't13', 'Approval Receipt (enlace declarativo al hash del TaskGraph)',
     ('engine/approval_receipt.py',), ('docs/PLATAFORMA_APROBACION_V1.md',)),
)

class BridgeError(Exception):
    pass


def now():
    return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())


def load_core():
    try:
        from . import core
    except ImportError:
        import core
    return core


def load_providers():
    try:
        from . import providers
    except ImportError:
        try:
            import providers
        except ImportError as exc:
            raise BridgeError('El módulo de proveedores no está instalado en este paquete.') from exc
    return providers


def normalize_repo(value):
    value = str(value or '').strip()
    if not value:
        return ''
    if '://' not in value and value.count('/') == 1:
        value = 'https://github.com/' + value
    parsed = urlsplit(value)
    if parsed.scheme != 'https' or parsed.hostname != 'github.com' or parsed.username or parsed.password or parsed.port or parsed.query or parsed.fragment:
        raise BridgeError('Usa la URL HTTPS pública de GitHub, sin credenciales ni parámetros.')
    parts = parsed.path.rstrip('/').split('/')
    if len(parts) != 3 or not all(parts[1:]) or any(not all(c.isalnum() or c in '._-' for c in p) for p in parts[1:]):
        raise BridgeError('La URL debe identificar un repositorio: https://github.com/propietario/repositorio.')
    return value.rstrip('/')


def normalize_config(raw, previous=None):
    if not isinstance(raw, dict):
        raise BridgeError('La configuración debe ser un objeto JSON.')
    unknown = set(raw) - CONFIG_KEYS
    if unknown:
        raise BridgeError('Campos de configuración no admitidos: ' + ', '.join(sorted(unknown)))
    result = dict(DEFAULT_CONFIG)
    result.update(previous or {})
    result.update(raw)
    for key, low, high in [('agent_count', 1, MAX_AGENTS), ('max_direct_reports', 1, 8), ('implementation_concurrency', 1, 3), ('council_concurrency', 1, MAX_AGENTS)]:
        value = result[key]
        if isinstance(value, bool) or isinstance(value, float) and not value.is_integer():
            raise BridgeError(f'{key} debe ser un número entero.')
        try:
            value = int(value)
        except (TypeError, ValueError):
            raise BridgeError(f'{key} debe ser un número entero.')
        if not low <= value <= high:
            raise BridgeError(f'{key} debe estar entre {low} y {high}.')
        result[key] = value
    result['implementation_concurrency'] = min(result['implementation_concurrency'], result['agent_count'])
    result['provider'] = str(result['provider']).strip().lower()
    if result['provider'] not in ALLOWED_PROVIDERS:
        raise BridgeError('Proveedor no admitido por este panel.')
    if result.get('autonomy_preset', 'autonomous') not in ('autonomous', 'manual', 'smart'):
        raise BridgeError('autonomy_preset debe ser autonomous, manual o smart.')
    result.setdefault('autonomy_preset', 'autonomous')
    if result['template'] not in ('arbitragex', 'generic'):
        raise BridgeError('Plantilla desconocida.')
    for key in ('repo_name', 'model', 'analysis_model', 'repo_ref'):
        result[key] = str(result[key] or '').strip()
        if len(result[key]) > 250 or any(ord(c) < 32 for c in result[key]):
            raise BridgeError(f'Valor no válido en {key}.')
    if not isinstance(result.get('objective', ''), str) or len(result.get('objective', '')) > 5000 or any(ord(c) < 32 and c not in '\n\r\t' for c in result.get('objective', '')):
        raise BridgeError('objective debe ser texto de hasta 5000 caracteres.')
    result['objective'] = result.get('objective', '').strip()
    source_kind = result.get('source_kind', 'github_repository')
    if source_kind not in ('github_repository', 'website'):
        raise BridgeError('source_kind debe ser github_repository o website.')
    if source_kind == 'website':
        url = str(result['repo_url'] or '').strip()
        try:
            parsed = urlsplit(url)
            valid = (parsed.scheme == 'https' and parsed.hostname and not parsed.username
                     and not parsed.password and parsed.port in (None, 443) and not parsed.fragment)
        except ValueError:
            valid = False
        if url and (not valid or len(url) > 2048 or any(ord(c) < 32 for c in url)):
            raise BridgeError('Usa una URL web pública HTTPS, sin credenciales, fragmentos ni puertos especiales.')
        result['repo_url'] = url
    else:
        result['repo_url'] = normalize_repo(result['repo_url'])
    try:
        budget = float(result['llm_budget_usd'])
    except (TypeError, ValueError):
        raise BridgeError('El límite orientativo debe ser un número.')
    if not 0 <= budget <= 100:
        raise BridgeError('El límite orientativo debe estar entre 0 y 100 USD; 0 significa sin presupuesto monetario aprobado.')
    result['llm_budget_usd'] = budget
    result.update(normalize_autonomy_config(result, enabled=True))
    return result


def workbook_contract():
    path = ROOT / 'workbook' / 'sheet_ranges.json'
    if path.exists():
        return json.loads(path.read_text('utf-8'))
    return {'configuration': {'sheet': 'CONFIG', 'cells': {}}, 'assignments': {'sheet': 'Asignacion_modelos'}}


def read_xlsx_snapshot(path):
    """Read saved CONFIG/Configuracion and manual assignments without writing XML."""
    path = Path(path).expanduser().resolve()
    if path.suffix.lower() != '.xlsx' or not path.is_file():
        raise BridgeError('Selecciona un archivo .xlsx existente.')
    if path.stat().st_size > MAX_XLSX:
        raise BridgeError('El libro supera el límite de 30 MB.')
    try:
        with zipfile.ZipFile(path) as zf:
            if len(zf.infolist()) > 2000 or sum(x.file_size for x in zf.infolist()) > 80 * 1024 * 1024:
                raise BridgeError('El libro excede los límites de lectura segura.')
            def xml(name):
                info = zf.getinfo(name)
                if info.file_size > 12 * 1024 * 1024:
                    raise BridgeError('Una parte XML del libro es demasiado grande.')
                data = zf.read(name)
                if b'<!DOCTYPE' in data.upper() or b'<!ENTITY' in data.upper():
                    raise BridgeError('No se admiten entidades XML en el libro.')
                return ET.fromstring(data)
            shared = []
            if 'xl/sharedStrings.xml' in zf.namelist():
                shared = [''.join(n.itertext()) for n in xml('xl/sharedStrings.xml').findall('s:si', NS)]
            workbook = xml('xl/workbook.xml')
            relationships = {x.attrib['Id']: x.attrib['Target'] for x in xml('xl/_rels/workbook.xml.rels')}
            sheets = {}
            sheet_formulas = {}
            for sheet in workbook.findall('s:sheets/s:sheet', NS):
                rid = sheet.attrib['{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id']
                target = relationships[rid]
                sheet_path = target.lstrip('/') if target.startswith('/') else 'xl/' + target
                cells = {}
                formulas = set()
                for cell in xml(sheet_path).findall('.//s:sheetData/s:row/s:c', NS):
                    if cell.find('s:f', NS) is not None:
                        formulas.add(cell.attrib.get('r', ''))
                    typ = cell.attrib.get('t')
                    val = cell.find('s:v', NS)
                    inline = cell.find('s:is', NS)
                    if typ == 'inlineStr' and inline is not None:
                        value = ''.join(inline.itertext())
                    elif typ == 's' and val is not None:
                        value = shared[int(val.text)]
                    elif val is not None:
                        value = val.text
                    else:
                        value = ''
                    cells[cell.attrib.get('r', '')] = value
                sheets[sheet.attrib['name']] = cells
                sheet_formulas[sheet.attrib['name']] = formulas
            contract = workbook_contract()
            config_sheet = contract['configuration']['sheet']
            config_cells = contract['configuration'].get('cells', {})
            if config_sheet not in sheets:
                raise BridgeError('Falta la hoja de configuración indicada en el contrato del libro.')
            rows = {k: sheets[config_sheet].get(v, '') for k, v in config_cells.items() if k in CONFIG_KEYS and sheets[config_sheet].get(v, '') != ''}
            if not config_cells:
                cells = sheets[config_sheet]
                for ref, value in cells.items():
                    if ref.startswith('A') and value in CONFIG_KEYS:
                        rows[value] = cells.get('B' + ref[1:], '')
            if not rows:
                raise BridgeError('La hoja de configuración no contiene las claves esperadas.')
            assignment = contract.get('assignments', {})
            cells = sheets.get(assignment.get('sheet', ''), {})
            columns = assignment.get('columns', {'id': 'B', 'provider': 'D', 'model': 'E'})
            overrides = {}
            formulas = sheet_formulas.get(assignment.get('sheet', ''), set())
            for row in range(6, 38):
                aid = str(cells.get(columns.get('id', 'B') + str(row), '')).strip()
                provider = str(cells.get(columns.get('provider', 'D') + str(row), '')).strip().lower()
                model = str(cells.get(columns.get('model', 'E') + str(row), '')).strip()
                manual = {}
                if provider and columns.get('provider', 'D') + str(row) not in formulas:
                    manual['provider'] = provider
                if model and columns.get('model', 'E') + str(row) not in formulas:
                    manual['model'] = model
                if aid and manual:
                    overrides[aid] = manual
            model_cells = sheets.get(contract.get('models', {}).get('sheet', 'Modelos'), {})
            preferences = []
            for row in range(6, 206):
                provider = model_cells.get('A' + str(row), '')
                model = model_cells.get('B' + str(row), '')
                if provider and model:
                    preferences.append({'provider': provider, 'model': model, 'user_rank': model_cells.get('E' + str(row), ''), 'capabilities': model_cells.get('G' + str(row), '')})
            return clean_snapshot({'config': rows, 'model_overrides': overrides, 'model_preferences': preferences})
    except (zipfile.BadZipFile, KeyError, ET.ParseError, IndexError, ValueError) as exc:
        raise BridgeError('No se pudo leer el formato del libro .xlsx.') from exc


def read_xlsx_config(path):
    return read_xlsx_snapshot(path)['config']


def normalize_preferences(rows):
    result = []
    for row in rows or []:
        if not isinstance(row, dict) or not row.get('provider') or not row.get('model'):
            continue
        item = {'provider': str(row['provider']).strip().lower(), 'model': str(row['model']).strip()}
        rank = row.get('user_rank')
        if rank not in (None, ''):
            try:
                number = float(rank)
                if number.is_integer() and 1 <= number <= 100000:
                    item['user_rank'] = int(number)
            except (TypeError, ValueError):
                pass
        caps = row.get('capabilities', '')
        if isinstance(caps, str):
            try:
                caps = json.loads(caps)
            except ValueError:
                caps = [x.strip() for x in caps.split(',') if x.strip()]
        if isinstance(caps, dict):
            for key in ('capabilities', 'context_window', 'input_modalities', 'output_modalities', 'max_output_tokens'):
                if key in caps:
                    item[key] = caps[key]
        elif isinstance(caps, list) and caps:
            item['capabilities'] = [str(x) for x in caps]
        for field in ('context_window', 'input_modalities', 'output_modalities', 'max_output_tokens'):
            if field in row and field not in item:
                item[field] = row[field]
        result.append(item)
    return result


def clean_snapshot(snapshot):
    return {'config': normalize_config(snapshot['config']), 'model_overrides': snapshot.get('model_overrides', {}),
            'model_preferences': normalize_preferences(snapshot.get('model_preferences', []))}


def config_fingerprint(config):
    def value(v):
        return str(int(v)) if isinstance(v, float) and v.is_integer() else ('' if v is None else str(v))
    return '|'.join(value(config.get(k, '')) for k in workbook_contract()['configuration'].get('fingerprint_fields', []))


def snapshot_digest(snapshot):
    return hashlib.sha256(json.dumps(snapshot, sort_keys=True, ensure_ascii=False).encode('utf-8')).hexdigest()


class WindowsSecretStore:
    """Opt-in DPAPI CurrentUser store; never writes a plaintext credential file."""
    def __init__(self, path=None):
        self.path = Path(path) if path else Path(os.environ.get('LOCALAPPDATA', str(ROOT))) / 'OrgDNA' / 'keys.dpapi'

    @staticmethod
    def _crypt(data, decrypt=False):
        if os.name != 'nt':
            raise BridgeError('El guardado cifrado DPAPI sólo está disponible en Windows.')
        from ctypes import wintypes
        class DATA_BLOB(ctypes.Structure):
            _fields_ = [('cbData', wintypes.DWORD), ('pbData', ctypes.POINTER(ctypes.c_ubyte))]
        buf = ctypes.create_string_buffer(data)
        source = DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_ubyte)))
        output = DATA_BLOB()
        crypt32 = ctypes.WinDLL('crypt32', use_last_error=True)
        kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        kernel32.LocalFree.restype = ctypes.c_void_p
        crypt32.CryptProtectData.argtypes = [ctypes.POINTER(DATA_BLOB), wintypes.LPCWSTR, ctypes.POINTER(DATA_BLOB), ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(DATA_BLOB)]
        crypt32.CryptProtectData.restype = wintypes.BOOL
        crypt32.CryptUnprotectData.argtypes = [ctypes.POINTER(DATA_BLOB), ctypes.c_void_p, ctypes.POINTER(DATA_BLOB), ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(DATA_BLOB)]
        crypt32.CryptUnprotectData.restype = wintypes.BOOL
        if decrypt:
            ok = crypt32.CryptUnprotectData(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(output))
        else:
            ok = crypt32.CryptProtectData(ctypes.byref(source), 'OrgDNA local provider keys', None, None, None, 1, ctypes.byref(output))
        if not ok:
            raise BridgeError('Windows no pudo procesar el almacén cifrado.')
        try:
            return ctypes.string_at(output.pbData, output.cbData)
        finally:
            kernel32.LocalFree(output.pbData)

    def save(self, credentials):
        encoded = json.dumps(credentials).encode('utf-8')
        encrypted = self._crypt(encoded)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix('.tmp')
        temp.write_bytes(encrypted)
        os.replace(temp, self.path)

    def load(self):
        if os.name != 'nt' or not self.path.exists():
            return {}
        decoded = json.loads(self._crypt(self.path.read_bytes(), decrypt=True).decode('utf-8'))
        return {k: v for k, v in decoded.items() if k in ALLOWED_PROVIDERS and isinstance(v, str)}

    def delete(self):
        self.path.unlink(missing_ok=True)


def excel_call(action, workbook, payload=None):
    if os.name != 'nt':
        raise BridgeError('Excel COM requiere Windows y Excel de escritorio. El panel y las exportaciones JSON funcionan sin Excel.')
    path = Path(workbook).expanduser().resolve()
    if path.suffix.lower() != '.xlsx' or not path.is_file():
        raise BridgeError('Selecciona el libro .xlsx existente que deseas actualizar.')
    arguments = ['powershell.exe', '-NoProfile', '-NonInteractive', '-File', str(ROOT / 'engine' / 'excel_bridge.ps1'), '-Action', action, '-WorkbookPath', str(path)]
    temp_path = None
    try:
        if payload is not None:
            with tempfile.NamedTemporaryFile('w', encoding='utf-8-sig', suffix='.json', delete=False) as f:
                json.dump(payload, f, ensure_ascii=False)
                temp_path = f.name
            arguments += ['-PayloadPath', temp_path]
        result = subprocess.run(arguments, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=120, check=False)
        if result.returncode:
            raise BridgeError('Excel no pudo completar la acción. Cierra los diálogos abiertos y comprueba que Excel permite ejecutar el script PowerShell firmado o de confianza. No se cambió la política de ejecución. Detalle: ' + result.stderr[-1000:])
        try:
            return json.loads(result.stdout.lstrip('\ufeff').strip())
        except ValueError as exc:
            raise BridgeError('El adaptador de Excel no devolvió una respuesta JSON válida.') from exc
    except subprocess.TimeoutExpired as exc:
        raise BridgeError('Excel no respondió a tiempo. Revisa los diálogos pendientes antes de reintentar.') from exc
    finally:
        if temp_path:
            Path(temp_path).unlink(missing_ok=True)


def sheet_payload(organization, catalog, receipts):
    """Only ranges explicitly mapped by the shipped workbook contract may be written."""
    agents = organization.get('agents', [])
    contract = workbook_contract()
    def text(value):
        if isinstance(value, str):
            return value
        if isinstance(value, list) and all(isinstance(x, str) for x in value):
            return '\n'.join(value)
        return json.dumps(value, ensure_ascii=False)
    profiles, cvs, skills, council, subteams, assignments = [], [], [], [], [], []
    audits = {a['subject_id']: a for a in organization.get('audit_assignments', [])}
    for slot, a in enumerate(agents, 1):
        cv = a.get('cv', {})
        profiles.append([slot, a['id'], a.get('display_name', a['name']), a.get('title', a.get('role')), a.get('department'), cv.get('summary'), text(a.get('responsibilities', [])), text(a.get('deliverables', [])), '\n'.join(j.get('name', '') + ': ' + j.get('acceptance', '') for j in a.get('journeys', [])), 'DISEÑADO_NO_EJECUTADO'])
        cvs.append([slot, a.get('display_name', a['name']), 'Resumen', cv.get('summary', ''), cv.get('disclaimer', ''), 'FICTICIO / NO ACREDITADO'])
        for row in cv.get('experience', []):
            detail = row.get('position', '') + '. ' + row.get('scope', '') + '\nObjetivos: ' + '; '.join(row.get('achievements', []))
            cvs.append([slot, a.get('display_name', a['name']), 'Experiencia objetivo', detail, row.get('verification', ''), 'FICTICIO / NO ACREDITADO'])
        for row in cv.get('education', []):
            detail = row.get('program', '') + '\nMódulos: ' + '; '.join(row.get('modules', []))
            cvs.append([slot, a.get('display_name', a['name']), 'Formación objetivo', detail, row.get('institution', ''), row.get('status', 'No título obtenido')])
        for row in cv.get('certifications', []):
            cvs.append([slot, a.get('display_name', a['name']), 'Certificaciones objetivo', row.get('name', ''), row.get('acceptance', ''), row.get('status', 'No obtenida')])
        for skill in a.get('skills', []):
            skills.append([slot, a.get('display_name', a['name']), skill['id'], skill['name'], skill.get('target_level', skill.get('level')), skill.get('verified_level') if skill.get('verified_level') is not None else 'NO VERIFICADO', skill.get('evidence'), 'Evaluación práctica independiente pendiente'])
        council.append([slot, a['id'], a.get('display_name', a['name']), a.get('title', a.get('role')), None, 'Council / solo lectura', 'Hechos, riesgos, alternativas y disenso con evidencia', 'Consolidación CEO en run nuevo', 'NO INICIADO'])
        audit = audits.get(a['id'], {})
        consultants = organization.get('annexes', {}).get('consultants', [])
        subteams.append([slot, a.get('display_name', a['name']), a.get('department'), None, audit.get('reviewer_id', 'OWNER_EXTERNAL'), 'Pool propuesto; seleccionar según alcance y sin conflicto', text(a.get('responsibilities', [])), audit.get('reason', audit.get('status', '')), 'PROPUESTO / NO EJECUTADO'])
        source = a.get('selection_source', 'default_unbenchmarked')
        automatic = source in ('user_priority_verified_catalog', 'capability_heuristic_verified_route')
        override = organization.get('config', {}).get('model_assignments', {}).get(a['id'], {})
        assignments.append([slot, a['id'], a.get('title', a.get('role')), override.get('provider'), override.get('model'), None, None, None, source, a.get('provider') if automatic else '', a.get('model') if automatic else ''])
    models = [[m.get('provider'), m.get('model', m.get('id')), m.get('name', m.get('model', m.get('id'))), 'AVAILABLE' if m.get('available') is True else ('UNAVAILABLE' if m.get('available') is False else 'UNVERIFIED'), m.get('user_rank', ''), m.get('checked_at', ''), text({k: m[k] for k in ('capabilities', 'context_window', 'max_output_tokens', 'input_modalities', 'output_modalities') if k in m}), m.get('source', m.get('status', ''))] for m in catalog]
    rows_by_key = {'profiles': profiles, 'cv': cvs, 'skills': skills, 'council': council, 'subteams': subteams, 'assignments': assignments, 'models': models}
    result = {'schema_version': '1.0', 'sheets': {}}
    for key, rows in rows_by_key.items():
        if key not in contract:
            continue
        definition = contract[key]
        capacities = {'profiles': 32, 'cv': 400, 'skills': 400, 'council': 32, 'subteams': 32, 'assignments': 32, 'models': 200}
        if len(rows) > capacities[key]:
            raise BridgeError(f'{definition["sheet"]} admite {capacities[key]} filas, pero hay {len(rows)}. No se trunca: exporta el ADN completo o reduce la selección antes de aplicar.')
        result['sheets'][key] = {'rows': rows}
    return result


class BridgeState:
    def __init__(self, workbook=None, credential_store=None, provider_module=None, project_store=None, coordination_store=None, gang_registry=None, *, sandbox_policy=None, sandbox_data_root=None, sandbox_clock=None):
        self.lock = threading.RLock()
        self.csrf = secrets.token_urlsafe(32)
        self.cookie = secrets.token_urlsafe(32)
        self.config = dict(DEFAULT_CONFIG)
        self.config_version = 1
        self._export_cache = None
        self.workbook = str(Path(workbook).expanduser().resolve()) if workbook else ''
        self.organization = None
        self.generation_stale = False
        self.has_manual_edits = False
        self._design_context = None
        self.recovery_draft_config = None
        self._last_design_restore = None
        self.project_store = project_store or ProjectStore(ROOT / 'data' / 'projects')
        self.coordination_store = coordination_store or CoordinationStore(self.project_store.root / '_coordination')
        # GenTeam P2/P4: canal dirigido (en memoria, por diseño del port) y memoria de
        # equipo persistente. Se montan lazy sobre la organización vigente.
        self.team_channel = None
        self._team_channel_signature = None
        self._team_memory_registry = None
        self._team_memory_store = None
        self._team_memory_signature = None
        # GenTeam P3: motor de seguimiento montado sobre EL MISMO canal del panel (una
        # sola instancia). Se reconstruye cuando cambia el roster, declarado en la vista.
        self.team_followups = None
        self._followups_signature = None
        self.followups_agent_member_id = None       # identidad de coordinacion (def. miembro raiz)
        self.followups_supervisor_member_id = None  # supervision declarada (def. la misma identidad)
        # GenTeam P1/M4: sandbox con aprobacion en dos pasos. La politica es inyectable
        # SOLO por pruebas; el defecto es la politica v1 del contrato (las ocho puertas en
        # require_human_approval). Estado en memoria de la sesion: nada se persiste.
        self._sandbox_policy_override = sandbox_policy
        self._sandbox_policy_cache = None
        self._sandbox_data_root_override = sandbox_data_root
        self.sandbox_clock = sandbox_clock or time.time
        self.sandbox_requests = {}   # request_id -> registro (orden de alta)
        self.sandbox_runs = []       # ejecuciones (acotado por SANDBOX_MAX_RUNS)
        self.records_version = 1
        self.project = {'id': None, 'name': '', 'version_id': None, 'dirty': False}
        self.records = {'council_sessions': [], 'skill_registry': [], 'remediation_records': [], 'subteams': [], 'performance_records': [], 'promotion_records': [], 'governance_events': []}
        self.analysis = None
        self.repo_inventory = None
        self.repo_cache = None
        self.pending_consent = None
        self._pending_analysis_account_stamp = None
        self.model_overrides = {}
        self.workbook_snapshot = None
        self.models = []
        self.verified_catalog_providers = set()
        self._model_account_stamps = {}
        self.receipts = []
        self.secret_store = credential_store or WindowsSecretStore()
        self.credentials = {}
        self.gang_registry = gang_registry or _gang_registry_module.GangRegistry(
            journal=gang_journal.Journal(self.project_store.root / '_gang_journal.jsonl'))
        self.gang_servers = None      # {id: ServidorGang} cuando el operador los monta
        self.gang_supervisor = None   # Supervisor vivo mientras esten montados
        self._last_gang_artifact = None
        self._sensitive_values = set()
        self.persisted = False
        self.provider_module = provider_module
        self.generation = GenerationPipeline(self)
        self.evaluations = EvaluationRuns(self.project_store.root / '_evaluations')
        self.integrations = IntegrationTools(self)
        self.capabilities_hub = CapabilityHub(self)
        self.capability_recommendations = IntegrationRecommendations(self)
        self.dsh_launcher = DSHLauncher((Path(os.environ.get("LOCALAPPDATA", str(ROOT / "data"))) / "OrgDNA" / "dsh-backups") if os.name == "nt" else ROOT / "data" / "dsh-backups")
        self.dsh_harness = DSHHarness(self.dsh_launcher, self.integrations._connection())
        self.resource_workflows = ResourceWorkflows(self)
        try:
            self.credentials = self.secret_store.load()
            self._sensitive_values.update(self.credentials.values())
            self.persisted = bool(self.credentials)
        except Exception:
            self.receipt('credentials', 'warning', 'No se pudo abrir el almacén DPAPI; introduce la clave de nuevo.')
        if self.workbook:
            try:
                snapshot = read_xlsx_snapshot(self.workbook)
                self.config = snapshot['config']
                self.model_overrides = snapshot['model_overrides']
                self.merge_preferences(snapshot.get('model_preferences', []))
                self.workbook_snapshot = snapshot_digest(snapshot)
                self.receipt('import', 'success', 'Valores guardados del libro; no incluye cambios sin guardar.')
            except Exception as exc:
                self.receipt('import', 'warning', str(exc))

    def redact(self, value):
        """Walk data before JSON encoding so quotes/backslashes cannot evade redaction."""
        self._sensitive_values.update(self.credentials.values())
        if isinstance(value, str):
            for secret in tuple(self._sensitive_values):
                if secret:
                    value = value.replace(secret, '[REDACTED]')
            return value
        if isinstance(value, dict):
            return {self.redact(str(k)): self.redact(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [self.redact(v) for v in value]
        if value is None or isinstance(value, (int, float, bool)):
            return value
        return self.redact(str(value))

    def receipt(self, action, status, message, **extra):
        entry = self.redact({'timestamp': now(), 'action': action, 'status': status, 'message': message, **extra})
        self.receipts.append(entry)
        self.receipts = self.receipts[-100:]
        return entry

    def tool_catalog(self):
        path = ROOT / 'engine' / 'tool_catalog.json'
        return json.loads(path.read_text('utf-8')) if path.is_file() else {'tools': [], 'role_presets': [], 'runtime_verified': False}

    def require_version(self, body):
        if self.organization is None or self.generation_stale:
            raise BridgeError('Genera un diseño actualizado antes de registrar esta acción.')
        if type(body.get('expected_state_version')) is not int or body['expected_state_version'] != self.organization.get('state_version', 1):
            raise BridgeError('Versión obsoleta: recarga el estado antes de guardar; expected_state_version debe coincidir.')

    @staticmethod
    def _design_digest(value):
        return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                         separators=(',', ':'), allow_nan=False).encode()).hexdigest()

    def remember_current_design(self):
        """Retain the matching context, never a consent or an alternate roster.

        The organization itself remains authoritative and stays in place while a
        later attempt runs or fails. Keeping only its context avoids rolling back
        user records, administrative edits, runtime evidence or DSH connections.
        """
        if self.organization is None or self.generation_stale:
            return
        try:
            if (self._design_context
                    and self._design_context['organization_id'] == self.organization.get('organization_id')
                    and self._design_context['organization_config_sha256'] == self._design_digest(self.organization.get('config'))
                    and self._design_context['config'] == self.config
                    and self._design_context['model_overrides'] == self.model_overrides):
                return  # A fresh source read is not a new published design.
            if not load_core().validate_organization(self.organization).get('valid'):
                return
            context = {'config': copy.deepcopy(self.config),
                'organization_id': self.organization.get('organization_id'),
                'organization_config_sha256': self._design_digest(self.organization.get('config')),
                'model_overrides': copy.deepcopy(self.model_overrides),
                'analysis': copy.deepcopy(self.analysis), 'repo_inventory': copy.deepcopy(self.repo_inventory)}
            if self.redact(context) != context:
                return
            context['snapshot_id'] = self._design_digest(context)
            if self._design_context and self._design_context['organization_id'] != context['organization_id']:
                self.recovery_draft_config = None
                self._last_design_restore = None
            elif self.recovery_draft_config is not None and normalize_config(self.recovery_draft_config) == normalize_config(self.config):
                self.recovery_draft_config = None
            self._design_context = context
        except (TypeError, ValueError):
            # A malformed design must stay blocked; a recovery marker cannot
            # replace ordinary organization/export validation.
            return

    def _refreshed_design_context(self, context, previous, updated):
        """Rebind only the revision stamp changed by a trusted catalog refresh."""
        if not context or context.get('organization_id') != previous.get('organization_id'):
            return context
        before, after = previous.get('config', {}), updated.get('config', {})
        if (context.get('organization_config_sha256') != self._design_digest(before)
                or {k: v for k, v in before.items() if k != 'dna_revision'} !=
                   {k: v for k, v in after.items() if k != 'dna_revision'}):
            return context
        result = copy.deepcopy(context)
        result['organization_config_sha256'] = self._design_digest(after)
        result['snapshot_id'] = self._design_digest({k: v for k, v in result.items() if k != 'snapshot_id'})
        return result

    def design_recovery(self):
        context = self._design_context
        org = self.organization
        matches = bool(context and org and context.get('organization_id') == org.get('organization_id')
            and context.get('organization_config_sha256') == self._design_digest(org.get('config')))
        valid = False
        if matches:
            try:
                valid = bool(load_core().validate_organization(org).get('valid'))
            except (TypeError, ValueError):
                pass
        available = matches and valid
        active = bool(self.generation._active())
        reason = ('Termina o cancela la generación pendiente antes de recuperar el diseño.' if active else
                  'La versión conservada no supera la validación actual; no se omiten sus errores.' if matches and not valid else
                  'Esta versión no tiene una configuración conservada compatible. Puedes cargar una versión guardada anterior.' if not matches else
                  'Puedes volver al diseño conservado sin regenerarlo. La configuración pendiente quedará como borrador.' if self.generation_stale else
                  'El diseño actual conserva su configuración y puede validarse para exportar.')
        return {'available': bool(available), 'can_restore': bool(available and self.generation_stale and not active),
            'requires_restore': bool(self.generation_stale), 'snapshot_id': context.get('snapshot_id') if context else None,
            'expected_config_version': self.config_version,
            'config': copy.deepcopy(context['config']) if context else None,
            'draft_config': copy.deepcopy(self.recovery_draft_config),
            'agent_count': len((org or {}).get('agents', [])),
            'organization_id': (org or {}).get('organization_id'), 'dna_revision': (org or {}).get('dna_revision'),
            'has_manual_edits': self.has_manual_edits, 'reason': reason}

    def restore_design(self, body):
        if body.get('confirmed') is not True:
            raise BridgeError('Confirma que deseas volver a la configuración del diseño conservado; la pendiente quedará como borrador.')
        request = (body.get('snapshot_id'), body.get('expected_config_version'))
        if self.generation._active():
            raise BridgeError('Termina o cancela la generación pendiente antes de recuperar el diseño.')
        if (self._last_design_restore == request and not self.generation_stale
                and self._design_context and self.config == self._design_context['config']):
            return  # A repeated click cannot mutate state or spend again.
        if type(body.get('expected_config_version')) is not int or body['expected_config_version'] != self.config_version:
            raise BridgeError('La configuración cambió. Revisa de nuevo la versión conservada antes de recuperarla.')
        recovery = self.design_recovery()
        if not recovery['can_restore'] or body.get('snapshot_id') != recovery['snapshot_id']:
            raise BridgeError('La versión conservada ya no coincide o no supera la validación. Recarga el estado antes de recuperarla.')
        context = self._design_context
        if self.redact(context) != context or self.redact(self.organization) != self.organization:
            raise BridgeError('Una credencial de sesión aparece en el diseño conservado; no se puede recuperar ni exportar.')
        # Validate everything before committing. Do not replace the organization,
        # model catalog, records, capability library or any live connection.
        config = normalize_config(context['config'])
        draft = copy.deepcopy(self.config)
        self.config = config
        self.config_version += 1
        self.model_overrides = copy.deepcopy(context['model_overrides'])
        self.analysis = copy.deepcopy(context['analysis'])
        self.repo_inventory = copy.deepcopy(context['repo_inventory'])
        self.pending_consent = None
        self.generation_stale = False
        self.recovery_draft_config = draft
        self._last_design_restore = request
        self.project['dirty'] = True
        self.receipt('design-restore', 'success', 'Diseño conservado recuperado sin regenerar. La configuración pendiente sigue disponible como borrador; no se llamó a ninguna API ni se cambió la conexión DSH.')
        self.remember_current_design()

    def generation_diagnostic(self, job_id=None):
        """Support download built from safe counters/codes, never raw responses."""
        job = self.generation.jobs.get(job_id or self.generation.current_id)
        if not job or job.get('status') not in ('completed', 'failed', 'cancelled'):
            raise BridgeError('No hay un diagnóstico de un intento terminado para esa generación.')
        fields = ('job_id', 'status', 'stage', 'failed_stage', 'created_at', 'updated_at', 'finished_at',
            'provider', 'model', 'agent_count', 'progress', 'max_requests', 'sent_requests',
            'completed_requests', 'completed_profiles', 'max_output_tokens', 'total_max_output_tokens',
            'max_total_output_tokens', 'profiles_per_request', 'response_mode', 'read_files', 'known_safe_files',
            'potentially_billed', 'confirmation_consumed', 'receipts_pending', 'interrupted_snapshot')
        error_fields = ('code', 'category', 'message', 'next_action', 'stage', 'provider', 'model',
            'field', 'profile_slot', 'batch_index', 'http_status', 'provider_error_code', 'provider_parameter',
            'finish_reason', 'source_stage', 'adapter_code', 'source_kind', 'reading_note',
            'sent_requests', 'completed_requests', 'max_requests', 'completed_profiles',
            'request_status', 'retry_requires_new_consent')
        def bounded(source, allowed):
            return {key: (value[:2000] if isinstance(value, str) else value)
                for key in allowed if key in source
                for value in (source[key],) if value is None or isinstance(value, (str, int, float, bool))}
        safe_job = self.generation._saved_job(job)
        return self.redact({'format': 'orgdna-generation-diagnostic', 'version': 2,
            'generated_at': now(), 'job': dict(bounded(job, fields), request_receipts=safe_job['request_receipts'], usage_summary=safe_job['usage_summary']),
            'request_receipts': safe_job['request_receipts'], 'usage_summary': safe_job['usage_summary'],
            'error': bounded(job.get('error') or {}, error_fields),
            'recovery': {'state_scope': 'current_local_project_at_download',
                         'previous_design_present': self.organization is not None,
                         'config_requires_restore': self.generation_stale},
            'privacy': {'source_content_included': False, 'raw_response_included': False,
                        'credentials_included': False, 'consent_payload_included': False},
            'note': 'Informe local. No se envía automáticamente. Los contadores no prueban ausencia de cargos; cualquier intento nuevo necesita autorización nueva.'})

    def platform_planes_status(self):
        """Estado de validacion DECLARATIVO de los planos de plataforma. Estrictamente de solo lectura.

        No importa ni ejecuta ningun modulo de plano, no escribe en disco, no envia nada,
        no abre conexiones, no consume consentimiento ni presupuesto y no anade recibos.
        Informa presencia, tamano y SHA-256 de cada artefacto declarado, y su coherencia
        con la allowlist runtime y con MANIFIESTO_SHA256.txt. Un artefacto presente y con
        hash coincidente no acredita ejecucion, conexion ni identidad.
        """
        try:
            from . import bundle
        except ImportError:
            import bundle

        def entry(relative):
            path = ROOT / relative
            if not path.is_file():
                return {'path': relative, 'present': False, 'bytes': None, 'sha256': None}
            data = path.read_bytes()
            return {'path': relative, 'present': True, 'bytes': len(data),
                    'sha256': hashlib.sha256(data).hexdigest()}

        manifest_path = ROOT / 'MANIFIESTO_SHA256.txt'
        listed = {}
        manifest_sha256 = None
        if manifest_path.is_file():
            manifest_bytes = manifest_path.read_bytes()
            manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
            for line in manifest_bytes.decode('utf-8').splitlines():
                digest, separator, name = line.partition('  ')
                if separator and len(digest) == 64 and all(c in '0123456789abcdef' for c in digest):
                    listed[name] = digest
        allowlist = set(bundle.RUNTIME_ALLOWLIST)
        planes, declared = [], []
        for key, flow, name, modules, contracts in PLATFORM_PLANES:
            module_entries = [entry(relative) for relative in modules]
            contract_entries = [entry(relative) for relative in contracts]
            declared.extend(modules)
            declared.extend(contracts)
            planes.append({'plane': key, 'flow': flow, 'name': name, 'modules': module_entries,
                           'contracts': contract_entries, 'declaration': 'inert_by_default',
                           'runtime_verified': False, 'executed_by_this_action': False})
        missing_on_disk = sorted(path for path in declared if not (ROOT / path).is_file())
        not_in_allowlist = sorted(path for path in declared if path not in allowlist)
        not_in_manifest = sorted(path for path in declared if path not in listed)
        manifest_mismatches = sorted(
            path for path in declared
            if path in listed and (ROOT / path).is_file()
            and hashlib.sha256((ROOT / path).read_bytes()).hexdigest() != listed[path])
        return {
            'action': 'platform-planes-status',
            'read_only': True, 'executed': False, 'network_used': False,
            'consent_consumed': False, 'spend_performed': False, 'planes_executed': False,
            'receipts_added': 0, 'generated_at': now(),
            'planes': planes,
            'delivery': {
                'runtime_allowlist_entries': len(bundle.RUNTIME_ALLOWLIST),
                'declared_artifacts': len(declared),
                'missing_on_disk': missing_on_disk,
                'not_in_runtime_allowlist': not_in_allowlist,
                'not_in_manifest': not_in_manifest,
                'manifest_hash_mismatches': manifest_mismatches,
                'manifest_file_count': len(listed),
                'manifest_sha256': manifest_sha256,
            },
            'note': ('Estado declarativo. Ningun plano se ha ejecutado al responder esta consulta: '
                     'la presencia y el hash de un artefacto no acreditan ejecucion, conexion, '
                     'identidad autenticada ni rentabilidad.'),
        }

    def _gang_public(self):
        """Ensamblado del gang (sobre la organizacion actual) y registro de despliegue.

        El ensamblado es calculo local sellado: valida invariantes, resuelve la
        jerarquia, ordena topologicamente y sella con SHA-256. El registro declara
        la verdad: los servicios NO estan montados y solo se registran hashes.
        """
        ensamblado, sha = None, None
        if self.organization is not None:
            try:
                artifact, sha = gang_assembly.assemble(self.organization, previous=self._last_gang_artifact)
                self._last_gang_artifact = artifact
                manifest = artifact['manifest']
                ensamblado = {'schema_version': artifact['schema_version'],
                              'total': manifest['total'], 'version': manifest['version'],
                              'sha256': sha, 'changelog': manifest['changelog'],
                              'orden': artifact['orden'][:12], 'orden_total': len(artifact['orden']),
                              'contrato': artifact['contrato']}
            except gang_assembly.AssemblyError as exc:
                ensamblado = {'error': exc.code, 'detail': str(exc)}
        return {'ensamblado': ensamblado, 'servicios': self.gang_registry.snapshot(),
                'sync': self.gang_registry.sync_verdict(sha),
                'auditoria': self.gang_registry.history()[-12:],
                'montado': bool(self.gang_servers),
                'urls': ({sid: servidor.url() for sid, servidor in self.gang_servers.items()}
                         if self.gang_servers else {}),
                'epoch': (self.gang_supervisor.epoch if self.gang_supervisor else None)}

    def public(self):
        with self.lock:
            self.remember_current_design()
            return self.redact({'config': self.config, 'config_version': self.config_version,
                'generation_job': self.generation.public(), 'evaluations': self.evaluations.public(), 'export_artifacts': self.export_artifacts(),
                'design_recovery': self.design_recovery(),
                'generation_diagnostic_available': (self.generation.public() or {}).get('status') in ('completed', 'failed', 'cancelled'),
                'autonomy_preview': self.autonomy_preview(),
                'capability_library': self.capabilities_hub.public(), 'capability_recommendations': self.capability_recommendations.public(),
                'cordis_addon': self.integrations.public_cordis(), 'plugin_shop': self.integrations.public_shop(),
                'dsh_connection': self.integrations.public_dsh(),
                'dsh_launcher': self.dsh_launcher.public(),
                'dsh_harness': self.dsh_harness.public(), 'resource_workflows': self.resource_workflows.public(),
                'workbook': self.workbook, 'organization': self.organization,
                'analysis': self.analysis, 'repo_inventory': self.repo_inventory, 'pending_consent': self.pending_consent, 'model_overrides': self.model_overrides, 'models': self.public_models(), 'receipts': self.receipts,
                'credentials_configured': sorted(self.credentials), 'credentials_persisted': self.persisted,
                'project': self.project, 'records_version': self.records_version,
                'coordination': self.coordination_store.public(), 'tool_catalog': self.tool_catalog(),
                'team_channel': self.team_channel_public(), 'team_memory': self.team_memory_public(),
                'team_followups': self.followups_public(), 'sandbox': self.sandbox_public(),
'gang': self._gang_public(),
                'scoreboard': build_scoreboard(self.organization, self.records) if self.organization else {'rows': [], 'evidence_status': 'manual_records_not_runtime_verified'},
                'generation_stale': self.generation_stale, 'has_manual_edits': self.has_manual_edits, **self.records,
                'capabilities': {'agents_runtime': False, 'excel_com': os.name == 'nt', 'dpapi': os.name == 'nt', 'network_on_start': False, 'local_coordination': True, 'filesystem_lock_enforced': False, 'dsh_enforced': False, 'reviewer_identity_verified': False},
                'verification': {'excel_com': 'not_tested_here', 'provider_live_calls': 'not_run_automatically'}})

    def autonomy_preview(self):
        return build_autonomy(self.config, analysis=self.analysis or self.repo_inventory,
                              agents=(self.organization or {}).get('agents'))

    # ------------------------------------------------------------- GenTeam P2/P4

    @staticmethod
    def _team_token_name(raw, slot, used):
        """Token de @mención: el name del perfil sanitizado (sin espacios ni '@'), único.
        El port exige tokens; los display_name con espacios no sirven de clave."""
        token = re.sub(r'[^A-Za-z0-9_.-]', '', str(raw or ''))[:60]
        if not token:
            token = 'member'
        candidate, suffix = token, 2
        while candidate in used or candidate == 'all':
            candidate = f'{token}{suffix}'
            suffix += 1
        used.add(candidate)
        return candidate

    def _team_roster(self):
        members, used = [], set()
        for agent in (self.organization or {}).get('agents', []):
            reports_to = agent.get('reports_to')
            if reports_to == 'OWNER_EXTERNAL':
                reports_to = None  # el canal exige jefes dentro del roster; el owner es externo
            members.append({'member_id': agent['id'],
                            'name': self._team_token_name(agent.get('name'), agent.get('slot'), used),
                            'role': str(agent.get('title') or agent.get('role') or '')[:200],
                            'reports_to': reports_to})
        return members

    def _ensure_team_channel(self):
        """Canal dirigido en memoria sobre el roster vigente; se reinicia con cada
        rediseño (el port team_channel.py no persiste, por diseño)."""
        if self.organization is None:
            return None
        signature = (self.organization.get('organization_id'),
                     tuple(agent['id'] for agent in self.organization.get('agents', [])))
        if self.team_channel is None or self._team_channel_signature != signature:
            self.team_channel = TeamChannel(self._team_roster())
            self._team_channel_signature = signature
        return self.team_channel

    def _ensure_team_memory(self):
        """Memoria de equipo persistente (P4) por organización: fragmentos .md gobernados
        más índice MEMORY.md, member 'equipo' compartido por el roster.

        Solo organiza bajo el contrato v1 de tenants (organization_id UUID en
        minúsculas); una plantilla sin UUID no registra boundary y la vista lo
        declara no disponible en vez de inventar una identidad."""
        if self.organization is None:
            return None
        organization_id = self.organization.get('organization_id')
        if not re.fullmatch(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}',
                            str(organization_id or '')):
            return None
        signature = (organization_id,)
        if self._team_memory_store is None or self._team_memory_signature != signature:
            tenant_id = 'orgdna-' + organization_id.replace('-', '')
            registry = TenantRegistry()
            registry.register(TenantBoundary.default(tenant_id, organization_id))
            self._team_memory_registry = registry
            self._team_memory_store = TeamMemoryStore(
                self.project_store.root / '_team_memory', registry, tenant_id, 'equipo')
            self._team_memory_signature = signature
        return self._team_memory_store

    def team_channel_public(self):
        """Vista del canal para el panel: ledger completo (copias) + roster resuelto.

        Un roster inválido (IDs repetidos) degrada a no disponible con el motivo;
        nunca revienta public() del bridge."""
        if self.organization is None:
            return {'available': False, 'reason': 'Genera un diseño para abrir el canal del equipo.'}
        try:
            channel = self._ensure_team_channel()
        except ChannelError as exc:
            return {'available': False, 'reason': 'Roster inválido para el canal: %s' % exc}
        if channel is None:
            return {'available': False, 'reason': 'Genera un diseño para abrir el canal del equipo.'}
        view = channel.ledger_view()
        view['available'] = True
        view['in_memory_session_only'] = True
        return view

    def team_memory_public(self):
        """Índice MEMORY.md del equipo + fragmentos vivos para el panel.

        Sin organization_id UUID (plantilla sin identidad persistente) la vista
        lo declara: la memoria vive solo para organizaciones con contrato v1."""
        store = self._ensure_team_memory()
        if store is None:
            return {'available': False,
                    'reason': 'La memoria de equipo requiere un diseño con organization_id (contrato v1); '
                              'una plantilla sin identidad persistente no registra memoria.'}
        snapshot = store.index_snapshot()
        rows = []
        for line in snapshot['content'].splitlines():
            match = re.match(r'- \[(\w+)\] (\S+) \(([^)]*)\)(?:: (.*))?', line)
            if match:
                rows.append({'plane': match.group(1), 'file': match.group(2),
                             'recorded_at': match.group(3), 'description': match.group(4) or ''})
        return {'available': True, 'index': snapshot, 'fragments': rows,
                'index_path': str(store.index_path), 'tenant_member': 'equipo',
                'append_only': True}

    def _team_apply(self, action, body):
        """Despacha las acciones GenTeam sobre los módulos portados. Todo es registro
        local: nada ejecuta agentes, llama proveedores ni modifica el diseño."""
        if action in TEAM_MEMORY_ACTIONS:
            store = self._ensure_team_memory()
            if store is None:
                raise BridgeError('Genera un diseño actualizado antes de escribir en la memoria de equipo.')
            memory_id = body.get('memory_id')
            if not isinstance(memory_id, str) or not re.fullmatch(MEMORY_ID_PATTERN, memory_id):
                raise BridgeError('memory_id debe tener de 2 a 64 caracteres de [a-z0-9_-] '
                                  '(patron del contrato v1 que aplica el governor de memoria).')
            author = body.get('author')
            if not isinstance(author, str) or not any(m['member_id'] == author for m in self._team_roster()):
                raise BridgeError('author debe ser un miembro del roster vigente.')
            try:
                # El governor exige scope: plane 'project' requiere project_id y
                # 'execution' requiere task_id; el resto queda en scope_kind por plano.
                store.append(memory_id, body.get('plane'), body.get('content'),
                             role_ref=author, description=body.get('description'),
                             ttl_seconds=body.get('ttl_seconds'), author=author,
                             task_id=body.get('task_id'),
                             project_id=body.get('project_id') or self.project.get('id')
                             or self.organization.get('organization_id'),
                             origin_ref='team-memory://panel')
            except MemoryGovernanceError as error:
                raise BridgeError('La memoria de equipo rechazó el alta: %s' % error) from None
            self.receipt(action, 'success',
                         'Memoria de equipo registrada en el índice MEMORY.md. Registro con evidencia; no entrena modelos.')
            return
        channel = self._ensure_team_channel()
        if channel is None:
            raise BridgeError('Genera un diseño actualizado antes de usar el canal del equipo.')
        sender = body.get('sender') or body.get('actor') or body.get('reviewer')
        try:
            if action == 'channel-publish':
                result = channel.publish(sender, to=body.get('to', 'all'), text=body.get('text', ''),
                                         topic=body.get('topic') or 'coordination',
                                         ttl_secs=body.get('ttl_secs'), task_title=body.get('task_title'))
                note = 'Mensaje publicado en el canal dirigido.'
                if result['task'] is not None:
                    note += ' La @mención creó una tarea dirigida (estado open).'
                self.receipt(action, 'success', note)
            elif action == 'channel-assign':
                channel.assign(sender, body.get('member'), body.get('task', ''), title=body.get('title'))
                self.receipt(action, 'success', 'Asignación directa registrada en el canal (estado open).')
            elif action == 'channel-evidence':
                channel.record_evidence(sender, body.get('locator'), body.get('sha256'), body.get('summary'))
                self.receipt(action, 'success', 'Evidencia registrada con SHA declarado; no acredita lectura del artefacto.')
            elif action == 'channel-claim':
                channel.claim(sender, body.get('task_id'), note=body.get('note'))
                self.receipt(action, 'success', 'Tarea reclamada por su dueño en el canal.')
            elif action == 'channel-submit':
                channel.submit(sender, body.get('task_id'), body.get('evidence_ids') or [],
                               output=body.get('output', ''), note=body.get('note'))
                self.receipt(action, 'success', 'Tarea entregada con evidencia; queda pendiente de revisión independiente.')
            elif action == 'channel-accept':
                channel.accept(sender, body.get('task_id'), note=body.get('note'),
                               evidence_ids=body.get('evidence_ids') or [])
                self.receipt(action, 'success', 'Revisión independiente aceptada en el canal.')
            elif action == 'channel-reject':
                channel.reject(sender, body.get('task_id'), note=body.get('note'),
                               evidence_ids=body.get('evidence_ids') or [])
                self.receipt(action, 'success', 'Revisión independiente rechazada en el canal.')
            elif action == 'channel-inbox':
                drained = channel.inbox(body.get('member'), max_count=int(body.get('max_count') or 100))
                self.receipt(action, 'success', 'Inbox drenado: %d mensaje(s) entregados (lectura destructiva).' % len(drained))
            else:
                raise BridgeError('Acción GenTeam desconocida.')
        except ChannelError as error:
            raise BridgeError('El canal rechazó la acción: %s' % error) from None

    # ------------------------------------------------------------- GenTeam P3: seguimiento

    def _followups_clock(self):
        """Reloj del motor de seguimiento (epoch float).

        Es un SEAM DE PRUEBA, no una superficie de producto: el arnes de navegador lo
        sobrescribe en una subclase para avanzar el tiempo sin esperar el intervalo real
        (3600 s) y poder observar un recordatorio. El bridge de produccion no expone
        control de tiempo por HTTP, no lee variables de entorno y no toca el reloj global.
        """
        return time.time()

    def _followups_clock_source(self):
        """`system` o `injected`, por introspeccion del seam (nunca por variable de entorno)."""
        return 'system' if type(self)._followups_clock is BridgeState._followups_clock else 'injected'

    def _followups_identities(self):
        """(identidad de coordinacion, supervision) resueltas sobre el roster vigente.

        Por defecto la coordinacion es el miembro raiz (reports_to externo) y la supervision
        declarada es esa misma identidad: el owner es externo y el panel no inventa un
        supervisor dentro del roster. Ambas pueden fijarse por atributo para operacion.
        """
        roster = self._team_roster()
        if not roster:
            return None, None
        root = next((member for member in roster if member.get('reports_to') is None), roster[0])
        agent = self.followups_agent_member_id or root['member_id']
        supervisor = self.followups_supervisor_member_id or agent
        return agent, supervisor

    def _followups_authority(self):
        """Declaracion de autoria de los recordatorios: identidad de coordinacion, no un miembro."""
        agent, supervisor = self._followups_identities()
        roster = {member['member_id']: member for member in self._team_roster()}
        member = roster.get(agent) or {}
        detail = '"%s (%s)"' % (member.get('name') or 'coordinacion', agent) if agent else 'sin diseno'
        return {'kind': 'coordination', 'is_member_authored': False,
                'actor_member_id': agent, 'supervisor_member_id': supervisor,
                'topic': FOLLOWUP_TOPIC, 'provenance': FOLLOWUPS_PROVENANCE,
                'role_label': 'Coordinacion local (motor de seguimiento)',
                'identity_verified': False,
                'note': 'Los recordatorios y escalaciones los emite el motor engine.followups con la '
                        'identidad de coordinacion %s (miembro raiz, reports_to externo); ningun miembro '
                        'del roster es su autor.' % detail}

    def _team_loop_public(self):
        """Sobre de solo lectura del bucle continuo (engine/team_loop.py).

        NO se cablea a esta vista, y el motivo es de honestidad, no de pereza: cada paso
        del bucle lo ejecuta un TRABAJADOR (`worker=`), y aqui ese trabajador seria el
        runtime de agentes, que este producto no tiene (el envio a DSH es
        CAPABILITY_UNAVAILABLE y la app es inerte por diseno). Cablearlo con un trabajador
        simulado produciria «ciclos» que no hacen nada: apariencia de trabajo continuo.
        Asi que el bucle se publica como lo que es —modulo probado y disponible para un
        LLAMADOR (lanzador, cron, prueba o el dia que exista runtime)— y no se finge.
        """
        return {
            'available': False,
            'wired': False,
            'module': 'engine/team_loop.py',
            'tests': 'tests_team_loop.py',
            'driver': 'run(cycles=N) desde el llamador; start()/stop() son maquina de estados, '
                      'sin hilos dentro del modulo',
            'reason': 'El bucle existe y esta verificado, pero cada paso necesita un trabajador '
                      '(worker=) que ejecute el trabajo del slot. Ese trabajador es el runtime de '
                      'agentes, que no esta disponible en esta app (envio a DSH: '
                      'CAPABILITY_UNAVAILABLE). No se simula: un ciclo sin trabajador real no es '
                      'trabajo, es teatro.',
            'state': None,
        }

    def _followups_unavailable(self, reason):
        """Vista degradada: available=False con motivo. Nunca lanza."""
        try:
            authority, clock = self._followups_authority(), self._followups_clock_source()
        except Exception:  # el motivo ya se declara; la autoria cae a su forma vacia
            authority = {'kind': 'coordination', 'is_member_authored': False, 'actor_member_id': None,
                         'supervisor_member_id': None, 'topic': FOLLOWUP_TOPIC,
                         'provenance': FOLLOWUPS_PROVENANCE,
                         'role_label': 'Coordinacion local (motor de seguimiento)',
                         'identity_verified': False,
                         'note': 'Los recordatorios y escalaciones los emite el motor engine.followups; '
                                 'ningun miembro del roster es su autor.'}
            clock = 'system'
        return {'available': False, 'reason': reason, 'authority': authority,
                'clock_source': clock, 'loop': self._team_loop_public()}

    def _ensure_team_followups(self):
        """Motor de seguimiento sobre EL MISMO TeamChannel del panel (una sola instancia).

        Se reconstruye cuando cambia la firma del roster (el canal tambien se reconstruye,
        de modo que el motor nuevo no puede duplicar tareas de un ledger anterior).
        """
        channel = self._ensure_team_channel()
        if channel is None:
            return None
        agent, supervisor = self._followups_identities()
        if agent is None:
            return None
        signature = (self._team_channel_signature, agent, supervisor)
        if self.team_followups is None or self._followups_signature != signature:
            self.team_followups = FollowupsEngine(channel, agent, supervisor,
                                                  clock=self._followups_clock)
            self._followups_signature = signature
        return self.team_followups

    def followups_public(self):
        """Vista del seguimiento (P3) para el panel: ledger del motor + autoria declarada.

        `public()` se llama en cada lectura de estado: esta vista NUNCA lanza. Sin diseno,
        sin canal o con roster invalido devuelve `available: false` con el motivo.
        """
        try:
            channel = self._ensure_team_channel()
            if channel is None:
                return self._followups_unavailable('Genera un diseno para abrir el seguimiento del equipo.')
            engine = self._ensure_team_followups()
            if engine is None:
                return self._followups_unavailable('Genera un diseno para abrir el seguimiento del equipo.')
            view = engine.ledger_view()
            view.update({'available': True, 'reason': None, 'in_memory_session_only': True,
                         'reset_policy': 'session_only', 'authority': self._followups_authority(),
                         'clock_source': self._followups_clock_source(),
                         'loop': self._team_loop_public()})
            return view
        except (ChannelError, FollowupsError) as error:
            return self._followups_unavailable('El motor de seguimiento no esta disponible: %s' % error)
        except Exception as error:  # defensa explicita: una vista rota no tumba el panel
            return self._followups_unavailable(
                'El motor de seguimiento fallo (%s): %s' % (type(error).__name__, error))

    def _followups_apply(self, action, body):
        """Despacha las acciones P3 y devuelve el sobre efimero de la accion.

        Registro local: no ejecuta agentes, no llama proveedores, no abre red y no escribe
        fuera del proyecto local. El sobre (`followups_tick` / `followups_drained`) viaja
        solo en la respuesta de la accion, nunca en /api/state.
        """
        engine = self._ensure_team_followups()
        if engine is None:
            raise BridgeError('Genera un diseno actualizado antes de usar el seguimiento del equipo.')
        if action == 'followups-tick':
            events = engine.tick()
            counts = {}
            for row in events:
                kind = row.get('event') if isinstance(row, dict) else None
                counts[kind] = counts.get(kind, 0) + 1
            envelope = {'events': len(events), 'commitments': counts.get('commitment', 0),
                        'reminders': counts.get('reminder', 0),
                        'escalations': counts.get('escalated', 0),
                        'reported': counts.get('reported', 0),
                        'skipped': counts.get('commitment_skipped', 0), 'at': now()}
            self.receipt(action, 'success',
                         'Tick explicito de seguimiento: %d evento(s), %d recordatorio(s), %d escalacion(es). '
                         'No se ejecutaron agentes ni se llamo a ningun proveedor.'
                         % (len(events), envelope['reminders'], envelope['escalations']))
            return {'followups_tick': self.redact(envelope)}
        if action == 'followups-drain':
            member = body.get('member')
            max_count = body.get('max_count')
            if not isinstance(member, str) or not member.strip():
                raise BridgeError('member debe ser un miembro del roster vigente.')
            if isinstance(max_count, bool) or not isinstance(max_count, int) \
                    or not 1 <= max_count <= FOLLOWUPS_MAX_DRAIN:
                raise BridgeError('max_count debe ser un entero entre 1 y %d.' % FOLLOWUPS_MAX_DRAIN)
            channel = self._ensure_team_channel()
            try:
                channel.resolve(member)
            except ChannelError:
                raise BridgeError('member debe ser un miembro del roster vigente.') from None
            drained = list(channel.inbox(member, max_count=max_count))
            reminders = [row for row in drained if row.get('topic') == FOLLOWUP_TOPIC]
            other = [row for row in drained if row.get('topic') != FOLLOWUP_TOPIC]
            authority = self._followups_authority()
            for row in reminders:
                row['authority'] = dict(authority)
            envelope = {'member': member, 'max_count': max_count, 'at': now(),
                        'reminders': reminders, 'other': other,
                        'counts': {'delivered': len(drained), 'reminders': len(reminders),
                                   'other': len(other)}}
            self.receipt(action, 'success',
                         'Inbox de seguimiento drenado: %d mensaje(s) entregados (%d recordatorio(s) de '
                         'seguimiento, %d de otros topicos; lectura destructiva).'
                         % (len(drained), len(reminders), len(other)))
            return {'followups_drained': self.redact(envelope)}
        raise BridgeError('Accion de seguimiento desconocida.')

    # -------------------------------------------------- GenTeam P1/M4: sandbox

    def _sandbox_policy(self):
        """Politica v1 que gobierna el sandbox: la del contrato, o la inyectada en pruebas.

        No se construye ninguna puerta nueva ni se relaja ninguna: se consume
        `engine/policy_engine.py` tal cual. Por defecto, las ocho puertas quedan en
        `require_human_approval` y la escritura (`write_file`) levanta la puerta `write`.
        """
        if self._sandbox_policy_override is not None:
            return self._sandbox_policy_override
        if self._sandbox_policy_cache is None:
            organization_id = str((self.organization or {}).get('organization_id') or '')
            candidate = organization_id if re.fullmatch(r'[a-z0-9][a-z0-9._-]{1,40}',
                                                        organization_id) else 'orgdna-plataforma'
            self._sandbox_policy_cache = platform_policy.Policy.default(candidate)
        return self._sandbox_policy_cache

    def _sandbox_instant(self):
        return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(self.sandbox_clock()))

    def _sandbox_data_root(self):
        if self._sandbox_data_root_override is not None:
            return Path(self._sandbox_data_root_override)
        return self.project_store.root / '_sandbox'

    def _sandbox_member(self, agent_id):
        """El agente debe ser miembro del roster vigente; se valida ANTES de tocar el disco."""
        if not isinstance(agent_id, str) or not agent_id.strip():
            raise BridgeError('agent_id debe ser un miembro del roster vigente.')
        channel = self._ensure_team_channel()
        if channel is None:
            raise BridgeError('Genera un diseno actualizado antes de usar el sandbox.')
        try:
            member = channel.resolve(agent_id.strip())
        except ChannelError:
            raise BridgeError('agent_id debe ser un miembro del roster vigente; no se toco '
                              'el disco ni se creo ninguna solicitud.') from None
        roster = {row['member_id']: row for row in self._team_roster()}
        return roster.get(member.member_id) or {'member_id': member.member_id,
                                                'name': member.member_id}

    def _sandbox_recipient(self, member):
        """Destinatario de la entrega: la identidad de coordinacion (miembro raiz)."""
        roster = self._team_roster()
        roots = [row for row in roster if not row.get('reports_to')]
        return (roots[0] if roots else (roster[0] if roster else member))['member_id']

    @staticmethod
    def _sandbox_digest(value):
        return hashlib.sha256(value.encode('utf-8')).hexdigest()

    def _sandbox_limits(self, body):
        timeout = body.get('timeout_seconds', sandbox_runtime.DEFAULT_TIMEOUT_SECONDS)
        if isinstance(timeout, bool) or not isinstance(timeout, int) \
                or not 1 <= timeout <= sandbox_runtime.MAX_TIMEOUT_SECONDS:
            raise BridgeError('timeout_seconds debe ser un entero entre 1 y %d.'
                              % sandbox_runtime.MAX_TIMEOUT_SECONDS)
        limit = body.get('max_output_bytes', sandbox_runtime.DEFAULT_MAX_OUTPUT_BYTES)
        if isinstance(limit, bool) or not isinstance(limit, int) \
                or not sandbox_runtime.MIN_MAX_OUTPUT_BYTES <= limit <= sandbox_runtime.MAX_MAX_OUTPUT_BYTES:
            raise BridgeError('max_output_bytes debe ser un entero entre %d y %d.'
                              % (sandbox_runtime.MIN_MAX_OUTPUT_BYTES,
                                 sandbox_runtime.MAX_MAX_OUTPUT_BYTES))
        return timeout, limit

    def _sandbox_request_or_error(self, request_id):
        if not isinstance(request_id, str) or request_id not in self.sandbox_requests:
            raise BridgeError('request_id desconocido: crea primero la solicitud con '
                              'sandbox-request.')
        return self.sandbox_requests[request_id]

    def _sandbox_request_view(self, record):
        """Vista declarativa de la solicitud: sin ejecutar, con el motivo del bloqueo."""
        approval = record.get('approval') or {}
        if not record['executable']:
            blocked = 'policy_denied'
        elif not approval:
            blocked = 'human_approval_required'
        elif record.get('consumed_at'):
            blocked = 'approval_consumed'
        elif self.sandbox_clock() - (record.get('approval_epoch') or 0) > SANDBOX_APPROVAL_TTL_SECONDS:
            blocked = 'approval_expired'
        else:
            blocked = 'ready'
        return {'request_id': record['request_id'], 'agent_id': record['agent_id'],
                'agent_name': record.get('agent_name'), 'created_at': record['created_at'],
                'code_view': record['code_view'], 'code_truncated': record['code_truncated'],
                'code_bytes': record['code_bytes'], 'code_sha256': record['code_sha256'],
                'timeout_seconds': record['timeout_seconds'],
                'max_output_bytes': record['max_output_bytes'],
                'scope_hash': record['scope_hash'], 'policy': dict(record['policy']),
                'action': {'action_kind': record['action']['action_kind'],
                           'target': record['action']['target']},
                'executable': record['executable'], 'approved': bool(approval),
                'approved_at': record.get('approved_at'),
                'approver_role': approval.get('approver_role'),
                'approval_ttl_seconds': SANDBOX_APPROVAL_TTL_SECONDS,
                'consumed_at': record.get('consumed_at'),
                'consumed_reason': record.get('consumed_reason'),
                'blocked_reason': blocked, 'run_id': record.get('run_id')}

    def _sandbox_run_view(self, run):
        """Vista acotada de la ejecucion: estado real, artefacto firmado y evidencia."""
        artifact = run.get('artifact') or None
        return {'run_id': run['run_id'], 'agent_id': run['agent_id'],
                'status': run['status'], 'ok': run['ok'], 'exit_code': run['exit_code'],
                'timed_out': run['timed_out'], 'output_truncated': run['output_truncated'],
                'stdout': run['stdout'][:2000], 'stderr': run['stderr'][:2000],
                'stdout_bytes': run['stdout_bytes'], 'stderr_bytes': run['stderr_bytes'],
                'error': run['error'], 'sandboxed': False,
                'os_isolation': run['os_isolation'],
                'policy': dict(run['policy']),
                'artifact': dict(artifact) if artifact else None,
                'artifact_error': run['artifact_error'],
                'evidence_id': run['evidence_id'], 'delivered_to': run['delivered_to'],
                'delivery_error': run['delivery_error']}

    def _sandbox_request(self, body):
        """Paso 1: valida, evalua la politica y devuelve request_id + scope_hash + vista."""
        member = self._sandbox_member(body.get('agent_id'))
        code = body.get('code')
        if not isinstance(code, str) or not code.strip():
            raise BridgeError('code debe ser codigo explicito no vacio.')
        if len(code) > SANDBOX_MAX_CODE_CHARS:
            raise BridgeError('code supera el tope de %d caracteres.'
                              % SANDBOX_MAX_CODE_CHARS)
        timeout_seconds, max_output_bytes = self._sandbox_limits(body)
        if len(self.sandbox_requests) >= SANDBOX_MAX_REQUESTS:
            raise BridgeError('Cola de solicitudes llena (%d): resuelve o ejecuta las '
                              'pendientes antes de crear otra.' % SANDBOX_MAX_REQUESTS)
        policy = self._sandbox_policy()
        request_id = uuid.uuid4().hex
        action = {'action_kind': 'write_file',
                  'target': 'sandbox/%s/%s.py' % (request_id, member['member_id']),
                  'idempotency_key': 'sbx-' + request_id}
        scope_hash = policy.scope_hash(action)
        action['scope_hash'] = scope_hash
        decision = platform_policy.evaluate(policy, action, now=self._sandbox_instant())
        record = {'request_id': request_id, 'agent_id': member['member_id'],
                  'agent_name': member.get('name'), 'code': code,
                  'code_sha256': self._sandbox_digest(code),
                  'code_bytes': len(code.encode('utf-8')),
                  'code_view': code[:SANDBOX_CODE_VIEW_CHARS],
                  'code_truncated': len(code) > SANDBOX_CODE_VIEW_CHARS,
                  'timeout_seconds': timeout_seconds, 'max_output_bytes': max_output_bytes,
                  'action': action, 'scope_hash': scope_hash,
                  'policy': {'decision': decision['decision'], 'gate': decision['gate'],
                             'reason': decision['reason'],
                             'policy_id': decision['policy_id'],
                             'policy_revision': decision['policy_revision'],
                             'rules': [rule['rule_id'] for rule in decision['matched_rules']]},
                  'executable': decision['decision'] != platform_policy.DECISION_DENY,
                  'created_at': now(), 'approved_at': None, 'approval': None,
                  'approval_epoch': None, 'consumed_at': None, 'consumed_reason': None,
                  'run_id': None}
        self.sandbox_requests[request_id] = record
        self.receipt('sandbox-request', 'pending',
                     'Solicitud de sandbox preparada SIN ejecutar: agente %s, %d bytes de codigo, '
                     'puerta %s, decision %s. Faltan la aprobacion humana y la ejecucion explicita.'
                     % (member.get('name') or member['member_id'], record['code_bytes'],
                        decision['gate'] or 'ninguna', decision['decision']),
                     request_id=request_id, scope_hash=scope_hash,
                     policy_decision=decision['decision'])
        return self.redact(self._sandbox_request_view(record))

    def _sandbox_approve(self, body):
        """Paso 2: registra la aprobacion de un solo uso ligada a (request_id, scope_hash)."""
        record = self._sandbox_request_or_error(body.get('request_id'))
        scope_hash = body.get('scope_hash')
        if not isinstance(scope_hash, str) or scope_hash != record['scope_hash']:
            raise BridgeError('scope_mismatch: el scope_hash no corresponde a esta solicitud '
                              '(vigente: %s); la aprobacion no se registra.'
                              % record['scope_hash'])
        if record.get('consumed_at'):
            raise BridgeError('replay_rejected: la aprobacion de esta solicitud ya fue consumida '
                              '(%s); crea una solicitud nueva.' % record['consumed_reason'])
        if not record['executable'] or record['policy']['decision'] == platform_policy.DECISION_DENY:
            raise BridgeError("La politica deniega esta solicitud (gate %s): ninguna aprobacion "
                              'del panel la convierte en allow.' % (record['policy']['gate'] or 'write'))
        role = body.get('approver_role', SANDBOX_APPROVER_ROLE)
        if not isinstance(role, str) or not role.strip() or len(role) > 120 \
                or any(ord(character) < 32 for character in role):
            raise BridgeError('approver_role debe ser un rol declarativo de 1 a 120 caracteres.')
        if not record.get('approval'):
            record['approval'] = {'gate': record['policy']['gate'] or 'write',
                                  'approver_role': role.strip(),
                                  'approved_at': now(),
                                  'scope_hash': record['scope_hash'], 'one_shot': True}
            record['approved_at'] = record['approval']['approved_at']
            record['approval_epoch'] = self.sandbox_clock()
            self.receipt('sandbox-approve', 'success',
                         "Aprobacion de un solo uso registrada para la solicitud %s (puerta '%s', "
                         'scope_hash %s). Declarativa: identidad no autenticada. Aun no se ejecuto nada.'
                         % (record['request_id'], record['approval']['gate'],
                            record['scope_hash'][:16]),
                         request_id=record['request_id'], scope_hash=record['scope_hash'])
        return self.redact(self._sandbox_request_view(record))

    def _sandbox_executor(self, policy, record):
        """Ejecutor P1 con un aprobador que traduce la aprobacion del panel UNA sola vez."""
        minted = {'done': False}

        def approver(*, gate, action, expected_scope_hash, decision):
            approval = record.get('approval') or {}
            if minted['done'] or not approval or approval.get('scope_hash') != record['scope_hash']:
                return None
            minted['done'] = True
            return {'gate': gate, 'approver_role': approval.get('approver_role')
                    or SANDBOX_APPROVER_ROLE,
                    'approved_at': approval.get('approved_at') or now(),
                    'scope_hash': expected_scope_hash, 'one_shot': True}

        return sandbox_runtime.SandboxExecutor(policy, data_root=self._sandbox_data_root(),
                                               approver=approver, clock=self.sandbox_clock)

    def _sandbox_exec(self, body):
        """Paso 3: unico camino que ejecuta. Exige aprobacion vigente; la politica manda."""
        record = self._sandbox_request_or_error(body.get('request_id'))
        submitted_code = body.get('code')
        if submitted_code is not None:
            if not isinstance(submitted_code, str):
                raise BridgeError('code debe ser texto si se envia.')
            if self._sandbox_digest(submitted_code) != record['code_sha256']:
                raise BridgeError('scope_mismatch: el codigo enviado no es el aprobado (sha256 '
                                  'distinto); la aprobacion no autoriza esta ejecucion y no se '
                                  'ejecuta nada.')
        submitted_agent = body.get('agent_id')
        if submitted_agent is not None and submitted_agent != record['agent_id']:
            raise BridgeError('scope_mismatch: el agent_id no es el de la solicitud aprobada.')
        gate_name = record['policy']['gate'] or 'write'
        if not record.get('approval'):
            raise BridgeError("gate '%s': requiere aprobacion humana en dos pasos "
                              '(sandbox-request -> sandbox-approve) antes de ejecutar; '
                              'no se ejecuto nada.' % gate_name)
        if record.get('consumed_at'):
            raise BridgeError('replay_rejected: la aprobacion de esta solicitud ya fue consumida '
                              '(%s); crea una solicitud nueva y apruebala.'
                              % record['consumed_reason'])
        if self.sandbox_clock() - (record.get('approval_epoch') or 0) > SANDBOX_APPROVAL_TTL_SECONDS:
            raise BridgeError('approval_expired: la aprobacion supero su vigencia de %d s; '
                              'solicita y aprueba de nuevo.' % SANDBOX_APPROVAL_TTL_SECONDS)
        policy = self._sandbox_policy()
        decision = platform_policy.evaluate(policy, record['action'], now=self._sandbox_instant())
        if decision['decision'] == platform_policy.DECISION_DENY:
            record['consumed_at'] = now()
            record['consumed_reason'] = 'policy_denied'
            self.receipt('sandbox-exec', 'warning',
                         'La politica denego la ejecucion en el momento de ejecutar: no se ejecuto '
                         'nada. La aprobacion del panel se consumio en el intento.',
                         request_id=record['request_id'])
            raise BridgeError('deny: la politica deniega esta ejecucion (gate %s): %s'
                              % (decision['gate'], decision['reason']))
        # La aprobacion se consume ANTES de ejecutar: pase lo que pase, no se reutiliza.
        record['consumed_at'] = now()
        record['consumed_reason'] = 'exec_attempted'
        member = self._sandbox_member(record['agent_id'])
        channel = self._ensure_team_channel()
        executor = self._sandbox_executor(policy, record)
        try:
            run = executor.execute(record['agent_id'], record['code'], channel=channel,
                                   recipient=self._sandbox_recipient(member),
                                   timeout_seconds=record['timeout_seconds'],
                                   max_output_bytes=record['max_output_bytes'])
        except sandbox_runtime.SandboxPolicyError as exc:
            record['consumed_reason'] = 'policy_gate'
            self.receipt('sandbox-exec', 'warning',
                         "El ejecutor bloqueo la ejecucion en la puerta '%s': no se ejecuto nada. "
                         'La aprobacion se consumio en el intento.' % (exc.gate or gate_name),
                         request_id=record['request_id'])
            raise BridgeError("gate '%s': %s" % (exc.gate or gate_name, exc)) from None
        except sandbox_runtime.SandboxConfigError as exc:
            record['consumed_reason'] = 'invalid_config'
            raise BridgeError('No se pudo ejecutar: %s La aprobacion se consumio en el intento.'
                              % exc) from None
        record['run_id'] = run['run_id']
        self.sandbox_runs.append(run)
        self.sandbox_runs = self.sandbox_runs[-SANDBOX_MAX_RUNS:]
        artifact = run.get('artifact') or {}
        self.receipt('sandbox-exec', 'success' if run['ok'] else 'warning',
                     'Ejecucion sandbox %s para %s: status %s, exit_code %s. Artefacto sha256=%s '
                     'entregado a %s (evidencia %s). Aprobacion consumida.'
                     % (run['run_id'], run['agent_id'], run['status'], run['exit_code'],
                        artifact.get('sha256') or '(sin firma: %s)' % run['artifact_error'],
                        run['delivered_to'] or '(sin canal)', run['evidence_id'] or '(ninguna)'),
                     request_id=record['request_id'], run_id=run['run_id'])
        return self.redact(self._sandbox_run_view(run))

    def _sandbox_apply(self, action, body):
        """Despacha las acciones P1/M4 y devuelve el sobre de la accion."""
        if action == 'sandbox-request':
            return {'sandbox_request': self._sandbox_request(body)}
        if action == 'sandbox-approve':
            return {'sandbox_approval': self._sandbox_approve(body)}
        if action == 'sandbox-exec':
            return {'sandbox_execution': self._sandbox_exec(body)}
        raise BridgeError('Accion de sandbox desconocida.')

    def sandbox_public(self):
        """Estado de las puertas, solicitudes y ejecuciones. Nunca lanza (vista degradada)."""
        view = {'available': False,
                'reason': 'Genera un diseno para abrir el sandbox del panel.',
                'provenance': SANDBOX_PROVENANCE,
                'flow': {'steps': ['sandbox-request', 'sandbox-approve', 'sandbox-exec'],
                         'two_step_required': True, 'single_use_approval': True,
                         'deny_by_default': True,
                         'approval_ttl_seconds': SANDBOX_APPROVAL_TTL_SECONDS,
                         'consumes_policy_gates': True, 'adds_new_gates': False},
                'policy': None, 'requests': [], 'executions': [],
                'counts': {'requests': 0, 'pending': 0, 'approved': 0, 'executed': 0},
                'sandboxed': False,
                'os_isolation': sandbox_runtime.OS_ISOLATION_NOTE,
                'in_memory_session_only': True,
                'max_requests': SANDBOX_MAX_REQUESTS,
                'max_code_chars': SANDBOX_MAX_CODE_CHARS}
        try:
            if self.organization is None:
                return self.redact(view)
            policy = self._sandbox_policy()
            limits = policy.limits
            view['available'] = True
            view['reason'] = None
            view['policy'] = {'policy_id': policy.policy_id,
                              'policy_revision': policy.policy_revision,
                              'policy_hash': policy.policy_hash,
                              'gates': [{'gate': gate,
                                         'default_outcome': policy.gate_default_outcome(gate),
                                         'required': gate in limits['approvals_required']}
                                        for gate in platform_policy.GATES],
                              'approvals_required': list(limits['approvals_required']),
                              'write_allowed': limits['write_allowed'],
                              'network_allowed': limits['network_allowed'],
                              'autonomy_ceiling': limits['autonomy_ceiling'],
                              'gates_total': len(platform_policy.GATES)}
            requests = [self._sandbox_request_view(record)
                        for record in self.sandbox_requests.values()]
            view['requests'] = requests
            view['executions'] = [self._sandbox_run_view(run) for run in self.sandbox_runs]
            view['counts'] = {'requests': len(requests),
                              'pending': sum(1 for row in requests
                                             if row['blocked_reason'] == 'human_approval_required'),
                              'approved': sum(1 for row in requests if row['approved']),
                              'executed': len(self.sandbox_runs)}
            return self.redact(view)
        except Exception as exc:  # la vista nunca revienta public()
            view['available'] = False
            view['reason'] = 'Sandbox no disponible: %s' % self.redact(str(exc))
            return self.redact(view)


    def merge_preferences(self, preferences):
        by_key = {(m.get('provider'), m.get('model', m.get('id'))): m for m in self.models}
        for pref in normalize_preferences(preferences):
            key = (pref['provider'], pref['model'])
            target = by_key.get(key)
            if target is None:
                target = dict(pref, id=pref['model'], available=None, availability_verified=False,
                    source='workbook_reference_not_account_verification', status='MANUAL_NOT_VERIFIED')
                self.models.append(target)
                by_key[key] = target
            else:
                for field in ('user_rank', 'capabilities', 'context_window', 'input_modalities', 'output_modalities', 'max_output_tokens'):
                    if field == 'user_rank':
                        target.pop(field, None)
                    if field in pref:
                        target[field] = pref[field]

    def generation_catalog(self):
        models = [dict(m) for m in self.models]
        choices = {(self.config['provider'], self.config['model'])}
        choices.update((a.get('provider', self.config['provider']), a.get('model', self.config['model'])) for a in self.model_overrides.values())
        # API catalogs do not enumerate local DSH aliases. Preserve every current
        # runtime route as an unverified reference unless an exact row exists.
        choices.update((a['provider'], a['model']) for a in (self.organization or {}).get('agents', []))
        runtime_blocked = {(a['provider'], a['model']) for a in (self.organization or {}).get('agents', [])
                           if a.get('model_verification', {}).get('runtime_status') == 'UNAVAILABLE'}
        for provider, model in choices:
            if (provider, model) in runtime_blocked:
                models.append({'provider': provider, 'model': model, 'available': False, 'source': 'runtime_unavailable_preserved', 'catalog_scope': 'dsh_runtime'})
            if not any((m.get('provider'), m.get('model', m.get('id'))) == (provider, model) for m in models):
                models.append({'provider': provider, 'model': model, 'available': None, 'source': 'manual_not_verified', 'catalog_scope': 'dsh_runtime_reference'})
        return models or None

    def _api_account_stamp(self, config):
        """Ephemeral account binding. Never exported, saved or used as a key."""
        key = self.credentials.get(config['provider'])
        return hmac.new(self.csrf.encode('utf-8'), key.encode('utf-8'), hashlib.sha256).hexdigest() if key else None

    def _record_model_account(self, config):
        self._model_account_stamps[(config['provider'], config['model'])] = self._api_account_stamp(config)

    def _api_row_current(self, row, config):
        stamp = self._api_account_stamp(config)
        return bool(stamp and self._model_account_stamps.get((row.get('provider'), row.get('model', row.get('id')))) == stamp)

    def api_model_metadata(self, config):
        route = PROVIDER_ROUTES[config['provider']]
        rows = [row for row in self.models if isinstance(row, dict) and
                PROVIDER_ROUTES.get(row.get('provider')) == route and
                row.get('model', row.get('id')) == config['model'] and
                row.get('catalog_scope') not in ('dsh_runtime', 'dsh_runtime_reference')]
        verified = [row for row in rows if row.get('available') is True and self._api_row_current(row, config) and
                    (row.get('source') == 'live_api' or row.get('status') == 'VERIFIED_INFERENCE' or
                     row.get('source') == 'live_inference' and row.get('availability_verified') is True)]
        documented = [row for row in rows if row.get('source') == 'official_docs_snapshot' and
                      row.get('available') is not False] if load_providers().provider_config(route)['discovery'] is False else []
        return copy.deepcopy((verified or documented)[0]) if verified or documented else None

    def public_models(self):
        rows = copy.deepcopy(self.models)
        for row in rows:
            route = PROVIDER_ROUTES.get(row.get('provider'))
            if (not route or row.get('catalog_scope') in ('dsh_runtime', 'dsh_runtime_reference') or
                    not (row.get('source') in ('live_api', 'live_inference') or row.get('status') == 'VERIFIED_INFERENCE')):
                continue
            config = self.config if PROVIDER_ROUTES[self.config['provider']] == route else {'provider': row['provider']}
            if not self._api_row_current(row, config):
                row.update(available=None, availability_verified=False, status='ACCOUNT_RECHECK_REQUIRED',
                           account_verification_status='recheck_required')
            else:
                row['account_verification_status'] = 'current_session_match'
        return rows

    def validate_api_model_choice(self, config, manual_confirmed=False):
        # Exact provider API IDs only. Never reinterpret a display name or a DSH
        # alias, and never silently pick another model from the catalog.
        route = PROVIDER_ROUTES[config['provider']]
        route_rows = [m for m in self.models if isinstance(m, dict) and
                      PROVIDER_ROUTES.get(m.get('provider')) == route and
                      m.get('catalog_scope') not in ('dsh_runtime', 'dsh_runtime_reference')]
        # La notacion se RESUELVE para DIAGNOSTICAR, nunca para aceptar. Dos tests
        # del repositorio prohiben expresamente que un nombre visible pase por un ID
        # ('test_api_display_name_or_alias_rejected_even_if_manual_preference_exists'
        # y 'test_provider_alias_does_not_bypass_exact_api_catalog'), y el catalogo
        # de prueba lleva 'name' a proposito para que exista y aun asi no se use.
        # Este modulo NO cambia esa regla: solo hace que el error diga cual es el ID
        # exacto, en vez de dejar al operador en un callejon sin salida.
        resolution = model_resolver.resolve(config['model'], route_rows)
        rows = [m for m in route_rows if m.get('model', m.get('id')) == config['model']]
        api_rows = [m for m in rows if m.get('available') is True and
                    self._api_row_current(m, config) and
                    (m.get('source') == 'live_api' or m.get('status') == 'VERIFIED_INFERENCE' or
                     (m.get('source') == 'live_inference' and m.get('availability_verified') is True))]
        if any(m.get('available') is False for m in rows):
            api_rows = []
        if api_rows:
            inference = any(m.get('status') == 'VERIFIED_INFERENCE' or m.get('source') == 'live_inference' for m in api_rows)
            return {'status': 'inference_verified' if inference else 'catalog_verified',
                'provider': config['provider'], 'model': config['model'], 'account_verified': True,
                'capabilities_verified': False}
        # A provider without a documented list endpoint needs an explicit,
        # honest manual path. A reference is not an account/capability check.
        policy = load_providers().provider_config(route)
        documented = (not any(m.get('available') is False for m in rows) and
                      any(m.get('source') == 'official_docs_snapshot' and m.get('available') is not False for m in rows))
        if policy['discovery'] is False and documented:
            if manual_confirmed is not True:
                raise BridgeError('Este proveedor no tiene un catálogo de cuenta documentado. Confirma explícitamente el ID de la referencia oficial; disponibilidad de cuenta y capacidades siguen sin verificar.')
            return {'status': 'manual_documented', 'provider': config['provider'], 'model': config['model'],
                'account_verified': False, 'capabilities_verified': False, 'documentation_url': policy.get('docs')}
        raise BridgeError('El ID elegido para la API no está verificado. Consulta el catálogo y elige un ID exacto antes de preparar el consentimiento; un nombre visible o alias local DSH puede ser distinto. No se cambió ningún modelo ni se inició una llamada de diseño. ' + model_resolver.describe(resolution))



    def _provider(self):
        return self.provider_module or load_providers()

    def project_snapshot(self):
        # Explicit allowlist. No credentials, browser-session material, pending
        # approvals, source-machine workbook paths, or DPAPI bytes are saved.
        self.remember_current_design()
        if self.redact(self._design_context) != self._design_context:
            raise BridgeError('Una credencial aparece en el contexto conservado. Corrige esa coincidencia antes de guardar el proyecto.')
        return self.redact({'config': self.config, 'organization': self.organization,
            'design_context': self._design_context, 'recovery_draft_config': self.recovery_draft_config,
            'generation_stale': self.generation_stale, 'has_manual_edits': self.has_manual_edits,
            'model_overrides': self.model_overrides, 'models': self.models,
            'analysis': self.analysis, 'repo_inventory': self.repo_inventory,
            'receipts': self.receipts, 'records': self.records, 'records_version': self.records_version,
            'generation_history': self.generation.saved(),
            'coordination_snapshot': self.coordination_store.public(), 'integrations': self.integrations.saved(),
            'capability_library': self.capabilities_hub.saved()})

    def load_project(self, body):
        if self.project.get('dirty') and body.get('confirmed') is not True:
            raise BridgeError('Hay cambios sin guardar. Guarda una versión o confirma que deseas cargar el proyecto seleccionado.')
        envelope = self.project_store.load(body.get('project_id'), body.get('version_id'))
        snapshot = envelope['snapshot']
        # Validate receipt history before any mutation. Older projects omit it.
        history_check = GenerationPipeline(self)
        history_check.load_saved(snapshot.get('generation_history'))
        organization = snapshot.get('organization')
        saved_config = dict(snapshot.get('config', {}))
        design_context = snapshot.get('design_context')
        if design_context is not None:
            expected_keys = {'config', 'organization_id', 'organization_config_sha256', 'model_overrides', 'analysis', 'repo_inventory', 'snapshot_id'}
            if not isinstance(design_context, dict) or set(design_context) != expected_keys:
                raise BridgeError('Contexto de recuperación guardado no válido.')
            payload = {k: v for k, v in design_context.items() if k != 'snapshot_id'}
            if design_context['snapshot_id'] != self._design_digest(payload):
                raise BridgeError('El contexto de recuperación no coincide con su hash.')
            normalize_config(design_context['config'])
            if not isinstance(design_context['model_overrides'], dict):
                raise BridgeError('Asignaciones de recuperación no válidas.')
        recovery_draft = snapshot.get('recovery_draft_config')
        if recovery_draft is not None:
            recovery_draft = normalize_config(recovery_draft)
        if 'autonomy_preset' not in saved_config and organization is not None:
            saved_config['autonomy_preset'] = (organization.get('autonomy') or {}).get('preset', 'manual')
        config = normalize_config(saved_config)
        if organization is not None:
            validation = load_core().validate_organization(organization)
            structural = [e for e in validation.get('errors', []) if not e.startswith('Modelo no disponible:')]
            if structural:
                raise BridgeError('El diseño guardado no supera la validación: ' + '; '.join(structural))
            # Historical availability is not an account check in this session.
            previous_organization = organization
            organization = load_core().refresh_model_catalog(organization, None)
            design_context = self._refreshed_design_context(design_context, previous_organization, organization)
        models = []
        for row in snapshot.get('models', []):
            if isinstance(row, dict):
                models.append(dict(row, available=None, availability_verified=False,
                    status='UNVERIFIED_SAVED_PROJECT', prior_source=row.get('source'), source='saved_project_reference'))
        records = snapshot.get('records', {})
        if not isinstance(records, dict):
            raise BridgeError('El proyecto contiene un registro local no válido.')
        record_limits = [('council_sessions', 100), ('skill_registry', 500), ('remediation_records', 500), ('subteams', 100),
                         ('performance_records', 2000), ('promotion_records', 500), ('governance_events', 10000)]
        for key, limit in record_limits:
            if not isinstance(records.get(key, []), list) or len(records.get(key, [])) > limit or any(not isinstance(row, dict) for row in records.get(key, [])):
                raise BridgeError('El proyecto contiene un registro local no válido.')
        if organization is not None:
            organization = ensure_governance(organization)
            build_scoreboard(organization, records)  # Validate derived view before committing loaded state.
        records_version = snapshot.get('records_version', 1)
        if type(records_version) is not int or records_version < 1:
            raise BridgeError('Versión de registros locales no válida.')
        integrations = IntegrationTools(self)
        integrations.load_saved(snapshot.get('integrations'))
        integrations.adopt_connection(self.integrations)
        library_snapshot = snapshot.get('capability_library') or {}
        if not isinstance(library_snapshot, dict) or set(library_snapshot) - {'library_id', 'library_revision'}:
            raise BridgeError('Referencia de biblioteca guardada inválida.')
        capabilities_hub = CapabilityHub(self, library_snapshot.get('library_id'), library_snapshot.get('library_revision'))
        self.integrations = integrations
        self.dsh_harness.connection = self.integrations._connection()
        self.resource_workflows = ResourceWorkflows(self)
        self.capabilities_hub = capabilities_hub
        self.capability_recommendations = IntegrationRecommendations(self)
        self.config = config
        self.config_version += 1
        self.generation.invalidate('Se cargó otro proyecto. La generación pendiente no se aplicará.')
        self.generation.load_saved(history_check.saved())
        self.organization = organization
        self._design_context = copy.deepcopy(design_context)
        self.recovery_draft_config = recovery_draft
        self._last_design_restore = None
        self.generation_stale = bool(snapshot.get('generation_stale'))
        self.has_manual_edits = bool(snapshot.get('has_manual_edits'))
        self.model_overrides = snapshot.get('model_overrides', {})
        self.models = models
        self.verified_catalog_providers = set()
        self.analysis = snapshot.get('analysis')
        self.repo_inventory = snapshot.get('repo_inventory')
        self.pending_consent = None
        self.workbook = ''
        self.workbook_snapshot = None
        self.receipts = snapshot.get('receipts', [])[-100:]
        self.records = {key: records.get(key, []) for key, _ in record_limits}
        self.records_version = records_version
        # Saved ticket snapshots are historical only. The global durable ledger
        # remains authoritative; loading or forking a project never revives leases.
        meta = envelope['metadata']
        self.project = {'id': meta['project_id'], 'name': meta['name'], 'version_id': meta['version_id'], 'dirty': False}
        self.receipt('project-load', 'success', 'Proyecto cargado. La disponibilidad guardada vuelve a no verificada; no se restauran claves ni autorizaciones de gasto.')

    def execute(self, action, body):
        with self.lock:
            if not isinstance(body, dict):
                raise BridgeError('El cuerpo debe ser un objeto JSON.')
            if action == 'platform-planes-status':
                # Unica accion de la capa V9: solo lectura, antes de cualquier memo o
                # invalidacion, para que no toque estado ni marque el proyecto como sucio.
                return self.platform_planes_status()
            self.remember_current_design()
            if action == 'design-restore':
                self.restore_design(body)
                return self.public()
            if action in ('evaluation-prepare', 'evaluation-start', 'evaluation-cancel'):
                if action != 'evaluation-cancel':
                    if self.organization is None or self.generation_stale or self.generation._active():
                        raise BridgeError('Prepara un diseño vigente y termina la generación antes de evaluar.')
                    if self.redact(body) != body:
                        raise BridgeError('No incluyas claves de sesión en un plan de evaluación.')
                if action == 'evaluation-prepare':
                    plan = self.evaluations.prepare(body, self.organization)
                    self.receipt(action, 'pending', 'Comando local preparado, todavía no ejecutado. Revisa archivos, directorio, hash y efectos.', plan_id=plan['id'], plan_hash=plan['plan_hash'])
                elif action == 'evaluation-start':
                    if body.get('confirmed') is not True:
                        raise BridgeError('Confirma expresamente el comando, directorio, hash y efectos de esta ejecución local.')
                    run = self.evaluations.start(body.get('plan_id'), body.get('plan_hash'), self.organization)
                    self.receipt(action, 'started', 'Prueba local autorizada para este plan exacto. No valida toda una competencia ni activa DSH.', run_id=run['id'])
                else:
                    run = self.evaluations.cancel(body.get('run_id'))
                    self.receipt(action, 'warning', 'Cancelación solicitada para esta prueba. Consulta el estado final; no supone rollback de efectos del código.', run_id=run['id'])
                return self.public()
            if action in HARNESS_ACTIONS:
                self.dsh_harness.connection = self.integrations._connection()
                if action == 'dsh-harness-pair' and isinstance(body.get('pairing_code'), str):
                    self._sensitive_values.add(body['pairing_code'])
                self.dsh_harness.apply(action, body)
                return self.public()
            if action in RESOURCE_ACTIONS:
                return self.resource_workflows.apply(action, body)
            if action in LAUNCHER_ACTIONS:
                self.dsh_launcher.apply(action, body)
                return self.public()
            if action in GENERATION_ACTIONS:
                return self.generation.apply(action, body)
            if action in CAPABILITY_AI_ACTIONS:
                return self.capability_recommendations.apply(action, body)
            if action in CAPABILITY_ACTIONS:
                return self.capabilities_hub.apply(action, body)
            if action in INTEGRATION_ACTIONS:
                result = self.integrations.apply(action, body)
                if action == 'dsh-disconnect':
                    self.dsh_harness.connection = self.integrations._connection()
                    return self.public()
                return result
            if self.generation._active() and action in ('analyze-repository', 'prepare-analysis', 'prepare-verification', 'confirm-analysis', 'discover-models'):
                raise BridgeError('Hay una generación automática pendiente. Termínala o cancélala antes de iniciar otra operación del proveedor.')
            if action in TEAM_ACTIONS:
                # GenTeam P2/P4: canal dirigido y memoria de equipo sobre los módulos
                # portados. Versionado como el resto de mutaciones; sin efectos externos.
                self.require_version(body)
                if self.redact(body) != body:
                    raise BridgeError('Una clave de sesión aparece en los datos del canal; no se puede guardar.')
                self._team_apply(action, body)
                return self.public()
            if action in FOLLOWUPS_ACTIONS:
                # GenTeam P3: seguimiento de compromisos sobre el MISMO canal del panel.
                # Versionado igual que el canal; registro en memoria, sin efectos externos.
                self.require_version(body)
                if self.redact(body) != body:
                    raise BridgeError('Una clave de sesión aparece en los datos del seguimiento; no se puede guardar.')
                envelope = self._followups_apply(action, body)
                result = self.public()
                result.update(envelope)
                return result
            if action in SANDBOX_ACTIONS:
                # GenTeam P1/M4: sandbox con aprobacion humana en DOS pasos. Consume el
                # policy_engine TAL CUAL (no relaja ni anade puertas) y el ejecutor probado
                # de engine/sandbox_executor.py sin modificarlo. Deny by default.
                self.require_version(body)
                if self.redact(body) != body:
                    raise BridgeError('Una clave de sesión aparece en los datos del sandbox; '
                                      'no se puede ejecutar.')
                envelope = self._sandbox_apply(action, body)
                result = self.public()
                result.update(envelope)
                return result
            if action in COORDINATION_ACTIONS:
                if action == 'lease-acquire' and (self.organization is None or self.generation_stale):
                    raise BridgeError('Genera un diseño actualizado antes de adquirir tickets.')
                if self.redact(body) != body:
                    raise BridgeError('Una clave de sesión aparece en los datos del ticket; no se puede guardar.')
                self.coordination_store.apply(action, body,
                    agent_ids={a['id'] for a in (self.organization or {}).get('agents', [])}, project_id=self.project.get('id'))
                self.receipt(action, 'success', 'Ticket local actualizado. Identidad declarada; no bloquea archivos ni ejecuta agentes o DSH.')
                self.project['dirty'] = True
                return self.public()
            if action == 'project-save':
                name = body.get('name') or self.project.get('name') or self.config['repo_name']
                if self.redact(name) != name or self.redact(self.config) != self.config or (self.organization is not None and self.redact(self.organization) != self.organization):
                    raise BridgeError('Una clave de la sesión aparece en el nombre o diseño del proyecto. Elimina esa coincidencia antes de guardarlo.')
                project_id = None if body.get('as_new') is True else self.project.get('id')
                prior_hub = self.capabilities_hub
                if body.get('as_new') is True:
                    fork_id = uuid.uuid4().hex
                    prior_hub.library.fork(fork_id, expected_revision=prior_hub.library.status()['revision'])
                    self.capabilities_hub = CapabilityHub(self, fork_id)
                try:
                    metadata = self.project_store.save(self.project_snapshot(), name, project_id,
                        expected_version=self.project.get('version_id') if project_id else None)
                except Exception:
                    if self.capabilities_hub is not prior_hub:
                        # Discard only this just-created private namespace on failed Save As.
                        with self.capabilities_hub.library._connection(True) as db:
                            for table in ('requests', 'events', 'assignments', 'items', 'projects'):
                                db.execute('DELETE FROM '+table+' WHERE project=?', (self.capabilities_hub.library_id,))
                        self.capabilities_hub = prior_hub
                    raise
                self.capabilities_hub.saved_revision = self.capabilities_hub.library.status()['revision']
                self.project = {'id': metadata['project_id'], 'name': metadata['name'], 'version_id': metadata['version_id'], 'dirty': False}
                self.receipt(action, 'success', 'Nueva versión guardada localmente. Las versiones anteriores se conservan y no se han guardado claves.')
                return self.public()
            elif action == 'project-load':
                self.load_project(body)
                return self.public()
            elif action == 'tool-policy':
                self.require_version(body)
                self.organization = load_core().apply_tool_policy(self.organization, body)
                self.has_manual_edits = True
                self.receipt(action, 'success', 'Política por perfil actualizada. Restricción de diseño; disponibilidad y enforcement del runtime no verificados.')
            elif action in GOVERNANCE_ACTIONS:
                self.require_version(body)
                candidate_records = apply_governance_action(self.organization, self.records, action, body)
                build_scoreboard(self.organization, candidate_records)
                self.records = candidate_records
                self.records_version += 1
                self.organization['state_version'] = self.organization.get('state_version', 1) + 1
                self.receipt(action, 'success', 'Registro de méritos actualizado. Evidencia e identidad declaradas; no ejecuta pruebas ni aplica ascensos o permisos.')
            elif action == 'model-overrides':
                if self.organization is None or self.generation_stale:
                    raise BridgeError('Genera un diseño actualizado antes de cambiar sus modelos.')
                assignments = body.get('assignments')
                if not isinstance(assignments, dict):
                    raise BridgeError('assignments debe ser un objeto por ID de agente.')
                ids = {a['id'] for a in self.organization['agents']}
                cleaned = {}
                for aid, row in assignments.items():
                    if aid not in ids or not isinstance(row, dict) or set(row) - {'provider', 'model'}:
                        raise BridgeError('Asignación manual no válida: usa un ID actual y campos provider/model.')
                    entry = {key: str(value).strip() for key, value in row.items() if value is not None and str(value).strip()}
                    if entry.get('provider', self.config['provider']) not in PROVIDER_ROUTES:
                        raise BridgeError('La ruta del proveedor no está mapeada en esta app.')
                    if entry:
                        cleaned[aid] = entry
                candidate_catalog = self.generation_catalog()
                # Unknown manual choices remain explicitly UNVERIFIED when a
                # complete real catalogue for that route has not been read.
                for entry in cleaned.values():
                    provider = entry.get('provider', self.config['provider'])
                    model = entry.get('model', self.config['model'])
                    if not any((m.get('provider'), m.get('model', m.get('id'))) == (provider, model) for m in candidate_catalog):
                        candidate_catalog.append({'provider': provider, 'model': model, 'available': None, 'source': 'manual_not_verified', 'catalog_scope': 'dsh_runtime_reference'})
                candidate = load_core().apply_model_assignments(self.organization, cleaned, candidate_catalog,
                    expected_state_version=body.get('expected_state_version'))
                self.organization = candidate
                self.model_overrides = cleaned
                self.receipt(action, 'success', 'Selección de modelos actualizada sin regenerar perfiles ni jerarquía. No se ejecutó ninguna inferencia.')
            elif action == 'model-preferences':
                if self.organization is None or self.generation_stale:
                    raise BridgeError('Genera un diseño actualizado antes de aplicar preferencias de modelos.')
                preferences = body.get('preferences')
                if not isinstance(preferences, list) or len(preferences) > 2000 or any(not isinstance(p, dict) or not p.get('provider') or not p.get('model') for p in preferences):
                    raise BridgeError('preferences debe ser una lista acotada de pares provider/model.')
                if any(p['provider'] not in PROVIDER_ROUTES for p in preferences):
                    raise BridgeError('Una preferencia usa un proveedor no mapeado.')
                previous_models = copy.deepcopy(self.models)
                try:
                    self.merge_preferences(preferences)
                    candidate = load_core().apply_model_assignments(self.organization, self.model_overrides,
                        self.generation_catalog(), expected_state_version=body.get('expected_state_version'))
                except Exception:
                    self.models = previous_models
                    raise
                self.organization = candidate
                self.receipt(action, 'success', 'Preferencias aplicadas a rutas verificadas cuando hay evidencia suficiente. No acreditan calidad ni disponibilidad y no cambian overrides manuales.')
            elif action == 'edit-organization':
                if self.organization is None or self.generation_stale:
                    raise BridgeError('Genera un diseño actualizado antes de editarlo.')
                self.organization = load_core().apply_organization_edits(self.organization, body.get('edits', {}))
                self.has_manual_edits = True
                self.receipt(action, 'success', 'Edición validada y aplicada al diseño. No se ha ejecutado ningún agente.')
            elif action in RECORD_ACTIONS:
                if 'expected_state_version' in body or action == 'skill-feedback':
                    self.require_version(body)
                if action == 'subteam-save' and (self.organization is None or self.generation_stale):
                    raise BridgeError('Genera un diseño actualizado antes de editar subequipos.')
                candidate_records = apply_record_action(self.organization, self.records, action, body)
                if action == 'subteam-save':
                    teams = [{k: t[k] for k in ('id', 'name', 'type', 'member_ids', 'facilitator_id', 'scope')} for t in candidate_records['subteams']]
                    self.organization = load_core().apply_functional_subteams(self.organization, teams, expected_state_version=body.get('expected_state_version'))
                    self.has_manual_edits = True
                self.records = candidate_records
                self.records_version += 1
                if self.organization is not None and action != 'subteam-save':
                    self.organization['state_version'] = self.organization.get('state_version', 1) + 1
                self.receipt(action, 'success', 'Registro manual actualizado. No acredita ejecución de agentes ni pruebas reales.')
            elif action == 'config':
                new_config = normalize_config(body.get('config', {}), self.config)
                if new_config == normalize_config(self.config):
                    return self.public()
                if (new_config['source_kind'], new_config['repo_url'], new_config['repo_ref']) != (self.config.get('source_kind', 'github_repository'), self.config['repo_url'], self.config['repo_ref']):
                    self.repo_inventory = None
                    if self.repo_cache is not None:
                        self.repo_cache.clear()
                    self.analysis = None
                self.config = new_config
                self.config_version += 1
                self.generation_stale = True
                self.pending_consent = None
                self.receipt(action, 'success', 'Configuración pendiente actualizada. Prepara un diseño nuevo o recupera la versión conservada para exportarla.')
            elif action == 'credentials':
                provider = str(body.get('provider', '')).lower()
                key = body.get('api_key', '')
                if provider not in ALLOWED_PROVIDERS or not isinstance(key, str) or not 8 <= len(key) <= 4096 or any(c.isspace() for c in key):
                    raise BridgeError('Introduce un proveedor válido y una clave sin espacios.')
                self.credentials[provider] = key
                self._sensitive_values.add(key)
                if body.get('persist') is True:
                    self.secret_store.save(self.credentials)
                    self.persisted = True
                self.receipt(action, 'success', 'Clave preparada en memoria.' if not body.get('persist') else 'Claves guardadas con DPAPI para este usuario de Windows.')
                # Con la clave en memoria, cargar el catálogo del proveedor en el acto.
                # El operador lo pidió explícitamente: pega la clave y los modelos cargan
                # solos, sin adivinar IDs. La llamada es de METADATOS (listar modelos),
                # no de diseño ni de inferencia. Si falla, la clave SIGUE guardada: se
                # degrada a aviso y el botón manual queda disponible.
                if body.get('auto_discover') is True and load_providers().provider_config(PROVIDER_ROUTES[provider]).get('discovery') is True:
                    try:
                        return self.execute('discover-models', {'confirmed': True, 'auto': True})
                    except BridgeError as exc:
                        self.receipt('discover-models', 'warning',
                                     'El catálogo automático no pudo consultarse (%s); la clave sigue preparada: usa el botón de catálogo.' % str(exc)[:160])
                        return self.public()
            elif action == 'gang-publish':
                if self.organization is None:
                    raise BridgeError('Genera primero un diseño del gang para ensamblar y publicar.')
                artifact, sha = gang_assembly.assemble(self.organization, previous=self._last_gang_artifact)
                self._last_gang_artifact = artifact
                resultado = self.gang_registry.publish_atomic(sha)
                self.receipt(action, 'success',
                             'Artefacto %s registrado de forma atómica en los %d objetivos%s. Los servicios no están montados en este árbol: se registra el hash del artefacto, no se ejecuta nada.'
                             % (sha[:12], resultado['objetivos'],
                                ' — idempotente: ya estaba registrado, no se tocó nada' if resultado.get('idempotente') else ''))
            elif action == 'gang-mount':
                # El operador monta los 3 servicios DESDE LA APLICACION: procesos
                # HTTP reales en puertos locales. El registro pasa de grabador a
                # coordinador 2PC REAL contra ellos; el journal no se toca.
                if self.gang_servers:
                    raise BridgeError('Los servicios ya están montados.')
                nodos = {sid: gang_services.ServicioGang(sid) for sid in _gang_registry_module.TARGETS}
                self.gang_servers = {sid: gang_services.ServidorGang(nodo) for sid, nodo in nodos.items()}
                urls = {sid: servidor.url() for sid, servidor in self.gang_servers.items()}
                self.gang_supervisor = gang_supervisor.Supervisor(
                    journal=self.gang_registry.journal, urls=urls,
                    owner='panel-%s' % (self.project.get('id') or 'local'))
                self.gang_registry = _gang_registry_module.GangRegistry(
                    transport=gang_services.transporte_http(urls, epoch=lambda: self.gang_supervisor.epoch),
                    journal=self.gang_registry.journal)
                self.receipt(action, 'success',
                             'Tres servicios montados como procesos HTTP locales (%s). El registro ahora publica por 2PC real contra ellos; el journal en disco conserva toda la historia.'
                             % ', '.join('%s=%s' % (sid, url.replace('http://', '')) for sid, url in sorted(urls.items())))
            elif action == 'gang-unmount':
                if not self.gang_servers:
                    raise BridgeError('Los servicios no están montados.')
                journal = self.gang_registry.journal
                for servidor in self.gang_servers.values():
                    servidor.stop()
                self.gang_servers = None
                self.gang_supervisor = None
                self.gang_registry = _gang_registry_module.GangRegistry(journal=journal)
                self.receipt(action, 'success',
                             'Servicios desmontados. El registro vuelve a grabar localmente; el journal conserva la historia completa para reanudar cuando se vuelvan a montar.')
            elif action == 'gang-tick':
                # El tick del supervisor, disparado desde el panel. Revalida el
                # epoch, adopta si el lease vencio y reanuda lo que quedo en duda.
                if not self.gang_supervisor:
                    raise BridgeError('Monta primero los servicios: sin nodos no hay nada que supervisar.')
                reporte = self.gang_supervisor.tick()
                reanudados = len(reporte.get('reanudados', []))
                errores = sum(1 for fila in reporte.get('reanudados', []) if 'error' in fila)
                self.receipt(action, 'success' if not errores else 'warning',
                             'Tick: epoch %d, lease %s, reanudados %d%s. Los servicios siguen no-montados-para-DSH: esto coordina los nodos locales, no ejecuta nada en DSH.'
                             % (reporte.get('epoch', 1), reporte.get('lease') or 'sin store',
                                reanudados, ' (%d con error)' % errores if errores else ''))
            elif action == 'forget-credentials':
                self.secret_store.delete()
                self.credentials.clear()
                self.persisted = False
                self.receipt(action, 'success', 'Claves eliminadas de la memoria y del almacén local de este panel.')
            elif action in ('import-workbook', 'read-excel'):
                workbook = str(body.get('workbook', self.workbook)).strip()
                if not workbook:
                    raise BridgeError('Indica la ruta local completa del libro .xlsx.')
                if action == 'read-excel':
                    result = excel_call('Read', workbook)
                    snapshot = clean_snapshot(result)
                    config = snapshot['config']
                else:
                    snapshot = read_xlsx_snapshot(workbook)
                    config = snapshot['config']
                self.model_overrides = snapshot['model_overrides']
                self.merge_preferences(snapshot.get('model_preferences', []))
                self.workbook_snapshot = snapshot_digest(snapshot)
                self.workbook = str(Path(workbook).expanduser().resolve())
                self.config = config
                self.config_version += 1
                self.pending_consent = None
                self.repo_inventory = None
                self.analysis = None
                self.generation_stale = True
                self.pending_consent = None
                self.receipt(action, 'success', 'Configuración leída de Excel abierto.' if action == 'read-excel' else 'Configuración leída del archivo guardado; los cambios sin guardar no se incluyen.')
            elif action == 'detach-workbook':
                self.workbook = ''
                self.workbook_snapshot = None
                self.model_overrides = {}
                self.generation_stale = True
                self.receipt(action, 'success', 'El panel usa su propia configuración; vuelve a generar la organización.')
            elif action == 'reset-model-overrides':
                if self.organization is not None and not self.generation_stale:
                    self.organization = load_core().apply_model_assignments(self.organization, {}, self.generation_catalog())
                self.model_overrides = {}
                self.receipt(action, 'success', 'Overrides restablecidos sin borrar perfiles. Aplica a Excel si quieres restaurar allí las fórmulas de herencia.')
            elif action == 'generate':
                if self.has_manual_edits and body.get('confirmed_discard_edits') is not True:
                    raise BridgeError('Hay ediciones manuales del diseño. Guarda una versión o confirma su reemplazo para regenerar desde la configuración.')
                for assignment in self.model_overrides.values():
                    if assignment.get('provider', self.config['provider']) not in PROVIDER_ROUTES:
                        raise BridgeError('Una asignación manual usa una ruta de proveedor no mapeada. Usa deepseek-official, deepseek, zai, zai-official u openai.')
                generation_config = dict(self.config, model_overrides=self.model_overrides)
                if (self.organization or {}).get('organization_id'):
                    generation_config.update(organization_id=self.organization['organization_id'], identity_mode='revision',
                        dna_revision=self.organization.get('dna_revision', 1) + 1)
                else:
                    generation_config.update(organization_id=str(uuid.uuid4()), identity_mode='new', dna_revision=1)
                candidate = load_core().generate_organization(generation_config, analysis=self.analysis, model_catalog=self.generation_catalog(),
                    previous_organization=self.organization if generation_config.get('identity_mode') == 'revision' else None)
                validation = load_core().validate_organization(candidate)
                errors = [e for e in validation.get('errors', []) if not e.startswith('Modelo no disponible:')]
                if errors:
                    raise BridgeError('La organización no superó la validación: ' + '; '.join(errors))
                current_ids = {a['id'] for a in candidate['agents']}
                teams = []
                for team in self.records.get('subteams', []):
                    if set(team['member_ids']) <= current_ids:
                        teams.append({k: team[k] for k in ('id', 'name', 'type', 'member_ids', 'facilitator_id', 'scope')})
                        team['status'] = 'proposed'
                    else:
                        team['status'] = 'stale_members_not_applied'
                if teams:
                    candidate = load_core().apply_functional_subteams(candidate, teams)
                self.organization = ensure_governance(candidate)
                if self.project.get('id') is None:
                    self.project['id'] = candidate['organization_id']
                    self.project['name'] = self.config['repo_name']
                self.generation_stale = False
                self.has_manual_edits = False
                self.receipt(action, 'success', 'Organización generada localmente, sin llamada a una API ni inicio de agentes.', source='local_deterministic', metrics=validation.get('metrics', {}))
            elif action == 'discover-models':
                if body.get('confirmed') is not True:
                    raise BridgeError('Confirma que deseas consultar el catálogo del proveedor.')
                auto = body.get('auto') is True
                provider = self.config['provider']
                if PROVIDER_ROUTES[provider] != 'zai' and not self.credentials.get(provider):
                    raise BridgeError('Introduce primero la clave de este proveedor para consultar su catálogo real.')
                result = self._provider().discover_models(PROVIDER_ROUTES[provider], self.credentials.get(provider))
                models = result.get('models', [])
                if not isinstance(models, list):
                    raise BridgeError('El proveedor devolvió un catálogo no válido.')
                normalized = [dict(m, provider=provider, model=m.get('model', m.get('id')),
                    available=True if m.get('availability_verified') is True and m.get('source') == 'live_api' else None,
                    status='AVAILABLE' if m.get('availability_verified') is True and m.get('source') == 'live_api' else 'MANUAL_NOT_VERIFIED',
                    checked_at=result.get('verified_at', ''), catalog_scope='provider_api') for m in models]
                preferences = [dict(m) for m in self.models if m.get('provider') == provider]
                # A newer catalog supersedes older API observations on the same
                # endpoint, even through another spelling of the provider. DSH
                # runtime aliases remain separate and are never reinterpreted.
                self.models = [m for m in self.models if not (
                    PROVIDER_ROUTES.get(m.get('provider')) == PROVIDER_ROUTES[provider] and
                    m.get('catalog_scope') not in ('dsh_runtime', 'dsh_runtime_reference') and
                    (m.get('provider') == provider or m.get('source') in ('live_api', 'live_inference', 'official_docs_snapshot') or
                     m.get('status') == 'VERIFIED_INFERENCE'))] + normalized
                self.merge_preferences(preferences)
                live = result.get('source') == 'live_api'
                if live:
                    self.verified_catalog_providers.add(provider)
                    for row in normalized:
                        if row.get('available') is True:
                            self._record_model_account(dict(self.config, model=row['model']))
                self.receipt(action, 'success' if live else 'warning',
                    f'Catálogo {"de cuenta consultado" if live else "de referencia, sin verificar cuenta"}: {len(models)} modelos. No demuestra precio ni calidad.'
                    + (' Consulta AUTOMÁTICA al guardar la clave: solo lista modelos, no llama a diseño.' if auto else ''),
                    source=result.get('source'), provider=provider, warnings=result.get('warnings', []))
                if self.organization is not None:
                    previous_organization = self.organization
                    self.organization = load_core().refresh_model_catalog(self.organization, self.generation_catalog())
                    self._design_context = self._refreshed_design_context(self._design_context, previous_organization, self.organization)
            elif action == 'analyze-repository':
                if not self.config['repo_url']:
                    raise BridgeError('Indica primero la URL de la fuente y guarda la configuración.')
                self.pending_consent = None
                options = {}
                for key in ('profile', 'max_files', 'max_bytes', 'budget_confirmed', 'max_workers'):
                    if key in body:
                        options[key] = body[key]
                provider_module = self._provider()
                if hasattr(provider_module, 'RepositoryCache'):
                    if self.repo_cache is None:
                        self.repo_cache = provider_module.RepositoryCache()
                    options['cache'] = self.repo_cache
                if self.config.get('source_kind') == 'website':
                    if __package__:
                        from .web_sources import analyze_website
                    else:
                        from web_sources import analyze_website
                    self.repo_inventory = analyze_website(self.config['repo_url'])
                else:
                    self.repo_inventory = provider_module.analyze_repository(self.config['repo_url'], ref=self.config.get('repo_ref') or None, **options)
                self.analysis = self.repo_inventory
                self.generation_stale = True
                self.receipt(action, 'success', 'Inventario de lectura completado. No se ha enviado contenido a ningún LLM.',
                    source=self.config.get('source_kind', 'github_repository') + '_read_only', repository=self.repo_inventory.get('repository', {}), limits=self.repo_inventory.get('limits', {}), coverage=self.repo_inventory.get('coverage', {}))
            elif action == 'prepare-analysis':
                if self.repo_inventory is None:
                    raise BridgeError('Inventaría primero el repositorio que deseas analizar.')
                model = self.config['analysis_model'] or self.config['model']
                self.validate_api_model_choice(dict(self.config, model=model), manual_confirmed=body.get('manual_model_confirmed') is True)
                self.pending_consent = self._provider().prepare_llm_consent(self.repo_inventory, PROVIDER_ROUTES[self.config['provider']], model, max_output_tokens=body.get('max_output_tokens', 8192))
                self._pending_analysis_account_stamp = self._api_account_stamp(self.config)
                self.pending_consent['approval_id'] = secrets.token_urlsafe(24)
                coverage = copy.deepcopy(self.repo_inventory.get('coverage') or {})
                self.pending_consent['coverage_review'] = coverage
                self.pending_consent['partial_inventory_required'] = coverage.get('inventory_complete') is not True
                self.pending_consent['coverage_sha256'] = snapshot_digest({'coverage': coverage,
                    'config_version': self.config_version, 'payload_sha256': self.pending_consent['payload_sha256'],
                    'approval_id': self.pending_consent['approval_id']})
                self.receipt(action, 'pending', 'Revisa el contenido exacto, destino y límite de tokens. El coste monetario no está verificado; todavía no se ha enviado al LLM.')
            elif action == 'prepare-verification':
                self.pending_consent = self._provider().prepare_model_verification_consent(PROVIDER_ROUTES[self.config['provider']], self.config['model'], max_output_tokens=32)
                self._pending_analysis_account_stamp = self._api_account_stamp(self.config)
                self.pending_consent['approval_id'] = secrets.token_urlsafe(24)
                self.receipt(action, 'pending', 'Revisa la prueba mínima de un modelo. Una solicitud de 32 tokens máximos; no se garantiza un tope en USD.')
            elif action == 'confirm-analysis':
                pending = self.pending_consent
                if pending is None:
                    raise BridgeError('No hay un consentimiento pendiente. Prepara y revisa uno nuevo.')
                if body.get('confirmed') is not True or body.get('consent_id') != pending.get('approval_id') or body.get('payload_sha256') != pending.get('payload_sha256') or any(body.get(k) is not True for k in ('data_reviewed', 'budget_acknowledged')):
                    raise BridgeError('Confirma el contenido exacto y reconoce el coste desconocido de esta solicitud.')
                if pending.get('partial_inventory_required') and (body.get('partial_inventory_acknowledged') is not True
                        or body.get('coverage_sha256') != pending.get('coverage_sha256')):
                    raise BridgeError('Revisa y acepta expresamente la cobertura parcial de esta solicitud antes de enviarla.')
                provider = self.config['provider']
                if not self.credentials.get(provider):
                    raise BridgeError('Prepara primero la clave del proveedor seleccionado.')
                if self._pending_analysis_account_stamp != self._api_account_stamp(self.config):
                    raise BridgeError('La cuenta del proveedor cambió desde la preparación. Revisa su catálogo y prepara una autorización nueva.')
                consent = dict(pending, confirmed=True, data_reviewed=True, budget_acknowledged=True)
                self.pending_consent = None  # Consume before I/O, even for uncertain failures.
                self.receipt(action, 'started', 'Consentimiento consumido para una sola solicitud. Un error no autoriza un reintento automático.',
                    source=provider, payload_sha256=consent.get('payload_sha256'))
                try:
                    if consent.get('kind') == 'model_verification':
                        result = self._provider().verify_model(PROVIDER_ROUTES[provider], self.config['model'], self.credentials[provider], consent, max_output_tokens=32)
                    else:
                        result = self._provider().analyze_with_llm(self.repo_inventory, PROVIDER_ROUTES[provider],
                            self.config['analysis_model'] or self.config['model'], self.credentials[provider], consent, max_output_tokens=consent['max_output_tokens'])
                except Exception:
                    self.receipt(action, 'failed', 'La solicitud no produjo un análisis aplicable. Puede haber tenido coste. Se requiere nuevo consentimiento para reintentar.')
                    raise
                if consent.get('kind') == 'model_verification':
                    verified = result.get('availability_verified') is True
                    model = self.config['model']
                    self.models = [m for m in self.models if (m.get('provider'), m.get('model', m.get('id'))) != (provider, model)]
                    self.models.append(dict(result, provider=provider, model=model, id=model,
                        available=True if verified else None, checked_at=result.get('verified_at', '')))
                    if verified:
                        self._record_model_account(self.config)
                    self.receipt('verify-model', 'success' if verified else 'warning',
                        'Inferencia mínima verificada para este modelo y cuenta.' if verified else 'No se verificó la inferencia. Un error de cuota no demuestra que el modelo sea inexistente.',
                        source=provider, result=result)
                else:
                    self.analysis = dict(result, signals=self.repo_inventory.get('signals', []))
                    self.receipt(action, 'success', 'Análisis recibido y validado como propuestas. Genera la organización para incorporarlo.',
                        source=provider, audit=result.get('audit', {}), usage=result.get('usage', {}))
                self.generation_stale = True
            elif action == 'apply-excel':
                if body.get('confirmed') is not True:
                    raise BridgeError('Confirma que se reemplazarán las tablas de salida del libro.')
                if self.organization is None or self.generation_stale:
                    raise BridgeError('Genera primero una organización actualizada.')
                if self.organization.get('config', {}).get('hierarchy_mode') == 'manual':
                    raise BridgeError('El libro usa jerarquía automática BFS. No se aplica una jerarquía manual de la app a esas fórmulas; conserva la app y exporta JSON o restablece jerarquía automática explícitamente.')
                if not self.workbook:
                    raise BridgeError('Selecciona primero el libro .xlsx.')
                live_snapshot = clean_snapshot(excel_call('Read', self.workbook))
                if snapshot_digest(live_snapshot) != self.workbook_snapshot:
                    raise BridgeError('El libro cambió desde la sincronización. Sincroniza y genera de nuevo antes de aplicar para conservar tus ediciones.')
                result = excel_call('Apply', self.workbook, dict(sheet_payload(self.organization, self.models, self.receipts), config=self.config, fingerprint=config_fingerprint(self.config)))
                snapshot = clean_snapshot(result['snapshot'])
                self.model_overrides = snapshot.get('model_overrides', {})
                self.workbook_snapshot = snapshot_digest(snapshot)
                self.receipt(action, 'success', 'Tablas de Excel actualizadas y libro guardado.', source='windows_excel_com', adapter=result)
            else:
                raise BridgeError('Acción desconocida.')
            if action not in ('credentials', 'prepare-analysis', 'prepare-verification'):
                self.generation.invalidate('El estado cambió durante la generación. No se aplicarán resultados pendientes.')
            if action not in ('credentials', 'forget-credentials', 'prepare-analysis', 'prepare-verification'):
                self.project['dirty'] = True
            return self.public()

    def _exports(self):
        if self.organization is None or self.generation_stale:
            raise BridgeError('Genera una organización actualizada desde la app; la configuración cambió o aún no hay un diseño.')
        if self.redact(self.organization) != self.organization:
            raise BridgeError('Una clave de esta sesión aparece en el contenido del diseño. Elimina esa coincidencia antes de exportar; no se modifican silenciosamente identidades o hashes.')
        try:
            from .export_artifacts import build_export_snapshot, organization_fingerprint
            from .capability_deployment import export_skillhub_library
        except ImportError:
            from export_artifacts import build_export_snapshot, organization_fingerprint
            from capability_deployment import export_skillhub_library
        fingerprint = organization_fingerprint(self.organization)
        library_revision = self.capabilities_hub.library.status()['revision']
        if not self._export_cache or self._export_cache['organization_sha256'] != fingerprint or self._export_cache.get('library_revision') != library_revision:
            companion = export_skillhub_library(self.capabilities_hub.library, self.organization) if self.capabilities_hub.library.status()['item_count'] else None
            exported_at = self._export_cache['snapshot'].exported_at if self._export_cache and self._export_cache['organization_sha256'] == fingerprint else None
            snapshot = build_export_snapshot(self.organization, exported_at=exported_at, capability_library=companion)
            self._export_cache = {'organization_sha256': fingerprint, 'library_revision': library_revision, 'snapshot': snapshot, 'package': None}
        return self._export_cache

    def export_artifacts(self):
        if self.organization is None or self.generation_stale:
            return None
        try:
            cache = self._exports()
            snapshot = cache['snapshot']
            result = {}
            for kind, alias in (('definitions', 'definitions.json'), ('implementation', 'implementation.json'),
                                ('manifest', 'export-manifest.json')):
                payload = snapshot.file_for(alias)
                result[kind] = {'filename': snapshot.filename_for(alias), 'url': '/download/' + alias,
                                'sha256': hashlib.sha256(payload).hexdigest(), 'bytes': len(payload)}
            if cache.get('package') is not None:
                payload = cache['package']
                result['package'] = {'filename': self.download_filename('package.zip'), 'url': '/download/package.zip',
                                     'sha256': hashlib.sha256(payload).hexdigest(), 'bytes': len(payload)}
            return result
        except (ValueError, BridgeError):
            # Invalid or unavailable routes are visible in organization validation;
            # they must not make the status endpoint itself unreadable.
            return None

    def download_filename(self, filename, job_id=None):
        if filename == 'generation-diagnostic.json':
            report = self.generation_diagnostic(job_id)
            return 'orgdna-generation-diagnostic-' + report['job']['job_id'] + '.json'
        if filename in ('cordis-implementation.json', 'cordis-definitions.json'):
            try:
                return self.integrations.download(filename)[1]
            except ValueError as exc:
                raise BridgeError(str(exc)) from None
        if filename == 'cordis-addon.zip':
            return self.integrations.download()[1]
        if filename == 'package.zip':
            try:
                from .bundle import package_filename
            except ImportError:
                from bundle import package_filename
            return package_filename(self.organization)
        if filename in ('implementation.json', 'definitions.json', 'council.json', 'export-manifest.json'):
            return self._exports()['snapshot'].filename_for(filename)
        return filename

    def download(self, filename, job_id=None):
        with self.lock:
            if filename == 'generation-diagnostic.json':
                return json.dumps(self.generation_diagnostic(job_id), ensure_ascii=False, indent=2).encode('utf-8')
            if filename == 'capability-update.json':
                return self.capabilities_hub.deployment_download()
            if filename in ('cordis-implementation.json', 'cordis-definitions.json'):
                try:
                    return self.integrations.download(filename)[0]
                except ValueError as exc:
                    raise BridgeError(str(exc)) from None
            if filename == 'cordis-addon.zip':
                return self.integrations.download()[0]
            if self.workbook and filename != 'evidence.json':
                snapshot = excel_call('Read', self.workbook) if os.name == 'nt' else read_xlsx_snapshot(self.workbook)
                snapshot = clean_snapshot(snapshot)
                if self.workbook_snapshot != snapshot_digest(snapshot):
                    raise BridgeError('El libro cambió desde la última sincronización. Lee Excel de nuevo y genera la organización antes de exportar.')
            if filename == 'lifecycle.json':
                result = {'format': 'orgdna-local-lifecycle', 'version': 1, 'generated_at': now(),
                    'records_version': self.records_version, 'records': self.records,
                    'scoreboard': build_scoreboard(self.organization, self.records) if self.organization else {'rows': []},
                    'coordination_snapshot': self.coordination_store.public(), 'runtime_identity_verified': False,
                    'note': 'Registro local histórico. Importarlo no restaura tickets activos ni concede permisos.'}
            elif filename == 'evidence.json':
                result = {'generated_at': now(), 'receipts': self.receipts, 'verification': self.public()['verification'], 'evaluations': self.evaluations.public()}
            else:
                cache = self._exports()
                if filename == 'package.zip':
                    if cache['package'] is None:
                        try:
                            from .bundle import build_package_bytes
                        except ImportError:
                            from bundle import build_package_bytes
                        cache['package'] = build_package_bytes(self.organization, export_snapshot=cache['snapshot'])
                    return cache['package']
                if filename == 'organization.json':
                    result = self.organization
                elif filename in ('implementation.json', 'definitions.json', 'council.json', 'export-manifest.json'):
                    return cache['snapshot'].file_for(filename)
                elif filename in cache['snapshot'].files:
                    return cache['snapshot'].files[filename]
                else:
                    raise BridgeError('Archivo desconocido.')
            return json.dumps(self.redact(result), ensure_ascii=False, indent=2).encode('utf-8')


class LocalServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False
    def __init__(self, address, state):
        if address[0] != '127.0.0.1':
            raise BridgeError('El servidor sólo puede escuchar en 127.0.0.1.')
        super().__init__(address, LocalHandler)
        self.state = state
        self.origin = f'http://127.0.0.1:{self.server_address[1]}'


class LocalHandler(BaseHTTPRequestHandler):
    server_version = 'OrgDNA-Local/1.0'
    sys_version = ''
    def log_message(self, fmt, *args):
        # Do not log URLs, request bodies, provider exceptions, or credentials.
        pass

    def _check(self, require_session=False, mutation=False):
        if self.client_address[0] != '127.0.0.1' or self.headers.get('Host') != self.server.origin.removeprefix('http://'):
            self._json({'error': 'Host local no válido.'}, 403)
            return False
        if self.headers.get('Sec-Fetch-Site') == 'cross-site':
            self._json({'error': 'Origen cruzado bloqueado.'}, 403)
            return False
        if mutation and self.headers.get('Origin') != self.server.origin:
            self._json({'error': 'Origin local obligatorio.'}, 403)
            return False
        if require_session:
            cookie = http.cookies.SimpleCookie()
            try:
                cookie.load(self.headers.get('Cookie', ''))
                value = cookie.get('orgdna_session')
                valid = value is not None and secrets.compare_digest(value.value, self.server.state.cookie)
            except http.cookies.CookieError:
                valid = False
            if not valid:
                self._json({'error': 'Abre primero el panel local en esta sesión.'}, 403)
                return False
        if mutation and not secrets.compare_digest(self.headers.get('X-CSRF-Token', ''), self.server.state.csrf):
            self._json({'error': 'Token de sesión no válido. Recarga el panel.'}, 403)
            return False
        return True

    def _send(self, payload, content_type, status=200, cookie=False, disposition=None):
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(payload)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        if cookie:
            self.send_header('Set-Cookie', f'orgdna_session={self.server.state.cookie}; HttpOnly; SameSite=Strict; Path=/')
        if disposition:
            self.send_header('Content-Disposition', f'attachment; filename="{disposition}"')
        self.end_headers()
        self.wfile.write(payload)

    def _json(self, value, status=200):
        self._send(json.dumps(value, ensure_ascii=False).encode('utf-8'), 'application/json; charset=utf-8', status)

    def do_GET(self):
        if not self._check():
            return
        path = urlsplit(self.path).path
        try:
            if path == '/':
                payload = (WEB / 'index.html').read_text('utf-8').replace(
                '__CSRF_TOKEN__', self.server.state.csrf).replace('__MAX_AGENTS__', str(MAX_AGENTS)).encode('utf-8')
                self._send(payload, 'text/html; charset=utf-8', cookie=True)
            elif path in ('/app.js', '/style.css'):
                self._send((WEB / path[1:]).read_bytes(), 'application/javascript; charset=utf-8' if path.endswith('.js') else 'text/css; charset=utf-8')
            elif path == '/api/instance':
                self._json(instance_identity(self.server.origin, self.server.state.workbook))
            elif path == '/api/projects':
                if self._check(require_session=True):
                    self._json(self.server.state.redact({'projects': self.server.state.project_store.list_projects()}))
            elif path == '/api/state':
                if self._check(require_session=True):
                    self._json(self.server.state.public())
            elif path.startswith('/download/'):
                # Download links from Excel work after the panel was opened in
                # the same browser. They only read an already generated state.
                if self._check(require_session=True):
                    name = path.removeprefix('/download/')
                    job_id = None
                    if name == 'generation-diagnostic.json':
                        query = parse_qs(urlsplit(self.path).query, keep_blank_values=True)
                        if set(query) != {'job_id'} or len(query['job_id']) != 1 or not query['job_id'][0]:
                            raise BridgeError('Indica el intento exacto para descargar su diagnóstico.')
                        job_id = query['job_id'][0]
                    with self.server.state.lock:
                        payload = self.server.state.download(name, job_id=job_id) if job_id else self.server.state.download(name)
                        disposition = self.server.state.download_filename(name, job_id=job_id) if job_id else self.server.state.download_filename(name)
                    self._send(payload, 'application/zip' if name in ('package.zip', 'cordis-addon.zip') else 'application/json; charset=utf-8', disposition=disposition)
            else:
                self._json({'error': 'Ruta no encontrada.'}, 404)
        except BridgeError as exc:
            self._json({'error': str(exc)}, 400)
        except ValueError:
            self._json({'error': 'La exportación no superó la validación local. Revisa la disponibilidad de las rutas del diseño en Modelos y actualiza el catálogo; los alias DSH conservan su ID y necesitan un preflight del runtime. No se generó el archivo.', 'code': 'export_validation_failed'}, 400)
        except Exception:
            self._json({'error': 'No se pudo completar la lectura local.'}, 500)

    def do_POST(self):
        if not self._check(require_session=True, mutation=True):
            return
        if self.headers.get('Transfer-Encoding'):
            self._json({'error': 'Transfer-Encoding no admitido.'}, 400)
            return
        try:
            length = int(self.headers.get('Content-Length', '0'))
        except ValueError:
            self._json({'error': 'Longitud no válida.'}, 400)
            return
        body_limit = 2 * 1024 * 1024 if urlsplit(self.path).path == '/api/capability-deployment-plan' else MAX_BODY
        if not 0 < length <= body_limit:
            self._json({'error': 'Cuerpo vacío o demasiado grande.'}, 413)
            return
        if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
            self._json({'error': 'Se requiere application/json.'}, 415)
            return
        try:
            body = json.loads(self.rfile.read(length))
            if not isinstance(body, dict):
                raise BridgeError('El cuerpo debe ser un objeto JSON.')
            path = urlsplit(self.path).path
            if not path.startswith('/api/'):
                self._json({'error': 'Ruta no encontrada.'}, 404)
                return
            result = self.server.state.execute(path.removeprefix('/api/'), body)
            self._json(result)
        except (BridgeError, ValueError, TypeError) as exc:
            error = self.server.state.redact(str(exc))
            self._json({'error': error}, 400)
        except Exception as exc:
            # Provider errors are contained, scrubbed, and never printed.
            message = self.server.state.redact(str(exc))
            self.server.state.receipt('error', 'failed', message)
            self._json({'error': 'La acción no terminó: ' + message}, 502)


def main():
    try:
        from .launcher import main as launch_main
    except ImportError:
        from launcher import main as launch_main
    launch_main()


if __name__ == '__main__':
    main()
