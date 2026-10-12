"""Offline, additive SkillHub package publication. Never installs or starts DSH.

A successful publication only means verified bytes in a new namespace/version;
activation remains pending until native identity/tool/manifest readback succeeds.
"""
from __future__ import annotations

if __package__:
    from .limits import MAX_AGENTS
else:
    from limits import MAX_AGENTS

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import tempfile
import uuid

PROTOCOL = 'orgdna-skillhub-deployment/1'
SAFE_VERSION = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$')


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _bytes(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + '\n').encode()


def skillhub_manifest_bytes(manifest):
    """Canonical snapshot bytes used by exports, delta CAS and runtime hash pinning."""
    return _bytes(manifest)


def _safe_path(path):
    path = Path(path).absolute()
    for component in (path, *path.parents):
        if component.is_symlink():
            raise ValueError('Symlinks are not allowed in publication paths')
    return path


def _identity(organization_id, namespace):
    identifier = str(uuid.UUID(organization_id))
    if namespace != 'orgdna_' + identifier.replace('-', ''):
        raise ValueError('Namespace must match the existing organization UUID')
    return identifier


def build_deployment_plan(library_manifest, organization_id, member_ids):
    """Return a non-executable plan, including explicit runtime blockers."""
    identifier = str(uuid.UUID(organization_id))
    namespace = 'orgdna_' + identifier.replace('-', '')
    if not isinstance(library_manifest, dict) or library_manifest.get('organization_id') != identifier:
        raise ValueError('Library belongs to a different organization')
    ids = [str(uuid.UUID(value)) for value in member_ids]
    if len(ids) != len(set(ids)) or not 1 <= len(ids) <= MAX_AGENTS:
        raise ValueError('Existing roster requires 1–%d unique members' % MAX_AGENTS)
    return {'protocol': PROTOCOL, 'organization_id': identifier, 'namespace': namespace,
            'member_ids': ids, 'manifest_sha256': _sha(_bytes(library_manifest)),
            'status': 'PREVIEW_ONLY', 'runtime_activated': False,
            'teams_role': 'profile_library', 'agentteams_role': 'existing_orchestrator',
            'cordis_role': 'namespaced_capabilities', 'new_agents': 0,
            'existing_files_modified': 0, 'network_calls': 0,
            'pending': ['Verify installed host version and its supported overlay CLI from local source.',
                        'Verify native profiles and live session bindings match these existing UUIDs.',
                        'Obtain separate native approval for any plugin install/activation or persistent scopes.',
                        'Read back live namespace, profile UUIDs, manifest hash and per-capability health.'],
            'connector_policy': {'email': 'BLOCKED_AUTH_AND_HEALTH', 'messaging': 'BLOCKED_AUTH_AND_HEALTH',
                                 'voice': 'BLOCKED_AUTH_AND_HEALTH', 'send_now': False,
                                 'impersonate_human': False, 'secrets_exported': False}}


