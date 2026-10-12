"""Cota unica del tamano de equipo, compartida por todas las capas.

Ninguna otra capa redefine MAX_AGENTS. Antes era un literal duplicado en doce
modulos, con tres formatos de mensaje distintos y al menos un sitio donde la
cota viajaba como ARGUMENTO (`autonomy.py`: `_integer(n,'agent_count',1,32)`)
mientras el mensaje se componia en otro punto (`autonomy.py:20`). Por eso un
barrido de literales no la encontraba y el limite se desincronizaba entre capas:
subir el gate de `core` dejaba el de `autonomy` en 32 y N=40 seguia fallando.

Sin imports y sin efectos secundarios: solo el numero.
"""

MAX_AGENTS = 40
