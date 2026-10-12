"""Isolated real-HTTP application fixture. ONLY synthetic provider / DSH observations.

Run only on a machine where browser execution is permitted. It never discovers,
attaches to, or replaces a user's running OrgDNA/DSH instance. Port zero and a
TemporaryDirectory are compulsory; no user path or port can be supplied.
"""
from __future__ import annotations
import copy
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time
from urllib.parse import urlsplit
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from engine import bridge, org_design
from engine.project_store import ProjectStore
from synthetic_data import inventory_fixture, design_result

SENTINEL = 'E2E_SYNTHETIC_NONCREDENTIAL_NEVER_A_REAL_KEY'
FIXTURE_NOTICE = 'E2E FIXTURE ONLY: no live provider, repository, DSH, Excel or paid calls.'
MODES = {'success', 'fail_design', 'blocked_design', 'blocked_inventory', 'partial'}

class MemoryOnlyStore:
    def load(self): return {}
    def delete(self): pass
    def save(self, _): raise bridge.BridgeError('E2E forbids persistent credential storage.')

class InertProvider:
    def __init__(self):
        self.mode = 'success'
        self.inventory_calls = 0
        self.design_calls = 0
        self.release = threading.Event()
        self.release.set()
    def configure(self, mode):
        if mode not in MODES: raise ValueError('Unknown synthetic scenario')
        self.mode = mode
        self.release.clear() if mode.startswith('blocked_') else self.release.set()
    def analyze_repository(self, repo_url, ref=None, **_):
        self.inventory_calls += 1
        if self.mode == 'blocked_inventory': self.release.wait(25)
        value = inventory_fixture()
        value['repository']['url'] = repo_url
        if self.mode == 'partial':
            value['coverage'].update(inventory_complete=False, truncated=True, total_files=25)
        return value
    def prepare_design_consent(self, *args, **kwargs):
        return org_design.prepare_design_consent(*args, **kwargs)
    def design_with_llm(self, summary, provider, model, config, api_key, consent, **kwargs):
        assert api_key == SENTINEL, 'Only the noncredential fixture sentinel is permitted'
        self.design_calls += 1
        if self.mode == 'blocked_design': self.release.wait(25)
        if self.mode == 'fail_design':
            raise RuntimeError('E2E controlled synthetic failure; never an upstream response')
        result = design_result(config['agent_count'])
        result['provenance'].update(provider=provider, model=model, generation_method='mock_only')
        result['audit'].update(fixture=True, actual_provider_calls=0)
        kwargs.get('progress_callback', lambda _: None)({'completed_requests': 1, 'total_requests': 1})
        return result
    def discover_models(self, provider, api_key):
        assert api_key == SENTINEL
        # Exercise the real gate using synthetic catalog observations only.
        return {'models': [{'id': 'fixture-model', 'source': 'live_api', 'availability_verified': True,
                            'synthetic_fixture': True}],
                'source': 'live_api', 'status': 'fixture_only', 'verified_at': 'E2E_FIXTURE_ONLY'}

SAFE_ACTIONS = {
    'config', 'credentials', 'forget-credentials', 'generate', 'generation-plan',
    'generation-confirm', 'generation-cancel', 'design-restore', 'project-save',
    'project-load', 'edit-organization', 'tool-policy', 'model-overrides', 'model-preferences',
    'discover-models', 'analyze-repository', 'council-create', 'council-add-entry',
    'council-close', 'skill-register', 'subteam-save',
    'capability-search', 'capability-save', 'capability-preview', 'capability-apply',
    'capability-discard', 'capability-recommend', 'capability-assignments', 'capability-audit',
    'cordis-prepare', 'resource-workflow-example', 'resource-workflow-baseline',
    'resource-workflow-preview', 'resource-workflow-apply',
    'performance-create', 'performance-review', 'promotion-create', 'promotion-update',
    'lease-acquire', 'lease-renew', 'lease-release',
    'skill-feedback', 'remediation-create', 'remediation-update',
}
DSH_READ_ACTIONS = {'dsh-status', 'dsh-read-profiles', 'dsh-read-team', 'dsh-preview-import'}