def publish_package(files, destination, namespace, version, organization_id, *, approve=False):
    """Preview or exclusively publish bytes in destination/namespace/version.

    Never replaces an existing version. The receipt allows rollback only if every
    published file is unchanged and no foreign file was added. Existing versions,
    profiles, history and other plugins are neither read nor modified.
    """
    identifier = _identity(organization_id, namespace)
    if not isinstance(version, str) or not SAFE_VERSION.fullmatch(version) or version in ('.', '..'):
        raise ValueError('Unsafe package version')
    if not isinstance(files, dict) or not files or len(files) > 1000:
        raise ValueError('Expected bounded package files')
    checked = {}
    for name, content in files.items():
        if not isinstance(name, str) or '\\' in name or ':' in name:
            raise ValueError('Unsafe package path')
        rel = PurePosixPath(name)
        if rel.is_absolute() or any(p in ('', '.', '..') for p in name.split('/')) or name == '.publication.json':
            raise ValueError('Unsafe package path')
        if not isinstance(content, bytes) or len(content) > 8 * 1024 * 1024:
            raise ValueError('Package files must be bounded bytes')
        checked[name] = content
    if sum(map(len, checked.values())) > 64 * 1024 * 1024:
        raise ValueError('Package exceeds size limit')
    root = _safe_path(destination)
    target = _safe_path(root / namespace / version)
    if target.exists():
        raise FileExistsError('Version already exists; no overwrite or implicit upgrade')
    receipt = {'protocol': PROTOCOL, 'organization_id': identifier, 'namespace': namespace, 'version': version,
               'files': {name: _sha(data) for name, data in sorted(checked.items())},
               'runtime_activated': False, 'existing_files_modified': 0}
    result = {'status': 'PREVIEW_ONLY', 'target': str(target), 'receipt': receipt,
              'activation_status': 'PENDING_NATIVE_PREFLIGHT_AND_READBACK', 'backup': 'Not needed: exclusive new version; existing versions retained.'}
    if not approve:
        return result
    root.mkdir(parents=True, exist_ok=True)
    parent = _safe_path(root / namespace)
    parent.mkdir(exist_ok=True)
    # Exclusive target creation also prevents a racing publisher from replacing it.
    target.mkdir()
    try:
        for name, data in checked.items():
            out = target / name
            out.parent.mkdir(parents=True, exist_ok=True)
            with out.open('xb') as handle:
                handle.write(data)
        (target / '.publication.json').write_bytes(_bytes(receipt))
        for name, digest in receipt['files'].items():
            if _sha((target / name).read_bytes()) != digest:
                raise IOError('Publication readback mismatch')
    except Exception:
        # This directory was exclusively created above and has never been activated.
        shutil.rmtree(target)
        raise
    result['status'] = 'PUBLISHED_BYTES_VERIFIED_NOT_ACTIVATED'
    return result


def rollback_publication(destination, receipt, *, approve=False):
    if receipt.get('protocol') != PROTOCOL:
        raise ValueError('Invalid publication receipt')
    _identity(receipt['organization_id'], receipt['namespace'])
    if not SAFE_VERSION.fullmatch(receipt['version']) or receipt['version'] in ('.', '..'):
        raise ValueError('Unsafe package version')
    target = _safe_path(Path(destination) / receipt['namespace'] / receipt['version'])
    stored = json.loads((target / '.publication.json').read_text())
    if stored != receipt:
        raise ValueError('Receipt differs from original publication')
    expected = set(receipt['files']) | {'.publication.json'}
    actual = set()
    for file in target.rglob('*'):
        if file.is_symlink():
            raise ValueError('Rollback refuses symlinks')
        if file.is_file():
            actual.add(file.relative_to(target).as_posix())
    if actual != expected:
        raise ValueError('Rollback refuses foreign or missing files')
    for name, digest in receipt['files'].items():
        if _sha((target / name).read_bytes()) != digest:
            raise ValueError('Rollback refuses modified files')
    if approve:
        shutil.rmtree(target)
    return {'status': 'ROLLED_BACK_OWN_VERSION' if approve else 'ROLLBACK_PREVIEW',
            'target': str(target), 'other_plugins_modified': False,
            'native_deactivation': 'Not performed; detach any active native addon first.'}


