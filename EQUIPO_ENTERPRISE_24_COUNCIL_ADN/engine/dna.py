"""Strict structured organization DNA: evidence-bound fictional profiles and identity.

No network, repository execution, tool installation, or permission grants occur here.
The API design boundary is deliberately different from the explicit offline template.
"""
from __future__ import annotations

if __package__:
    from .limits import MAX_AGENTS
else:
    from limits import MAX_AGENTS

import copy
import hashlib
import json
import re
import unicodedata
import uuid
from pathlib import PurePosixPath
from datetime import datetime
from urllib.parse import urlsplit

if __package__:
    from .profiles import ROLE_SEEDS
else:
    from profiles import ROLE_SEEDS

DNA_VERSION = '3.0'
PROMPT_TARGET_UTF16 = 25000
KNOWN_ROLES = frozenset(seed[0] for seed in ROLE_SEEDS)
FICTION_NOTICE = ('PERSONA FICTICIA Y PERFIL ASPIRACIONAL. Biografía, trayectoria e instituciones '
                  'son inventadas; no acredita empleos, títulos, premios ni certificaciones reales. '
                  'Las capacidades objetivo exigen evaluación independiente.')
PROFILE_KEYS = {'name','display_name','role','title','department','mission','personality',
                'responsibilities','deliverables','skills','evidence_paths','cv',
                'functional_roles','tool_preset_role'}
REQUIRED_KEYS = PROFILE_KEYS - {'functional_roles','tool_preset_role'}
CONTROL = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]')
INJECTION = re.compile(r'ignore(?: all)? (?:rules|instructions)|disregard.*instructions|override.*(?:system|rules)|reveal.*(?:secret|password)|(?:transfer|send).*(?:funds|credentials|secrets)|(?:ejecuta|ejecutar|run)\s+(?:sudo|curl|powershell)|ignora.*(?:reglas|instrucciones)|borra.*(?:archivos|datos)',re.I)
AWARDS = re.compile(r'\bnobel\b|\bturing\s+(?:award|prize)\b|\bpremio\s+turing\b|\bfields\s+medal\b|\bmedalla\s+fields\b',re.I)


def canonical_json(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical_json(value).encode('utf-8')).hexdigest()


def utf16_len(value):
    return len(value.encode('utf-16-le')) // 2


def _key(value):
    value=unicodedata.normalize('NFKC',value).casefold()
    return ' '.join(value.split())


def _text(value,field,maximum,minimum=1):
    if not isinstance(value,str) or CONTROL.search(value):
        raise ValueError(f'{field}: se requiere texto sin controles.')
    value=value.strip()
    if not minimum<=utf16_len(value)<=maximum:
        raise ValueError(f'{field}: longitud requerida {minimum}..{maximum} UTF16.')
    if INJECTION.search(value):
        raise ValueError(f'{field}: instrucciones no confiables requieren revisión manual.')
    if AWARDS.search(value):
        raise ValueError(f'{field}: no atribuir premios reales a una persona ficticia.')
    return value


def _strings(value,field,minimum,maximum,text_maximum):
    if not isinstance(value,list) or not minimum<=len(value)<=maximum:
        raise ValueError(f'{field}: se requieren {minimum}..{maximum} elementos; no se trunca.')
    result=[_text(item,field,text_maximum) for item in value]
    if len({_key(x) for x in result})!=len(result):
        raise ValueError(f'{field}: valores duplicados.')
    return result


def _object(value,field,required,optional=()):
    if not isinstance(value,dict) or set(value)-set(required)-set(optional) or set(required)-set(value):
        raise ValueError(f'{field}: campos requeridos o desconocidos; sólo {", ".join(sorted(set(required)|set(optional)))}.')
    return value


def _relative_path(value):
    value=_text(value,'evidence_path',500)
    if '\\' in value or value.startswith(('/','~')) or '://' in value or re.match(r'^[A-Za-z]:',value):
        raise ValueError('evidence_path debe ser ruta relativa observada del repositorio.')
    parts=PurePosixPath(value).parts
    if not parts or any(p in ('..','.') for p in value.split('/')) or str(PurePosixPath(value))!=value:
        raise ValueError('evidence_path no puede escapar ni normalizar ambiguamente una ruta.')
    return value


