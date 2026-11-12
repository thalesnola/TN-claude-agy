"""Ponte do argon: unico ponto que executa o agy.

Recebe um papel (contraprova, pesquisa, explorar, delegar, caderno), passa pela guarda de
sigilo, copia a pasta de origem para uma area isolada, roda o agy num perfil proprio (sem os
plugins, MCPs e permissoes do usuario) com tudo fora da copia negado, tenta os modelos da
cascata do papel ate um responder e imprime ao chamador um JSON curto com o resultado.
No `delegar`, as edicoes voltam como patch; a origem nunca e tocada.

Uso:
  ponte.py --papel contraprova --prompt "..." [--dir D] [--arquivo F ...] [--modelo M]
  echo "prompt" | ponte.py --papel explorar --dir D
  ponte.py --papel contraprova --schema schemas/revisao.json --prompt "..."
  ponte.py --modelos           # catalogo do agy cruzado com as cascatas

Codigos de saida (o agy sai 0 ate quando falha; estes sao da ponte):
  0 ok · 1 erro do agy · 2 uso · 3 vazio · 12 timeout · 13 telemetria
  14 nenhum modelo disponivel · 15 negado · 16 prompt longo demais · 17 area de trabalho
  20 bloqueado pela guarda
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import area  # noqa: E402
import guarda  # noqa: E402

# Medido em 01/11/2026 (agy 1.4.4): os 12 modelos que responderam; gpt-oss-120b fora.
CASCATAS = {
    "contraprova": ["gemini-4-argon-high", "gemini-4-argon-medium", "gemini-3.8-flash-high"],
    "pesquisa": ["gemini-4-argon-high", "gemini-4-argon-medium", "gemini-3.8-flash-high"],
    "explorar": ["gemini-4-argon-medium", "gemini-3.8-flash-high", "gemini-3.8-flash-medium"],
    "delegar": ["claude-opus-5-5-high", "claude-opus-5-5-medium", "claude-sonnet-5-5-medium",
                "claude-sonnet-5-5-high", "gemini-4-argon-high"],
    "caderno": ["gemini-4-argon-medium", "gemini-4-argon-low", "gemini-3.8-flash-high"],
}
# Contraprova so vale de outra familia: Claude nunca entra, nem por --modelo.
SO_GEMINI = {"contraprova"}

MODO_PADRAO = {"delegar": "accept-edits"}  # demais papeis: plan (so leitura)

# Linha de comando do Windows aceita ~32 mil caracteres; folga para os demais argumentos.
LIMITE_PROMPT = 25_000
# Alem do --print-timeout do agy, a ponte espera esta folga antes de matar a arvore.
FOLGA_TIMEOUT = 30

DIR_ESTADO = Path(os.environ.get("ARGON_ESTADO", Path.home() / ".claude" / "argon"))
AREA = Path(os.environ.get("ARGON_AREA", area.AREA_PADRAO))
CACHE_MODELOS = DIR_ESTADO / "modelos.json"
TTL_CACHE = 24 * 3600

RX_MODELO = re.compile(r"^[\w.-]+$")

COD = {"ok": 0, "erro": 1, "vazio": 3, "timeout": 12, "telemetria": 13, "sem-modelo": 14,
       "modelo-ausente": 14, "negado": 15, "longo": 16, "area": 17, "bloqueado": 20}

# Falhas em que vale tentar o proximo modelo. Telemetria nao: quebra todos igual.
PULA_PARA_PROXIMO = {"negado", "modelo-ausente", "vazio", "timeout", "erro"}
# Com escrita ligada, so repete o que certamente nao tocou em arquivo: um timeout ou erro
# pode ter deixado edicao pela metade, e o modelo seguinte aplicaria por cima.
PULA_COM_ESCRITA = {"negado", "modelo-ausente"}


def achar_agy() -> list[str]:
    env = os.environ.get("AGY_BIN")
    if env:
        # Um .py permite os testes trocarem o binario por um agy falso.
        return [sys.executable, env] if env.endswith(".py") else [env]
    nome = "agy.exe" if os.name == "nt" else "agy"
    p = Path.home() / ".gemini" / "bin" / nome
    if p.is_file():
        return [str(p)]
    raise FileNotFoundError(f"agy nao encontrado em {p}; defina AGY_BIN")


def listar_modelos(agy: list[str], forcar: bool = False) -> list[str]:
    if not forcar and CACHE_MODELOS.is_file():
        try:
            dados = json.loads(CACHE_MODELOS.read_text(encoding="utf-8"))
            if time.time() - dados.get("quando", 0) < TTL_CACHE and dados.get("agy") == agy:
                return dados["modelos"]
        except (OSError, ValueError, KeyError):
            pass  # cache corrompido: refaz
    try:
        r = subprocess.run([*agy, "models"], capture_output=True, text=True, encoding="utf-8",
                           errors="replace", stdin=subprocess.DEVNULL, timeout=120)
    except (OSError, subprocess.TimeoutExpired):
        return []
    modelos = [l.split("\t")[0].strip() for l in r.stdout.splitlines()
               if "\t" in l and not l.startswith("Fetching")]
    if modelos:
        CACHE_MODELOS.parent.mkdir(parents=True, exist_ok=True)
        area._gravar_atomico(CACHE_MODELOS, json.dumps({"quando": time.time(), "agy": agy,
                                                        "modelos": modelos}))
    return modelos


def montar_cascata(papel: str, modelo: str | None, disponiveis: list[str]) -> list[str]:
    ordem = ([modelo] if modelo else []) + [m for m in CASCATAS[papel] if m != modelo]
    if papel in SO_GEMINI:
        ordem = [m for m in ordem if m.startswith("gemini-")]
    # Catalogo vazio (agy models falhou): tenta a cascata mesmo assim, o agy dira.
    return [m for m in ordem if m in disponiveis] if disponiveis else ordem


def ler_json_do_agy(stdout: str) -> tuple[str, dict | None]:
    """Separa o texto solto (avisos como `jetski: ...`) do objeto JSON final do agy."""
    i = stdout.find('{"conversation_id"')
    if i < 0:
        return stdout, None
    try:
        return stdout[:i], json.loads(stdout[i:])
    except ValueError:
        return stdout, None


def classificar(texto: str, stderr: str = "", dados: dict | None = None) -> str:
    s = texto.strip()
    resposta = (dados or {}).get("response", "").strip() if dados else ""
    if s.startswith("jetski: no output produced") and not resposta:
        return "negado"
    if dados is not None:
        return "ok" if resposta else "vazio"
    # Sem JSON: erro de plataforma so conta no comeco de uma saida curta (ou no stderr com
    # stdout vazio); uma resposta valida que cite essas frases nao pode virar falha.
    cabeca = s[:300] if len(s) < 1000 else ""
    for t in (cabeca, stderr if not s else ""):
        if "datacloud_telemetry" in t or ("Cannot find module" in t and "telemetry" in t):
            return "telemetria"
        if re.search(r"model .* is not recognized|unknown model", t, re.I):
            return "modelo-ausente"
    return "ok" if s else "vazio"


def _matar_arvore(proc: subprocess.Popen) -> None:
    # subprocess.kill mata so o filho; um neto segurando o pipe trava o communicate.
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                           capture_output=True, timeout=30)
        else:
            os.killpg(proc.pid, signal.SIGKILL)
    except (OSError, subprocess.TimeoutExpired):
        proc.kill()


def chamar(agy: list[str], prompt: str, modelo: str, modo: str, cwd: Path, timeout: int,
           env: dict | None = None, schema: Path | None = None) -> dict:
    cmd = [*agy, "-p", prompt, "--model", modelo, "--mode", modo, "--print-timeout", f"{timeout}s",
           "--output-format", "json"]
    if schema:
        cmd += ["--json-schema", str(schema)]
    extra = ({"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt"
             else {"start_new_session": True})
    t0 = time.monotonic()
    # stdin desacoplado: sem isso o agy -p pode travar sem console no Windows.
    proc = subprocess.Popen(cmd, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            stdin=subprocess.DEVNULL, text=True, encoding="utf-8",
                            errors="replace", **extra)
    try:
        out, err = proc.communicate(timeout=timeout + FOLGA_TIMEOUT)
        estado = None
    except subprocess.TimeoutExpired:
        _matar_arvore(proc)
        try:
            out, err = proc.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            out, err = "", ""
        estado = "timeout"
    out, err = out or "", err or ""
    texto, dados = ler_json_do_agy(out)
    if estado is None:
        estado = classificar(texto, err, dados)
        if estado == "ok" and proc.returncode != 0:
            estado = "erro"
    return {"estado": estado, "segundos": time.monotonic() - t0, "texto": texto, "stderr": err,
            "dados": dados or {}}


def gravar_log(papel: str, modelo: str, prompt: str, r: dict, patch: str | None = None) -> Path:
    seguro = re.sub(r"[^\w.-]", "_", modelo)
    p = DIR_ESTADO / "logs" / f"{datetime.now():%Y%m%d-%H%M%S-%f}-{os.getpid()}-{papel}-{seguro}.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    corpo = r["dados"].get("response") or r["texto"]
    p.write_text(f"# {papel} · {modelo}\n\n## Prompt\n\n{prompt}\n\n## Resposta\n\n{corpo}\n"
                 + (f"\n## Saida solta\n\n{r['texto']}\n" if r["dados"] and r["texto"].strip() else "")
                 + (f"\n## stderr\n\n{r['stderr']}\n" if r["stderr"].strip() else ""), encoding="utf-8")
    if patch:
        p.with_suffix(".patch").write_text(patch, encoding="utf-8")
    return p


def registrar_uso(reg: dict) -> None:
    DIR_ESTADO.mkdir(parents=True, exist_ok=True)
    with open(DIR_ESTADO / "uso.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(reg, ensure_ascii=False) + "\n")


def auditar_copia(copia: Path, rel: list[Path], cfg: guarda.Config) -> list[str]:
    """Aviso, nao bloqueio (o usuario afrouxou a porta): arquivos da copia com achado."""
    try:
        aud = guarda._carregar_auditor(cfg.auditor)
    except Exception:  # noqa: BLE001 -- a guarda ja exigiu o auditor; aqui so o aviso falha
        return ["auditor indisponivel para a varredura da copia"]
    com_achado = []
    for p in rel:
        try:
            if guarda.auditar_texto(guarda.ler_texto(copia / p), p.name, aud):
                com_achado.append(str(p))
        except (OSError, ValueError):
            continue
    return com_achado


NOME_DIFF = "ARGON_DIFF.patch"


def coletar_diff(origem: Path, ref: str) -> str:
    """Diff da origem contra `ref` (versionados) mais a lista dos arquivos novos."""
    r = area._git(origem, "diff", ref, "--")
    if r.returncode != 0:
        raise area.AreaErro(f"git diff {ref} falhou: {r.stderr.strip()[:200]}")
    novos = area._git(origem, "ls-files", "--others", "--exclude-standard").stdout.split()
    return r.stdout + ("".join(f"\n# arquivo novo, nao versionado: {n}" for n in novos) if novos else "")


def executar(papel: str, prompt: str, cwd: Path, arquivos: list[str], modelo: str | None,
             modo: str | None, timeout: int, cfg: guarda.Config | None = None,
             schema: Path | None = None, diff_ref: str | None = None) -> tuple[int, dict]:
    if len(prompt) > LIMITE_PROMPT:
        return COD["longo"], {"status": "longo", "detalhe":
                              f"prompt com {len(prompt)} caracteres (limite {LIMITE_PROMPT}); "
                              "ponha o material em arquivo dentro de --dir e cite o caminho"}
    try:
        cfg = cfg or guarda.carregar_config()
    except Exception as e:  # noqa: BLE001
        return COD["bloqueado"], {"status": "bloqueado", "motivo": "configuracao invalida",
                                  "detalhes": [str(e)]}
    b = guarda.checar(prompt, cwd, arquivos, cfg)
    if b:
        return COD["bloqueado"], {"status": "bloqueado", "motivo": b.motivo, "detalhes": b.detalhes}
    fora = [a for a in guarda.resolver_arquivos(arquivos, cwd) if not guarda._dentro(a, cwd)]
    if fora:
        return COD["bloqueado"], {"status": "bloqueado", "motivo": "arquivo fora de --dir",
                                  "detalhes": [str(a) for a in fora]}

    agy = achar_agy()
    cascata = montar_cascata(papel, modelo, listar_modelos(agy))
    if not cascata:
        return COD["sem-modelo"], {"status": "sem-modelo", "detalhe":
                                   f"nenhum modelo da cascata '{papel}' esta no catalogo do agy"}
    modo = modo or MODO_PADRAO.get(papel, "plan")
    repete = PULA_COM_ESCRITA if modo == "accept-edits" else PULA_PARA_PROXIMO

    limpeza = area.varrer_orfas(AREA)
    try:
        diff = coletar_diff(cwd, diff_ref) if diff_ref else None
        if diff_ref and not diff.strip():
            return COD["vazio"], {"status": "vazio", "detalhe": f"nada a revisar contra {diff_ref}"}
        copia, rel = area.copiar_para_area(cwd, AREA)
    except (area.AreaErro, OSError) as e:
        return COD["area"], {"status": "area", "detalhe": str(e)}
    perfil = DIR_ESTADO / "perfis" / copia.name
    falha_area = None
    try:
        if diff:
            # O diff vai como arquivo dentro da copia: nao esbarra no limite da linha de comando.
            (copia / NOME_DIFF).write_text(diff, encoding="utf-8")
            rel = [*rel, Path(NOME_DIFF)]
            prompt += (f"\n\nAs mudancas a revisar estao em {NOME_DIFF} (diff contra {diff_ref}), "
                       "na raiz desta pasta; o codigo completo esta ao lado.")
        avisos = auditar_copia(copia, rel, cfg)
        if modo == "accept-edits":
            area.fotografar(copia)
        env = area.preparar_perfil(perfil, copia)
        tentativas, r, m = [], None, cascata[0]
        for m in cascata:
            r = chamar(agy, prompt, m, modo, copia, timeout, env, schema)
            tentativas.append({"modelo": m, "estado": r["estado"], "segundos": round(r["segundos"], 1)})
            if r["estado"] not in repete:
                break
        patch = area.extrair_patch(copia) if modo == "accept-edits" else None
    except (area.AreaErro, OSError) as e:
        falha_area = str(e)
    finally:
        # Limpeza nunca derruba a chamada: o que nao sair vira aviso (e a varredura tenta depois).
        aviso = area.descartar(copia)
        if aviso:
            limpeza.append(aviso)
        shutil.rmtree(perfil, ignore_errors=True)
    if falha_area is not None:
        res = {"status": "area", "detalhe": falha_area}
        if limpeza:
            res["aviso_limpeza"] = limpeza
        return COD["area"], res

    log = gravar_log(papel, m, prompt, r, patch)
    uso = r["dados"].get("usage", {})
    registrar_uso({"quando": datetime.now().isoformat(timespec="seconds"), "papel": papel,
                   "status": r["estado"], "modelo": m, "tentativas": tentativas,
                   "segundos": round(sum(t["segundos"] for t in tentativas), 1),
                   "arquivos_copiados": len(rel), "chars_prompt": len(prompt),
                   "tokens_entrada": uso.get("input_tokens"), "tokens_saida": uso.get("output_tokens"),
                   "negadas": r["dados"].get("denied_actions")})
    res = {"status": r["estado"], "modelo": m, "tentativas": tentativas, "log": str(log),
           "tokens": {k: uso.get(k) for k in ("input_tokens", "output_tokens", "cache_read_tokens")
                      if uso.get(k) is not None}}
    if r["dados"].get("denied_actions"):
        res["negadas"] = r["dados"]["denied_actions"]
    if limpeza:
        res["aviso_limpeza"] = limpeza
    if avisos:
        res["aviso_sigilo"] = {"arquivos_com_achado": avisos[:20], "total": len(avisos)}
    if patch is not None:
        res["patch"] = str(log.with_suffix(".patch")) if patch else None
        res["arquivos_alterados"] = re.findall(r"^diff --git a/(\S+)", patch, re.M)
    if r["estado"] == "ok":
        if r["dados"].get("structured_output") is not None:
            res["estruturado"] = r["dados"]["structured_output"]
        res["resposta"] = (r["dados"].get("response") or r["texto"]).strip()
        return COD["ok"], res
    if r["estado"] == "telemetria":
        res["detalhe"] = "rode: agy plugin disable googlecloudtools.datacloud_telemetry"
    res["inicio_saida"] = (r["texto"].strip() or r["stderr"].strip())[:400]
    return COD.get(r["estado"], 1), res


def status() -> int:
    rel: dict = {}
    try:
        agy = achar_agy()
        v = subprocess.run([*agy, "--version"], capture_output=True, text=True, timeout=60,
                           stdin=subprocess.DEVNULL)
        rel["agy"] = {"caminho": agy[-1], "versao": v.stdout.strip()}
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired) as e:
        print(json.dumps({"ok": False, "agy": str(e)}, ensure_ascii=False, indent=2))
        return COD["sem-modelo"]
    disp = listar_modelos(agy, forcar=True)
    rel["cascatas"] = {p: [m for m in c if m in disp] for p, c in CASCATAS.items()}
    rel["fora_do_catalogo"] = sorted({m for c in CASCATAS.values() for m in c} - set(disp))
    try:
        cfg = guarda.carregar_config()
        rel["guarda"] = {"auditor": str(cfg.auditor) if cfg.auditor else None,
                         "pastas_caso": [str(p) for p in cfg.pastas_caso]}
    except Exception as e:  # noqa: BLE001
        rel["guarda"] = {"erro": str(e)}
    sonda = DIR_ESTADO / "sonda"
    sonda.mkdir(parents=True, exist_ok=True)
    (sonda / "LEIA.txt").write_text("sonda do argon\n", encoding="utf-8")
    cod, r = executar("explorar", "Responda apenas: OK", sonda, [], None, None, 90)
    rel["sonda"] = {k: r.get(k) for k in ("status", "modelo", "tentativas", "tokens", "detalhe", "motivo",
                                                 "aviso_limpeza")
                    if r.get(k) is not None}
    rel["ok"] = cod == 0 and all(rel["cascatas"].values())
    print(json.dumps(rel, ensure_ascii=False, indent=2))
    return cod


def main() -> int:
    # Console e pipe do Windows em cp1252 quebram o primeiro acento.
    for fluxo in (sys.stdin, sys.stdout, sys.stderr):
        fluxo.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="Ponte do argon para o agy.")
    ap.add_argument("--papel", choices=sorted(CASCATAS))
    ap.add_argument("--prompt", help="texto do prompt; sem ele, le da entrada padrao")
    ap.add_argument("--dir", default=os.getcwd(), help="pasta de origem, copiada para a area isolada")
    ap.add_argument("--arquivo", action="append", default=[], help="arquivo citado (auditado), dentro de --dir")
    ap.add_argument("--modelo", help="modelo a tentar primeiro")
    ap.add_argument("--modo", choices=["plan", "accept-edits"])
    ap.add_argument("--schema", help="schema JSON da resposta estruturada")
    ap.add_argument("--timeout", type=int, default=240, help="segundos por modelo")
    ap.add_argument("--diff", metavar="REF", help="revisa o diff da origem contra REF (ex.: HEAD, main)")
    ap.add_argument("--modelos", action="store_true", help="mostra catalogo x cascatas e sai")
    ap.add_argument("--status", action="store_true", help="checa agy, catalogo, guarda, area e faz uma sonda")
    a = ap.parse_args()

    if a.status:
        return status()
    if a.modelos:
        disp = listar_modelos(achar_agy(), forcar=True)
        rel = {p: {m: (m in disp) for m in c} for p, c in CASCATAS.items()}
        fora = [m for m in disp if not any(m in c for c in CASCATAS.values())]
        print(json.dumps({"catalogo": disp, "cascatas": rel, "fora_das_cascatas": fora},
                         ensure_ascii=False, indent=2))
        return 0
    if not a.papel:
        ap.error("--papel e obrigatorio")
    if a.modelo and not RX_MODELO.match(a.modelo):
        ap.error("--modelo so aceita letras, digitos, ponto, hifen e sublinhado")
    cwd = Path(a.dir).resolve()
    if not cwd.is_dir():
        ap.error(f"--dir inexistente: {cwd}")
    schema = Path(a.schema).resolve() if a.schema else None
    if schema and not schema.is_file():
        ap.error(f"--schema inexistente: {schema}")
    prompt = a.prompt if a.prompt is not None else sys.stdin.read()
    if not prompt.strip():
        ap.error("prompt vazio")
    try:
        cod, res = executar(a.papel, prompt, cwd, a.arquivo, a.modelo, a.modo, a.timeout,
                            schema=schema, diff_ref=a.diff)
    except FileNotFoundError as e:
        cod, res = COD["sem-modelo"], {"status": "sem-agy", "detalhe": str(e)}
    print(json.dumps(res, ensure_ascii=False, indent=2))
    return cod


if __name__ == "__main__":
    sys.exit(main())