def export_skillhub_library(library, organization):
    """Snapshot a paginated registry; revisions must stay stable throughout export."""
    identifier = str(uuid.UUID(organization['organization_id']))
    ids = [str(uuid.UUID(a['id'])) for a in organization['agents']]
    if len(ids) != len(set(ids)) or not 1 <= len(ids) <= MAX_AGENTS:
        raise ValueError('Invalid existing roster')
    items, assignments, revisions = [], [], set()
    for method, target, maximum in ((library.search, items, 10000), (library.manifest_page, assignments, 320000)):
        offset = 0
        while True:
            page = method(offset=offset, limit=100)
            revisions.add(page['revision'])
            if len(revisions) != 1:
                raise ValueError('Library changed during export; retry from a stable revision')
            target.extend(page['items'])
            if len(target) > maximum:
                raise ValueError('Excessive library pagination')
            next_offset = page.get('next_offset')
            if next_offset is None:
                break
            if not isinstance(next_offset, int) or next_offset <= offset:
                raise ValueError('Invalid or excessive library pagination')
            offset = next_offset
    # No opaque metadata, credential objects, OAuth grants or executable handlers.
    exported = [{key: item[key] for key in ('id', 'kind', 'name', 'description', 'content', 'tags', 'content_hash', 'provenance', 'tool_needs') if key in item}
                for item in items]
    for item in exported:
        item['exported_payload_sha256'] = _sha(json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode())
    selected = [{key: row[key] for key in ('agent_id', 'item_id', 'kind', 'content_hash', 'active') if key in row}
                for row in assignments if row.get('agent_id') in ids]
    result = {'protocol': 'orgdna-skillhub/1', 'organization_id': identifier,
              'namespace': 'orgdna_' + identifier.replace('-', ''), 'member_ids': ids,
              'revision': next(iter(revisions)), 'items': exported, 'assignments': selected,
              'context_budget_bytes': 12000, 'permission_grants': [], 'runtime_verified': False,
              'connectors': [{'kind': k, 'status': 'BLOCKED_AUTH_AND_HEALTH', 'required': ['native_package_review', 'explicit_auth_scopes', 'health_readback', 'separate_send_authorization'], 'installed': False}
                             for k in ('email', 'messaging', 'voice')]}
    # Reject common credential forms rather than exporting suspected secrets.
    serialized = json.dumps(result, ensure_ascii=False)
    if re.search(r'(?i)(?:sk-[a-z0-9_-]{12,}|Bearer\s+[a-z0-9._-]{12,}|(?:api[_-]?key|access[_-]?token|password)\s*[:=]\s*["\']?[^\s"\',}]{6,})', serialized):
        raise ValueError('Possible credential in library: remove it before exporting')
    return validate_skillhub_manifest(result, organization)


