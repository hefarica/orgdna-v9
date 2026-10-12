"""Versioned local project storage. Explicit saves only; no secrets or deletion API."""
from __future__ import annotations
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import uuid

try:
    from .coordination import local_file_lock
except ImportError:
    from coordination import local_file_lock

MAX_PROJECT_BYTES = 16 * 1024 * 1024
VERSION_RE = re.compile(r'^\d{8}T\d{12}Z-[a-f0-9]{8}$')
FORBIDDEN_FIELDS = {'credentials','api_key','api_keys','pending_consent','csrf','cookie','password','access_token','refresh_token','client_secret','private_key','authorization','bearer_token'}

class ProjectStoreError(ValueError):
    pass


def _identifier(value):
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, TypeError, AttributeError):
        raise ProjectStoreError('Identificador de proyecto no válido.') from None


def _safe_name(value):
    if not isinstance(value,str) or not value.strip() or len(value)>120 or any(ord(c)<32 for c in value):
        raise ProjectStoreError('El nombre debe tener entre 1 y 120 caracteres legibles.')
    return value.strip()


def _reject_secret_fields(value):
    if isinstance(value,dict):
        for key,item in value.items():
            normalized = re.sub(r'(?<!^)(?=[A-Z])', '_', str(key)).lower().replace('-', '_')
            if normalized in FORBIDDEN_FIELDS or re.sub(r'[^a-z0-9]', '', str(key).lower()) in {re.sub(r'[^a-z0-9]', '', k) for k in FORBIDDEN_FIELDS}:
                raise ProjectStoreError('El proyecto contiene un campo de credencial o consentimiento que no se puede guardar.')
            _reject_secret_fields(item)
    elif isinstance(value,list):
        for item in value:_reject_secret_fields(item)


