"""Porta de sigilo do argon: nada de caso sobe para o Google.

O agy le tudo dentro do seu cwd, entao a guarda checa:
  1. Pastas de caso -- o cwd nao pode estar DENTRO de uma pasta de caso nem CONTER uma
     (cwd = C:\\ liberaria C:\\Casos inteira); arquivos citados idem; atalhos (symlink,
     juncao) no primeiro nivel do cwd que apontem para caso tambem bloqueiam.
  2. Auditor da vault -- o motor de `auditar.py` (CPF, CNJ, telefone, placa, IMEI...)
     roda sobre o prompt e sobre os arquivos citados explicitamente.
Tudo fecha em caso de duvida: caminho UNC, arquivo binario ou grande, auditor ausente ou
quebrado, configuracao invalida.

Configuracao em ~/.claude/argon.toml (ver argon.exemplo.toml).
"""
from __future__ import annotations

import codecs
import importlib.util
import os
import re
import sys
import tomllib
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

CONFIG_PADRAO = Path.home() / ".claude" / "argon.toml"

# Casos e a unica pasta proibida por padrao. Acervo do ACERVO entra pela config.
PASTAS_CASO_PADRAO = [r"C:\Casos", "~/Casos"]

AUDITORES_CANDIDATOS = [
    r"C:\ACERVO\Segundo_Cerebro\.sistema\scripts\auditar.py",
    "~/ACERVO/Segundo_Cerebro/.sistema/scripts/auditar.py",
]

# Formato que o auditor de texto nao enxerga: bloqueia em vez de deixar passar cego.
EXTENSOES_BINARIAS = {
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".odt", ".ods", ".rtf",
    ".zip", ".7z", ".rar", ".gz", ".tar", ".e01", ".ufdr", ".db", ".sqlite", ".sqlite3",
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tif", ".tiff", ".heic", ".webp",
    ".mp3", ".mp4", ".m4a", ".wav", ".ogg", ".opus", ".mov", ".avi",
}
TAMANHO_MAX_ARQUIVO = 2 * 1024 * 1024


@dataclass
class Config:
    pastas_caso: list[Path] = field(default_factory=list)
    auditor: Path | None = None


@dataclass
class Bloqueio:
    motivo: str
    detalhes: list[str]


def _tirar_prefixo_longo(s: str) -> str:
    # \\?\C:\x e \\?\UNC\srv\x sao o mesmo caminho que C:\x e \\srv\x.
    if s.startswith("\\\\?\\UNC\\"):
        return "\\\\" + s[8:]
    if s.startswith("\\\\?\\"):
        return s[4:]
    return s


def _normalizar(p: str | Path, base: Path | None = None, expandir: bool = False) -> Path:
    # expandvars so na config: num caminho real, uma pasta chamada %X% seria trocada e a
    # guarda avaliaria um caminho enquanto o agy le outro.
    s = os.path.expandvars(str(p)) if expandir else str(p)
    alvo = Path(_tirar_prefixo_longo(s)).expanduser()
    if base is not None and not alvo.is_absolute():
        alvo = base / alvo
    return Path(_tirar_prefixo_longo(str(alvo.resolve(strict=False))))


def _chave(p: Path) -> str:
    # Caixa e forma Unicode: C:\casos == C:\Casos; no macOS o APFS guarda acento em NFD.
    s = unicodedata.normalize("NFC", os.path.normcase(str(p))).casefold()
    return s.replace("\\", "/").rstrip("/")


def _dentro(filho: Path, pai: Path) -> bool:
    f, p = _chave(filho), _chave(pai)
    return f == p or f.startswith(p + "/")


def _e_unc(p: Path) -> bool:
    return str(p).startswith("\\\\") or str(p).startswith("//")


def carregar_config(caminho: Path | None = None) -> Config:
    caminho = caminho or Path(os.environ.get("ARGON_CONFIG", CONFIG_PADRAO))
    dados = {}
    if caminho.is_file():
        with open(caminho, "rb") as f:
            dados = tomllib.load(f)
    sig = dados.get("sigilo", {})
    pastas = PASTAS_CASO_PADRAO + list(sig.get("pastas_caso", []))
    auditor = sig.get("auditor")
    if not auditor:
        auditor = next((a for a in AUDITORES_CANDIDATOS
                        if _normalizar(a, expandir=True).is_file()), None)
    return Config(
        pastas_caso=[_normalizar(p, expandir=True) for p in pastas],
        auditor=_normalizar(auditor, expandir=True) if auditor else None,
    )


def resolver_arquivos(arquivos: list[str | Path], cwd: Path) -> list[Path]:
    # O agy le relativo ao seu cwd, nao ao da ponte: auditar o mesmo arquivo que ele vera.
    return [_normalizar(a, base=cwd) for a in arquivos]


def _atalhos_do_cwd(cwd: Path) -> list[tuple[Path, Path]]:
    pares = []
    try:
        entradas = list(os.scandir(cwd))
    except OSError:
        return pares
    for e in entradas:
        p = Path(e.path)
        try:
            atalho = e.is_symlink() or (hasattr(p, "is_junction") and p.is_junction())
        except OSError:
            atalho = False
        if atalho:
            pares.append((p, _normalizar(p)))
    return pares