def validate_skillhub_manifest(manifest, organization):
    identifier = str(uuid.UUID(organization['organization_id']))
    ids = [str(uuid.UUID(a['id'])) for a in organization['agents']]
    if (not isinstance(manifest, dict) or manifest.get('protocol') != 'orgdna-skillhub/1' or
        manifest.get('organization_id') != identifier or manifest.get('namespace') != 'orgdna_' + identifier.replace('-', '') or
        manifest.get('member_ids') != ids or len(ids) != len(set(ids)) or not 1 <= len(ids) <= MAX_AGENTS):
        raise ValueError('SkillHub organization/roster mismatch')
    if set(manifest) - {'protocol','organization_id','namespace','member_ids','revision','items','assignments','context_budget_bytes','permission_grants','runtime_verified','connectors'}:
        raise ValueError('Unknown SkillHub manifest fields')
    if type(manifest.get('revision')) is not int or manifest['revision'] < 0:
        raise ValueError('Invalid library revision')
    if manifest.get('permission_grants') != [] or manifest.get('runtime_verified') is not False:
        raise ValueError('Export cannot claim permission grants or runtime verification')
    if type(manifest.get('context_budget_bytes')) is not int or not 256 <= manifest['context_budget_bytes'] <= 12000:
        raise ValueError('Invalid SkillHub context budget')
    for connector in manifest.get('connectors', []):
        if not isinstance(connector, dict) or set(connector) != {'kind','status','required','installed'} or connector.get('kind') not in {'email','messaging','voice'} or connector.get('status') != 'BLOCKED_AUTH_AND_HEALTH' or connector.get('installed') is not False or connector.get('required') != ['native_package_review','explicit_auth_scopes','health_readback','separate_send_authorization']:
            raise ValueError('Invalid connector contract')
    items = manifest.get('items'); assignments = manifest.get('assignments')
    if not isinstance(items, list) or len(items) > 10000 or not isinstance(assignments, list) or len(assignments) > 320000:
        raise ValueError('Invalid SkillHub bounds')
    kinds = {'skill_instructions','memory_policy','plugin_package','connector'}
    index = {}
    for item in items:
        if (not isinstance(item, dict) or not isinstance(item.get('id'), str) or not item['id'] or item['id'] in index or
            item.get('kind') not in kinds or not isinstance(item.get('name'), str) or not isinstance(item.get('content'), str) or
            len(item['content'].encode()) > 256000 or not re.fullmatch('[a-f0-9]{64}', str(item.get('content_hash')))):
            raise ValueError('Invalid SkillHub item')
        if set(item) - {'id','kind','name','description','content','tags','content_hash','provenance','tool_needs','exported_payload_sha256'}:
            raise ValueError('Opaque item fields are not exportable')
        if len(item['id']) > 200 or len(item['name'].encode()) > 256 or not isinstance(item.get('description', ''), str):
            raise ValueError('Invalid bounded item metadata')
        for field in ('tags','tool_needs'):
            values=item.get(field, [])
            if not isinstance(values, list) or len(values)>128 or any(not isinstance(v,str) or len(v.encode())>512 for v in values):
                raise ValueError('Invalid item reference list')
        payload = {k:v for k,v in item.items() if k != 'exported_payload_sha256'}
        if item.get('exported_payload_sha256') != _sha(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()):
            raise ValueError('SkillHub exported payload hash mismatch')
        source = item.get('provenance', {})
        if not isinstance(source, dict) or set(source) - {'type','evidence','url','source_id','retrieved_at','sha256'} or any(not isinstance(v, str) or len(v.encode())>32000 for v in source.values()):
            raise ValueError('Invalid source evidence fields')
        if source.get('url'):
            from urllib.parse import urlsplit
            url = urlsplit(source['url'])
            if url.scheme != 'https' or not url.netloc or url.username or url.password or url.query or url.fragment:
                raise ValueError('Source URL cannot transmit credentials or query data')
        index[item['id']] = item
    seen = set()
    for row in assignments:
        if not isinstance(row, dict) or set(row) - {'agent_id','item_id','kind','content_hash','active'}:
            raise ValueError('Unknown assignment fields')
        item = index.get(row.get('item_id')); key = (row.get('agent_id'),row.get('item_id'))
        if (row.get('agent_id') not in ids or not item or row.get('kind') != item['kind'] or
            row.get('content_hash') != item['content_hash'] or type(row.get('active')) is not bool or key in seen):
            raise ValueError('Invalid SkillHub assignment')
        if row['active'] and item['kind'] not in {'skill_instructions','memory_policy'}:
            raise ValueError('Executable capabilities cannot be active instructions')
        seen.add(key)
    serialized = json.dumps(manifest, ensure_ascii=False)
    if len(serialized.encode()) > 16 * 1024 * 1024:
        raise ValueError('SkillHub manifest exceeds byte limit')
    if re.search(r'(?i)(?:sk-[a-z0-9_-]{12,}|Bearer\s+[a-z0-9._-]{12,}|(?:api[_-]?key|access[_-]?token|password)\s*[:=]\s*["\']?[^\s"\',}]{6,})', serialized):
        raise ValueError('Possible credential in SkillHub manifest')
    return manifest