def website_provenance(analysis):
    """Validate an inert, metadata-only page ledger without DNS or network calls."""
    if __package__:
        from .web_sources import canonical_url
    else:
        from web_sources import canonical_url
    def url(value):
        try:
            if canonical_url(value) != value:
                raise ValueError("URL no canónica.")
        except (TypeError, ValueError) as exc:
            raise ValueError("Referencia web inválida.") from exc
        return value
    root = url(analysis.get('source_url'))
    rows = analysis.get('snapshots')
    if not isinstance(rows, list) or not 1 <= len(rows) <= 100:
        raise ValueError('Se requieren snapshots web acotados con procedencia.')
    snapshots = []
    seen = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError('Snapshot web inválido.')
        page = url(row.get('url'))
        if page in seen or urlsplit(page).netloc != urlsplit(root).netloc:
            raise ValueError('Snapshot duplicado o fuera del origen aprobado.')
        seen.add(page)
        sha = row.get('sha256')
        if not isinstance(sha, str) or not re.fullmatch(r'[0-9a-f]{64}', sha):
            raise ValueError('Snapshot web requiere SHA256 del contenido leído.')
        fetched = row.get('fetched_at')
        try:
            parsed = datetime.fromisoformat(fetched.replace("Z", "+00:00"))
            if parsed.tzinfo is None: raise ValueError('Timestamp sin zona.')
        except (AttributeError, TypeError, ValueError):
            raise ValueError('Snapshot web requiere fetched_at ISO con zona.') from None
        status = row.get('content_status')
        if status not in ('usable_static_html', 'javascript_shell', 'no_usable_evidence'):
            raise ValueError('Estado de evidencia web inválido.')
        snapshots.append({'url': page, 'sha256': sha, 'fetched_at': fetched, 'content_status': status})
    manifest = [{'url': row['url'], 'sha256': row['sha256']} for row in sorted(snapshots, key=lambda row: row['url'])]
    expected = hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()
    if analysis.get('source_hash') != expected:
        raise ValueError('source_hash no coincide con snapshots web.')
    evidence = analysis.get('evidence_urls')
    usable = {row['url'] for row in snapshots if row['content_status'] == 'usable_static_html'}
    if (not isinstance(evidence, list) or any(not isinstance(item, str) for item in evidence)
            or len(set(evidence)) != len(evidence) or set(evidence) != usable):
        raise ValueError('evidence_urls debe coincidir con las páginas realmente leídas y utilizables.')
    return {'source_kind': 'website', 'source_url': root, 'source_hash': expected,
            'snapshots': snapshots, 'evidence_urls': list(evidence)}


def observed_paths(analysis):
    """Only the reader's explicit read-file ledger establishes evidence membership."""
    if not isinstance(analysis,dict):
        return set()
    if analysis.get('source_kind') == 'website':
        return set(website_provenance(analysis)['evidence_urls'])
    rows=analysis.get('repository_files',[])
    if not isinstance(rows,list):
        raise ValueError('analysis.repository_files debe ser una lista de rutas leídas.')
    result=set()
    for item in rows:
        if isinstance(item,dict): item=item.get('path')
        result.add(_relative_path(item))
    return result


def _paths(value,field,observed,maximum=12):
    rows=_strings(value,field,1,maximum,2048)
    # URLs can only pass when membership was established by website_provenance.
    paths=[x if x.startswith('https://') and x in observed else _relative_path(x) for x in rows]
    missing=set(paths)-observed
    if missing:
        raise ValueError(f'{field}: evidencia no leída/no observada: {", ".join(sorted(missing))}.')
    return paths


def _cv(value,field):
    keys={'summary','experience','education','certifications','languages','working_style'}
    _object(value,field,keys)
    result={'summary':_text(value['summary'],field+'.summary',1600),
            'languages':_strings(value['languages'],field+'.languages',1,4,180),
            'working_style':_strings(value['working_style'],field+'.working_style',2,6,250)}
    if not isinstance(value['experience'],list) or not 2<=len(value['experience'])<=4:
        raise ValueError(field+'.experience: se requieren 2..4 experiencias ficticias.')
    result['experience']=[]
    for index,row in enumerate(value['experience']):
        p=f'{field}.experience[{index}]'
        _object(row,p,{'position','organization','period','scope','achievements'})
        item={k:_text(row[k],p+'.'+k,500 if k=='scope' else 180) for k in ('position','organization','period','scope')}
        item['achievements']=_strings(row['achievements'],p+'.achievements',1,4,300)
        result['experience'].append(item)
    if not isinstance(value['education'],list) or len(value['education'])!=2:
        raise ValueError(field+'.education: se requieren Maestría y Doctorado ficticios, exactamente dos entradas.')
    result['education']=[]
    for index,row in enumerate(value['education']):
        p=f'{field}.education[{index}]'
        _object(row,p,{'program','institution','modules'})
        result['education'].append({'program':_text(row['program'],p+'.program',240),
                                    'institution':_text(row['institution'],p+'.institution',240),
                                    'modules':_strings(row['modules'],p+'.modules',2,6,180)})
    if not isinstance(value['certifications'],list) or not 1<=len(value['certifications'])<=3:
        raise ValueError(field+'.certifications: se requieren 1..3 evaluaciones objetivo ficticias.')
    result['certifications']=[]
    for index,row in enumerate(value['certifications']):
        p=f'{field}.certifications[{index}]'
        _object(row,p,{'name','acceptance'})
        result['certifications'].append({'name':_text(row['name'],p+'.name',180),'acceptance':_text(row['acceptance'],p+'.acceptance',400)})
    return result