class ProjectStore:
    def __init__(self,root):
        self.root=Path(root).expanduser().resolve()

    def _inside(self,path):
        path=Path(path)
        if not path.resolve().is_relative_to(self.root):
            raise ProjectStoreError('La ruta del proyecto sale del almacén local autorizado.')
        current=path
        while current!=self.root:
            if current.is_symlink():raise ProjectStoreError('No se admiten enlaces simbólicos dentro del almacén de proyectos.')
            if current.parent==current:raise ProjectStoreError('Ruta de proyecto no válida.')
            current=current.parent
        return path

    def _read(self,path):
        self._inside(path)
        if not path.is_file() or path.stat().st_size>MAX_PROJECT_BYTES:
            raise ProjectStoreError('El archivo de proyecto no existe o supera el límite seguro.')
        try:
            value=json.loads(path.read_text('utf-8'))
        except (OSError,ValueError):
            raise ProjectStoreError('No se pudo leer esta versión del proyecto.') from None
        if not isinstance(value,dict):raise ProjectStoreError('Formato de proyecto incorrecto.')
        return value

    def list_projects(self):
        if not self.root.exists():return []
        result=[]
        for directory in self.root.iterdir():
            if not directory.is_dir():continue
            try:
                project_id=_identifier(directory.name)
                current=self._read(directory/'current.json')
                if current.get('project_id')!=project_id:continue
                versions=self.list_versions(project_id)
                result.append(dict(current,versions=versions,version_count=len(versions)))
            except ProjectStoreError:
                continue
        return sorted(result,key=lambda row:row.get('saved_at',''),reverse=True)

    def list_versions(self,project_id):
        directory=self._inside(self.root/_identifier(project_id)/'versions')
        if not directory.exists():return []
        return sorted([p.stem for p in directory.glob('*.json') if VERSION_RE.fullmatch(p.stem)],reverse=True)

    def save(self,snapshot,name,project_id=None,expected_version=None):
        with local_file_lock(self.root / '.projects.lock'):
            return self._save(snapshot,name,project_id,expected_version)

    def _save(self,snapshot,name,project_id=None,expected_version=None):
        if not isinstance(snapshot,dict):raise ProjectStoreError('El proyecto debe ser un objeto.')
        _reject_secret_fields(snapshot)
        name=_safe_name(name)
        project_id=_identifier(project_id) if project_id else str(uuid.uuid4())
        self.root.mkdir(parents=True,exist_ok=True,mode=0o700)
        directory=self.root/project_id
        versions=self._inside(directory/'versions')
        if expected_version is not None:
            current=self._read(directory/'current.json')
            if current.get('version_id')!=expected_version:
                raise ProjectStoreError('Versión de proyecto obsoleta: otra sesión guardó cambios. Recarga o guarda como proyecto nuevo.')
        versions.mkdir(parents=True,exist_ok=True)
        stamp=datetime.now(timezone.utc)
        version_id=stamp.strftime('%Y%m%dT%H%M%S%fZ')+'-'+secrets.token_hex(4)
        saved_at=stamp.isoformat().replace('+00:00','Z')
        metadata={'project_id':project_id,'name':name,'version_id':version_id,'saved_at':saved_at,
                  'agent_count':len((snapshot.get('organization') or {}).get('agents',[]))}
        organization = snapshot.get('organization') or {}
        if organization.get('organization_id') is not None:
            metadata['organization_id'] = _identifier(organization['organization_id'])
            revision = organization.get('dna_revision')
            dna_hash = organization.get('dna_hash')
            if type(revision) is not int or revision < 1 or not isinstance(dna_hash, str) or not re.fullmatch(r'[a-f0-9]{64}', dna_hash):
                raise ProjectStoreError('La identidad ADN debe incluir revisión positiva y hash SHA-256.')
            metadata['dna_revision'] = revision
            metadata['dna_hash'] = dna_hash
        envelope={'format':'orgdna-local-project','version':1,'metadata':metadata,'snapshot':snapshot}
        payload=json.dumps(envelope,ensure_ascii=False,indent=2,allow_nan=False).encode('utf-8')
        if len(payload)>MAX_PROJECT_BYTES:raise ProjectStoreError('El proyecto supera 16 MB; reduce evidencias embebidas.')
        # A version is never overwritten. Only the pointer to the latest version
        # is atomically replaced after the complete new version is durable.
        with (versions/(version_id+'.json')).open('xb') as output:
            output.write(payload);output.flush();os.fsync(output.fileno())
        digest=hashlib.sha256(payload).hexdigest()
        with (versions/(version_id+'.sha256')).open('x',encoding='ascii') as output:
            output.write(digest);output.flush();os.fsync(output.fileno())
        pointer=dict(metadata,sha256=digest)
        temp=directory/('current.'+secrets.token_hex(4)+'.tmp')
        with temp.open('x',encoding='utf-8') as output:
            json.dump(pointer,output,ensure_ascii=False,indent=2);output.flush();os.fsync(output.fileno())
        os.replace(temp,directory/'current.json')
        return pointer

    def load(self,project_id,version_id=None):
        project_id=_identifier(project_id)
        directory=self.root/project_id
        if version_id is None:
            version_id=self._read(directory/'current.json').get('version_id')
        if not isinstance(version_id,str) or not VERSION_RE.fullmatch(version_id):
            raise ProjectStoreError('Identificador de versión no válido.')
        version_path=self._inside(directory/'versions'/(version_id+'.json'))
        hash_path=self._inside(directory/'versions'/(version_id+'.sha256'))
        if not hash_path.is_file() or hash_path.stat().st_size>100:
            raise ProjectStoreError('Falta la comprobación de integridad de esta versión.')
        if not version_path.is_file() or version_path.stat().st_size>MAX_PROJECT_BYTES:
            raise ProjectStoreError('Versión inexistente o demasiado grande.')
        expected_hash=hash_path.read_text('ascii').strip()
        if not re.fullmatch(r'[a-f0-9]{64}',expected_hash) or hashlib.sha256(version_path.read_bytes()).hexdigest()!=expected_hash:
            raise ProjectStoreError('La versión no coincide con su hash de integridad; conserva el archivo y revisa la copia anterior.')
        current=self._read(directory/'current.json')
        if current.get('version_id')==version_id and current.get('sha256')!=expected_hash:
            raise ProjectStoreError('El puntero actual no coincide con el hash de su versión.')
        envelope=self._read(version_path)
        if envelope.get('format')!='orgdna-local-project' or envelope.get('version')!=1:
            raise ProjectStoreError('Versión de formato de proyecto no compatible.')
        metadata=envelope.get('metadata',{})
        if metadata.get('project_id')!=project_id or metadata.get('version_id')!=version_id:
            raise ProjectStoreError('La identidad de la versión no coincide con su archivo.')
        snapshot=envelope.get('snapshot')
        if not isinstance(snapshot,dict):raise ProjectStoreError('Falta el estado del proyecto.')
        _reject_secret_fields(snapshot)
        organization = snapshot.get('organization') or {}
        if 'organization_id' in metadata:
            if any(metadata.get(key) != organization.get(key) for key in ('organization_id', 'dna_revision', 'dna_hash')):
                raise ProjectStoreError('La identidad ADN del proyecto no coincide con su versión guardada.')
            _identifier(metadata['organization_id'])
        return envelope