class FixtureState(bridge.BridgeState):
    def __init__(self, root, seed=True):
        self.fixture_actions = []
        self.fixture_blocked_actions = []
        self.fixture_provider = InertProvider()
        self.fixture_workspace = str(root / 'synthetic-workspace')
        super().__init__(credential_store=MemoryOnlyStore(), provider_module=self.fixture_provider,
                         project_store=ProjectStore(root / 'projects'))
        self.config.update(repo_url='https://github.com/example/qa-fixture', repo_name='E2E Synthetic Organization',
                           template='generic', provider='deepseek-official', model='fixture-model',
                           agent_count=4, council_concurrency=4)
        self.credentials['deepseek-official'] = SENTINEL
        self._sensitive_values.add(SENTINEL)
        super().execute('discover-models', {'confirmed': True})
        if seed: super().execute('generate', {})
        self.receipt('e2e-fixture', 'warning', FIXTURE_NOTICE)
    def execute(self, action, body):
        self.fixture_actions.append(action)
        if action in DSH_READ_ACTIONS:
            # Exercise read-only rendering using observations, never a connection.
            self.integrations.dsh_status = {'status': 'disconnected', 'connected': False,
                'identity_verified': False, 'dispatch_supported': False, 'fixture': True,
                'reason': 'E2E_SYNTHETIC_OBSERVATION_NO_CONNECTION'}
            if action == 'dsh-read-profiles':
                self.integrations.dsh_profiles = {'fixture': True, 'profiles': [], 'runtime_verified': False}
            if action == 'dsh-read-team':
                self.integrations.dsh_team = {'fixture': True, 'tasks': [], 'runtime_verified': False}
            if action == 'dsh-preview-import':
                self.integrations.dsh_preview = {'fixture': True, 'dry_run': True, 'imported': False}
            self.receipt(action, 'warning', FIXTURE_NOTICE)
            return self.public()
        if action not in SAFE_ACTIONS:
            self.fixture_blocked_actions.append(action)
            raise bridge.BridgeError('E2E fixture blocks this action: ' + action)
        if action == 'credentials' and (body.get('api_key') != SENTINEL or body.get('persist')):
            raise bridge.BridgeError('E2E accepts only its sentinel, in memory, never real credentials.')
        if action == 'lease-acquire' and body.get('workspace') != self.fixture_workspace:
            raise bridge.BridgeError('E2E leases may reference only the synthetic temporary workspace.')
        if action in {'config', 'generation-plan'}:
            config = body.get('config', {})
            if config.get('source_kind', 'github_repository') != 'github_repository':
                raise bridge.BridgeError('E2E fixture does not fetch websites; source-switch UI is field-only.')
            url = config.get('repo_url', self.config['repo_url'])
            if url != 'https://github.com/example/qa-fixture':
                raise bridge.BridgeError('Only the synthetic source URL is permitted.')
        return super().execute(action, body)
    def tool_catalog(self):
        return json.loads((ROOT / 'engine' / 'tool_catalog.json').read_text('utf-8'))
    def public(self):
        result = super().public()
        result['e2e_fixture'] = {'notice': FIXTURE_NOTICE, 'live_provider_calls': 0,
            'synthetic_workspace': self.fixture_workspace,
            'synthetic_design_calls': self.fixture_provider.design_calls,
            'synthetic_inventory_calls': self.fixture_provider.inventory_calls,
            'actions': list(self.fixture_actions), 'blocked_actions': list(self.fixture_blocked_actions)}
        result['verification']['provider_live_calls'] = 'NOT_RUN_E2E_FIXTURE_ONLY'
        return result

class FixtureHandler(bridge.LocalHandler):
    def do_GET(self):
        if urlsplit(self.path).path == '/favicon.ico':
            self._send(b'', 'image/x-icon', 204)
            return
        super().do_GET()
    def do_POST(self):
        if not urlsplit(self.path).path.startswith('/__e2e__/'):
            return super().do_POST()
        if not self._check(require_session=True, mutation=True): return
        try:
            length = int(self.headers.get('Content-Length', 0))
            if not 0 < length < 8192: raise ValueError('Invalid fixture body')
            body = json.loads(self.rfile.read(length))
            path = urlsplit(self.path).path
            state = self.server.state
            if path == '/__e2e__/mode':
                state.fixture_provider.configure(body['mode'])
            elif path == '/__e2e__/release':
                state.fixture_provider.release.set()
            elif path == '/__e2e__/reset':
                state.fixture_provider.release.set()
                active = state.generation._active()
                if active: state.execute('generation-cancel', {'job_id': active['job_id']})
                root = self.server.fixture_root / ('case-' + str(time.monotonic_ns()))
                replacement = FixtureState(root, seed=body.get('seed', True))
                replacement.csrf, replacement.cookie = state.csrf, state.cookie
                replacement._record_model_account(replacement.config)
                self.server.state = replacement
            else: raise ValueError('Unknown fixture route')
            self._json(self.server.state.public())
        except (ValueError, KeyError, TypeError) as exc:
            self._json({'error': str(exc)}, 400)

def denied(*args, **kwargs):
    raise RuntimeError('E2E DENIED: outbound sockets and subprocess execution are inert')

def main():
    # No call to launcher.main, instance discovery, user credential store, or DSH.
    with tempfile.TemporaryDirectory(prefix='orgdna-e2e-') as temporary:
        root = Path(temporary)
        old_cwd = Path.cwd()
        with patch.dict(os.environ, {'LOCALAPPDATA': str(root), 'APPDATA': str(root),
                                    'USERPROFILE': str(root), 'HOME': str(root)}), \
             patch.object(bridge, 'ROOT', root), \
             patch.object(socket.socket, 'connect', denied), \
             patch.object(socket, 'create_connection', denied), \
             patch.object(subprocess, 'Popen', denied), patch.object(subprocess, 'run', denied):
            os.chdir(root)
            state = FixtureState(root)
            server = bridge.LocalServer(('127.0.0.1', 0), state)
            server.RequestHandlerClass = FixtureHandler
            server.fixture_root = root
            print(json.dumps({'origin': server.origin, 'fixture': True, 'notice': FIXTURE_NOTICE}), flush=True)
            try: server.serve_forever(poll_interval=.15)
            except KeyboardInterrupt: pass
            finally:
                server.state.fixture_provider.release.set()
                server.server_close()
                os.chdir(old_cwd)

if __name__ == '__main__': main()
