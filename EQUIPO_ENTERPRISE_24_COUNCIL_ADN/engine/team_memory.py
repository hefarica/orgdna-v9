"""Team memory (P4): memoria Markdown de equipo que materializa los planos de memory_governance.

Port REA de agentscope-ai/agentscope@26ec620 (Apache-2.0): semantica de _middleware.py
(filesystem long-term memory, indice MEMORY.md acotado), reescrita para los planos de
engine/memory_governance.py. Vectores: middleware_filesystem_memory_test.py.

Que se porta (semantica del fuente, cuaderno docs/rea/agentscope_notebook.md segmento 4):
  * layout workspace-local con indice `MEMORY.md` creado VACIO solo si no existe
    (`_ensure_layout` nunca pisa una edicion previa);
  * indice acotado por presupuesto con recorte proporcional + backtrack de a 10
    caracteres, marca `<<<TRUNCATED>>>` y reminder con offset de linea y ruta;
  * texto de vacio cuando el indice no tiene contenido (o queda vacio tras truncar);
  * frontmatter tolerante: el fence de cierre puede estar al final del texto
    (`(?:\n|$)` load-bearing) y solo se leen campos escalares;
  * seleccion con filtro de nombres inexistentes, dedup preservando orden y
    presupuesto de 5 archivos; seleccion vacia => nada; sin archivos de topico el
    selector ni se invoca;
  * hint `Memory (saved {edad}): {ruta}:` con edad relativa today/yesterday/N days ago,
    partes unidas con `\n\n---\n\n`, cuerpo truncado por archivo;
  * recuperacion deshabilitable por configuracion (equivalente de retrieval_async=False).

Adaptaciones declaradas (fuente -> destino; la forma del destino gana):
  * tokens -> bytes UTF-8: context_compiler presupuesta en bytes (BYTES_PER_TOKEN=3);
    `memory_max_tokens=4000` del fuente se traduce como presupuesto en bytes del indice;
  * mtime -> `recorded_at`: la marca temporal del contrato MemoryRecord v1 sustituye al
    mtime del archivo (determinista y offline); la edad relativa se calcula contra `now`;
  * selector LLM -> solape de terminos offline (misma familia de seleccion que
    context_compiler: overlap / sqrt(terminos), sin red y sin modelo);
  * asyncio -> stdlib sincrono: `search` es sincrono y `retrieval_enabled=False` la apaga;
  * el indice MEMORY.md es un artefacto DERIVADO de los fragmentos gobernados (aqui no
    hay un LLM editandolo como upstream): se regenera tras cada append y nunca contiene
    contenido de fragmentos, solo el manifiesto `- [tipo] archivo (fecha): descripcion`.

Materializacion de los planos (NO reemplaza a engine/memory_governance.py):
  * cada alta pasa por `build_record` + `MemoryStore.accept` del gobernador: planos,
    tenant, permisos, TTL e integridad del contrato v1 se aplican antes de escribir disco;
  * la lectura y la busqueda delegan en `MemoryStore.read` / `MemoryStore.list_plane`:
    los caducados no se devuelven nunca y el aislamiento entre planos e inquilinos manda;
  * cada fragmento se materializa en `<root>/<tenant>/<member>/<plane>/<memory_id>.md`
    con frontmatter legible y el registro canonico embebido en una linea (el reload
    rehidrata el gobernador desde ese registro; el Markdown es proyeccion, el registro
    es la verdad);
  * el append es append-only: un archivo de fragmento se escribe una vez; re-apendar el
    mismo registro es idempotente y el mismo id con otro contenido lo rechaza el
    contrato (`record_exists`), nunca se sobreescribe en silencio.

Enganche con context_compiler: los items del tier `memory` se exponen via
`memory_context_items()` listos para `compile_context({'memory': items, ...})`; el
presupuesto del indice se clampa a `context_compiler.MAX_TEXT_BYTES` para que el item
siempre sea admitido por el compilador. Este modulo no modifica a context_compiler ni a
memory_governance: solo los usa.

Offline, stdlib puro, sin red, sin efectos al importar.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

try:  # importacion como paquete del motor
    from . import context_compiler
    from .memory_governance import (MemoryGovernanceError, MemoryStore, PLANES,
                                    PLANE_SCOPES, build_record, canonical, parse_instant,
                                    utc_now, validate_record)
except ImportError:  # raiz de la suite en sys.path
    import context_compiler
    from memory_governance import (MemoryGovernanceError, MemoryStore, PLANES,
                                   PLANE_SCOPES, build_record, canonical, parse_instant,
                                   utc_now, validate_record)

INDEX_FILENAME = 'MEMORY.md'
INDEX_HEADER = '## MEMORY.md'
EMPTY_INDEX_TEXT = ('Your MEMORY.md is currently empty. When you save new memories, they '
                    'will appear here.')
TRUNCATED_MARK = '<<<TRUNCATED>>>'

#: Fuente: memory_max_tokens=4000 (~12k bytes a 3 bytes/token). El default se recorta a
#: 6000 para que el snapshot quepa como UN item del tier memory de context_compiler
#: (tope MAX_TEXT_BYTES=8000) dejando aire para el reminder de truncamiento.
INDEX_BUDGET_BYTES = 6_000
#: Fuente: retrieval_max_tokens_per_md=2000 tokens -> 6000 bytes por archivo del hint.
SEARCH_BYTES_PER_FILE = 6_000
#: Fuente: retrieval_max_files=200 archivos considerados por la recuperacion.
SEARCH_MAX_FILES = 200
#: Fuente: presupuesto del selector (los duplicados no lo consumen).
SELECT_MAX_FILES = 5
#: Aire reservado para el reminder de truncamiento dentro del item del tier memory.
REMINDER_RESERVE_BYTES = 400
#: Campos escalares del frontmatter que el hint re-serializa (los del fuente: name,
#: description, type); la gobernanza restante viaja en el registro embebido.
HINT_FIELDS = ('name', 'description', 'type')

_MEMBER_RE = re.compile(r'^[a-z0-9][a-z0-9._-]{1,63}$')
#: Cierre al final del string permitido (`(?:\n|$)` load-bearing del fuente) y campos
#: escalares solamente: nested se ignora a proposito.
_FRONTMATTER_RE = re.compile(r'^\s*---\s*\n(?P<body>.*?)\n---\s*(?:\n|$)', re.DOTALL)
_FIELD_RE = re.compile(r'^(\w+)\s*:\s*(.+)$', re.MULTILINE)
_TOKEN_RE = re.compile(r'[0-9a-z_]{3,}')
_RECORD_LINE_RE = re.compile(r'<!-- team_memory:record (.*) -->')


def _write_text(path, text):
    """Escribe UTF-8 con newlines LF estables (independiente del SO)."""
    with open(path, 'w', encoding='utf-8', newline='\n') as handle:
        handle.write(text)


def _read_text(path):
    with open(path, 'r', encoding='utf-8') as handle:
        return handle.read()


def _parse_frontmatter_fields(text):
    """Campos escalares del frontmatter, o None si el texto no trae fence valido.

    Vector portado (FrontmatterParseTest): el fence de cierre puede terminar al final
    del string y los campos se conservan igual con o sin body detras.
    """
    match = _FRONTMATTER_RE.match(text)
    if match is None:
        return None
    return dict(_FIELD_RE.findall(match.group('body')))


def _format_frontmatter(fields):
    """Serializa campos escalares en orden de insercion: `---\nk: v\n...\n---\n`."""
    lines = ['---']
    lines.extend('%s: %s' % (key, value) for key, value in fields.items())
    lines.append('---')
    return '\n'.join(lines) + '\n'


def _truncate_if_needed(text, budget_bytes):
    """Recorte proporcional con backtrack de a 10 caracteres (formula del fuente).

    Fuente `_truncate_if_needed`: budget <= 0 -> ''; si cabe -> intacto; si no, indice
    proporcional y backtrack en pasos de 10 CHARS hasta caber. Adaptado de tokens a
    bytes UTF-8 (la unidad de presupuesto del destino).
    """
    if budget_bytes is None:
        budget_bytes = INDEX_BUDGET_BYTES
    if budget_bytes <= 0:
        return ''
    total = len(text.encode('utf-8'))
    if total <= budget_bytes:
        return text
    index = int((budget_bytes / total) * len(text))
    while index > 0 and len(text[:index].encode('utf-8')) > budget_bytes:
        index = max(0, index - 10)
    return text[:index]


def _byte_len(text):
    return len(text.encode('utf-8'))


def _terms(text):
    return frozenset(_TOKEN_RE.findall(text.casefold()))


def _relevance(query_terms, text):
    """Solape de terminos (misma familia de seleccion que context_compiler, offline)."""
    terms = _terms(text)
    if not terms or not query_terms:
        return 0.0
    overlap = len(query_terms & terms)
    if not overlap:
        return 0.0
    return overlap / (len(terms) ** 0.5)


def _as_utc(moment):
    if isinstance(moment, datetime):
        return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)
    return parse_instant(moment)


def _age_label(recorded_at, now):
    """Edad relativa del fuente: today / yesterday / '{N} days ago'."""
    if not recorded_at:
        return None
    moment = _as_utc(now) if now is not None else datetime.now(timezone.utc)
    delta_seconds = (moment - _as_utc(recorded_at)).total_seconds()
    days = max(0, int(delta_seconds // 86_400))
    if days == 0:
        return 'today'
    if days == 1:
        return 'yesterday'
    return '%d days ago' % days


def _clean_description(text, limit=120):
    flat = ' '.join(str(text or '').split())
    return flat[:limit]


class TeamMemoryStore:
    """Store Markdown append-only por organizacion (tenant) y miembro, gobernado por I4.

    Materializa el contrato de `engine/memory_governance.py` (planos, permisos, TTL,
    integridad) sobre un directorio workspace-local con la semantica de memoria de
    agentscope@26ec620: fragmentos `.md` inmutables + indice `MEMORY.md` acotado.
    """

    def __init__(self, root, registry, tenant_id, member, *, index_budget_bytes=None,
                 retrieval_enabled=True, now=None):
        if not isinstance(root, (str, Path)):
            raise MemoryGovernanceError('invalid_request', 'root debe ser una ruta del workspace.')
        if not isinstance(member, str) or not _MEMBER_RE.match(member):
            raise MemoryGovernanceError('invalid_request', (
                'member debe cumplir el patron de identificador (2..64 de [a-z0-9._-]).'))
        self._governor = MemoryStore(registry, tenant_id)  # unknown_tenant si no esta registrado
        self.root = Path(root)
        self.member = member
        self.index_budget_bytes = index_budget_bytes if index_budget_bytes is not None \
            else INDEX_BUDGET_BYTES
        self.retrieval_enabled = retrieval_enabled
        self.base_dir = self.root / self.tenant_id / member
        self._ignored_on_reload = []
        self._ensure_layout()
        self._reload(now=now)

    # ------------------------------------------------------------------ gobierno

    @property
    def tenant_id(self):
        return self._governor.tenant_id

    @property
    def governor(self):
        """Acceso al MemoryStore gobernador (promociones, politica, sweep, close_task)."""
        return self._governor

    @property
    def base_path(self):
        return self.base_dir

    @property
    def index_path(self):
        return self.base_dir / INDEX_FILENAME

    @property
    def ignored_on_reload(self):
        """Archivos .md sin registro embebido encontrado en el reload (fail-honest)."""
        return tuple(self._ignored_on_reload)

    def record_path(self, plane, memory_id):
        """Ruta logica del gobernador: `tenants/<t>/memories/<plane>/<id>`."""
        return self._governor.record_path(memory_id, plane)

    def fragment_file(self, plane, memory_id):
        """Ruta fisica del fragmento materializado, dentro de tenant/miembro."""
        logical = self.record_path(plane, memory_id)
        expected_suffix = 'memories/%s/%s' % (plane, memory_id)
        if not logical.endswith(expected_suffix):
            raise MemoryGovernanceError('invalid_request', (
                'La ruta del gobernador (%s) no termina en %s: el acoplamiento con los '
                'planos cambio y este port debe revisarse.' % (logical, expected_suffix)))
        return self.base_dir / plane / ('%s.md' % memory_id)

    # ------------------------------------------------------------------ layout

    def _ensure_layout(self):
        """Crea el directorio y el indice VACIO solo si no existe (nunca pisa)."""
        self.base_dir.mkdir(parents=True, exist_ok=True)
        if not self.index_path.exists():
            _write_text(self.index_path, '')

    def _reload(self, *, now=None):
        """Rehidrata el gobernador desde los registros embebidos en el disco."""
        self._ignored_on_reload = []
        for plane in PLANES:
            plane_dir = self.base_dir / plane
            if not plane_dir.is_dir():
                continue
            for path in sorted(plane_dir.glob('*.md')):
                text = _read_text(path)
                match = _RECORD_LINE_RE.search(text)
                if match is None:
                    self._ignored_on_reload.append(str(path))
                    continue
                try:
                    record = validate_record(json.loads(match.group(1)))
                except ValueError:
                    self._ignored_on_reload.append(str(path))
                    continue
                self._governor.accept(record, now=now)

    # ------------------------------------------------------------------ escritura

    def append(self, memory_id, plane, content, *, role_ref, description=None,
               scope=None, confidence=0.8, ttl_seconds=None, source_kind='manual_entry',
               origin_ref=None, author=None, task_id=None, project_id=None, now=None):
        """Alta gobernada + materializacion Markdown + regeneracion del indice.

        El registro pasa primero por el contrato v1 (build_record + accept del
        gobernador); solo si lo admite se escribe el archivo. Re-apantar un registro
        identico es idempotente; el mismo id con otro contenido lo rechaza el contrato.
        """
        if plane not in PLANES:
            raise MemoryGovernanceError('invalid_record', 'plane debe pertenecer a %s.'
                                        % (PLANES,))
        moment = now if now is not None else utc_now()
        if scope is None:
            scope = {'scope_kind': PLANE_SCOPES[plane]}
            if task_id is not None:
                scope['task_id'] = task_id
            if project_id is not None:
                scope['project_id'] = project_id
        else:
            scope = dict(scope)
        origin = {'source_kind': source_kind,
                  'ref': origin_ref or 'team-memory://%s/%s' % (self.tenant_id, self.member),
                  'captured_at': moment}
        if author is not None:
            origin['author'] = author
        record = build_record(
            memory_id, plane, tenant_id=self.tenant_id, origin=origin, content=content,
            recorded_at=moment, scope=scope, confidence=confidence,
            ttl_seconds=ttl_seconds,
            read_permissions=[{'role_ref': role_ref, 'tenant_id': self.tenant_id,
                               'plane': plane}])
        stored = self._governor.accept(record, now=now)
        self._materialize(stored, description=description)
        self._write_index(role_ref=role_ref, now=now)
        return stored

    def _materialize(self, record, *, description=None):
        """Escribe el fragmento .md una sola vez (append-only e idempotente)."""
        plane = record['plane']
        memory_id = record['memory_id']
        path = self.fragment_file(plane, memory_id)
        if description is None:
            description = _clean_description(record['content_ref']['value'])
        fields = {'name': '%s.md' % memory_id,
                  'description': _clean_description(description),
                  'type': plane,
                  'tenant': self.tenant_id,
                  'member': self.member,
                  'recorded_at': record['recorded_at']}
        body = record['content_ref']['value'].rstrip('\n')
        text = '%s\n%s\n\n<!-- team_memory:record %s -->\n' % (
            _format_frontmatter(fields), body, canonical(record))
        if path.exists():
            existing = _read_text(path)
            existing_match = _RECORD_LINE_RE.search(existing)
            if existing_match is not None and existing_match.group(1) == canonical(record):
                return path  # idempotente: no se reescribe
            raise MemoryGovernanceError('record_exists', (
                'El fragmento %s ya esta materializado con otro contenido en %s; el store '
                'es append-only.' % (memory_id, path)))
        path.parent.mkdir(parents=True, exist_ok=True)
        _write_text(path, text)
        return path

    def _live_fragments(self, role_ref, *, now=None):
        """Fragmentos vivos y permitidos al rol, orden recorded_at DESC (mtime-desc)."""
        rows = []
        for plane in PLANES:
            for view in self._governor.list_plane(plane, role_ref=role_ref, now=now):
                rows.append(self._governor.read(view['memory_id'], plane=plane,
                                                role_ref=role_ref, now=now))
        rows.sort(key=lambda r: (-_as_utc(r['recorded_at']).timestamp(), r['memory_id']))
        return rows

    def _index_lines(self, role_ref, *, now=None):
        """Manifiesto del fuente: `- [tipo] archivo (fecha)[: descripcion]`."""
        lines = []
        for record in self._live_fragments(role_ref, now=now)[:SEARCH_MAX_FILES]:
            date = record['recorded_at'][:10] if record.get('recorded_at') else 'unknown'
            line = '- [%s] %s (%s)' % (record['plane'], '%s.md' % record['memory_id'], date)
            stored = self._frontmatter_of(record)
            description = stored.get('description')
            if description:
                line += ': %s' % description
            lines.append(line)
        return lines

    def _frontmatter_of(self, record):
        path = self.fragment_file(record['plane'], record['memory_id'])
        if not path.exists():
            return {}
        parsed = _parse_frontmatter_fields(_read_text(path))
        return parsed or {}

    def _write_index(self, *, role_ref, now=None):
        lines = self._index_lines(role_ref, now=now)
        _write_text(self.index_path, '\n'.join(lines) + ('\n' if lines else ''))

    # ------------------------------------------------------------------ lectura

    def read(self, memory_id, *, plane, role_ref, now=None):
        """Lectura gobernada + verificacion de que el disco materializado coincide."""
        record = self._governor.read(memory_id, plane=plane, role_ref=role_ref, now=now)
        path = self.fragment_file(plane, memory_id)
        if not path.exists():
            raise MemoryGovernanceError('record_not_found', (
                'El fragmento %s esta gobernado pero no materializado en %s.'
                % (memory_id, path)))
        text = _read_text(path)
        match = _RECORD_LINE_RE.search(text)
        if match is None or json.loads(match.group(1)) != record:
            raise MemoryGovernanceError('invalid_record', (
                'El archivo materializado de %s difiere del registro gobernado; el '
                'registro manda y el archivo exige regeneracion explicita.' % memory_id))
        return {'record': record, 'markdown': text, 'path': str(path)}

    # ------------------------------------------------------------------ indice

    def index_snapshot(self, *, budget_bytes=None, role_ref=None, now=None):
        """Snapshot del indice acotado por presupuesto de bytes.

        Con `role_ref` se deriva de los fragmentos vivos permitidos al rol (sin
        escribir); sin rol se lee el archivo MEMORY.md materializado (fidelidad al
        fuente: el archivo es lo que se inyecta). `content` es el contenido acotado
        (siempre <= presupuesto; el texto de vacio y el reminder son encuadre fijo del
        sistema, no contenido del indice, igual que en el fuente).
        """
        budget = budget_bytes if budget_bytes is not None else self.index_budget_bytes
        if role_ref is not None:
            original = '\n'.join(self._index_lines(role_ref, now=now))
        else:
            original = _read_text(self.index_path) if self.index_path.exists() else ''
        content = _truncate_if_needed(original, budget)
        truncated = len(content) != len(original)
        total_lines = len(original.splitlines())
        remain_lines = len(content.splitlines())
        omitted = total_lines - remain_lines if truncated else 0
        reminder = None
        if truncated:
            reminder = (
                '\n%s\n<system-reminder>The remaining %d lines have been omitted due to '
                'context length limits. Use the `Read` tool with offset %d to access the '
                "rest of '%s'.</system-reminder>"
                % (TRUNCATED_MARK, omitted, remain_lines, self.index_path))
        visible = content if content else EMPTY_INDEX_TEXT
        text = visible + (reminder or '')
        return {'path': str(self.index_path), 'content': content,
                'content_bytes': _byte_len(content), 'budget_bytes': budget,
                'truncated': truncated, 'remain_lines': remain_lines,
                'omitted_lines': omitted, 'reminder': reminder, 'text': text,
                'placeholder_leak': '{memory_dir}' in text}

    def system_prompt_section(self, *, budget_bytes=None, role_ref=None, now=None):
        """Seccion `## MEMORY.md` con la ruta real: lo que se inyecta al system prompt."""
        snapshot = self.index_snapshot(budget_bytes=budget_bytes, role_ref=role_ref, now=now)
        return '%s (%s)\n%s' % (INDEX_HEADER, snapshot['path'], snapshot['text'])

    def memory_context_items(self, *, role_ref, budget_bytes=None, now=None):
        """Items listos para el tier `memory` de `compile_context`.

        El presupuesto efectivo se clampa a `context_compiler.MAX_TEXT_BYTES` menos la
        reserva del reminder: el item resultante siempre es admitido por el compilador
        y el contenido del indice sigue acotado por su propio presupuesto.
        """
        ceiling = context_compiler.MAX_TEXT_BYTES - REMINDER_RESERVE_BYTES
        budget = budget_bytes if budget_bytes is not None else self.index_budget_bytes
        budget = min(budget, ceiling)
        snapshot = self.index_snapshot(budget_bytes=budget, role_ref=role_ref, now=now)
        return [{'id': 'memory://%s/%s/%s' % (self.tenant_id, self.member, INDEX_FILENAME),
                 'kind': 'index', 'text': snapshot['text']}]

    # ------------------------------------------------------------------ busqueda

    def _format_part(self, record, now):
        """Parte del hint: header con edad + frontmatter name/description/type + body."""
        path = self.fragment_file(record['plane'], record['memory_id'])
        stored = self._frontmatter_of(record)
        fields = {}
        for key in HINT_FIELDS:
            if key == 'name':
                fields['name'] = '%s.md' % record['memory_id']
            elif key == 'description':
                fields['description'] = stored.get(
                    'description', _clean_description(record['content_ref']['value']))
            elif key == 'type':
                fields['type'] = record['plane']
        body = _truncate_if_needed(record['content_ref']['value'], SEARCH_BYTES_PER_FILE)
        body = body.rstrip('\n') + '\n'
        age = _age_label(record.get('recorded_at'), now)
        header = 'Memory (saved %s): %s:' % (age, path) if age else 'Memory: %s:' % path
        return '%s\n\n%s\n%s' % (header, _format_frontmatter(fields), body)

    @staticmethod
    def _join_parts(parts):
        return '\n\n---\n\n'.join(parts)

    def select_files(self, filenames, *, role_ref, now=None):
        """Seleccion por nombre: filtro de alucinados, dedup y presupuesto de 5.

        Vector portado: solo nombres reales, cada memoria una vez, orden del selector
        preservado; seleccion vacia => None.
        """
        if not self.retrieval_enabled:
            return None
        valid = {}
        for record in self._live_fragments(role_ref, now=now)[:SEARCH_MAX_FILES]:
            valid['%s.md' % record['memory_id']] = record
        chosen = [name for name in dict.fromkeys(filenames) if name in valid]
        if not chosen:
            return None
        parts = [self._format_part(valid[name], now) for name in chosen[:SELECT_MAX_FILES]]
        return self._join_parts(parts) if parts else None

    def search(self, query, *, role_ref, limit=SELECT_MAX_FILES, now=None):
        """Recuperacion por solape de terminos (selector offline del destino).

        Sin archivos de topico no se selecciona nada (None, el selector ni se invoca);
        seleccion vacia => None. No hay duplicados por construccion (un archivo por
        fragmento) y los caducados jamas participan (los excluye list_plane).
        """
        if not self.retrieval_enabled:
            return None
        candidates = self._live_fragments(role_ref, now=now)[:SEARCH_MAX_FILES]
        if not candidates:
            return None
        query_terms = _terms(query)
        scored = []
        for record in candidates:
            text = ' '.join([record['memory_id'], record['plane'],
                             record['content_ref']['value']])
            score = _relevance(query_terms, text)
            if score > 0.0:
                scored.append((score, record))
        if not scored:
            return None
        scored.sort(key=lambda pair: (-pair[0], pair[1]['memory_id']))
        top = limit if limit is not None else SELECT_MAX_FILES
        parts = [self._format_part(record, now) for _, record in
                 scored[:min(top, SELECT_MAX_FILES)]]
        return self._join_parts(parts) if parts else None


__all__ = ['TeamMemoryStore', 'INDEX_FILENAME', 'INDEX_HEADER', 'EMPTY_INDEX_TEXT',
           'TRUNCATED_MARK', 'INDEX_BUDGET_BYTES', 'SEARCH_BYTES_PER_FILE',
           'SEARCH_MAX_FILES', 'SELECT_MAX_FILES', 'REMINDER_RESERVE_BYTES', 'HINT_FIELDS']