def validate_profile_specs(specs,n,analysis):
    """Return a fully checked copy, or raise; incomplete API output never uses seeds."""
    if type(n) is not int or not 1<=n<=MAX_AGENTS:
        raise ValueError('agent_count debe ser entero 1..%d.' % MAX_AGENTS)
    if not isinstance(specs,list) or len(specs)!=n:
        raise ValueError(f'profile_specs debe contener EXACTAMENTE {n} perfiles, sin relleno ni truncamiento.')
    observed=observed_paths(analysis)
    if not observed:
        raise ValueError('profile_specs requiere un registro de evidencia realmente leída (archivos o snapshots web).')
    result=[]
    seen={field:set() for field in ('name','display_name','role','title','mission','cv_summary','cv_career','skill_set')}
    for index,row in enumerate(specs):
        field=f'profile_specs[{index}]'
        _object(row,field,REQUIRED_KEYS,PROFILE_KEYS-REQUIRED_KEYS)
        out={key:_text(row[key],field+'.'+key,maximum) for key,maximum in {
            'name':120,'display_name':120,'role':40,'title':160,'department':120,'mission':1000,'personality':800}.items()}
        if any('\n' in out[key] or '\r' in out[key] or '\t' in out[key] for key in ('name','display_name','title','department','role')):
            raise ValueError(field+': nombres y títulos deben ser texto de una sola línea.')
        if not re.fullmatch(r'[A-Z][A-Z0-9_]{0,39}',out['role']):
            raise ValueError(field+'.role: código estable en mayúsculas requerido.')
        if (index==0)!=(out['role']=='CEO'):
            raise ValueError('El primer y único CEO debe ocupar el slot 1.')
        out['responsibilities']=_strings(row['responsibilities'],field+'.responsibilities',3,8,400)
        out['deliverables']=_strings(row['deliverables'],field+'.deliverables',3,6,400)
        out['evidence_paths']=_paths(row['evidence_paths'],field+'.evidence_paths',observed)
        skills=row['skills']
        if not isinstance(skills,list) or not 3<=len(skills)<=12:
            raise ValueError(field+'.skills: se requieren 3..12 competencias objetivo.')
        out['skills']=[]; skill_names=set()
        for si,skill in enumerate(skills):
            sf=f'{field}.skills[{si}]'
            _object(skill,sf,{'name','description','evidence_paths'})
            name=_text(skill['name'],sf+'.name',120)
            if _key(name) in skill_names: raise ValueError(sf+': competencia duplicada.')
            skill_names.add(_key(name))
            out['skills'].append({'name':name,'description':_text(skill['description'],sf+'.description',400),
                                  'evidence_paths':_paths(skill['evidence_paths'],sf+'.evidence_paths',observed,8)})
        out['cv']=_cv(row['cv'],field+'.cv')
        roles=row.get('functional_roles',[])
        if not isinstance(roles,list) or len(roles)>2 or any(x not in ('auditor','consultant') for x in roles) or len(set(roles))!=len(roles):
            raise ValueError(field+'.functional_roles: sólo auditor y consultant, sin duplicados.')
        out['functional_roles']=list(roles)
        preset=row.get('tool_preset_role',out['role'] if out['role'] in KNOWN_ROLES else 'manual_review')
        if preset not in KNOWN_ROLES|{'manual_review'}:
            raise ValueError(field+'.tool_preset_role: preset desconocido; usar manual_review y revisar, no inventar herramientas.')
        out['tool_preset_role']=preset
        # Distinct names cannot disguise a copied career or identical competence set.
        career=[{'scope':x['scope'],'achievements':x['achievements']} for x in out['cv']['experience']]
        signatures={key:_key(out[key]) for key in ('name','display_name','role','title','mission')}
        signatures.update(cv_summary=_key(out['cv']['summary']),cv_career=_key(canonical_json(career)),skill_set=tuple(sorted(skill_names)))
        for key,value in signatures.items():
            if value in seen[key]: raise ValueError(f'{field}: {key} duplicado; se requieren perfiles diferenciados.')
            seen[key].add(value)
        if utf16_len(canonical_json(out))>16000:
            raise ValueError(field+': perfil demasiado extenso (>16000 UTF16); condensar sin perder evidencia.')
        result.append(out)
    return result