def checar_pastas(cwd: Path, arquivos: list[Path], cfg: Config) -> Bloqueio | None:
    violacoes = []
    for alvo in [cwd, *arquivos]:
        if _e_unc(alvo):
            violacoes.append(f"{alvo}: caminho de rede/UNC nao e aceito")
            continue
        for pasta in cfg.pastas_caso:
            if _dentro(alvo, pasta):
                violacoes.append(f"{alvo} esta sob a pasta de caso {pasta}")
            # So pasta que existe vaza; sem isso ~/Casos inexistente travaria o home inteiro.
            elif (alvo == cwd or alvo.is_dir()) and pasta.exists() and _dentro(pasta, alvo):
                violacoes.append(f"{alvo} contem a pasta de caso {pasta} (o agy leria tudo abaixo)")
    for atalho, destino in _atalhos_do_cwd(cwd):
        for pasta in cfg.pastas_caso:
            if _dentro(destino, pasta) or _dentro(pasta, destino):
                violacoes.append(f"atalho {atalho.name} no cwd aponta para {destino} (caso)")
    if violacoes:
        return Bloqueio("pasta de caso", violacoes)
    return None


def _carregar_auditor(caminho: Path):
    spec = importlib.util.spec_from_file_location("argon_auditor", caminho)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    if not hasattr(mod, "REGRAS") or not hasattr(mod, "eh_ruido"):
        raise AttributeError("auditor sem REGRAS/eh_ruido")
    return mod


def auditar_texto(texto: str, origem: str, auditor) -> list[str]:
    achados = []
    for r in auditor.REGRAS:
        if r.get("so_nome"):
            continue
        for linha in texto.splitlines():
            for m in re.finditer(r["rx"], linha):
                if not auditor.eh_ruido(m.group(0), linha, m.start()):
                    # O valor achado nao e repetido: so a regra e a origem.
                    achados.append(f"{origem}: {r['nome']}")
    return achados


def ler_texto(p: Path) -> str:
    """Decodifica para auditoria; levanta ValueError quando nao da para auditar."""
    if p.suffix.lower() in EXTENSOES_BINARIAS:
        raise ValueError(f"formato {p.suffix} nao e auditavel")
    if p.stat().st_size > TAMANHO_MAX_ARQUIVO:
        raise ValueError(f"maior que {TAMANHO_MAX_ARQUIVO // 1024} KB")
    dados = p.read_bytes()
    if dados.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return dados.decode("utf-16")
    if dados.startswith(codecs.BOM_UTF8):
        return dados[3:].decode("utf-8", errors="replace")
    if b"\x00" in dados:
        # UTF-16 sem BOM: NUL em toda posicao impar (LE) ou par (BE).
        if dados[1::2].count(0) > len(dados) // 4:
            return dados.decode("utf-16-le", errors="replace")
        if dados[0::2].count(0) > len(dados) // 4:
            return dados.decode("utf-16-be", errors="replace")
        raise ValueError("conteudo binario")
    return dados.decode("utf-8", errors="replace")


def checar_conteudo(prompt: str, arquivos: list[Path], cfg: Config) -> Bloqueio | None:
    if cfg.auditor is None or not cfg.auditor.is_file():
        # Sem auditor nao ha como provar que o prompt esta limpo: fecha.
        return Bloqueio("auditor ausente",
                        ["defina sigilo.auditor em argon.toml ou instale a vault do ACERVO"])
    try:
        auditor = _carregar_auditor(cfg.auditor)
    except Exception as e:  # noqa: BLE001 -- qualquer falha do auditor fecha a porta
        return Bloqueio("auditor com erro", [f"{cfg.auditor}: {type(e).__name__}: {e}"])
    achados = auditar_texto(prompt, "prompt", auditor)
    for p in arquivos:
        if p.is_dir():
            achados.append(f"{p.name}: diretorio como arquivo citado (use --dir)")
            continue
        try:
            achados += auditar_texto(ler_texto(p), p.name, auditor)
        except (OSError, ValueError) as e:
            achados.append(f"{p.name}: nao auditavel ({getattr(e, 'strerror', None) or e})")
    if achados:
        return Bloqueio("identificador de caso ou arquivo nao auditavel", sorted(set(achados)))
    return None


def checar(prompt: str, cwd: str | Path, arquivos: list[str | Path],
           cfg: Config | None = None) -> Bloqueio | None:
    try:
        cfg = cfg or carregar_config()
    except (OSError, tomllib.TOMLDecodeError) as e:
        return Bloqueio("configuracao invalida", [f"{type(e).__name__}: {e}"])
    cwd_n = _normalizar(cwd)
    arqs = resolver_arquivos(arquivos, cwd_n)
    return checar_pastas(cwd_n, arqs, cfg) or checar_conteudo(prompt, arqs, cfg)


if __name__ == "__main__":
    # Uso manual: guarda.py <cwd> [arquivo...]  (prompt pela entrada padrao)
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    b = checar(sys.stdin.read(), sys.argv[1] if len(sys.argv) > 1 else os.getcwd(), sys.argv[2:])
    if b:
        print(f"[ARGON] BLOQUEADO ({b.motivo}):")
        for d in b.detalhes:
            print(f"  {d}")
        sys.exit(20)
    print("[ARGON] Liberado.")
