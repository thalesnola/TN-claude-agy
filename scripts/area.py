"""Area isolada do argon: perfil proprio do agy e copia do trabalho fora do disco do usuario.

Medido em 01/11/2026 (agy 1.4.4): o agy le fora do seu cwd, e a config do usuario libera
MCPs de caso sem perguntar. O que segurou nos testes:
  - perfil separado (USERPROFILE/HOME apontando para outra pasta): o login vem do cofre de
    credenciais do sistema, mas plugins, MCPs, AGENTS.md e permissoes do usuario ficam de fora;
  - regras deny: deny vence ask e allow, e deny numa pasta bloqueia tudo abaixo. Entao a area
    de trabalho fica numa pasta propria e tudo o mais e negado por complemento: em cada nivel
    do caminho ate a area, nega-se toda entrada irma.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import stat
import string
import subprocess
import tempfile
import time
import uuid
from pathlib import Path

PERFIL_PADRAO = Path.home() / ".claude" / "argon" / "perfil-agy"
AREA_PADRAO = Path("C:/argon-ws") if os.name == "nt" else Path("~/argon-ws")

IGNORAR = {".git", "node_modules", ".venv", "venv", "__pycache__", ".mypy_cache", ".pytest_cache",
           ".tox", "dist", "build", ".next", "graphify-out"}
MAX_ARQUIVOS = 20_000
MAX_BYTES = 200 * 1024 * 1024

# Ferramentas de arquivo cujas regras aceitam caminho. Comando e MCP: negados por inteiro.
FERRAMENTAS_DE_ARQUIVO = ("read_file", "write_file")
NEGAR_SEMPRE = ["command(*)", "mcp(*)"]


class AreaErro(Exception):
    pass


def _barra(p: Path | str) -> str:
    return str(p).replace("\\", "/")


def regras_de_complemento(area: Path) -> list[str]:
    """Nega toda entrada que nao esteja no caminho ate `area`, em cada nivel."""
    area = area.resolve()
    negar: list[str] = []
    partes = area.parts  # ('C:\\', 'argon-ws') ou ('/', 'Users', 'Shared', 'argon-ws')
    atual = Path(partes[0])
    for proxima in partes[1:]:
        try:
            for e in os.scandir(atual):
                if e.name.casefold() != proxima.casefold():
                    negar.append(_barra(Path(atual) / e.name))
        except OSError as ex:
            raise AreaErro(f"nao consegui listar {atual}: {ex}") from ex
        atual = atual / proxima
    if os.name == "nt":
        unidade = area.drive.rstrip(":").upper()
        for d in string.ascii_uppercase:
            if d != unidade and os.path.exists(f"{d}:\\"):
                negar.append(f"{d}:/")
    regras = [f"{f}({p})" for p in negar for f in FERRAMENTAS_DE_ARQUIVO]
    return regras + NEGAR_SEMPRE


def preparar_perfil(perfil: Path, area: Path) -> dict:
    """Grava as regras do perfil e devolve o ambiente para rodar o agy dentro dele."""
    cli = perfil / ".gemini" / "antigravity-cli"
    cfg = perfil / ".gemini" / "config"
    cli.mkdir(parents=True, exist_ok=True)
    cfg.mkdir(parents=True, exist_ok=True)
    _gravar_atomico(cli / "settings.json",
                    json.dumps({"permissions": {"deny": regras_de_complemento(area)}}, indent=1))
    conf = cfg / "config.json"
    if not conf.exists():
        # Telemetria desligada: o plugin quebrava todas as ferramentas (22/09/2026).
        _gravar_atomico(conf, json.dumps({"plugins": {"googlecloudtools.datacloud_telemetry":
                                                      {"enabled": False}}}))
    env = dict(os.environ)
    env["USERPROFILE"] = str(perfil)
    env["HOME"] = str(perfil)
    return env


def _gravar_atomico(p: Path, texto: str) -> None:
    fd, tmp = tempfile.mkstemp(dir=p.parent, prefix=p.name, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(texto)
    os.replace(tmp, p)


def _git(origem: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(origem), *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL)


def listar_origem(origem: Path) -> list[Path]:
    """Arquivos a copiar: num repo git, versionados + novos nao ignorados; senao, a arvore."""
    r = _git(origem, "ls-files", "-z", "-co", "--exclude-standard")
    if r.returncode == 0:
        rel = [Path(p) for p in r.stdout.split("\0") if p]
    else:
        rel = []
        for pasta, dirs, nomes in os.walk(origem):
            dirs[:] = [d for d in dirs if d not in IGNORAR]
            base = Path(pasta).relative_to(origem)
            rel += [base / n for n in nomes]
    # Atalho (symlink, juncao) em qualquer nivel levaria a copia para fora da origem -- ate
    # uma pasta de caso. So entra o que, resolvido, continua dentro da origem.
    raiz = origem.resolve()
    rel = [p for p in rel if not (set(p.parts) & IGNORAR) and (origem / p).is_file()
           and (origem / p).resolve().is_relative_to(raiz)]
    if len(rel) > MAX_ARQUIVOS:
        raise AreaErro(f"{len(rel)} arquivos (limite {MAX_ARQUIVOS}); aponte --dir para uma subpasta")
    return rel


def copiar_para_area(origem: Path, area: Path) -> tuple[Path, list[Path]]:
    area.mkdir(parents=True, exist_ok=True)
    destino = area / uuid.uuid4().hex[:12]
    rel = listar_origem(origem)
    total = 0
    for p in rel:
        total += (origem / p).stat().st_size
        if total > MAX_BYTES:
            shutil.rmtree(destino, ignore_errors=True)
            raise AreaErro(f"mais de {MAX_BYTES // 2**20} MB; aponte --dir para uma subpasta")
        alvo = destino / p
        alvo.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(origem / p, alvo)
    destino.mkdir(parents=True, exist_ok=True)
    return destino, rel


def fotografar(copia: Path) -> None:
    """Repo git descartavel na copia, para o delegar devolver um patch."""
    for args in (["init", "-q"], ["add", "-A"],
                 ["-c", "user.name=argon", "-c", "user.email=argon@local", "-c", "core.autocrlf=false",
                  "commit", "-q", "--allow-empty", "-m", "antes"]):
        r = subprocess.run(["git", *args], cwd=copia, capture_output=True, text=True,
                           stdin=subprocess.DEVNULL)
        if r.returncode != 0:
            raise AreaErro(f"git {args[0]} na copia falhou: {r.stderr.strip()[:200]}")


def extrair_patch(copia: Path) -> str:
    subprocess.run(["git", "add", "-A"], cwd=copia, capture_output=True, stdin=subprocess.DEVNULL)
    r = subprocess.run(["git", "diff", "--cached", "--binary"], cwd=copia, capture_output=True,
                       text=True, encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL)
    return r.stdout


def _tirar_somente_leitura(func, caminho, _exc):
    # Objetos do .git sao somente-leitura no Windows: sem isto o rmtree falha calado.
    os.chmod(caminho, stat.S_IWRITE)
    func(caminho)


# Medido em 08/11/2026 (agy 1.4.x): o agy abre um `agy.exe --bg-updater` que herda o cwd (a copia)
# e pode sobreviver ao pai enquanto baixa atualizacao. Diretorio que e cwd de processo vivo nao se
# apaga no Windows (WinError 32): o rmtree esvazia a pasta e falha so na raiz. Nao se mata o
# updater (cortar a troca do agy.exe no meio poderia corromper o binario): espera-se, e a sobra
# fica para a varredura da proxima chamada.
ESPERAS = (0.25, 0.5, 1, 2, 4, 8)
IDADE_ORFA = 10 * 60


def _apagar(p: Path) -> None:
    shutil.rmtree(p, onexc=_tirar_somente_leitura)


def descartar(copia: Path, esperas: tuple[float, ...] | None = None) -> str | None:
    """Apaga a copia com retentativa. Nunca levanta: devolve o aviso se a pasta ficou."""
    esperas = ESPERAS if esperas is None else esperas
    for espera in (*esperas, None):
        if not copia.exists():
            return None
        try:
            _apagar(copia)
            return None
        except OSError as e:
            if espera is None:
                return (f"copia {copia} nao foi apagada ({e.__class__.__name__}: {e}); "
                        "a proxima chamada tenta de novo")
            time.sleep(espera)
    return None


def varrer_orfas(area: Path, idade: float = IDADE_ORFA) -> list[str]:
    """Apaga copias de chamadas anteriores que ficaram presas. Devolve as que ainda resistem."""
    if not area.is_dir():
        return []
    presas = []
    agora = time.time()
    for p in area.iterdir():
        # So o que a ponte cria (12 hex); a idade poupa a copia de uma chamada em curso.
        if not (p.is_dir() and re.fullmatch(r"[0-9a-f]{12}", p.name)):
            continue
        try:
            if agora - p.stat().st_mtime < idade:
                continue
            _apagar(p)
        except OSError:
            presas.append(str(p))
    return presas