def build_skillhub_delta(base, target, organization):
    """Versioned review artifact; no team recreation, permission grants or installs."""
    validate_skillhub_manifest(base, organization)
    validate_skillhub_manifest(target, organization)
    if base['revision'] == target['revision'] and base != target:
        raise ValueError('Changed snapshot requires a new library revision')
    index = lambda doc: {(a['agent_id'], a['item_id']): a for a in doc['assignments']}
    before, after = index(base), index(target)
    changes = []
    for key in sorted(set(before) | set(after)):
        old, new = before.get(key), after.get(key)
        if old != new:
            changes.append({'agent_id': key[0], 'item_id': key[1],
                            'action': 'add' if old is None else 'remove' if new is None else 'update',
                            'before': old, 'after': new})
    old_items={i['id']:i for i in base['items']};new_items={i['id']:i for i in target['items']}
    changed_items=[i for i in sorted(set(old_items)|set(new_items)) if old_items.get(i)!=new_items.get(i)]
    affected = sorted({c['agent_id'] for c in changes} | {a['agent_id'] for a in base['assignments']+target['assignments'] if a['item_id'] in changed_items})
    return {'protocol': 'orgdna-skillhub-delta/1', 'organization_id': base['organization_id'], 'namespace': base['namespace'],
            'base_revision': base['revision'], 'target_revision': target['revision'],
            'hash_encoding': 'UTF8 JSON sorted keys indent2 trailing newline',
            'base_hash': _sha(_bytes(base)), 'target_hash': _sha(_bytes(target)),
            'member_ids': base['member_ids'], 'affected_member_ids': affected,
            'assignment_changes': changes, 'changed_item_ids': changed_items,
            'permission_changes': [], 'plugin_installations': [], 'new_agents': 0,
            'requirements': ['Owner review of exact base/target hashes and affected members.',
                             'Native package approval and permissions are separate from these assignments.',
                             'Atomic compare-and-swap affects only the addon manifest; native profile scopes remain unchanged.',
                             'Reload hash-pinned addon through verified native mechanism and read back target hash.'],
            'rollback': {'base_hash': _sha(_bytes(target)), 'target_hash': _sha(_bytes(base)),
                         'assignment_changes': [{**c, 'action': 'remove' if c['action']=='add' else 'add' if c['action']=='remove' else 'update', 'before':c['after'],'after':c['before']} for c in changes]},
            'runtime_status': 'PENDING_REVIEW_CAS_AND_NATIVE_RELOAD', 'base_snapshot': base, 'target_snapshot': target}


def apply_skillhub_delta(manifest_path, delta, organization, *, approve=False):
    """CAS only a manifest under its own namespace. Retains immutable backup."""
    expected = build_skillhub_delta(delta['base_snapshot'], delta['target_snapshot'], organization)
    if delta != expected:
        raise ValueError('Delta differs from reviewed snapshots')
    path = _safe_path(manifest_path)
    if delta['namespace'] not in path.parts or path.name != 'skillhub-library.json':
        raise ValueError('Delta may only update its own namespaced SkillHub manifest')
    current = path.read_bytes()
    if _sha(current) != delta['base_hash']:
        raise ValueError('STALE_BASE: manifest changed; no update occurred')
    result = {'status':'DELTA_PREVIEW', 'base_hash':delta['base_hash'],'target_hash':delta['target_hash'],
              'affected_member_ids':delta['affected_member_ids'],'runtime_activated':False,
              'activation_status':'PENDING_NATIVE_RELOAD_AND_TARGET_HASH_READBACK','existing_profiles_modified':False}
    if not approve:
        return result
    lock=path.with_name('.skillhub-update.lock')
    with lock.open('xb') as lock_handle:
        lock_handle.close()  # Windows allows later cleanup after the exclusive create.
        try:
            if path.read_bytes() != current:
                raise ValueError('STALE_BASE: manifest changed before commit')
            backup=_safe_path(path.with_name('skillhub-backup-'+delta['base_hash']+'.json'))
            if backup.exists():
                if backup.read_bytes()!=current:raise ValueError('Backup collision')
            else:
                with backup.open('xb') as handle:handle.write(current)
            temp=path.with_name('.skillhub-'+str(uuid.uuid4())+'.tmp')
            try:
                with temp.open('xb') as handle:
                    handle.write(_bytes(delta['target_snapshot']));handle.flush();os.fsync(handle.fileno())
                os.replace(temp,path)
            finally:
                if temp.exists():temp.unlink()
            if _sha(path.read_bytes()) != delta['target_hash']:
                raise IOError('Target readback mismatch')
            result.update(status='DELTA_BYTES_VERIFIED_NOT_ACTIVATED',backup_path=str(backup))
        finally:
            lock.unlink()
    return result