def agent_id(organization_id,slot):
    if type(slot) is not int or not 1<=slot<=MAX_AGENTS:
        raise ValueError('slot debe ser entero 1..%d.' % MAX_AGENTS)
    return str(uuid.uuid5(uuid.UUID(organization_id),f'agent-slot:{slot}'))


def dna_payload(org):
    """Canonical design content; excludes hashes, derived prompts and live evaluation.

    The payload is public and self-contained so audits can reproduce dna_hash.
    Availability refreshes and merit/lease records are not persona design changes.
    """
    agent_fields=('id','slot','name','display_name','role','title','department','mission','personality',
                  'reports_to','functional_roles','skills','responsibilities','deliverables','journeys','cv',
                  'provider','model','tool_policy','tool_preset_role','tool_mapping_status','evidence_paths','profile_source')
    config_keys=('repo_url','repo_name','agent_count','max_direct_reports','template','provider','model',
                 'implementation_concurrency','council_concurrency','owner_name','language','hierarchy_mode',
                 'autonomy_preset','planning_context','response_mode','planner_max_tokens','member_timeout_ms',
                 'handoff_summary_max_chars','runtime_token_budget','quality_gate_rounds','objective')
    return {'dna_version':DNA_VERSION,'organization_id':org.get('organization_id'),
            'dna_revision':org.get('dna_revision',1),
            'config':{**{key:copy.deepcopy(org.get('config',{}).get(key)) for key in config_keys},
                      **({'orchestration_backend':org['config']['orchestration_backend']} if 'orchestration_backend' in org.get('config',{}) else {})},
            'agents':[{key:copy.deepcopy(a[key]) for key in agent_fields if key in a} for a in org.get('agents',[])],
            'functional_subteams':copy.deepcopy(org.get('functional_subteams',[])),
            'provenance':copy.deepcopy(org.get('provenance',{})),
            **({key:copy.deepcopy(org[key]) for key in ('identity_scheme','identity_anchors') if key in org})}


def compute_dna_hash(org):
    return digest(dna_payload(org))


def stamp_dna(org,increment=False):
    if not org.get('organization_id'):
        return org
    if increment:
        org['dna_revision']=org.get('dna_revision',1)+1
        org['config']['dna_revision']=org['dna_revision']
    org['dna_hash']=compute_dna_hash(org)
    return org


def build_provenance(config,analysis,specs=None,provided=None):
    if provided is not None and not isinstance(provided,dict):
        raise ValueError('provenance debe ser objeto.')
    provided=provided or {}
    source={}
    # Whitelist metadata: API keys, arbitrary provider output and credentials never persist.
    for key in ('provider','model','generation_id','generation_method','request_id','source_kind','design_version','schema_version','review_status'):
        if key in provided: source[key]=_text(provided[key],'provenance.'+key,200)
    for key in ('payload_sha256',):
        if key in provided:
            if not isinstance(provided[key],str) or not re.fullmatch(r'[0-9a-f]{64}',provided[key]):
                raise ValueError('provenance.'+key+': SHA256 canónico requerido.')
            source[key]=provided[key]
    if 'request_hashes' in provided:
        hashes=provided['request_hashes']
        if not isinstance(hashes,list) or not 1<=len(hashes)<=MAX_AGENTS or any(not isinstance(x,str) or not re.fullmatch(r'[0-9a-f]{64}',x) for x in hashes):
            raise ValueError('provenance.request_hashes: lista acotada de SHA256 requerida.')
        source['request_hashes']=list(hashes)
    if 'request_count' in provided:
        if type(provided['request_count']) is not int or not 1<=provided['request_count']<=MAX_AGENTS:
            raise ValueError('provenance.request_count inválido.')
        source['request_count']=provided['request_count']
    source.setdefault('provider',config['provider']);source.setdefault('model',config['model'])
    source['generation_mode']='api_generated' if specs is not None else 'offline_template'
    source_kind = analysis.get('source_kind', config.get('source_kind', 'github_repository'))
    if (source_kind not in ('github_repository', 'website')
            or provided.get('source_kind', source_kind) != source_kind
            or config.get('source_kind', source_kind) != source_kind):
        raise ValueError('Tipo de fuente y procedencia no coinciden.')
    source['source_kind'] = source_kind
    if source_kind == 'website':
        if provided.get('repository_sha') is not None or (analysis.get('repository') or {}).get('sha') is not None:
            raise ValueError('Una fuente web no tiene SHA Git de repositorio.')
        ledger = website_provenance(analysis)
        for key, value in ledger.items():
            if key in provided and canonical_json(provided[key]) != canonical_json(value):
                raise ValueError('Procedencia web no coincide con la evidencia revisada.')
        source.update(ledger)
    else:
        source['repository_sha']=(analysis.get('repository') or {}).get('sha') or provided.get('repository_sha')
        sha=source['repository_sha']
        if sha is not None and (not isinstance(sha,str) or not re.fullmatch(r'[0-9a-fA-F]{40}|[0-9a-fA-F]{64}',sha)):
            raise ValueError('provenance.repository_sha: SHA Git completo requerido cuando está disponible.')
    source['analysis_sha256']=analysis.get('input_digest') or digest(analysis)
    source['coverage']=copy.deepcopy(analysis.get('coverage',{}))
    source['evidence_paths']=sorted(observed_paths(analysis))
    source['profile_specs_sha256']=digest(specs) if specs is not None else None
    source['evidence_verification']=('website_snapshots_observed_not_backend_or_capabilities_proven' if source_kind == 'website'
                                     else 'repository_paths_observed_not_capabilities_proven')
    source['fictional_personas']=True
    source['runtime_verified']=False
    return source


