"""Best-effort text masking. Never executes SQL, shell commands, or SSH."""
from __future__ import annotations

from dataclasses import dataclass
import ipaddress
import re
import shlex


IDENT = r'(?:`[^`\n]+`|"[^"\n]+"|\$\{[\w:]+\}|\$\w+|[A-Za-z_][\w$-]*)'
PATH = rf'{IDENT}(?:\s*\.\s*{IDENT}){{0,2}}'
TABLE_CONTEXT = re.compile(
    rf'\b(?:FROM|JOIN|INTO|INSERT\s+OVERWRITE|UPDATE|(?:CREATE\s+(?:OR\s+REPLACE\s+)?(?:EXTERNAL\s+)?|'
    rf'ALTER\s+|DROP\s+|TRUNCATE\s+|DESCRIBE\s+|DESC\s+|SHOW\s+CREATE\s+)'
    rf'(?:TABLE|VIEW)|TRUNCATE|DESCRIBE|DESC)\s+'
    rf'(?:(?:IF\s+(?:NOT\s+)?EXISTS|OVERWRITE\s+TABLE|TABLE)\s+)?(?P<name>{PATH})', re.I,
)
DB_CONTEXT = re.compile(
    rf'\b(?:USE|(?:CREATE|ALTER|DROP)\s+(?:DATABASE|SCHEMA))\s+'
    rf'(?:IF\s+(?:NOT\s+)?EXISTS\s+)?(?P<name>{IDENT})', re.I,
)
ASSIGNMENT = re.compile(
    r'''(?m)(?<![\w])(?P<key>[A-Za-z_]\w*)=(?P<value>"[^"\n]*"|'[^'\n]*'|[^\s;]+)'''
)


@dataclass(frozen=True)
class MaskingResult:
    text: str
    mappings: list[dict[str, str]]