def request_skillhub_reload(manifest_path, delta, organization, *, approve=False):
    """Explicit owner action requesting in-memory reload, separate from publication.

    Writes only a hash-bound receipt beside our manifest. Native state polls that
    receipt read-only; it cannot publish a manifest or request its own reload.
    """
    if delta != build_skillhub_delta(delta['base_snapshot'],delta['target_snapshot'],organization):
        raise ValueError('Delta differs from reviewed snapshots')
    manifest = _safe_path(manifest_path)
    if delta['namespace'] not in manifest.parts or manifest.name != 'skillhub-library.json':
        raise ValueError('Reload requires own namespaced manifest')
    if _sha(manifest.read_bytes()) != delta['target_hash']:
        raise ValueError('Published target hash does not match reload request')
    receipt={'protocol':'orgdna-skillhub-reload/1','organization_id':delta['organization_id'],
             'namespace':delta['namespace'],'base_hash':delta['base_hash'],'target_hash':delta['target_hash'],
             'member_ids':delta['member_ids'],'request_id':str(uuid.uuid4()),'authority':'explicit_local_owner_request',
             'scope':'library_context_only_no_permissions_plugins_or_credentials'}
    path=_safe_path(manifest.with_name('skillhub-reload.json'))
    if approve:
        temp=path.with_name('.reload-'+receipt['request_id']+'.tmp')
        try:
            with temp.open('xb') as handle:
                handle.write(_bytes(receipt));handle.flush();os.fsync(handle.fileno())
            os.replace(temp,path)
        finally:
            if temp.exists():temp.unlink()
    return {'status':'RELOAD_REQUESTED_READBACK_PENDING' if approve else 'RELOAD_PREVIEW',
            'receipt':receipt,'receipt_path':str(path),'runtime_verified':False,
            'confirmation':'Read live state.summary.skillhub.manifest_sha256 and reload_request_id.'}


def main(argv=None):
    import argparse
    parser=argparse.ArgumentParser(description='SkillHub library-only delta; no native installs or grants.')
    parser.add_argument('operation',choices=('preview-delta','publish-delta','request-reload'))
    parser.add_argument('--base',required=True,help='Reviewed base snapshot JSON')
    parser.add_argument('--target',required=True,help='Reviewed target snapshot JSON')
    parser.add_argument('--organization',required=True,help='Existing organization JSON; same roster required')
    parser.add_argument('--manifest',help='Absolute own namespace skillhub-library.json for publication/reload')
    parser.add_argument('--reviewed',action='store_true',help='Explicit local approval of this exact operation and hashes')
    args=parser.parse_args(argv)
    def document(file):
        p=_safe_path(file)
        if p.stat().st_size>16*1024*1024:raise ValueError('Input exceeds size limit')
        return json.loads(p.read_text(encoding='utf8'))
    try:
        org=document(args.organization)
        delta=build_skillhub_delta(document(args.base),document(args.target),org)
        if args.operation=='preview-delta':
            result={key:value for key,value in delta.items() if key not in ('base_snapshot','target_snapshot')}
        else:
            if not args.manifest or not Path(args.manifest).is_absolute():
                raise ValueError('An absolute own namespace manifest path is required')
            operation=apply_skillhub_delta if args.operation=='publish-delta' else request_skillhub_reload
            result=operation(args.manifest,delta,org,approve=args.reviewed)
        print(json.dumps(result,ensure_ascii=False,indent=2));return 0
    except (ValueError,OSError,KeyError,TypeError) as error:
        print(json.dumps({'status':'BLOCKED','reason':str(error)},ensure_ascii=False));return 2

if __name__=='__main__':
    raise SystemExit(main())
