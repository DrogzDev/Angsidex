"""
Respaldo para modelos (p. ej. GLM) que a veces escriben la llamada a una herramienta como TEXTO en el contenido:

    <tool_call>propose_options<arg_key>options</arg_key><arg_value>[{...}]</arg_value></tool_call>

en vez de usar el canal estructurado `tool_calls`. El filtro retiene ese texto para que el visitante nunca lo vea y lo convierte
en una llamada normal, que se valida igual que cualquier otra (mismos esquemas, mismos límites).
"""
import json
import re
from typing import Any

OPEN = '<tool_call>'
CLOSE = '</tool_call>'
_BLOCK = re.compile(r'<tool_call>(.*?)(?:</tool_call>|$)', re.DOTALL)
_ARG = re.compile(r'<arg_key>(.*?)</arg_key>\s*<arg_value>(.*?)(?:</arg_value>|$)', re.DOTALL)
_NAME = re.compile(r'^\s*([A-Za-z_][A-Za-z0-9_]*)')


def parse_calls(raw: str) -> list[dict[str, str]]:
    """Convierte bloques <tool_call> en [{'id', 'name', 'arguments'(JSON)}]. Ignora lo que no se pueda interpretar."""
    calls: list[dict[str, str]] = []
    for i, m in enumerate(_BLOCK.finditer(raw)):
        body = m.group(1)
        name = _NAME.match(body)
        if not name:
            continue
        args: dict[str, Any] = {}
        rest = body[name.end():].strip()
        found = _ARG.findall(rest)
        for key, value in found:
            value = value.strip()
            try:
                args[key.strip()] = json.loads(value)
            except ValueError:
                args[key.strip()] = value
        if not found and rest.startswith('{'):
            # Variante: <tool_call>nombre {"arg": 1}</tool_call>
            try:
                parsed = json.loads(rest)
                if isinstance(parsed, dict):
                    args = parsed
            except ValueError:
                pass
        calls.append({'id': f'text_call_{i}', 'name': name.group(1), 'arguments': json.dumps(args, ensure_ascii=False)})
    return calls


class TextToolCallFilter:
    """Filtro incremental: deja pasar el texto normal y retiene todo lo que empiece en <tool_call>."""

    def __init__(self) -> None:
        self._pending = ''
        self._tool = ''
        self._in_tool = False

    def feed(self, text: str) -> str:
        """Devuelve el texto seguro para mostrar (puede ser vacío)."""
        if self._in_tool:
            self._tool += text
            return ''
        self._pending += text
        idx = self._pending.find(OPEN)
        if idx >= 0:
            visible = self._pending[:idx]
            self._tool = self._pending[idx:]
            self._pending = ''
            self._in_tool = True
            return visible
        # Se retiene el sufijo que podría ser el comienzo de "<tool_call>" cortado entre dos fragmentos.
        hold = 0
        for k in range(min(len(OPEN) - 1, len(self._pending)), 0, -1):
            if self._pending.endswith(OPEN[:k]):
                hold = k
                break
        visible = self._pending[: len(self._pending) - hold]
        self._pending = self._pending[len(self._pending) - hold:]
        return visible

    def finish(self) -> tuple[str, list[dict[str, str]]]:
        """Fin del stream: (texto pendiente que sí es visible, llamadas a herramientas halladas en el texto)."""
        tail = '' if self._in_tool else self._pending
        self._pending = ''
        return tail, parse_calls(self._tool) if self._tool else []