def mask_text(raw: str, *, tables: str = '', databases: str = '',
              extra: str = '', mask_ip: bool = True, mask_ssh: bool = True,
              mask_paths: bool = True,
              mappings: list[dict[str, str]] | None = None) -> MaskingResult:
    """Discover literal names, then replace in one pass to avoid alias cascades.

    Additional values are newline-separated literals. Matching is case sensitive;
    repeated literals are also masked in comments and strings. This is a heuristic,
    not a complete shell/SQL parser or a guarantee of removing every secret.
    """
    names: dict[str, str] = {}

    def add(value: str, kind: str) -> None:
        value = value.strip().strip('`"\'')
        if value and not any(c in value for c in '$\n\r'):
            names.setdefault(value, kind)

    # Explicit values take precedence over automatic classification.
    for values, kind in ((databases, 'DB'), (tables, 'TABLE'), (extra, 'MASK')):
        for value in values.splitlines():
            add(value, kind)

    path_spans: list[tuple[int, int, str]] = []
    if mask_paths:
        # Keep URL/JDBC components and the shell interpreter outside path masking.
        excluded = [m.span() for m in re.finditer(
            r'''[A-Za-z][\w+.-]*://[^\s'"<>]+|(?m:^\#![^\n]*)''', raw,
        )]
        path_pattern = re.compile(
            r'''(?P<quote>['"])(?P<quoted>(?:/|~/|\./|\.\./)[^\n]*?)(?P=quote)|'''
            r'''(?<![\w/.$~\\])(?P<plain>(?:/|~/|\./|\.\./)[^\s'"`<>|;&()]+)'''
        )
        for match in path_pattern.finditer(raw):
            group = 'quoted' if match['quoted'] is not None else 'plain'
            start, end = match.span(group)
            value = match[group]
            if any(start < b and end > a for a, b in excluded):
                continue
            if value in {'/', './', '../', '~/'} or '$' in value:
                continue
            add(value, 'PATH')
            path_spans.append((start, end, value))

    for match in ASSIGNMENT.finditer(raw):
        key = match['key'].upper()
        parts = key.split('_')
        kind = None
        if any(p in {'DB', 'DATABASE', 'SCHEMA'} for p in parts):
            kind = 'DB'
        elif any(p in {'TABLE', 'TBL'} for p in parts):
            kind = 'TABLE'
        elif mask_ssh and any(p in {'SSH', 'REMOTE'} for p in parts):
            if any(p in {'HOST', 'SERVER'} for p in parts):
                kind = 'HOST'
            elif any(p in {'USER', 'USERNAME'} for p in parts):
                kind = 'USER'
        value = match['value'].strip('"\'')
        if kind and re.fullmatch(r'[\w.-]+', value):
            if kind == 'HOST':
                try:
                    ipaddress.ip_address(value)
                except ValueError:
                    pass
                else:
                    if not mask_ip:
                        continue
                    kind = 'IP'
            add(value, kind)

    for match in DB_CONTEXT.finditer(raw):
        add(match['name'], 'DB')
    for match in re.finditer(r'jdbc:(?:hive2|mysql|postgresql)://[^/\s\'";]+/([\w-]+)', raw, re.I):
        add(match[1], 'DB')
    for match in TABLE_CONTEXT.finditer(raw):
        parts = re.findall(IDENT, match['name'])
        for part in parts[:-1]:
            add(part, 'DB')
        add(parts[-1], 'TABLE')

    # Validate candidate IPs instead of masking arbitrary dotted numbers.
    if mask_ip:
        candidates = re.finditer(
            r'(?<![\w.:])(?:\d{1,3}\.){3}\d{1,3}(?![\w.])|'
            r'(?<![\w:])(?:[0-9a-fA-F]{0,4}:){2,}[0-9a-fA-F:.]*(?:%[\w]+)?', raw,
        )
        for match in candidates:
            try:
                ipaddress.ip_address(match[0])
            except ValueError:
                continue
            # IP classification wins over a host variable classification.
            names[match[0]] = 'IP'

    def endpoint(value: str) -> None:
        value = value.removeprefix('ssh://')
        if '@' in value:
            user, value = value.rsplit('@', 1)
            add(user, 'USER')
        try:
            ipaddress.ip_address(value)
        except ValueError:
            host = value.split(']', 1)[0][1:] if value.startswith('[') else value.split(':', 1)[0]
        else:
            host = value
        try:
            ipaddress.ip_address(host)
        except ValueError:
            add(host, 'HOST')
        else:
            if mask_ip:
                add(host, 'IP')

    if mask_ssh:
        # user@host also covers scp endpoints and ProxyJump arguments.
        for match in re.finditer(r'[\w.-]+@(?:\[[0-9a-fA-F:]+\]|[\w.-]+)', raw):
            endpoint(match[0])
        for line in raw.replace('\\\n', ' ').splitlines():
            try:
                tokens = shlex.split(line, comments=True)
            except ValueError:
                continue
            for i, token in enumerate(tokens):
                if token != 'ssh':
                    continue
                args = iter(tokens[i + 1:])
                for arg in args:
                    if arg == '--':
                        endpoint(next(args, ''))
                        break
                    if arg.startswith('-'):
                        option = arg[:2]
                        if option in {'-p', '-i', '-l', '-o', '-J', '-F', '-L', '-R', '-D', '-W', '-b', '-c', '-E', '-e', '-m', '-S', '-w', '-B', '-O', '-Q'}:
                            value = arg[2:] or next(args, '')
                            if option == '-l':
                                add(value, 'USER')
                            elif option == '-J':
                                for jump in value.split(','):
                                    endpoint(jump)
                            elif option == '-o':
                                setting = re.split(r'[=\s]+', value, maxsplit=1)
                                if len(setting) == 2:
                                    if setting[0].lower() in {'hostname', 'proxyjump'}:
                                        for host in setting[1].split(','):
                                            endpoint(host)
                                    elif setting[0].lower() == 'user':
                                        add(setting[1], 'USER')
                        continue
                    endpoint(arg)
                    break

    if not names:
        return MaskingResult(raw, [])
    aliases = {row['Asli']: row['Masking'] for row in mappings or []}
    counts: dict[str, int] = {}
    for value, kind in names.items():
        if value in aliases:
            continue
        counts[kind] = counts.get(kind, 0) + 1
        alias = f'{kind}_{counts[kind]:03d}'
        while alias in raw or alias in aliases.values() or alias in aliases:
            counts[kind] += 1
            alias = f'{kind}_{counts[kind]:03d}'
        aliases[value] = alias
    # Literal boundaries keep e.g. orders_archive unchanged when masking orders.
    pattern = re.compile(r'(?<![\w])(?:' + '|'.join(
        re.escape(v) for v in sorted(names, key=len, reverse=True)
    ) + r')(?![\w])')
    used: set[str] = set()

    def replace(match: re.Match) -> str:
        used.add(match[0])
        return aliases[match[0]]

    # Replace whole path occurrences first, so a table name within a path cannot
    # expose the remaining directories. Do not replace path substrings in URLs.
    path_values = {value for _, _, value in path_spans}

    def replace_non_path(match: re.Match) -> str:
        if match[0] in path_values:
            return match[0]
        return replace(match)

    chunks: list[str] = []
    cursor = 0
    for start, end, value in path_spans:
        chunks.append(pattern.sub(replace_non_path, raw[cursor:start]))
        chunks.append(aliases[value])
        used.add(value)
        cursor = end
    chunks.append(pattern.sub(replace_non_path, raw[cursor:]))
    result = ''.join(chunks)
    return MaskingResult(result, [
        {'Jenis': names[v], 'Asli': v, 'Masking': aliases[v]}
        for v in names if v in used
    ])


def restore_text(raw: str, mappings: list[dict[str, str]]) -> MaskingResult:
    """Restore aliases in one pass, including lowercase and underscore suffixes.

    As with masking, replacement also applies to comments and string literals.
    Unknown aliases are left unchanged; no SQL or shell code is executed.
    """
    aliases = {row['Masking'].lower(): row['Asli'] for row in mappings}
    if not aliases:
        return MaskingResult(raw, [])
    pattern = re.compile(r'(?<![\w$])(?:' + '|'.join(
        re.escape(alias) for alias in sorted(aliases, key=len, reverse=True)
    ) + r')(?=_|(?![\w$]))', re.I)
    used: set[str] = set()

    def replace(match: re.Match) -> str:
        alias = match[0].lower()
        used.add(alias)
        return aliases[alias]

    text = pattern.sub(replace, raw)
    return MaskingResult(text, [row for row in mappings if row['Masking'].lower() in used])