def validate_dna(org):
    errors=[]
    if not org.get('organization_id'):
        if any(key in org for key in ('dna_hash','dna_revision','identity_mode','provenance')) or org.get('config',{}).get('organization_id'):
            errors.append('organization_id ausente en una organización con metadatos DNA.')
        return errors
    try:
        organization_id=str(uuid.UUID(org['organization_id']))
        if org['organization_id']!=organization_id: errors.append('organization_id no es UUID canónico.')
        if org.get('identity_mode') not in ('new','revision','import_legacy'):
            errors.append('identity_mode DNA inválido.')
        revision=org.get('dna_revision')
        if type(revision) is not int or revision<1: errors.append('dna_revision inválida.')
        if org.get('config',{}).get('organization_id')!=organization_id:
            errors.append('organization_id de config no coincide con DNA.')
        if org.get('config',{}).get('dna_revision')!=revision:
            errors.append('dna_revision de config no coincide con DNA.')
        if org.get('dna_hash')!=compute_dna_hash(org):
            errors.append('dna_hash no coincide con el payload canónico; no exportar ADN alterado.')
        legacy=org.get('identity_mode')=='import_legacy' or org.get('identity_scheme')=='imported_legacy'
        anchors=org.get('identity_anchors',{})
        if anchors and not isinstance(anchors,dict): raise ValueError('identity_anchors debe ser objeto por slot.')
        for slot,anchor in anchors.items():
            if not slot.isdigit() or not 1<=int(slot)<=MAX_AGENTS or not isinstance(anchor,dict) or set(anchor)!={'id','name'}:
                raise ValueError('Ancla de identidad legacy inválida.')
            uuid.UUID(anchor['id'])
        for agent in org.get('agents',[]):
            if legacy and anchors:
                anchor=anchors.get(str(agent['slot']))
                if not anchor or anchor.get('id')!=agent['id'] or anchor.get('name')!=agent['name']:
                    errors.append('Identidad de agente no coincide con su ancla legacy preservada.')
            elif not legacy and agent['id']!=agent_id(organization_id,agent['slot']):
                errors.append('Identidad de agente no deriva de organization_id y slot.')
        for key in ('display_name','title','mission'):
            values=[_key(a[key]) for a in org.get('agents',[])]
            if len(values)!=len(set(values)): errors.append(key+' duplicado en DNA.')
        summaries=[_key(a['cv']['summary']) for a in org.get('agents',[])]
        if len(summaries)!=len(set(summaries)): errors.append('CV duplicado en DNA.')
        api_agents=[a for a in org.get('agents',[]) if a.get('profile_source')=='api_structured']
        careers=[_key(canonical_json([{'scope':x.get('scope'),'achievements':x.get('achievements')} for x in a['cv'].get('experience',[])])) for a in api_agents]
        if len(careers)!=len(set(careers)): errors.append('Trayectoria de CV duplicada en DNA.')
        skill_sets=[tuple(sorted(_key(s['name']) for s in a['skills'] if s.get('source')!='hierarchy_assignment')) for a in api_agents]
        if len(skill_sets)!=len(set(skill_sets)): errors.append('Conjunto de competencias duplicado en DNA.')
    except (KeyError,ValueError,TypeError,AttributeError) as exc:
        errors.append('DNA mal formado: '+str(exc))
    return errors
